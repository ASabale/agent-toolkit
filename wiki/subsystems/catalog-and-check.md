# Catalog and check

On 2026-11-03, `ASabale/agent-toolkit@9d469d7` added `lib/catalog.py` (530 lines in that commit). `CODING_STANDARDS.md` at the same commit named this module the discovery, indexing, and validation seam. The public functions in that file were `parse_tool_header`, `load_chain`, `discover_catalog`, `find_items`, `format_find_output`, `format_info_output`, `check_item`, and `check_all`.

## Index

On 2026-11-03, `parse_tool_header` at `ASabale/agent-toolkit@9d469d7` read the leading `# @tk-*` comment block and returned a dict with `kind: "tool"`, `name`, `summary`, `safety`, `args`, `output`, `example`, `verified`, and `path`. Each `@tk-arg` line split on `|` into flag, required-or-optional, type (`string`, `int`, `float`, `bool`), and description. A parenthetical `(default: X)` in the description became `default`. The env var was `TK_ARG_` plus the flag with the leading dashes removed, hyphens turned into underscores, and the remainder uppercased.

On 2026-11-03, `load_chain` at the same commit read `chains/<name>.json` and normalized `kind: "chain"` with `name`, `summary`, `safety`, `args`, `steps`, `output`, `example`, `verified`, and `path`.

On 2026-11-03, `discover_catalog` scanned `root_dir/tools` recursively, skipped path parts starting with `.` or `__`, and scanned `root_dir/chains/*.json`. Keys were item names (or a relative path / filename when the name was empty), and the returned dict was sorted by key. An unexpected failure returned whatever items had already been collected, still sorted.

On 2026-11-03 the catalog at `ASabale/agent-toolkit@9d469d7` included these tool files: `tools/fs/tree-digest`, `tools/gh/pr-failure-digest`, `tools/git/branch-digest`, `tools/git/diff-digest`, `tools/git/log-recent`, `tools/http/json-get`, `tools/json/pick`, and `tools/sys/port-owner`. `tools/git/branch-digest` carried `@tk-verified: 2026-11-03`. `chains/git.repo-health.json` carried `"verified": "none"`. `tools/.template` stayed a hidden-prefix file (`discover_catalog` skipped parts that start with `.`). *(Superseded on 2026-11-04 by `ASabale/agent-toolkit@c37e045`, which added `tools/docs/python-symbol`, `tools/gh/issue-view`, `tools/gh/search-code`, `tools/py/test-digest`, and `chains/gh.triage-pr.json`; and further superseded on 2026-11-04 by `ASabale/agent-toolkit@46a6538`, which added `tools/sql/schema`, `tools/sql/query`, `tools/web/read-text`, `tools/log/tail-errors`, `tools/wiki/lint`, and `chains/sql.inspect-db.json`, bringing the verified catalog to 20 items.)*

## Find ranking

On 2026-11-03, `find_items` at `ASabale/agent-toolkit@9d469d7` returned every item sorted by name when the query was empty. A non-empty query scored tokens against the name (exact name or name segment: 5; substring: 3), the summary (2), and arg flags plus descriptions (1). Matches sorted by descending score, then name. Zero-score items were omitted. `format_find_output` emitted the two-line shape required by [0002](../decisions/0002-minimum-cognitive-load-and-tokens.md). `format_info_output` printed name, kind, safety, summary, args, output, example, and verified.

On 2026-11-03, `tk` `_cmd_find` called this formatter and, when the formatted text was empty, called `log_event` with `search_miss`. See [Evolver and quarantine](evolver-and-quarantine.md).

## Check

On 2026-11-03, `check_item` at `ASabale/agent-toolkit@9d469d7` returned `{"name", "ok", "errors"}`. For tools it required the file to exist and to be executable, required header fields `name`, `summary`, `safety` in `{read-only, mutating, destructive}`, `output`, `example`, and `verified`, required the example to start with `tk run <name>` and to include every required flag, ran `bash -n` for a bash/sh shebang or `py_compile` for a Python shebang, and ran the file with `TK_DRY_RUN=1` plus dummy required values (`example`, `1`, or `true`). The dry-run had to exit 0 and print JSON on stdout. Other shebangs failed as unsupported. For chains, every step `tool` had to exist in `discover_catalog`. `check_all` aggregated `check_item` over the catalog into `{ok, checked, results, errors}`.

On 2026-11-03, `CODING_STANDARDS.md` at `ASabale/agent-toolkit@9d469d7` documented that same checklist. The header contract itself was specified earlier the same day in `ARCHITECTURE.md` at `ASabale/agent-toolkit@4b0e69c`. See [0001](../decisions/0001-clean-slate-single-file-contract.md).

On 2026-11-04, `ASabale/agent-toolkit@c37e045` hardened `_example_ok` in `lib/catalog.py` using `shlex.split` so every required non-bool `--flag` in `@tk-example` had to be followed by a non-empty value token (or `--flag=value`), and updated `tk check` in `./tk` to emit compact JSON on `stdout` even when `--json` was omitted. Later on 2026-11-04, `ASabale/agent-toolkit@b7f9668` added `suggest_closest_item(root_dir, name)` in `lib/catalog.py`, extended `check_item` to reject duplicate `--flag` names and invalid `(default: X)` values, and added `tools/code/symbols`, `tools/code/search`, `tools/sys/proc-info`, `tools/env/check`, and `chains/code.module-surface.json` (25 verified catalog items).

## Related

- [0001 — Clean-slate single-file contract](../decisions/0001-clean-slate-single-file-contract.md)
- [0002 — Minimum cognitive load and tokens](../decisions/0002-minimum-cognitive-load-and-tokens.md)
- [Runner and chains](runner-and-chains.md)
- [Evolver and quarantine](evolver-and-quarantine.md)
