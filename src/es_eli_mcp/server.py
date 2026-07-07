"""FastMCP entry point - Spanish BOE consolidated-law + Tribunal Constitucional tools.

Run:

    python -m es_eli_mcp.server

Configuration via env:

- ``ES_ELI_CACHE_DIR`` (default ``~/.matematic/cache/es-eli``)
- ``ES_ELI_AUDIT_DIR`` (default ``~/.matematic/audit``)
- ``ES_ELI_BASE_URL`` (default ``https://www.boe.es/datosabiertos/api``)
- ``ES_ELI_TC_BASE_URL`` (default ``https://hj.tribunalconstitucional.es``)
"""

from __future__ import annotations

import os

import httpx
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .audit import AuditLogger, hash_input, timer
from .citations import enrich_metadata, extract_gazette_items, tc_human_citation, tc_tipo_from_title
from .client import DEFAULT_BASE_URL, BoeClient, BoeError
from .models import (
    Act,
    ConstitutionalRuling,
    GazetteItem,
    GazetteResult,
    IndexBlock,
    IndexResult,
    LawText,
)
from .tc_client import DEFAULT_TC_BASE_URL, TcClient, TcError, TcNotFoundError, TcResolution

INSTRUCTIONS = """\
This MCP server exposes two Spanish open-data sources. It grounds Spanish consolidated legislation and Tribunal Constitucional (Constitutional Court) case law, with a stable citation contract on every response.

### BOE (Boletin Oficial del Estado) - consolidated legislation

Given a BOE id (e.g. `BOE-A-2018-16673`) or discovered via the daily gazette, returns metadata, structure and full consolidated text. Every response carries `eli_uri`, `human_readable_citation` and `source_url`.

## Call order (BOE)

1. `es_browse_gazette` - list documents published in the official gazette on a given date (`YYYYMMDD`). Use this to discover BOE ids when you do not already have one.
2. `es_get_act` - metadata for a BOE id: `eli_uri` (e.g. `https://www.boe.es/eli/es/lo/2018/12/05/3`), `human_readable_citation` (the official `titulo`), `source_url`.
3. `es_get_index` - the block index (articles, titles) of a consolidated law, so you can fetch a specific part.
4. `es_get_text` - the consolidated text (XML) of a whole law or a single block (`block_id` from the index).

### Tribunal Constitucional (hj.tribunalconstitucional.es) - constitutional case law

Sentencias (STC), Autos (ATC) and Declaraciones (DTC) of the Spanish Constitutional Court. TC case law has no ELI (ELI covers legislation, not case law); `ecli` (e.g. `ECLI:ES:TC:2016:117`) is the identifier instead, alongside `human_readable_citation` in the Spanish doctrinal convention ("STC 117/2016, de 20 de junio").

## Call order (Tribunal Constitucional)

1. If you already know the citation number and year (e.g. "STC 31/2010") - `es_search_constitutional(numero="31", anno="2010")` resolves it to the internal resolution id and returns the full ruling directly.
2. If you already have the internal resolution id (e.g. from a prior call or a citing STC's hyperlink) - `es_get_constitutional_ruling(resolution_id="6670")`.

## Hard constraints

- **No free-text search on BOE** - the BOE open-data keyword-search endpoint is unavailable (server-side error). Discover via `es_browse_gazette` (by date) or use a known BOE id / ELI. Relay the `dataset_note`.
- **No free-text full-content search on Tribunal Constitucional** - `es_search_constitutional` resolves by citation number+year only (the site's own search form), not by keyword.
- **ELI is the key to citability for BOE acts** - BOE returns a full ELI URL in `eli_uri`; do not invent it. TC rulings have no ELI - use `ecli` instead.
- **Every response has `human_readable_citation` + `source_url`** - cite both to the user.
- **No modification of official text** - returned verbatim from the source.
- **Audit log JSONL** - every tool call appends to `~/.matematic/audit/es-eli-mcp.jsonl`.

## Error iteration

Tools return a structured error with a `[code]` prefix:
- `invalid_arg` - a parameter is missing or malformed (e.g. empty id, a date that is not `YYYYMMDD`).
- `not_found` - the BOE id, gazette date, TC resolution id, or TC citation number+year does not exist.
- `upstream_error` - a BOE or Tribunal Constitucional error (HTTP, timeout, non-ok envelope, session/search failure). Retry once before surfacing.

## Response style

- Cite BOE acts as `human_readable_citation` with the ELI URL: "Ley Organica 3/2018, de 5 de diciembre... (https://www.boe.es/eli/es/lo/2018/12/05/3)".
- Cite TC rulings as `human_readable_citation` with the ECLI and `source_url`: "STC 31/2010, de 28 de junio (ECLI:ES:TC:2010:31) - https://hj.tribunalconstitucional.es/es/Resolucion/Show/6670".
- NEVER invent an ELI, ECLI, a BOE id, a TC resolution id or a date - take each from the tool output.
"""


