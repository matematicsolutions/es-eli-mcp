# Discovery: BOE open-data API (boe.es) - Spain

Date: 2026-06-24. **Status: CLOSED** for a grounding + gazette MVP (confirmed by live probing).

Spanish BOE (Boletin Oficial del Estado) open-data API. Keyless. Strong for GET-by-id and the
daily gazette; the consolidated-legislation keyword-search endpoint is broken server-side.

## Base API properties (CONFIRMED)

- **Base URL:** `https://www.boe.es/datosabiertos/api`
- **Authentication:** none (open data).
- **Formats:** JSON for metadata/index/gazette (`Accept: application/json`, wrapped in `{status, data}`);
  **XML only** for consolidated text blocks (`Accept: application/xml`; JSON returns 400).
- **ELI:** YES - full URL in `url_eli` (e.g. `https://www.boe.es/eli/es/lo/2018/12/05/3`).

## Endpoints

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/legislacion-consolidada/id/{id}/metadatos` | GET (json) | OK | metadata incl. `url_eli`, `titulo`, `url_html_consolidada` |
| `/legislacion-consolidada/id/{id}/texto/indice` | GET (json) | OK | block index `data[0].bloque[]` {id, titulo, url} |
| `/legislacion-consolidada/id/{id}/texto` | GET (xml) | OK | full consolidated text |
| `/legislacion-consolidada/id/{id}/texto/bloque/{block_id}` | GET (xml) | OK | one block: `<response><data><bloque><version><p>...` |
| `/legislacion-consolidada/id/{id}/metadata-eli` | GET | OK | dedicated ELI metadata (url_eli already in metadatos) |
| `/boe/sumario/{YYYYMMDD}` | GET (json) | OK | daily gazette; nested tree, items carry `identificador` + `titulo` |
| `/legislacion-consolidada` (keyword search) | GET | **HTTP 500** | broken server-side for all params (query/from-to/limit). NOT shipped. |

## Citation contract (Article IV) - CLOSED for ES

- `eli_uri` = `url_eli` (full ELI URL).
- `human_readable_citation` = `titulo` (the official Spanish citation, trailing period trimmed),
  e.g. "Ley Organica 3/2018, de 5 de diciembre, de Proteccion de Datos Personales...".
- `source_url` = `url_html_consolidada` (the openable consolidated-text page).

## Tool mapping - grounding + gazette MVP

| Tool | Endpoint |
|---|---|
| `es_browse_gazette` | `/boe/sumario/{date}` (discovery by date) |
| `es_get_act` | `/id/{id}/metadatos` |
| `es_get_index` | `/id/{id}/texto/indice` |
| `es_get_text` | `/id/{id}/texto` or `/texto/bloque/{block_id}` (XML) |

**Deferred / known limitation:** free-text search - the BOE open-data search endpoint returns 500.
Discovery is by date (gazette) or by known id/ELI. A future option: wrap the BOE HTML buscador, or
retry the open-data search if BOE fixes it.

## Differences vs DE/AT/PL

- Discovery is **not** keyword search (upstream broken) - it is by-id / by-date. Different shape, honestly scoped.
- Mixed formats: metadata/index/gazette JSON, but legal text XML-only.
- ELI is a full URL; `titulo` is already the canonical citation (no assembly).

## Decision: BUILD (grounding + gazette)

ELI present, keyless, official, rich GET-by-id + gazette. Reuse from the line: audit + cache verbatim,
server pattern. New: BOE client (status-envelope unwrap, JSON+XML), citations (metadata flatten + gazette walk).
WM chose this over pivoting to a working-search country (ROI: largest reachable market, grounding is the core value).
