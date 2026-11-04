# 0009 — Verification tiers

On 2026-11-04, `ASabale/agent-toolkit@80dc937` verified a tool in two different ways depending on `@tk-safety`, and neither way stamped a `mutating` or `destructive` tool.

`tk check` runs the header, syntax, and dry-run smoke. For `mutating` and `destructive` tools that smoke is `TK_DRY_RUN=1` in a scratch directory and requires stdout `{"dry_run":true,"plan":[...]}` with a non-empty `plan`. That check does not write `# @tk-verified`.

`tk evolve` stamps `# @tk-verified: <YYYY-MM-DD>` (or a chain's `"verified"` field) only when the item is `read-only`, `check_item` passes, and `state/events.jsonl` has a `run_ok` for that name. A `mutating` or `destructive` item with a `run_ok` stays `# @tk-verified: none`.

## Decision

Verification is explicit for anything that is not read-only.

- `tk check <name> --verify` takes exactly one name. `tk check --verify` and `tk check a b --verify` exit 2 with `fix` `tk check <name> --verify`.
- A name that fails `tk check` exits 1 with `error` `check_failed` and the check errors in `why`. The file is not stamped.
- `read-only`: `tk check` is the verification. `--verify` reports `{"ok":true,"name","safety","verified"}` from the current header and does not stamp. `tk evolve` still stamps a read-only item after a `run_ok`.
- `mutating`: `--verify` runs the tool again with `TK_DRY_RUN=1` in a scratch directory. A dry-run that fails, or that omits a non-empty `plan`, exits 1 with `error` `verify_failed`. Success stamps `# @tk-verified: <YYYY-MM-DD>`, logs `tool_verified` with `{name, safety, plan}`, and prints `{"ok":true,"name","safety","verified","plan"}`. Running it again is a no-op: exit 0, header unchanged, no second `tool_verified` event.
- `destructive`: `--verify` exits 2 with `error` `human_signoff_required` and `fix` `open a PR changing # @tk-verified: <YYYY-MM-DD> in <path> and request human review`. The file bytes stay as they were. `tk evolve` does not stamp `destructive` items either.

`lib/evolver.py` `verify_item` is the function `tk check --verify` calls. `evolve_report` is unchanged: its promote branch still requires `safety == "read-only"`.

## Related

- [0003 — Autonomous Chief-of-Staff governance](0003-autonomous-chief-of-staff-governance.md)
- [Evolver and quarantine](../subsystems/evolver-and-quarantine.md)
- [`ARCHITECTURE.md`](../../ARCHITECTURE.md)
- [`CODING_STANDARDS.md`](../../CODING_STANDARDS.md)
- Issue #31
