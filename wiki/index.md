# Chief-of-Staff historical wiki

On 2026-11-03 this index listed every page under `wiki/`. Claims on those pages carry a date and, when they describe code or repository state, a commit (`ASabale/agent-toolkit@<sha>`). See [Autonomous Chief-of-Staff governance](decisions/0003-autonomous-chief-of-staff-governance.md).

## Decisions

- [0001 — Clean-slate single-file contract](decisions/0001-clean-slate-single-file-contract.md) — On 2026-11-03, `ASabale/agent-toolkit@4b0e69c` rejected sidecar manifests and `cli-harness` ordering traps in favor of one executable file per tool.
- [0002 — Minimum cognitive load and tokens](decisions/0002-minimum-cognitive-load-and-tokens.md) — On 2026-11-03, `ASabale/agent-toolkit@d4c16aa` shortened the skill from Find → Inspect → Run to Find → Run and restated the token budget in the docs.
- [0003 — Autonomous Chief-of-Staff governance](decisions/0003-autonomous-chief-of-staff-governance.md) — On 2026-11-03, `ASabale/agent-toolkit@9d469d7` wrote the trust invariant in `CODING_STANDARDS.md`, and this wiki adopted dated, commit-cited history as its writing rule.

## Subsystems

- [Catalog and check](subsystems/catalog-and-check.md) — On 2026-11-03, `ASabale/agent-toolkit@9d469d7` indexed `tools/` headers and `chains/*.json` and validated them with `check_item`.
- [Runner and chains](subsystems/runner-and-chains.md) — On 2026-11-03, `ASabale/agent-toolkit@9d469d7` ran tools and chains behind one flag grammar and shipped `chains/git.repo-health.json`.
- [Evolver and quarantine](subsystems/evolver-and-quarantine.md) — On 2026-11-03, `ASabale/agent-toolkit@9d469d7` logged telemetry, rolled failed drafts into `state/quarantine/`, and promoted passing read-only tools.
