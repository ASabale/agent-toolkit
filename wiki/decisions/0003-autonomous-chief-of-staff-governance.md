# 0003 — Autonomous Chief-of-Staff governance

On 2026-11-03 this wiki opened under `wiki/` as a historical record: a claim about code or repository state names the date and the commit, and pages avoid an undated present tense for the tree. On 2026-11-03 the index of every page lived in [wiki/index.md](../index.md).

## Trust invariant landed with the dispatcher

On 2026-11-03, `ASabale/agent-toolkit@9d469d7` added `CODING_STANDARDS.md` (121 lines in that commit) and called its first section the trust invariant. That committed text required five rules:

1. The `tk` entrypoint and `lib/` modules catch unexpected exceptions and emit one JSON line on stderr: `error`, `why`, and `fix` (the documented fix string was `tk check`).
2. `stdout` for `tk run`, `tk save`, `tk chain`, `tk check --json`, and `tk evolve` stays compact JSON (`separators=(",", ":")`). `tk find` and `tk info` stay compact text. Diagnostics stay on stderr.
3. On 2026-11-03, `tk save` and `tk chain save` were required to run `check_item` before completing, and a failed draft was required to be removed so an invalid tool or chain would not stay in the catalog. At `ASabale/agent-toolkit@9d469d7`, the implementation copied the failed text under `state/quarantine/` before deleting or restoring the destination. See [Evolver and quarantine](../subsystems/evolver-and-quarantine.md).
4. On 2026-11-03, `log_event` in `lib/evolver.py` was required to wrap file I/O so telemetry failure would not stop `tk find` or `tk run`.
5. The core uses the Python 3.10+ standard library only. The committed list named `sys`, `os`, `json`, `re`, `subprocess`, `pathlib`, `shlex`, `datetime`, and `unittest`.

On 2026-11-03, the `./tk` section of `CODING_STANDARDS.md` at `ASabale/agent-toolkit@9d469d7` listed `find`, `info`, `run`, `chain run`, `chain save`, `save`, `check`, and `evolve`. That committed section did not list a `prune` subcommand. `tk` at the same commit routed those same names and did not define a prune command. `lib/evolver.py` at the same commit defined `log_event`, `save_tool`, `save_chain`, and `evolve_report`, and it did not define `prune_tools`.

## Module seams the standards named

On 2026-11-03, `CODING_STANDARDS.md` at `ASabale/agent-toolkit@9d469d7` split the implementation into three public seams: `lib/catalog.py` (discovery, indexing, validation), `lib/runner.py` (flag validation, execution, chaining), and `lib/evolver.py` (telemetry, creation, promotion, overlap report). `./tk` was the entrypoint. See [Catalog and check](../subsystems/catalog-and-check.md) and [Runner and chains](../subsystems/runner-and-chains.md).

On 2026-11-03, `AGENTS.md` at `ASabale/agent-toolkit@d4c16aa` already required agents to keep the `tk` surface small (`find`, `run`, `chain`, `save`, `evolve`, `check`, `info`) and to smoke-run the CLI rather than treat unit tests as a substitute. `ASabale/agent-toolkit@9d469d7` added `tests/test_catalog.py`, `tests/test_runner.py`, `tests/test_evolver.py`, and `tests/test_cli_integration.py` beside that rule.

## How this wiki records later edits

On 2026-11-03, history in this directory cites `ASabale/agent-toolkit@4b0e69c` for the clean-slate contract, `ASabale/agent-toolkit@d4c16aa` for the token and cognitive-load rewrite, and `ASabale/agent-toolkit@9d469d7` for the first executable toolkit. A later commit must be named before a page treats it as repository state. See [0001](0001-clean-slate-single-file-contract.md) and [0002](0002-minimum-cognitive-load-and-tokens.md).

## Related

- [0001 — Clean-slate single-file contract](0001-clean-slate-single-file-contract.md)
- [0002 — Minimum cognitive load and tokens](0002-minimum-cognitive-load-and-tokens.md)
- [Evolver and quarantine](../subsystems/evolver-and-quarantine.md)
