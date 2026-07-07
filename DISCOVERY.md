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

---

# Discovery: Tribunal Constitucional (hj.tribunalconstitucional.es) - 2026-07-07

Date: 2026-07-07. **Status: CLOSED** for id-based grounding + citation-number lookup (confirmed by
live probing). Gap found against Legal Data Hunter (`worldwidelaw/legal-sources` manifest, entry
`ES/ConstitutionalCourt`, `status: complete`, ~30K+ decisions, sequential-id + multi-range
iteration 1-30225 / 31220-current).

## Base site properties (CONFIRMED)

- **Base URL:** `https://hj.tribunalconstitucional.es` ("Sistema HJ / Buscador de jurisprudencia
  constitucional"). NOT the same host as `www.tribunalconstitucional.es` (the institutional
  site), which sits behind a Transparent Edge/Cloudflare-style JS bot-challenge (403 on direct
  fetch) - HJ is a separate, unprotected ASP.NET MVC subdomain.
- **No JSON API** - classic server-rendered HTML (IIS / ASP.NET MVC 4, anti-forgery tokens,
  session cookies). No `robots.txt` (404), no CAPTCHA encountered on either the resolution page
  or the search form.
- **BOE open-data API has no separate jurisprudencia-constitucional endpoint** - probed
  `/datosabiertos/api/jurisprudencia-constitucional` (404) and confirmed TC rulings are outside
  the `/legislacion-consolidada` scope; BOE only publishes the *announcement* of TC sentencias in
  its daily gazette (`Número y fecha BOE` field on the HJ ficha técnica), not the operative text.
- **Sequential internal ids** - `GET /es/Resolucion/Show/{id}` (e.g. `25015` -> SENTENCIA
  117/2016). A not-found/out-of-range id 200s but silently redirects to the search-form page
  (title "Buscador de jurisprudencia constitucional" instead of "Resolución: ..."); this is the
  not-found signal used by `tc_client.TcClient.get_resolution`.
- **No ELI** - ELI covers Spanish legislation, not TC case law. **ECLI is the identifier**
  (e.g. `ECLI:ES:TC:2016:117`), present on every resolution page.
- **Citation lookup by number+year works via the real search form**, not a permalink:
  1. `GET /es/Busqueda/Index` - collect `__RequestVerificationToken` + session cookie.
  2. `POST /es/Busqueda/Buscar` with `TIPO_RESOLUCION=SENTENCIA|AUTO|DECLARACION` (checkbox
     value, not an int code - this was the first failed probe attempt: `TIPO_RESOLUCION=2`
     produced a 302-to-error "Ha ocurrido un error inesperado"), `NUMERO_RESOLUCION`,
     `ANNO_RESOLUCION`. Returns 302 to `/es/Resolucion/List` with results kept server-side in
     the session (cookie jar must be shared with the next request, not re-sent per-call).
  3. `GET /es/Resolucion/List` (same client/cookies) - HTML list; parse
     `href="...Resolucion/Show/{id}"` anchors and match label against `"{TIPO} {numero}/{anno}"`.
  - Verified live: `NUMERO_RESOLUCION=31&ANNO_RESOLUCION=2010&TIPO_RESOLUCION=SENTENCIA` ->
    resolves to id `6670` -> STC 31/2010 ("de 28 de junio", ECLI:ES:TC:2010:31, the landmark
    Catalan Statute of Autonomy ruling). No CAPTCHA on this flow.

## Page structure (per resolution)

- `<title>` - "Sistema HJ - Resolución: SENTENCIA 117/2016" (no date - used only for the
  not-found/found signal).
- `<li id="resolucion-identifier"><h2>` - full heading "SENTENCIA 117/2016, de 20 de junio" +
  `(BOE núm. ..., de ...)` in a nested `<span>` (used as `title` for citation formatting).
- `<label class="ecli">` - ECLI.
- Sala/Pleno - "Pleno" | "Sala Primera" | "Sala Segunda" appears in the encabezamiento prose
  (regex-matched, no dedicated tag).
- `<p id="resolucion-sentencia">` - encabezamiento (case summary / procedural header, prose).
- `<p id="dictamen-texto">` (+ siblings) - fallo (operative ruling / holding).
- `#ficha-tecnica`, `#extractos`, `#indices`, `#descriptores` sections exist (BOE number/date,
  headnote extracts, cited-provision index, subject descriptors) - not extracted in this MVP;
  candidates for a v0.3 if deeper indexing is wanted.

## Citation contract (Article IV, amended for TC) - CLOSED for ES/TC

- `ecli` = the `<label class="ecli">` text (verbatim), e.g. `ECLI:ES:TC:2010:31`.
- `human_readable_citation` = the heading with the type word mapped to the Spanish doctrinal
  abbreviation: `SENTENCIA` -> `STC`, `AUTO` -> `ATC`, `DECLARACION` -> `DTC`, e.g.
  "STC 31/2010, de 28 de junio" (`citations.tc_human_citation`).
- `source_url` = `https://hj.tribunalconstitucional.es/es/Resolucion/Show/{id}`.

## Tool mapping

| Tool | Flow |
|---|---|
| `es_get_constitutional_ruling` | `GET /es/Resolucion/Show/{id}` (direct, if id already known) |
| `es_search_constitutional` | 3-request session flow above, then `get_resolution` on the resolved id |

**Deferred / known limitation:** no full-text keyword search (the site's own search form only
supports number+year, ECLI, magistrado, materia, descriptores, date range - not a body-text
query); `#extractos`/`#descriptores` sections are not yet parsed into structured fields.

## Priority 2 scouted, not built: ES/DGT-Consultas (binding tax rulings)

`https://petete.tributos.hacienda.gob.es/consultas` responds 200, same shape as TC (HTML
"Buscador" with a search form, no JSON API). Time budget for this round went to TC (higher
governance priority - constitutional review vs. tax doctrine); DGT-Consultas is a same-pattern
follow-up (new client module mirroring `tc_client.py`, own search-form fields) for a future
session, not started beyond the reachability probe.

## Decision: BUILD (TC id-lookup + citation-number search)

No JSON API, but a clean, unprotected HTML surface with real structured fields (ECLI, sala,
encabezamiento, fallo) and a genuine (non-CAPTCHA) search form for citation resolution - same
risk profile as a typical government HTML portal already in the fleet, not a ToS-fragile scrape.
Closes the largest LDH-flagged gap for `es-eli-mcp` (constitutional case law, `status: complete`
on their side, `priority: 2`).
