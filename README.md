# es-eli-mcp

<!-- mcp-name: io.github.matematicsolutions/es-eli-mcp -->

An MCP server for the Spanish **BOE** (Boletin Oficial del Estado) open-data API. It grounds
Spanish consolidated legislation: given a BOE id or a date in the official gazette, it returns
metadata, structure and full consolidated text, with verifiable ELI identifiers and Spanish
citations.

Part of the MateMatic `eu-legal-mcp` production line - after PL, DE and AT. Same citation
contract, BOE source.

> **No free-text search.** The BOE open-data keyword-search endpoint
> (`/legislacion-consolidada`) currently returns a server-side error, so this connector is
> grounding + gazette-browse, not keyword search. Discover documents via `es_browse_gazette`
> (by date) or use a known BOE id / ELI. Every response carries a `dataset_note`.
>
> **Licence.** Spanish BOE content is official public information published as open data;
> reuse presumes acceptance of the BOE reuse conditions. This connector relays that public
> content with attribution and a `source_url`.

## The tools

| Tool | What it does |
|---|---|
| `es_browse_gazette` | List documents published in the BOE on a date (`YYYYMMDD`) - discovery. |
| `es_get_act` | Metadata for a BOE id (eli_uri, official `titulo`, source). |
| `es_get_index` | The block index (articles, titles) of a consolidated law. |
| `es_get_text` | Consolidated text (XML), whole or by block. |

Every response carries the contract: `eli_uri` (a full ELI URL, e.g.
`https://www.boe.es/eli/es/lo/2018/12/05/3`), `human_readable_citation` (the official
`titulo`), and `source_url`.

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
- `ES_ELI_CACHE_DIR` - default `~/.matematic/cache/es-eli`
- `ES_ELI_AUDIT_DIR` - default `~/.matematic/audit`

No API key. BOE open data is keyless.

## Governance

- **Public data only** - read-only against BOE; no client data leaves the machine.
- **Audit log** - every tool call appends one JSON line to `~/.matematic/audit/es-eli-mcp.jsonl`.
- **Vendor-neutral** - talks only to `boe.es`; no LLM provider, no telemetry.
- **Verifiable citations** - every response is independently checkable via `source_url`.

See `CONSTITUTION.md` and `DISCOVERY.md`.

## Tests

```bash
pip install -e ".[dev]"
pytest tests/test_instructions_drift.py -v   # offline
pytest tests/test_smoke.py -v                # hits live BOE
```

## Licence

Apache-2.0. © Matematic Solutions / Wieslaw Mazur.
