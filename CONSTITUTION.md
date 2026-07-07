# Constitution of es-eli-mcp

Version: 0.2.0
Date: 2026-07-07
Licence: Apache-2.0

`es-eli-mcp` is an MCP server for two Spanish open-data sources: the BOE open-data API
(`boe.es/datosabiertos`, Boletin Oficial del Estado) and the Tribunal Constitucional
jurisprudence database (`hj.tribunalconstitucional.es`). It grounds Spanish consolidated
legislation by BOE id / ELI and browses the daily gazette, and it grounds Tribunal
Constitucional case law (Sentencias/Autos/Declaraciones) by internal id or by citation
number+year, with verifiable ELI / ECLI citations. Free-text keyword search is not offered on
either source (the BOE search endpoint is broken server-side; the TC site only supports
structured search by citation number+year, ECLI, magistrado, materia - not by keyword).

The 4 principles below are inherited from the `eu-legal-mcp` line Constitution (Article IV).

---

## Art. 1. Public data only

Both sources are official, public Spanish government data. BOE content and Tribunal
Constitucional resolutions are official public information published as open data (Spanish
PSI reuse regulations, `datos.gob.es/en/terms`); reuse presumes acceptance of the respective
reuse conditions. The server is read-only against both sources and sends nothing beyond the
requested id / date / citation number.

## Art. 2. Mandatory audit log

Every tool call MUST append one JSON line to `~/.matematic/audit/es-eli-mcp.jsonl`
(ts / tool / input_hash SHA-256 / output_count_or_size / duration_ms / status). Inability to write =
the tool returns an error, it does not silently skip.

## Art. 3. Vendor neutrality

No tool hardcodes an LLM provider, assumes a model, or adds commercial telemetry. The server talks
only to `boe.es`, `hj.tribunalconstitucional.es`, and the local filesystem. Authentication: none
(open data); own backoff + cache.

## Art. 4. Verifiable citations are mandatory

Every BOE response MUST carry:
- `eli_uri`: the canonical ELI. BOE exposes it as a full URL in `url_eli` (stored verbatim).
- `human_readable_citation`: the official `titulo` (Spanish convention), e.g.
  "Ley Organica 3/2018, de 5 de diciembre, de Proteccion de Datos Personales...".
- `source_url`: the openable consolidated-text page (`url_html_consolidada`).

Every Tribunal Constitucional response MUST carry (TC case law has no ELI - ELI covers
legislation, not case law):
- `ecli`: the European Case Law Identifier (e.g. `ECLI:ES:TC:2010:31`), the verifiable
  identifier for this source.
- `human_readable_citation`: the Spanish doctrinal convention, e.g. "STC 31/2010, de 28 de
  junio".
- `source_url`: the openable resolution page (`hj.tribunalconstitucional.es/es/Resolucion/Show/{id}`).

---

## Open points

1. **Free-text search** - the BOE open-data keyword-search endpoint returns HTTP 500; not shipped.
   Discovery is by date (gazette) or known id/ELI. Revisit if BOE fixes it, or wrap the HTML buscador.
2. **State law (autonomous communities)** - not in this MVP.
3. **Tribunal Constitucional free-text content search** - the site's search form supports
   citation number+year, ECLI, magistrado, materia, descriptores and date ranges, but not a
   full-text keyword search across resolution content; only number+year lookup is shipped
   (`es_search_constitutional`). Revisit if a materia/descriptor-based tool proves valuable.
4. **DGT-Consultas (binding tax rulings)** - scouted (has a similar HTML search form at
   `petete.tributos.hacienda.gob.es/consultas`) but not built in this round; deferred to a
   future session (see DISCOVERY.md).

## Ewolucja konstytucji

Changes to art. 1-4 follow SEMVER + an entry in `CHANGELOG.md` + a `pyproject.toml` bump.

First version: 2026-06-24. v0.2.0 (2026-07-07): added Tribunal Constitucional case law
(`es_get_constitutional_ruling`, `es_search_constitutional`) - Art. 1/3/4 extended to cover the
second source; Art. 4's ELI requirement narrowed to BOE only (TC uses ECLI). Author: Wieslaw
Mazur / MateMatic.
