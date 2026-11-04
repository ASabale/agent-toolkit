# 0002 — Minimum cognitive load and tokens

On 2026-11-03, `ASabale/agent-toolkit@d4c16aa` (message: "docs: codify minimum cognitive load and minimum token principles") edited only documentation and the tool template: `AGENTS.md`, `ARCHITECTURE.md`, `README.md`, `VISION.md`, `skills/toolkit/SKILL.md`, and `tools/.template` (92 insertions, 94 deletions). That commit added no Python and no `tk` binary.

## Skill path before and after

On 2026-11-03, `skills/toolkit/SKILL.md` at `ASabale/agent-toolkit@4b0e69c` instructed a three-step loop: Find, then Inspect (`tk info`), then Run. The same file told callers to pass `--raw` and pipe into another `tk run` with `--from-stdin`, and to save chains with `tk chain save <chain-name> --description`.

On 2026-11-03, `skills/toolkit/SKILL.md` at `ASabale/agent-toolkit@d4c16aa` replaced that loop with two steps:

1. `tk find "<intent>"` returns matching tools and an exact runnable command.
2. `tk run <tool> --flag "<value>"` executes that line. `tk info <tool>` stayed optional, for full flag details.

The same revision stated the purpose as getting the job done in minimum turns and minimum tokens, and it moved chain saving under an Evolve (`Save → Check`) section (`tk chain save <namespace>.<name> --summary ...`).

## Principles written into the docs

On 2026-11-03, `VISION.md` and `README.md` at `ASabale/agent-toolkit@d4c16aa` named three principles: minimum model cognitive load (one flat command shape, no ordering traps, errors that print a corrected command), minimum token footprint (a compact skill pointer, `tk find` that includes the `tk run` signature, distilled tool output), and usage-driven evolution. `README.md` at that commit described `skills/toolkit/SKILL.md` as a 35-line skill.

On 2026-11-03, `ARCHITECTURE.md` at `ASabale/agent-toolkit@d4c16aa` set a two-step budget: `tk find` returns a one-line summary plus a copy-pasteable `tk run` line so an agent does not spend a turn on `tk info`. The same file required distilled JSON on stdout and a compact JSON error on stderr containing a `fix` command.

On 2026-11-03, `AGENTS.md` at `ASabale/agent-toolkit@d4c16aa` required `tk find` to return the summary and the copy-pasteable example in two lines, forbade positional tool arguments, and required flag order to leave behavior unchanged.

## What the implementation matched on the same day

On 2026-11-03, `ASabale/agent-toolkit@9d469d7` implemented that budget in code. `lib/catalog.py` `format_find_output` printed two lines per item (`<name> [<safety>] — <summary>` and `  run: <example>`). `lib/runner.py` `validate_and_build_env` rejected positional tokens with `positional_arguments_forbidden` and built a `fix` string that kept already supplied flags. See [Runner and chains](../subsystems/runner-and-chains.md) and [Catalog and check](../subsystems/catalog-and-check.md).

## Related

- [0001 — Clean-slate single-file contract](0001-clean-slate-single-file-contract.md)
- [Catalog and check](../subsystems/catalog-and-check.md)
- [Runner and chains](../subsystems/runner-and-chains.md)
