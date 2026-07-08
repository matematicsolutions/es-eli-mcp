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
import re

import httpx
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .aepd_client import (
    DEFAULT_AEPD_BASE_URL,
    AepdClient,
    AepdError,
    AepdNotFoundError,
)
from .audit import AuditLogger, hash_input, timer
from .citations import (
    aepd_human_citation,
    dgt_human_citation,
    enrich_metadata,
    extract_gazette_items,
    tc_human_citation,
    tc_tipo_from_title,
    teac_human_citation,
)
from .client import DEFAULT_BASE_URL, BoeClient, BoeError
from .dgt_client import DEFAULT_DGT_BASE_URL, DgtClient, DgtError, DgtNotFoundError
from .models import (
    Act,
    AepdResolutionModel,
    AepdSearchResult,
    ConstitutionalRuling,
    GazetteItem,
    GazetteResult,
    IndexBlock,
    IndexResult,
    LawText,
    TaxRuling,
    TaxRulingHit,
    TaxRulingSearchResult,
    TeacCriterioResult,
    TeacDoctrineHit,
    TeacDoctrineSearchResult,
)
from .tc_client import DEFAULT_TC_BASE_URL, TcClient, TcError, TcNotFoundError, TcResolution
from .teac_client import (
    DEFAULT_TEAC_BASE_URL,
    TeacClient,
    TeacError,
    TeacNotFoundError,
    is_valid_criterio_id,
)

