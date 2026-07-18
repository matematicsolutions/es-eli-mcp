# es-eli-mcp

<!-- mcp-name: io.github.matematicsolutions/es-eli-mcp -->


## Install (one command)

Published on PyPI + MCP Registry (`io.github.matematicsolutions/es-eli-mcp`). Run without cloning:

```bash
uvx es-eli-mcp
```

Configure your MCP client (stdio):

```json
{ "mcpServers": { "es-eli-mcp": { "command": "uvx", "args": ["es-eli-mcp"] } } }
```

### Windows 11 with Smart App Control

Smart App Control blocks unsigned executables, which covers `uvx.exe`, `pip.exe`
and the `es-eli-mcp.exe` launcher that pip writes at install time. The `python.exe` and
`py.exe` from the python.org installer are signed by the Python Software
Foundation, so running the module through the interpreter works:

```bash
python -m pip install es-eli-mcp
python -m es_eli_mcp
```

`pip.exe` is blocked for the same reason, so install with `python -m pip`, not
`pip install`. If `python` is not on PATH, use the Windows launcher: `py -3 -m es_eli_mcp`.

```json
{ "mcpServers": { "es-eli-mcp": { "command": "python", "args": ["-m", "es_eli_mcp"] } } }
```

Do not turn Smart App Control off to work around this - it cannot be re-enabled
without reinstalling Windows.

Building from source: see [Install](#install).

An MCP server for five Spanish open-data sources:

1. **BOE** (Boletin Oficial del Estado) open-data API - consolidated legislation. Given a BOE id
   or a date in the official gazette, returns metadata, structure and full consolidated text,
   with verifiable ELI identifiers and Spanish citations.
2. **Tribunal Constitucional** (Sistema HJ / `hj.tribunalconstitucional.es`) - Spain's
   Constitutional Court case law (Sentencias / Autos / Declaraciones). Given an internal
   resolution id, or a citation number+year (e.g. "STC 31/2010"), returns the full ruling with
   ECLI and a Spanish doctrinal citation.
3. **DGT** (Direccion General de Tributos, `petete.tributos.hacienda.gob.es`) - binding tax
   rulings: ~69,500 consultas vinculantes + ~19,700 consultas generales (live-counted
   2026-07-08). Full-text/date search plus the full ruling text by NUM-CONSULTA (e.g.
   "V0001-25").
4. **TEAC** (Tribunales Economico-Administrativos, DYCTEA) - ~6,500 doctrine criterios with the
   full resolution text inline, searched by RG claim-number segments and/or date range.
5. **AEPD** (Agencia Espanola de Proteccion de Datos) - ~46,800 data-protection resolutions
   with Solr full-text search and a verified PDF permalink per expediente (e.g.
   "PS-00615-2025").

Part of the MateMatic `eu-legal-mcp` production line - after PL, DE and AT. Same citation
contract pattern, five Spanish sources.

> **Free-text search exists on DGT and AEPD only.** The BOE open-data keyword-search endpoint
> (`/legislacion-consolidada`) currently returns a server-side error; the Tribunal
> Constitucional site only supports structured search (citation number+year, ECLI, magistrado,
> materia); DYCTEA accepts text-looking parameters but silently ignores them (verified live).
> Discover BOE documents via `es_browse_gazette` (by date) or a known BOE id / ELI; TC rulings
> via `es_search_constitutional`; TEAC criterios via RG segments or dates. Every response
> carries a `dataset_note`.
>
> **Licence.** Both sources are official public information published as Spanish PSI
> (public-sector information) open data; reuse presumes acceptance of the respective reuse
> conditions. This connector relays that public content with attribution and a `source_url`.

## The tools

| Tool | What it does |
|---|---|
| `es_browse_gazette` | List documents published in the BOE on a date (`YYYYMMDD`) - discovery. |
| `es_get_act` | Metadata for a BOE id (eli_uri, official `titulo`, source). |
| `es_get_index` | The block index (articles, titles) of a consolidated law. |
| `es_get_text` | Consolidated text (XML), whole or by block. |
| `es_get_constitutional_ruling` | Tribunal Constitucional ruling by internal resolution id. |
| `es_search_constitutional` | Resolve a citation (numero+anno, e.g. 31/2010) to the full TC ruling. |
| `es_search_tax_rulings` | Full-text/date search over DGT consultas (vinculantes or generales). |
| `es_get_tax_ruling` | Full DGT ruling (facts, question, normativa, answer) by NUM-CONSULTA. |
| `es_search_teac_doctrine` | TEAC criterios by RG segments and/or resolution-date range. |
| `es_get_teac_criterio` | Full TEAC criterio + resolution text by DYCTEA id. |
| `es_search_aepd_resolutions` | Full-text/date search over AEPD resolutions. |
| `es_get_aepd_resolution` | AEPD resolution + verified full-text PDF permalink by expediente. |

Every BOE response carries the contract: `eli_uri` (a full ELI URL, e.g.
`https://www.boe.es/eli/es/lo/2018/12/05/3`), `human_readable_citation` (the official
`titulo`), and `source_url`.

Every Tribunal Constitucional response carries: `ecli` (e.g. `ECLI:ES:TC:2010:31` - TC case law
has no ELI, ELI covers legislation only), `human_readable_citation` (Spanish doctrinal
convention, e.g. "STC 31/2010, de 28 de junio"), and `source_url`.

## Install

```bash
cd es-eli-mcp
pip install -e .
```

## Configure (Claude Code / any MCP client)

```json
{
  "mcpServers": {
    "es-eli-mcp": { "command": "es-eli-mcp" }
  }
}
```

Environment:

- `ES_ELI_BASE_URL` - default `https://www.boe.es/datosabiertos/api`
- `ES_ELI_TC_BASE_URL` - default `https://hj.tribunalconstitucional.es`
- `ES_ELI_DGT_BASE_URL` - default `https://petete.tributos.hacienda.gob.es`
- `ES_ELI_TEAC_BASE_URL` - default `https://serviciostelematicosext.hacienda.gob.es/TEAC/DYCTEA`
- `ES_ELI_AEPD_BASE_URL` - default `https://www.aepd.es`
- `ES_ELI_CACHE_DIR` - default `~/.matematic/cache/es-eli`
- `ES_ELI_AUDIT_DIR` - default `~/.matematic/audit`

No API key. All five sources are keyless.

## Governance

- **Public data only** - read-only against the five official sources; no client data leaves the machine.
- **Audit log** - every tool call appends one JSON line to `~/.matematic/audit/es-eli-mcp.jsonl`.
- **Vendor-neutral** - talks only to the official `*.boe.es` / `*.tribunalconstitucional.es` / `*.hacienda.gob.es` / `*.aepd.es` hosts; no LLM provider, no telemetry.
- **Verifiable citations** - every response is independently checkable via `source_url`.

See `CONSTITUTION.md` and `DISCOVERY.md`.

## Tests

```bash
pip install -e ".[dev]"
pytest tests/ --ignore=tests/test_smoke.py -v   # offline (fixtures)
pytest tests/test_smoke.py -v                   # hits live BOE + TC + DGT + TEAC + AEPD
```

## Licence

Apache-2.0. © Matematic Solutions / Wieslaw Mazur.
