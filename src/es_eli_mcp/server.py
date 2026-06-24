"""FastMCP entry point - Spanish BOE consolidated-law tools.

Run:

    python -m es_eli_mcp.server

Configuration via env:

- ``ES_ELI_CACHE_DIR`` (default ``~/.matematic/cache/es-eli``)
- ``ES_ELI_AUDIT_DIR`` (default ``~/.matematic/audit``)
- ``ES_ELI_BASE_URL`` (default ``https://www.boe.es/datosabiertos/api``)
"""

from __future__ import annotations

import os

import httpx
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .audit import AuditLogger, hash_input, timer
from .citations import enrich_metadata, extract_gazette_items
from .client import DEFAULT_BASE_URL, BoeClient, BoeError
from .models import Act, GazetteItem, GazetteResult, IndexBlock, IndexResult, LawText

INSTRUCTIONS = """\
This MCP server exposes the Spanish BOE (Boletin Oficial del Estado) open-data API. It grounds Spanish consolidated legislation: given a BOE id (e.g. `BOE-A-2018-16673`) or discovered via the daily gazette, it returns metadata, structure and full consolidated text. Every response carries a stable `eli_uri`, a `human_readable_citation` and a `source_url` (the citation contract).

## Call order

1. `es_browse_gazette` - list documents published in the official gazette on a given date (`YYYYMMDD`). Use this to discover BOE ids when you do not already have one.
2. `es_get_act` - metadata for a BOE id: `eli_uri` (e.g. `https://www.boe.es/eli/es/lo/2018/12/05/3`), `human_readable_citation` (the official `titulo`), `source_url`.
3. `es_get_index` - the block index (articles, titles) of a consolidated law, so you can fetch a specific part.
4. `es_get_text` - the consolidated text (XML) of a whole law or a single block (`block_id` from the index).

## Hard constraints

- **No free-text search** - the BOE open-data keyword-search endpoint is unavailable (server-side error). Discover via `es_browse_gazette` (by date) or use a known BOE id / ELI. Relay the `dataset_note`.
- **ELI is the key to citability** - BOE returns a full ELI URL in `eli_uri`; do not invent it.
- **Every response has `human_readable_citation` + `source_url`** - cite both to the user.
- **No modification of official text** - returned verbatim from BOE.
- **Audit log JSONL** - every tool call appends to `~/.matematic/audit/es-eli-mcp.jsonl`.

## Error iteration

Tools return a structured error with a `[code]` prefix:
- `invalid_arg` - a parameter is missing or malformed (e.g. empty id, a date that is not `YYYYMMDD`).
- `not_found` - the BOE id or gazette date does not exist.
- `upstream_error` - a BOE API error (HTTP, timeout, non-ok envelope). Retry once before surfacing.

## Response style

- Cite acts as `human_readable_citation` with the ELI URL: "Ley Organica 3/2018, de 5 de diciembre... (https://www.boe.es/eli/es/lo/2018/12/05/3)".
- NEVER invent an ELI, a BOE id or a date - take each from the tool output.
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
    return exc


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


def main() -> None:
    """Run the MCP server over stdio (default for Claude Code)."""
    mcp.run()


if __name__ == "__main__":
    main()
