# Constitution of es-eli-mcp

Version: 0.1.0
Date: 2026-06-24
Licence: Apache-2.0

`es-eli-mcp` is an MCP server for the Spanish BOE open-data API (`boe.es/datosabiertos`,
Boletin Oficial del Estado). It grounds Spanish consolidated legislation by BOE id / ELI and
browses the daily gazette, with verifiable ELI citations. The MVP is grounding + gazette;
free-text search is not offered (the BOE search endpoint is broken server-side).

The 4 principles below are inherited from the `eu-legal-mcp` line Constitution (Article IV).

---

## Art. 1. Public data only

The BOE open-data API is the official, public source of Spanish law. BOE content is official public
information published as open data; reuse presumes acceptance of the BOE reuse conditions. The server
is read-only against BOE and sends nothing beyond the requested id / date.

## Art. 2. Mandatory audit log

Every tool call MUST append one JSON line to `~/.matematic/audit/es-eli-mcp.jsonl`
(ts / tool / input_hash SHA-256 / output_count_or_size / duration_ms / status). Inability to write =
the tool returns an error, it does not silently skip.

## Art. 3. Vendor neutrality

No tool hardcodes an LLM provider, assumes a model, or adds commercial telemetry. The server talks
only to `boe.es` and the local filesystem. Authentication: none (open data); own backoff + cache.

## Art. 4. ELI citations and a human-readable citation are mandatory

Every response MUST carry three fields:
- `eli_uri`: the canonical ELI. BOE exposes it as a full URL in `url_eli` (stored verbatim).
- `human_readable_citation`: the official `titulo` (Spanish convention), e.g.
  "Ley Organica 3/2018, de 5 de diciembre, de Proteccion de Datos Personales...".
- `source_url`: the openable consolidated-text page (`url_html_consolidada`).

---

## Open points

1. **Free-text search** - the BOE open-data keyword-search endpoint returns HTTP 500; not shipped.
   Discovery is by date (gazette) or known id/ELI. Revisit if BOE fixes it, or wrap the HTML buscador.
2. **State law (autonomous communities)** and **case law** - not in this MVP.

## Ewolucja konstytucji

Changes to art. 1-4 follow SEMVER + an entry in `CHANGELOG.md` + a `pyproject.toml` bump.

First version: 2026-06-24. Author: Wieslaw Mazur / MateMatic.
