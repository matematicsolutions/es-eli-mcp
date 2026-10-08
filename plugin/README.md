# es-eli-mcp - Claude plugin

Spanish law with verifiable citations, as a Claude plugin. It runs the
[es-eli-mcp](https://github.com/matematicsolutions/es-eli-mcp) MCP server, version 0.5.3
from PyPI. `uv.lock`, next to the manifest, pins that package and every dependency with
hashes. The plugin starts it with `uvx es-eli-mcp==0.5.3`, and Claude Code's locked launch
installs exactly the set in `uv.lock`, so it runs what was reviewed. (Run by hand outside
Claude Code, plain `uvx` resolves the dependency ranges from PyPI instead.) Every
answer carries the official source, so a citation can be checked instead of trusted.

What it covers: consolidated legislation and the daily gazette from the BOE open data API (ELI identifiers, index and text blocks), Constitutional Court rulings (hj.tribunalconstitucional.es), binding tax rulings of the Directorate-General for Taxes (DGT), TEAC doctrine (Tribunal Economico-Administrativo Central) and AEPD resolutions. The full tool list is in the
[main README](https://github.com/matematicsolutions/es-eli-mcp#readme).

## Requirements

Claude Code or the Claude desktop app, and [uv](https://docs.astral.sh/uv/) on your
machine (its `uvx` installs the locked packages on first start and runs the server).

## Install

```
/plugin marketplace add matematicsolutions/es-eli-mcp
/plugin install es-eli-mcp@es-eli-mcp
```

## Data

The server runs on your machine. Each tool call sends your query to the official Spanish source it names (BOE, Tribunal Constitucional, DGT at hacienda.gob.es, TEAC or AEPD)
and to nothing else; nothing goes to MateMatic. Your query and the results also pass
through whatever model you use, the same way as any other message.

The standalone server can fetch a small configuration file (updated source addresses) from
this repository's GitHub Releases on first use. The plugin turns that off
(`ES_ELI_RUNTIME_URL` set to empty in `plugin.json`), so it runs only the reviewed code with
its built-in source addresses and makes no request other than the tool calls above.

Two things are written locally, in your home directory:

- a response cache (`~/.matematic/cache/es-eli`), so a repeated lookup does not hit
  the source again. Court decisions are public records and can name the parties.
- an audit log (`~/.matematic/audit/es-eli-mcp.jsonl`), one line per tool call: the
  tool name, a SHA-256 hash of the input (not the input itself), result size, time
  and status.

Delete either folder at any time; `ES_ELI_CACHE_DIR` and `ES_ELI_AUDIT_DIR` move them.

## Licence

Apache-2.0, see the repository's [LICENSE](https://github.com/matematicsolutions/es-eli-mcp/blob/main/LICENSE).
