# MCP-vs-tk benchmark

On 2026-11-03, `ASabale/agent-toolkit@b7f6189` still had no reproducible measurement of VISION.md §1 MCP idle bloat against tk's §2.2 idle / discovery / output budget. `tests/test_token_budget.py` gated SKILL.md and `tk find` size only. This page records the first offline, model-free run of `python3 bench/mcp_vs_tk.py --json` over committed fixtures.

Token figures below are `bytes/4` estimates, labelled as such by the script. They are not model tokenizer counts.

## Capture provenance

Fixtures were recorded on 2026-11-03 from public servers. No tool-list or result payload was invented.

| Task | MCP source | `server_version` | Subject |
|---|---|---|---|
| why is CI red on PR N | https://github.com/github/github-mcp-server/releases/tag/v2.1.0 | 2.1.0 (default toolsets) | https://github.com/cli/cli/pull/14927 (`build (windows-latest)` failed) |
| show schema + 5 rows of table T | https://www.npmjs.com/package/mcp-server-sqlite-npx | 0.8.0 | Chinook `Album` from https://github.com/lerocha/chinook-database |
| read the text of URL U | https://pypi.org/project/mcp-server-fetch/2026.10.28/ | 2026.10.28 | https://example.com/ |

The official PyPI package `mcp-server-sqlite==2025.4.25` could not be captured: it exited on startup with `AttributeError: 'Server' object has no attribute 'list_resources'` against the MCP Python SDK installed that day. The recorded SQLite `tools/list` and query results come from the public npm port `mcp-server-sqlite-npx` 0.8.0 running against the public Chinook file.

GitHub MCP idle bytes are the compact JSON of the live `tools/list` result (46 tools, including the server's embedded icons). tk idle bytes are the live `skills/agent-toolkit/SKILL.md` size at `ASabale/agent-toolkit@b7f6189` (1,713 bytes). tk discovery and output are live `tk find` / `tk run` against local stubs of the same captured subjects (a `gh` stub of `cli/cli#14927` `statusCheckRollup`, a five-row Album SQLite extract, and the saved `example.com` HTML).

## First results (`ASabale/agent-toolkit@b7f6189`, 2026-11-03)

| Task | Side | idle bytes | discovery bytes | output bytes | tool calls | est. tokens (`bytes/4`) |
|---|---|---|---|---|---|---|
| why is CI red on PR N | MCP | 126642 | 0 | 9879 | 2 | 34130 |
| why is CI red on PR N | tk | 1713 | 482 | 172 | 1 | 591 |
| show schema + 5 rows of table T | MCP | 1656 | 0 | 1469 | 3 | 781 |
| show schema + 5 rows of table T | tk | 1713 | 536 | 669 | 2 | 729 |
| read the text of URL U | MCP | 1160 | 0 | 271 | 1 | 357 |
| read the text of URL U | tk | 1713 | 757 | 279 | 1 | 687 |

The fetch row's MCP output is the committed fixture (271 bytes). A live `mcp-server-fetch` 2026.10.28 read of the same URL is 246 bytes when `node` is on `PATH`.

MCP discovery is 0 because `tools/list` is already in the always-loaded system prompt (VISION.md §1). tk discovery is the `tk find` stdout for that task.

The GitHub default toolset alone is 126,642 idle bytes (~31k estimated tokens) before the first user message, against 1,713 idle bytes for SKILL.md. The one-tool fetch server and the five-tool SQLite server are smaller than SKILL.md plus `tk find`, so a single tiny MCP can beat tk on that task's estimated total; the VISION claim is about stacking many such servers, not that every individual MCP is larger than SKILL.md.

## Related

- [0002 — Minimum cognitive load and tokens](../decisions/0002-minimum-cognitive-load-and-tokens.md)
- [Catalog and check](catalog-and-check.md)