INSTRUCTIONS = """\
This MCP server exposes five Spanish open-data sources: BOE consolidated legislation, Tribunal Constitucional case law, DGT binding tax rulings, TEAC tax-tribunal doctrine, and AEPD data-protection resolutions - with a stable citation contract on every response.

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

### DGT (Direccion General de Tributos) - binding tax rulings

Consultas tributarias of the Spanish tax authority (petete.tributos.hacienda.gob.es): ~69,500 consultas vinculantes (V-numbers, binding on the tax administration) + ~19,700 consultas generales. Tax rulings have no ELI/ECLI; the official NUM-CONSULTA (e.g. `V0001-25`) is the durable identifier.

## Call order (DGT)

1. `es_search_tax_rulings` - full-text and/or date search over one of the two databases (`vinculantes` default). Returns NUM-CONSULTA per hit.
2. `es_get_tax_ruling` - the full ruling (facts, question, normativa, full answer) by NUM-CONSULTA, e.g. `es_get_tax_ruling(numero_consulta="V0001-25")`.

### TEAC (Tribunal Economico-Administrativo Central) - doctrine

Criterios of the Spanish tax administrative tribunals (DYCTEA, ~6,500 criterios with the full resolution text inline). NO full-text search - the portal silently ignores text parameters - so search is by RG claim-number segments and/or resolution-date range only.

## Call order (TEAC)

1. `es_search_teac_doctrine` - by RG segments (`sede`, `numero`, `anno`, e.g. 00/07082/2025) and/or a `dd/mm/aaaa` date range. Returns criterio ids.
2. `es_get_teac_criterio` - full criterio + resolution text by id, e.g. `es_get_teac_criterio(criterio_id="00/07082/2025/00/0/1")`.

### AEPD (Agencia Espanola de Proteccion de Datos) - resolutions

~46,800 data-protection resolutions (sanctions, warnings, terminations) with Solr full-text search. Each hit carries the expediente number (e.g. `PS-00615-2025`) and a PDF permalink with the full text.

## Call order (AEPD)

1. `es_search_aepd_resolutions` - full-text and/or signature-date search.
2. `es_get_aepd_resolution` - one resolution by expediente number; returns the `pdf_url` permalink (full text is the PDF - fetch it separately if the user needs the body).

## Hard constraints

- **No free-text search on BOE** - the BOE open-data keyword-search endpoint is unavailable (server-side error). Discover via `es_browse_gazette` (by date) or use a known BOE id / ELI. Relay the `dataset_note`.
- **No free-text full-content search on Tribunal Constitucional** - `es_search_constitutional` resolves by citation number+year only (the site's own search form), not by keyword.
- **No free-text search on TEAC** - DYCTEA accepts text-looking parameters but silently ignores them; `es_search_teac_doctrine` filters by RG segments and dates only.
- **AEPD full text is a PDF** - `es_get_aepd_resolution` returns the verified `pdf_url` permalink, not the PDF body.
- **ELI is the key to citability for BOE acts** - BOE returns a full ELI URL in `eli_uri`; do not invent it. TC rulings have no ELI - use `ecli` instead.
- **Every response has `human_readable_citation` + `source_url`** - cite both to the user.
- **No modification of official text** - returned verbatim from the source.
- **Audit log JSONL** - every tool call appends to `~/.matematic/audit/es-eli-mcp.jsonl`.

## Error iteration

Tools return a structured error with a `[code]` prefix:
- `invalid_arg` - a parameter is missing or malformed (e.g. empty id, a date that is not `YYYYMMDD`).
- `not_found` - the BOE id, gazette date, TC resolution id/citation, DGT consulta number, TEAC criterio id, or AEPD expediente does not exist.
- `upstream_error` - an upstream source error (HTTP, timeout, non-ok envelope, session/search failure). Retry once before surfacing.

## Response style

- Cite BOE acts as `human_readable_citation` with the ELI URL: "Ley Organica 3/2018, de 5 de diciembre... (https://www.boe.es/eli/es/lo/2018/12/05/3)".
- Cite TC rulings as `human_readable_citation` with the ECLI and `source_url`: "STC 31/2010, de 28 de junio (ECLI:ES:TC:2010:31) - https://hj.tribunalconstitucional.es/es/Resolucion/Show/6670".
- Cite DGT rulings by NUM-CONSULTA ("Consulta Vinculante V0001-25, de 2 de enero de 2025, de la Dirección General de Tributos"), TEAC doctrine by RG + date ("Resolución del TEAC de 24 de junio de 2026, RG 00/07082/2025"), AEPD resolutions by expediente + PDF permalink - always from the tool output's `human_readable_citation` + `source_url`.
- NEVER invent an ELI, ECLI, a BOE id, a TC resolution id, a NUM-CONSULTA, an RG number, an expediente or a date - take each from the tool output.
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


# ---------------------------------------------------------------------------
# feature-003: DGT tax rulings / TEAC doctrine / AEPD resolutions
# ---------------------------------------------------------------------------


def _dgt_base_url() -> str:
    return os.environ.get("ES_ELI_DGT_BASE_URL", DEFAULT_DGT_BASE_URL).rstrip("/")


def _teac_base_url() -> str:
    return os.environ.get("ES_ELI_TEAC_BASE_URL", DEFAULT_TEAC_BASE_URL).rstrip("/")


def _aepd_base_url() -> str:
    return os.environ.get("ES_ELI_AEPD_BASE_URL", DEFAULT_AEPD_BASE_URL).rstrip("/")


def _map_upstream_extra(exc: Exception) -> Exception:
    if isinstance(exc, (DgtNotFoundError, TeacNotFoundError, AepdNotFoundError)):
        return ToolError("not_found", str(exc))
    if isinstance(exc, DgtError):
        return ToolError("upstream_error", f"DGT (petete) error: {exc}")
    if isinstance(exc, TeacError):
        return ToolError("upstream_error", f"TEAC (DYCTEA) error: {exc}")
    if isinstance(exc, AepdError):
        return ToolError("upstream_error", f"AEPD error: {exc}")
    if isinstance(exc, (httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException)):
        return ToolError("upstream_error", f"Upstream error: {type(exc).__name__}: {exc}")
    return exc


_DDMMYYYY_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def _require_ddmmyyyy(value: str | None, name: str) -> str | None:
    if value is None or not value.strip():
        return None
    v = value.strip()
    if not _DDMMYYYY_RE.match(v):
        raise ToolError("invalid_arg", f"{name} must be dd/mm/aaaa, e.g. '01/01/2025'.")
    return v


@mcp.tool(annotations=READ_ONLY)
async def es_search_tax_rulings(
    texto: str | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    database: str = "vinculantes",
    page: int = 1,
) -> TaxRulingSearchResult:
    """Search DGT tax rulings (consultas tributarias) by free text and/or date.

    Args:
        texto: free-text query over the ruling corpus (e.g. ``"aerotermia"``).
        fecha_desde: earliest ``fecha salida``, ``dd/mm/aaaa``.
        fecha_hasta: latest ``fecha salida``, ``dd/mm/aaaa`` (requires fecha_desde).
        database: ``"vinculantes"`` (default, V-numbers, binding) or ``"generales"``.
        page: 1-based results page (20 hits per page).

    Returns:
        ``TaxRulingSearchResult`` with ``total`` and hits carrying ``num_consulta``
        (feed it to ``es_get_tax_ruling`` for the full ruling).
    """
    audit = _audit()
    db = (database or "vinculantes").strip().lower()
    if db not in ("vinculantes", "generales"):
        raise ToolError("invalid_arg", "database must be 'vinculantes' or 'generales'.")
    if not texto and not fecha_desde:
        raise ToolError("invalid_arg", "Provide texto and/or fecha_desde.")
    fd = _require_ddmmyyyy(fecha_desde, "fecha_desde")
    fh = _require_ddmmyyyy(fecha_hasta, "fecha_hasta")
    if fh and not fd:
        raise ToolError("invalid_arg", "fecha_hasta requires fecha_desde.")
    if page < 1:
        raise ToolError("invalid_arg", "page must be >= 1.")
    input_hash = hash_input(
        {"texto": texto, "fecha_desde": fd, "fecha_hasta": fh, "database": db, "page": page}
    )

    with timer() as t:
        try:
            async with DgtClient(base_url=_dgt_base_url()) as client:
                result = await client.search(
                    vinculantes=(db == "vinculantes"),
                    texto=texto.strip() if texto else None,
                    fecha_desde=fd,
                    fecha_hasta=fh,
                    page=page,
                )
        except Exception as exc:
            audit.log(tool="es_search_tax_rulings", input_hash=input_hash,
                      output_count_or_size=0, duration_ms=t.duration_ms if t.duration_ms else 0,
                      status="error", error=f"{type(exc).__name__}: {exc}")
            raise _map_upstream_extra(exc) from exc

    items = [
        TaxRulingHit(
            num_consulta=h.num_consulta,
            descripcion_hechos=h.descripcion_hechos,
            cuestion_planteada=h.cuestion_planteada,
        )
        for h in result.hits
    ]
    out = TaxRulingSearchResult(
        total=result.total, total_pages=result.total_pages, page=result.page,
        database=db, items=items,
    )
    audit.log(tool="es_search_tax_rulings", input_hash=input_hash,
              output_count_or_size=len(items), duration_ms=t.duration_ms, status="ok")
    return out


@mcp.tool(annotations=READ_ONLY)
async def es_get_tax_ruling(numero_consulta: str) -> TaxRuling:
    """Fetch a full DGT tax ruling by its official number.

    Args:
        numero_consulta: the official NUM-CONSULTA, e.g. ``"V0001-25"`` (vinculante)
            or ``"0001-03"`` (general).

    Returns:
        ``TaxRuling`` with ``normativa``, ``descripcion_hechos``, ``cuestion_planteada``,
        the full ``contestacion``, ``human_readable_citation`` and ``source_url``.
    """
    audit = _audit()
    num = (numero_consulta or "").strip()
    if not num:
        raise ToolError("invalid_arg", "numero_consulta must not be empty, e.g. 'V0001-25'.")
    input_hash = hash_input({"numero_consulta": num})

    with timer() as t:
        try:
            async with DgtClient(base_url=_dgt_base_url()) as client:
                ruling = await client.get_ruling_by_number(num)
        except Exception as exc:
            audit.log(tool="es_get_tax_ruling", input_hash=input_hash, output_count_or_size=0,
                      duration_ms=t.duration_ms if t.duration_ms else 0, status="error",
                      error=f"{type(exc).__name__}: {exc}")
            raise _map_upstream_extra(exc) from exc

    out = TaxRuling(
        num_consulta=ruling.num_consulta,
        organo=ruling.organo,
        fecha_salida=ruling.fecha_salida,
        normativa=ruling.normativa,
        descripcion_hechos=ruling.descripcion_hechos,
        cuestion_planteada=ruling.cuestion_planteada,
        contestacion=ruling.contestacion,
        human_readable_citation=dgt_human_citation(ruling.num_consulta, ruling.fecha_salida),
        source_url=ruling.source_url,
    )
    audit.log(tool="es_get_tax_ruling", input_hash=input_hash, output_count_or_size=1,
              duration_ms=t.duration_ms, status="ok")
    return out


@mcp.tool(annotations=READ_ONLY)
async def es_search_teac_doctrine(
    sede: str | None = None,
    numero: str | None = None,
    anno: str | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    page: int = 1,
) -> TeacDoctrineSearchResult:
    """Search TEAC doctrine (DYCTEA criterios) by RG segments and/or date range.

    Args:
        sede: RG sede segment, e.g. ``"00"`` (TEAC) - first part of RG 00/07082/2025.
        numero: RG claim number segment, e.g. ``"07082"``.
        anno: RG year segment, e.g. ``"2025"``.
        fecha_desde: earliest resolution date, ``dd/mm/aaaa``.
        fecha_hasta: latest resolution date, ``dd/mm/aaaa``.
        page: 1-based results page (10 hits per page, portal caps display at 100).

    Returns:
        ``TeacDoctrineSearchResult`` with ``total`` and hits carrying ``criterio_id``
        (feed it to ``es_get_teac_criterio``). No free-text search exists on DYCTEA.
    """
    audit = _audit()
    if not any([sede, numero, anno, fecha_desde]):
        raise ToolError(
            "invalid_arg",
            "Provide at least one filter: sede/numero/anno (RG segments) or fecha_desde.",
        )
    fd = _require_ddmmyyyy(fecha_desde, "fecha_desde")
    fh = _require_ddmmyyyy(fecha_hasta, "fecha_hasta")
    if page < 1:
        raise ToolError("invalid_arg", "page must be >= 1.")
    for name, val in (("sede", sede), ("numero", numero), ("anno", anno)):
        if val is not None and val.strip() and not val.strip().isdigit():
            raise ToolError("invalid_arg", f"{name} must be numeric (an RG segment).")
    input_hash = hash_input(
        {"sede": sede, "numero": numero, "anno": anno, "fd": fd, "fh": fh, "page": page}
    )

    with timer() as t:
        try:
            async with TeacClient(base_url=_teac_base_url()) as client:
                result = await client.search(
                    sede=sede, numero=numero, anno=anno,
                    fecha_desde=fd, fecha_hasta=fh, page=page,
                )
        except Exception as exc:
            audit.log(tool="es_search_teac_doctrine", input_hash=input_hash,
                      output_count_or_size=0, duration_ms=t.duration_ms if t.duration_ms else 0,
                      status="error", error=f"{type(exc).__name__}: {exc}")
            raise _map_upstream_extra(exc) from exc

    items = [
        TeacDoctrineHit(criterio_id=h.criterio_id, title=h.title, snippet=h.snippet)
        for h in result.hits
    ]
    out = TeacDoctrineSearchResult(total=result.total, page=result.page, items=items)
    audit.log(tool="es_search_teac_doctrine", input_hash=input_hash,
              output_count_or_size=len(items), duration_ms=t.duration_ms, status="ok")
    return out


@mcp.tool(annotations=READ_ONLY)
async def es_get_teac_criterio(criterio_id: str) -> TeacCriterioResult:
    """Fetch one TEAC criterio (with the full resolution text) by its DYCTEA id.

    Args:
        criterio_id: the DYCTEA id from ``es_search_teac_doctrine``, e.g.
            ``"00/07082/2025/00/0/1"``.

    Returns:
        ``TeacCriterioResult`` with ``asunto``, ``criterio``, ``referencias_normativas``,
        the full ``texto_resolucion``, ``human_readable_citation`` and ``source_url``.
    """
    audit = _audit()
    cid = (criterio_id or "").strip()
    if not cid or not is_valid_criterio_id(cid):
        raise ToolError(
            "invalid_arg",
            "criterio_id must look like '00/07082/2025/00/0/1' "
            "(from es_search_teac_doctrine).",
        )
    input_hash = hash_input({"criterio_id": cid})

    with timer() as t:
        try:
            async with TeacClient(base_url=_teac_base_url()) as client:
                criterio = await client.get_criterio(cid)
        except Exception as exc:
            audit.log(tool="es_get_teac_criterio", input_hash=input_hash,
                      output_count_or_size=0, duration_ms=t.duration_ms if t.duration_ms else 0,
                      status="error", error=f"{type(exc).__name__}: {exc}")
            raise _map_upstream_extra(exc) from exc

    out = TeacCriterioResult(
        criterio_id=criterio.criterio_id,
        rg=criterio.rg,
        calificacion=criterio.calificacion,
        unidad_resolutoria=criterio.unidad_resolutoria,
        fecha_resolucion=criterio.fecha_resolucion,
        asunto=criterio.asunto,
        criterio=criterio.criterio,
        referencias_normativas=criterio.referencias_normativas,
        texto_resolucion=criterio.texto_resolucion,
        human_readable_citation=teac_human_citation(
            criterio.rg, criterio.fecha_resolucion, criterio.unidad_resolutoria
        ),
        source_url=criterio.source_url,
    )
    audit.log(tool="es_get_teac_criterio", input_hash=input_hash, output_count_or_size=1,
              duration_ms=t.duration_ms, status="ok")
    return out


@mcp.tool(annotations=READ_ONLY)
async def es_search_aepd_resolutions(
    texto: str | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    page: int = 1,
) -> AepdSearchResult:
    """Search AEPD (Spanish DPA) resolutions by full text and/or signature date.

    Args:
        texto: full-text query (Solr), e.g. ``"videovigilancia"`` - an expediente
            number also works as an exact query.
        fecha_desde: earliest signature date, ``dd/mm/aaaa``.
        fecha_hasta: latest signature date, ``dd/mm/aaaa``.
        page: 1-based results page (10 hits per page).

    Returns:
        ``AepdSearchResult`` with ``total`` and hits carrying ``expediente`` and the
        full-text ``pdf_url`` permalink.
    """
    audit = _audit()
    if not texto and not fecha_desde:
        raise ToolError("invalid_arg", "Provide texto and/or fecha_desde.")
    fd = _require_ddmmyyyy(fecha_desde, "fecha_desde")
    fh = _require_ddmmyyyy(fecha_hasta, "fecha_hasta")
    if page < 1:
        raise ToolError("invalid_arg", "page must be >= 1.")
    input_hash = hash_input({"texto": texto, "fd": fd, "fh": fh, "page": page})

    with timer() as t:
        try:
            async with AepdClient(base_url=_aepd_base_url()) as client:
                result = await client.search(
                    texto=texto.strip() if texto else None,
                    fecha_desde=fd, fecha_hasta=fh, page=page,
                )
        except Exception as exc:
            audit.log(tool="es_search_aepd_resolutions", input_hash=input_hash,
                      output_count_or_size=0, duration_ms=t.duration_ms if t.duration_ms else 0,
                      status="error", error=f"{type(exc).__name__}: {exc}")
            raise _map_upstream_extra(exc) from exc

    items = [
        AepdResolutionModel(
            expediente=h.expediente,
            pdf_url=h.pdf_url,
            fecha_firma=h.fecha_firma,
            snippet=h.snippet,
            human_readable_citation=aepd_human_citation(h.expediente, h.fecha_firma),
            source_url=h.pdf_url,
        )
        for h in result.hits
    ]
    out = AepdSearchResult(total=result.total, page=result.page, items=items)
    audit.log(tool="es_search_aepd_resolutions", input_hash=input_hash,
              output_count_or_size=len(items), duration_ms=t.duration_ms, status="ok")
    return out


@mcp.tool(annotations=READ_ONLY)
async def es_get_aepd_resolution(expediente: str) -> AepdResolutionModel:
    """Resolve an AEPD expediente number to its resolution and full-text PDF permalink.

    Args:
        expediente: the AEPD procedure number, e.g. ``"PS-00615-2025"`` (PS = sanciones,
            PD = derechos, AI = actuaciones de investigacion).

    Returns:
        ``AepdResolutionModel`` with ``pdf_url`` (the full resolution PDF),
        ``fecha_firma``, ``human_readable_citation`` and ``source_url``.
    """
    audit = _audit()
    exp = (expediente or "").strip()
    if not exp:
        raise ToolError("invalid_arg", "expediente must not be empty, e.g. 'PS-00615-2025'.")
    input_hash = hash_input({"expediente": exp})

    with timer() as t:
        try:
            async with AepdClient(base_url=_aepd_base_url()) as client:
                hit = await client.get_resolution(exp)
        except Exception as exc:
            audit.log(tool="es_get_aepd_resolution", input_hash=input_hash,
                      output_count_or_size=0, duration_ms=t.duration_ms if t.duration_ms else 0,
                      status="error", error=f"{type(exc).__name__}: {exc}")
            raise _map_upstream_extra(exc) from exc

    out = AepdResolutionModel(
        expediente=hit.expediente,
        pdf_url=hit.pdf_url,
        fecha_firma=hit.fecha_firma,
        snippet=hit.snippet,
        human_readable_citation=aepd_human_citation(hit.expediente, hit.fecha_firma),
        source_url=hit.pdf_url,
    )
    audit.log(tool="es_get_aepd_resolution", input_hash=input_hash, output_count_or_size=1,
              duration_ms=t.duration_ms, status="ok")
    return out


def main() -> None:
    """Run the MCP server over stdio (default for Claude Code)."""
    mcp.run()


if __name__ == "__main__":
    main()
