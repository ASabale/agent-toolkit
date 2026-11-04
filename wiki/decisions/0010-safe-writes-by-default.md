# 0010 — Safe writes by default

On 2026-11-04, issue #84 changed `tk run` so a mutating or destructive tool, and a chain with such a step, does not change anything until the caller passes `--yes`. The dry-run plan contract this reuses was already on `ASabale/agent-toolkit@04844f8` (issue #30). There is no `TK_ASSUME_YES`.

## Decision

Without `--yes`, the run behaves as a dry-run and returns `dry_run`, `plan`, and `apply`. `apply` is `tk run <name> <the same flags> --yes`, which is the command that performs the change. `--yes` is a reserved global modifier, like `--raw`. A tool that declares `@tk-arg: --yes` fails check with `reserved flag: --yes` and a `fix`. Read-only tools accept `--yes` and return the same stdout as the command without it.

In-process `run_tool` and `run_chain` still execute when the caller does not pass `confirmed=False`. Only `tk run` withholds confirmation.

## Related

- [0006 — Raw output mode](0006-raw-output-mode.md)
