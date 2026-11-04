# 0006 — Raw output mode

On 2026-11-04, `ASabale/agent-toolkit@04d3803` (pull request #59, issue #17) accepted `--raw` as an order-independent no-op global modifier. The merge recorded that the flag changed nothing: `tk run` stdout was already the raw distilled JSON. This page records why the flag was kept rather than rejected or turned into a second output mode.

## What `--raw` meant at bootstrap

On 2026-11-03, `ARCHITECTURE.md` at `ASabale/agent-toolkit@4b0e69c` said `tk run` "wraps output in the standard JSON envelope" and defined the modifier as:

> `--raw`: Emits raw `data` on `stdout` instead of the JSON envelope (for shell piping).

On 2026-11-03, `skills/toolkit/SKILL.md` at `ASabale/agent-toolkit@4b0e69c` told callers to pass `--raw` to unwrap that envelope and pipe into `jq` or another `tk run` call.

## Why the flag lost its purpose

On 2026-11-03, `ASabale/agent-toolkit@d4c16aa` deleted the envelope and the `--raw` line from `ARCHITECTURE.md` together, replacing them with distilled output: tools emit compact JSON directly on `stdout` without wrapper ceremony. [0002 — Minimum cognitive load and tokens](0002-minimum-cognitive-load-and-tokens.md) records the SKILL.md side of that change. Nobody wrote down that `--raw` lost its unwrap job when the envelope went away.

## Why keep the flag as a no-op

On 2026-11-04, the Researcher conclusion on issue #17 recorded the decision: keep `--raw` as an accepted global modifier that changes nothing. [`VISION.md`](../../VISION.md) Pillar II already promised "Every tool emits clean JSON on `stdout` (or accepts `--raw`)". After `ASabale/agent-toolkit@d4c16aa`, the first branch held for every tool. Accepting the parenthetical honored older docs and other harnesses without inventing a text or passthrough mode, a `TK_RAW` environment variable, or a second output contract.

[`VISION.md`](../../VISION.md) forbade a byte-for-byte passthrough: tools are distillers, `run_tool` requires `json.loads(stdout)`, and one flat command shape is the cognitive-load rule. Rejecting `--raw` as `unknown_flag` failed that same rule: the generic `@tk-example` `fix` rewrote the caller's flags. Accepting a no-op matched the documented meaning of the flag (raw data, no envelope), which plain `tk run` already returned.

## What pull request #59 implemented

On 2026-11-04, `ASabale/agent-toolkit@04d3803` consumed `--raw` and `--raw=…` anywhere in argv in `lib/runner.py` `parse_cli_flags`, reserved `--raw` and `--dry-run` in `lib/catalog.py` `_header_errors`, and added the compatibility line to `ARCHITECTURE.md` and `CODING_STANDARDS.md`. Tools never saw `TK_RAW`. The wiki record of the decision was split to this page so the code fix could merge while `wiki/index.md` was held.

## Related

- [0002 — Minimum cognitive load and tokens](0002-minimum-cognitive-load-and-tokens.md)
