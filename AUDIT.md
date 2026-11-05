# Gap audit

Date: 2026-11-05. Tree: `3f2a3cd` plus the T0.1 docs commit on `plan/t0.1-baseline` (no product code).
Answers are from `tk`, `lib/`, `tests/`, `tools/`, `skills/agent-toolkit/SKILL.md`, `install.sh`, `bench/`, `README.md`, `ARCHITECTURE.md`, `SECURITY.md`, `CODING_STANDARDS.md`.

No later task is `ALREADY_DONE`. Two are partial: timeout already exists (T2.5), and `tk find` already ranks by keywords (T5.2).

| # | Answer | Evidence |
|---|---|---|
| A1 | No | `@tk-safety` is stored (`lib/catalog.py` header parse). A mutating/destructive dry-run uses a temp cwd and temp `HOME` (`lib/catalog.py` around the dry-run invoke). A read-only check can run the tool for real and only require JSON stdout (`_live_json_error`). No static denylist and no sandbox. |
| A2 | Yes, `--yes` is unbound | `tk` `_cmd_run` sets `confirmed` from the flag alone. `run_tool` dry-runs a mutating tool when `confirmed` is false and returns `plan`. Any later `--yes` executes. `SECURITY.md` states the same rule. No `plan_id`. |
| A3 | Yes | `lib/runner.py` `_tool_failure` returns a tool stderr object when it already has `error`, `why`, and `fix`. `_fix_command` appends the caller's flag values (`shlex.quote`). `_example` copies the header example. `lib/catalog.py` `_json_stdout_fix` builds a `tk save --from-cmd` from the tool body. Dry-run failures prefix the first stderr line. |
| A4 | No automatic scan | `SECURITY.md` forbids secrets in tool files, chains, stdout, stderr, and `state/events.jsonl`. Nothing in `tk check`, the event logger, or the error path scans those. `tools/sec/secret-scan` is a separate read-only tool the caller must run. |
| A5 | Free text, plus one chain check | `@tk-output` is stored as a string. Live stdout is `json.loads` only (`lib/runner.py`). `json.pick` / `json.query` chain steps check keys against an `{...}` shape (`_pick_query_key_errors`). No `@tk-schema`. |
| A6 | No | Parsed headers are name, summary, safety, args, output, example, verified. `install.sh` checks `python3` (hard fail) and `gh` (warning) at install time only. |
| A7 | No | `log_event` appends with `open("a")` and no lock (`lib/evolver.py`). Drafts, chain files, and `@tk-verified` promotion use `Path.write_text` (`_commit_draft`, chain save, `_promote_tool`). No `flock`, `O_APPEND` single-write, or `os.replace`. |
| A8 | In-clone, except state override | Tools: `tools/<namespace>/<name>` (`_tool_dest`). Chains: `chains/`. Telemetry, archive, quarantine: `<clone>/state/`, gitignored. `TK_STATE_DIR` overrides only that directory (`_state_dir`). No `TK_HOME`. `git pull` can conflict with agent-written files under `tools/` and `chains/`. |
| A9 | No | The only lifecycle header is `@tk-verified`. No `@tk-version`, `@tk-deprecated`, or `@tk-replaced-by`. |
| A10 | No pin | `_unused_tools` skips names present in run events and files newer than the first run event, and returns nothing until 50 run events. `tk prune` also skips names a kept chain still uses. No `@tk-keep`. A zero-use tool the user wants can still be archived once telemetry is deep enough. |
| A11 | Timeout yes; flag and exit 124 no | `run_tool` reads `TK_TIMEOUT`, default 60s, kills the process group, and returns exit 1 with `error: tool_timeout`. The `fix` is `TK_TIMEOUT=<2x> tk run ...` (`_timeout_fix`). Usage errors return 2 (`not_found` and unknown subcommand). A failed `tk check` returns 1. A tool's own non-zero status is passed through. `ARCHITECTURE.md` describes behavior and does not publish one exit-code table. No `--timeout` flag. |
| A12 | Keyword weights, not fuzzy rank | `_score`: exact name or segment +5, name substring +3, summary +2, args +1. Stopwords do not score summary or args. `difflib` is only a misspelling hint. `tests/test_catalog.py` covers exact-name ranking. No 25-query golden set and no `@tk-aliases`. |
| A13 | Only via the skill text | `install.sh` symlinks `tk` to `~/.local/bin/tk` and does not edit shell rc. `SKILL.md` tells the agent to `export PATH="$HOME/.local/bin:$PATH"` or call `~/.agent-toolkit/tk`. Later steps still say `tk`. There is no `tk doctor`. The skill is already at its 51-line ceiling, so a longer pointer does not fit. |
| A14 | Byte benchmark only | `bench/mcp_vs_tk.py` plus `bench/fixtures/`. It counts idle, discovery, and output bytes, tool-call count, and `est_tokens` as bytes/4. It does not score first-try success. |
| A15 | No | No test extracts or runs README fenced `tk` blocks. `README.md` is only a fixture path in unrelated tool tests. |

## What this does to later tasks

- T1.1 through T1.6, T2.1 through T2.4, T3.1 through T3.3, T3.5, T4.1 through T4.5, T5.1, T5.3 through T5.5: gap still open.
- T2.5: do not add a second timeout. Extend the existing `TK_TIMEOUT` path with `--timeout`, document exit codes without renumbering current 0/1/2, and decide 124 versus today's exit 1 before changing it.
- T5.2: keep `_score`. Add the golden file and aliases on top.
- T3.4: `tests/test_token_budget.py` already fails above 51 skill lines, 2700 skill bytes, and 140-character find lines. The plan's baseline+15% and "+5 tools" gates are not that test.
- T4.1 `tk doctor` is a new subcommand. `tk` currently dispatches `find`, `info`, `run`, `chain`, `save`, `check`, `evolve`, `prune` only. Memory said not to rebuild a doctor; the plan asks for one. Re-check `VISION.md` at that task. The PATH hint in `SKILL.md` is already present.
- T1.2's new `SKILL.md` line conflicts with the 51-line cap. Skip that line.
