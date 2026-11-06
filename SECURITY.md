# Security

`tk` runs tools on the machine where you invoke it. There is no account, registry, or remote tool download.

- Do not put secrets, tokens, or credentials in a tool file, a chain file, `stdout`, `stderr`, or `state/events.jsonl`.
- Leave credentials in the caller environment. A GitHub tool uses the existing `gh` login. It does not store a token in the catalog.
- A mutating or destructive `tk run` returns `plan` and does not change anything until the same command includes `--yes`.
- Check a tool with `tk check <name>` before you rely on it. Do not run a script you have not read.
- The lint is not a sandbox; tools run as the user.
- `state/events.jsonl` and `state/audit.jsonl` append while an advisory `fcntl.flock` is held on a sibling lock file. The lock is local to one filesystem. `O_APPEND` is not the lock. Telemetry swallows a lock or write error. A mutating or destructive run is denied with `audit_failed` when its audit line cannot be written. `isolation` on that line is `none` unless a later control applies something else.
