# 0001 — Clean-slate single-file contract

On 2026-11-03, `ASabale/agent-toolkit@4b0e69c` bootstrapped the repository with `VISION.md`, `ARCHITECTURE.md`, `AGENTS.md`, `README.md`, `skills/toolkit/SKILL.md`, `tools/.template`, and empty `chains/`, `state/`, and `tests/` placeholders. That commit contained no `tk` dispatcher and no `lib/` modules.

## What the bootstrap rejected

On 2026-11-03, `VISION.md` at `ASabale/agent-toolkit@4b0e69c` said the repository started from scratch to leave behind structural debt of an earlier `cli-harness`. The same section recorded four replacements:

| Earlier friction recorded on 2026-11-03 | Rule written in `ASabale/agent-toolkit@4b0e69c` |
|---|---|
| Sidecar `.yaml` plus `.sh` files drifted | One file per tool; header comments inside the executable were the manifest |
| `--instance <vm> <plane> <cmd>` ordering | Flat `--flag value` grammar; order does not change behavior |
| Hardcoded company-specific planes and 3-tier folders | Flat `tools/<namespace>/<verb-noun>` layout |
| Heavy scaffolding to add a capability | `tk save` and a single-file drop-in |

On 2026-11-03, `ARCHITECTURE.md` at `ASabale/agent-toolkit@4b0e69c` stated that the executable file was the manifest. The indexer was specified to parse `# @tk-*` directives from the top comment block of files under `tools/<namespace>/<tool-name>`. The header example in that file named `@tk-name`, `@tk-summary`, `@tk-safety`, `@tk-arg`, `@tk-output`, `@tk-example`, and `@tk-verified`.

On 2026-11-03, `tools/.template` at `ASabale/agent-toolkit@4b0e69c` was a bash skeleton with those directives and `@tk-verified: none`. `ASabale/agent-toolkit@d4c16aa` later touched that template (two lines) without adding a second manifest format.

## What later commits kept

On 2026-11-03, `ASabale/agent-toolkit@9d469d7` implemented the contract in `lib/catalog.py` (`parse_tool_header`) and placed eight starter tools under `tools/` with no sidecar YAML. Chain definitions stayed JSON files under `chains/`, which `ARCHITECTURE.md` at `ASabale/agent-toolkit@4b0e69c` had already separated from the tool-file contract. See [Catalog and check](../subsystems/catalog-and-check.md) and [Evolver and quarantine](../subsystems/evolver-and-quarantine.md).

On 2026-11-03, `AGENTS.md` at `ASabale/agent-toolkit@4b0e69c` forbade sidecar `.yaml` or `.json` manifests for tools. `ASabale/agent-toolkit@d4c16aa` rewrote surrounding cognitive-load wording and left that single-file rule in place. See [0002](0002-minimum-cognitive-load-and-tokens.md).

## Related

- [0002 — Minimum cognitive load and tokens](0002-minimum-cognitive-load-and-tokens.md)
- [0003 — Autonomous Chief-of-Staff governance](0003-autonomous-chief-of-staff-governance.md)
- [Catalog and check](../subsystems/catalog-and-check.md)