class ToolError(Exception):
    """Structured error for es-eli MCP tools - visible to the LLM with a [code] prefix."""

    VALID_CODES = frozenset({"invalid_arg", "not_found", "upstream_error"})

    def __init__(self, code: str, message: str):
        if code not in self.VALID_CODES:
            raise ValueError(f"Unknown ToolError code: {code}. Valid: {sorted(self.VALID_CODES)}")
        self.code = code
        super().__init__(f"[{code}] {message}")


READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    idempotentHint=True,
    destructiveHint=False,
    openWorldHint=True,
)

mcp: FastMCP = FastMCP(name="es-eli-mcp", instructions=INSTRUCTIONS)


def _base_url() -> str:
    return os.environ.get("ES_ELI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _audit() -> AuditLogger:
    return AuditLogger()


def _map_upstream(exc: Exception) -> Exception:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
        return ToolError("not_found", "Not found in BOE.")
    if isinstance(exc, (BoeError, httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException)):
        return ToolError("upstream_error", f"BOE API error: {type(exc).__name__}: {exc}")
    if isinstance(exc, TcNotFoundError):
        return ToolError("not_found", str(exc))
    if isinstance(exc, TcError):
        return ToolError("upstream_error", f"Tribunal Constitucional error: {exc}")
    return exc


def _tc_base_url() -> str:
    return os.environ.get("ES_ELI_TC_BASE_URL", DEFAULT_TC_BASE_URL).rstrip("/")


def _require_id(boe_id: str) -> str:
    if not boe_id or not boe_id.strip():
        raise ToolError("invalid_arg", "BOE id must not be empty (e.g. 'BOE-A-2018-16673').")
    return boe_id.strip()


# ---------------------------------------------------------------------------
# es_get_act
# ---------------------------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
async def es_get_act(boe_id: str) -> Act:
    """Fetch consolidated-law metadata from BOE by id.

    Args:
        boe_id: a BOE identifier, e.g. ``"BOE-A-2018-16673"``.

    Returns:
        ``Act`` with ``eli_uri``, ``human_readable_citation``, ``source_url``.
    """
    audit = _audit()
    bid = _require_id(boe_id)
    input_hash = hash_input({"boe_id": bid})

    with timer() as t:
        try:
            async with BoeClient(base_url=_base_url()) as client:
                raw = await client.metadatos(bid)
        except Exception as exc:
            audit.log(tool="es_get_act", input_hash=input_hash, output_count_or_size=0,
                      duration_ms=t.duration_ms if t.duration_ms else 0, status="error",
                      error=f"{type(exc).__name__}: {exc}")
            raise _map_upstream(exc) from exc

    act = Act.model_validate(enrich_metadata(raw))
    audit.log(tool="es_get_act", input_hash=input_hash, output_count_or_size=1,
              duration_ms=t.duration_ms, status="ok")
    return act


# ---------------------------------------------------------------------------
# es_get_index
# ---------------------------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
async def es_get_index(boe_id: str) -> IndexResult:
    """List the block index (articles, titles) of a consolidated law.

    Args:
        boe_id: a BOE identifier, e.g. ``"BOE-A-2018-16673"``.

    Returns:
        ``IndexResult`` with ``blocks`` (each ``id`` is usable as ``block_id`` in es_get_text).
    """
    audit = _audit()
    bid = _require_id(boe_id)
    input_hash = hash_input({"boe_id": bid})

    with timer() as t:
        try:
            async with BoeClient(base_url=_base_url()) as client:
                blocks_raw = await client.indice(bid)
        except Exception as exc:
            audit.log(tool="es_get_index", input_hash=input_hash, output_count_or_size=0,
                      duration_ms=t.duration_ms if t.duration_ms else 0, status="error",
                      error=f"{type(exc).__name__}: {exc}")
            raise _map_upstream(exc) from exc

    blocks = [IndexBlock.model_validate(b) for b in blocks_raw]
    result = IndexResult(id=bid, blocks=blocks)
    audit.log(tool="es_get_index", input_hash=input_hash, output_count_or_size=len(blocks),
              duration_ms=t.duration_ms, status="ok")
    return result


# ---------------------------------------------------------------------------
# es_get_text
# ---------------------------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
async def es_get_text(boe_id: str, block_id: str | None = None) -> LawText:
    """Fetch the consolidated text (XML) of a law, whole or by block.

    Args:
        boe_id: a BOE identifier, e.g. ``"BOE-A-2018-16673"``.
        block_id: optional block id from ``es_get_index`` (e.g. ``"a1"`` for Articulo 1).
            Omit for the full consolidated text (can be large).

    Returns:
        ``LawText`` with ``eli_uri``, ``human_readable_citation``, ``source_url`` and ``content`` (XML).
    """
    audit = _audit()
    bid = _require_id(boe_id)
    input_hash = hash_input({"boe_id": bid, "block_id": block_id})

    with timer() as t:
        try:
            async with BoeClient(base_url=_base_url()) as client:
                meta = enrich_metadata(await client.metadatos(bid))
                text, ct = await client.texto(bid, block_id=block_id)
        except Exception as exc:
            audit.log(tool="es_get_text", input_hash=input_hash, output_count_or_size=0,
                      duration_ms=t.duration_ms if t.duration_ms else 0, status="error",
                      error=f"{type(exc).__name__}: {exc}")
            raise _map_upstream(exc) from exc

    result = LawText(
        id=bid,
        block_id=block_id,
        eli_uri=meta.get("eli_uri"),
        human_readable_citation=meta.get("human_readable_citation"),
        source_url=meta.get("source_url"),
        format="xml",
        content=text,
        content_type=ct,
        byte_size=len(text.encode("utf-8")),
    )
    audit.log(tool="es_get_text", input_hash=input_hash, output_count_or_size=result.byte_size or 0,
              duration_ms=t.duration_ms, status="ok")
    return result


# ---------------------------------------------------------------------------
# es_browse_gazette
# ---------------------------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
async def es_browse_gazette(date: str) -> GazetteResult:
    """List documents published in the official BOE gazette on a date.

    Args:
        date: the publication date as ``YYYYMMDD`` (e.g. ``"20181206"``).

    Returns:
        ``GazetteResult`` with the documents (``id`` + ``titulo``) published that day.
    """
    audit = _audit()
    d = (date or "").strip()
    if not (len(d) == 8 and d.isdigit()):
        raise ToolError("invalid_arg", "date must be YYYYMMDD, e.g. '20181206'.")
    input_hash = hash_input({"date": d})

    with timer() as t:
        try:
            async with BoeClient(base_url=_base_url()) as client:
                raw = await client.sumario(d)
        except Exception as exc:
            audit.log(tool="es_browse_gazette", input_hash=input_hash, output_count_or_size=0,
                      duration_ms=t.duration_ms if t.duration_ms else 0, status="error",
                      error=f"{type(exc).__name__}: {exc}")
            raise _map_upstream(exc) from exc

    items = [GazetteItem.model_validate(i) for i in extract_gazette_items(raw)]
    result = GazetteResult(date=d, total=len(items), items=items)
    audit.log(tool="es_browse_gazette", input_hash=input_hash, output_count_or_size=len(items),
              duration_ms=t.duration_ms, status="ok")
    return result


# ---------------------------------------------------------------------------
# es_get_constitutional_ruling
# ---------------------------------------------------------------------------


def _ruling_from_tc(res: TcResolution) -> ConstitutionalRuling:
    citation = tc_human_citation(res.title)
    return ConstitutionalRuling(
        id=res.id,
        tipo=tc_tipo_from_title(res.title),
        sala=res.sala,
        ecli=res.ecli,
        encabezamiento=res.encabezamiento,
        fallo=res.fallo,
        human_readable_citation=citation,
        source_url=res.source_url,
    )


@mcp.tool(annotations=READ_ONLY)
async def es_get_constitutional_ruling(resolution_id: str) -> ConstitutionalRuling:
    """Fetch a Tribunal Constitucional ruling (Sentencia/Auto/Declaracion) by internal id.

    Args:
        resolution_id: the internal Sistema HJ sequential id (e.g. ``"6670"`` for STC 31/2010).
            Get this id either from ``es_search_constitutional`` or from a hyperlink inside
            another ruling's text (``.../Resolucion/Show/{id}``).

    Returns:
        ``ConstitutionalRuling`` with ``ecli``, ``human_readable_citation`` (e.g.
        "STC 31/2010, de 28 de junio"), ``source_url``, ``encabezamiento`` (summary of the
        case) and ``fallo`` (the operative ruling/holding).
    """
    audit = _audit()
    rid = (resolution_id or "").strip()
    if not rid or not rid.isdigit():
        raise ToolError("invalid_arg", "resolution_id must be a non-empty numeric id, e.g. '6670'.")
    input_hash = hash_input({"resolution_id": rid})

    with timer() as t:
        try:
            async with TcClient(base_url=_tc_base_url()) as client:
                res = await client.get_resolution(rid)
        except Exception as exc:
            audit.log(tool="es_get_constitutional_ruling", input_hash=input_hash,
                      output_count_or_size=0, duration_ms=t.duration_ms if t.duration_ms else 0,
                      status="error", error=f"{type(exc).__name__}: {exc}")
            raise _map_upstream(exc) from exc

    ruling = _ruling_from_tc(res)
    audit.log(tool="es_get_constitutional_ruling", input_hash=input_hash, output_count_or_size=1,
              duration_ms=t.duration_ms, status="ok")
    return ruling


# ---------------------------------------------------------------------------
# es_search_constitutional
# ---------------------------------------------------------------------------


_VALID_TIPOS = frozenset({"SENTENCIA", "AUTO", "DECLARACION"})


@mcp.tool(annotations=READ_ONLY)
async def es_search_constitutional(
    numero: str, anno: str, tipo: str = "SENTENCIA"
) -> ConstitutionalRuling:
    """Resolve a Tribunal Constitucional citation (number + year) to the full ruling.

    Args:
        numero: the citation number, e.g. ``"31"`` for "STC 31/2010".
        anno: the citation year, e.g. ``"2010"``.
        tipo: one of ``"SENTENCIA"`` (default, -> STC), ``"AUTO"`` (-> ATC), or
            ``"DECLARACION"`` (-> DTC).

    Returns:
        ``ConstitutionalRuling`` for the matching resolution (same shape as
        ``es_get_constitutional_ruling``).
    """
    audit = _audit()
    num = (numero or "").strip()
    yr = (anno or "").strip()
    tp = (tipo or "SENTENCIA").strip().upper()
    if not num or not num.isdigit():
        raise ToolError("invalid_arg", "numero must be a non-empty numeric string, e.g. '31'.")
    if not yr or not yr.isdigit() or len(yr) != 4:
        raise ToolError("invalid_arg", "anno must be a 4-digit year, e.g. '2010'.")
    if tp not in _VALID_TIPOS:
        raise ToolError("invalid_arg", f"tipo must be one of {sorted(_VALID_TIPOS)}.")
    input_hash = hash_input({"numero": num, "anno": yr, "tipo": tp})

    with timer() as t:
        try:
            async with TcClient(base_url=_tc_base_url()) as client:
                rid = await client.find_id_by_citation(num, yr, tipo=tp)
                res = await client.get_resolution(rid)
        except Exception as exc:
            audit.log(tool="es_search_constitutional", input_hash=input_hash,
                      output_count_or_size=0, duration_ms=t.duration_ms if t.duration_ms else 0,
                      status="error", error=f"{type(exc).__name__}: {exc}")
            raise _map_upstream(exc) from exc

    ruling = _ruling_from_tc(res)
    audit.log(tool="es_search_constitutional", input_hash=input_hash, output_count_or_size=1,
              duration_ms=t.duration_ms, status="ok")
    return ruling


def main() -> None:
    """Run the MCP server over stdio (default for Claude Code)."""
    mcp.run()


if __name__ == "__main__":
    main()
