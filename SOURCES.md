# Sources ledger - Spain (ES)

See `eu-legal-mcp/PLAYBOOK.md` section 8 and `eu-legal-mcp/template/SOURCES.template.md` for the
process this file supports.

| LDH id | LDH name | Our status | Our tool(s) | Notes / rejection reason |
|---|---|---|---|---|
| ES/BOE | Official Gazette + consolidated legislation | shipped | `es_get_act`, `es_get_index`, `es_get_text`, `es_browse_gazette` | original build, ~12 331 consolidated acts live-confirmed |
| ES/ConstitutionalCourt | Tribunal Constitucional | shipped | `es_get_constitutional_ruling`, `es_search_constitutional` | 2026-07-07, commit 2e7d1f8. `hj.tribunalconstitucional.es` (plain ASP.NET HTML, no CAPTCHA) - the institutional site `www.tribunalconstitucional.es` is bot-gated (403) but this is the same ruling database LDH itself uses. ~30k+ decisions, sequential internal ids 1-30225 + 31220-present. BOE has NO separate constitutional-jurisprudence endpoint (checked live, 404) - it only announces publication, not full text. |
| ES/DGT-Consultas | Binding tax rulings (Consultas Vinculantes) | todo | - | scouted: `petete.tributos.hacienda.gob.es/consultas` responds 200, same HTML-form pattern as the TC client (`tc_client.py`) could be reused. Deprioritized behind constitutional-court work this round, not because it's hard. |
| ES/TribunalSupremo | Supreme Court | rejected | - | `captcha_required` per LDH's own manifest; not attempted this round |
| ES regional legislation (17 comunidades) | various | todo | - | not yet evaluated, lower priority than national courts |

Last updated: 2026-07-07 (widen round, see `eu-legal-mcp/AUDIT-LOG.md`).
