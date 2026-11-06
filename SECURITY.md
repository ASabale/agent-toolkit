# Security

`tk` runs tools on the machine where you invoke it. There is no account, registry, or remote tool download.

- Do not put secrets, tokens, or credentials in a tool file, a chain file, `stdout`, `stderr`, or `state/events.jsonl`.
- Leave credentials in the caller environment. A GitHub tool uses the existing `gh` login. It does not store a token in the catalog.
- A mutating `tk run` returns `plan` until `--yes` or a matching `--confirm`. `--yes` satisfies only a class-level mutating confirm, writes a deprecation warning, and is not standing authorization. It does not satisfy a hash or name confirm.
- A destructive `tk run` needs an exact-hash allow or confirm for these bytes and a matching `--confirm <plan_id>` on this invocation. `--yes` does not run it. Class deny stays deny. The printed `apply` hint is `--confirm`, not `--yes`.
- `state/policy.json` version 1 decides allow, confirm, or deny. An applicable deny wins across hash and name. Two decisions at the same rank are `policy_conflict`. Otherwise one hash decision is standing authorization for those bytes, except a destructive hash allow still needs the plan id. Name `allow` is not a byte grant and falls through to the class default. Draft bytes do not receive class allow. A missing file uses read-only allow, mutating confirm, and destructive deny. A same-user process can still edit that file or exec the tool directly. This policy is not that boundary.
- Check a tool with `tk check <name>` before you rely on it. Do not run a script you have not read.
- `safety` is a declaration. `tk check` is not a sandbox. Tools run as the user.
- `@tk-verified` is a date in the header. It is not a signature. `@tk-provenance: local` is not approval. A save or an import is an execution draft until an exact-hash policy rule allows those bytes. Invalid `state/evidence.json` blocks class-level allow. A missing evidence file is not approval and does not block a capability that was never marked a draft. Approval stored for one hash does not survive a byte change.
- `state/trace.jsonl` is best-effort. A failed trace write does not block read-only work. It is not the writer audit.
- A writer authorization audit failure blocks the start. A terminal audit failure does not undo a finished operation.
- `TK_DRY_RUN` is cooperative. The audit field `isolation` is `none`.
- A chain is not a transaction. A `bin:` an earlier step would install still fails preflight. Install it, then run `tk run` again.
- `state/events.jsonl` and `state/audit.jsonl` append while an advisory `fcntl.flock` is held on a sibling lock file. The lock is local to one filesystem. `O_APPEND` is not the lock. Telemetry swallows a lock or write error. A mutating or destructive run is denied with `audit_failed` when its audit line cannot be written. `isolation` on that line is `none` unless a later control applies something else.
