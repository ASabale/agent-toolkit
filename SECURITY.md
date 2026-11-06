# Security

`tk` runs tools on the machine where you invoke it. There is no account, registry, or remote tool download.

- Do not put secrets, tokens, or credentials in a tool file, a chain file, `stdout`, `stderr`, or `state/events.jsonl`.
- Leave credentials in the caller environment. A GitHub tool uses the existing `gh` login. It does not store a token in the catalog.
- A mutating or destructive `tk run` returns `plan` and does not change anything until the same command includes `--yes`.
- Check a tool with `tk check <name>` before you rely on it. Do not run a script you have not read.
- `safety` is a declaration. `tk check` is not a sandbox. Tools run as the user.
- `@tk-verified` is a date in the header. It is not a signature.
- `state/trace.jsonl` is best-effort. A failed trace write does not block read-only work. It is not the writer audit.
- A writer authorization audit failure blocks the start. A terminal audit failure does not undo a finished operation.
- `TK_DRY_RUN` is cooperative. The audit field `isolation` is `none`.
- A chain is not a transaction. A `bin:` an earlier step would install still fails preflight. Install it, then run `tk run` again.
- `state/events.jsonl` and `state/audit.jsonl` append while an advisory `fcntl.flock` is held on a sibling lock file. The lock is local to one filesystem. `O_APPEND` is not the lock. Telemetry swallows a lock or write error. A mutating or destructive run is denied with `audit_failed` when its audit line cannot be written. `isolation` on that line is `none` unless a later control applies something else.
