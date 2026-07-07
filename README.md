# es-eli-mcp

<!-- mcp-name: io.github.matematicsolutions/es-eli-mcp -->


## Instalacja (jedna komenda)

Opublikowany na PyPI + MCP Registry (`io.github.matematicsolutions/es-eli-mcp`). Uruchomienie bez klonowania:

```bash
uvx es-eli-mcp
```

Konfiguracja klienta MCP (stdio):

```json
{ "mcpServers": { "es-eli-mcp": { "command": "uvx", "args": ["es-eli-mcp"] } } }
```

(Budowanie ze źródeł — niżej.)

An MCP server for two Spanish open-data sources:

1. **BOE** (Boletin Oficial del Estado) open-data API - consolidated legislation. Given a BOE id
   or a date in the official gazette, returns metadata, structure and full consolidated text,
   with verifiable ELI identifiers and Spanish citations.
2. **Tribunal Constitucional** (Sistema HJ / `hj.tribunalconstitucional.es`) - Spain's
   Constitutional Court case law (Sentencias / Autos / Declaraciones). Given an internal
   resolution id, or a citation number+year (e.g. "STC 31/2010"), returns the full ruling with
   ECLI and a Spanish doctrinal citation.

Part of the MateMatic `eu-legal-mcp` production line - after PL, DE and AT. Same citation
contract pattern, two Spanish sources.

> **No free-text search on either source.** The BOE open-data keyword-search endpoint
> (`/legislacion-consolidada`) currently returns a server-side error; the Tribunal
> Constitucional site only supports structured search (citation number+year, ECLI, magistrado,
> materia), not a body-text query. Discover BOE documents via `es_browse_gazette` (by date) or a
> known BOE id / ELI; discover TC rulings via `es_search_constitutional` (citation number+year)
> or a known internal id. Every response carries a `dataset_note`.
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
- `ES_ELI_CACHE_DIR` - default `~/.matematic/cache/es-eli`
- `ES_ELI_AUDIT_DIR` - default `~/.matematic/audit`

No API key. Both BOE open data and the Tribunal Constitucional site are keyless.

## Governance

- **Public data only** - read-only against BOE; no client data leaves the machine.
- **Audit log** - every tool call appends one JSON line to `~/.matematic/audit/es-eli-mcp.jsonl`.
- **Vendor-neutral** - talks only to `boe.es`; no LLM provider, no telemetry.
- **Verifiable citations** - every response is independently checkable via `source_url`.

See `CONSTITUTION.md` and `DISCOVERY.md`.

## Tests

```bash
pip install -e ".[dev]"
pytest tests/test_instructions_drift.py tests/test_tc_offline.py -v   # offline
pytest tests/test_smoke.py -v                                          # hits live BOE + TC
```

## Licence

Apache-2.0. © Matematic Solutions / Wieslaw Mazur.
