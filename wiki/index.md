# Chief-of-Staff historical wiki

On 2026-11-03 this index listed every page under `wiki/`. Claims on those pages carry a date and, when they describe code or repository state, a commit (`ASabale/agent-toolkit@<sha>`). See [Autonomous Chief-of-Staff governance](decisions/0003-autonomous-chief-of-staff-governance.md).

## Decisions

- [0001 — Clean-slate single-file contract](decisions/0001-clean-slate-single-file-contract.md) — On 2026-11-03, `ASabale/agent-toolkit@4b0e69c` rejected sidecar manifests and `cli-harness` ordering traps in favor of one executable file per tool.
- [0002 — Minimum cognitive load and tokens](decisions/0002-minimum-cognitive-load-and-tokens.md) — On 2026-11-03, `ASabale/agent-toolkit@d4c16aa` shortened the skill from Find → Inspect → Run to Find → Run and restated the token budget in the docs.
- [0003 — Autonomous Chief-of-Staff governance](decisions/0003-autonomous-chief-of-staff-governance.md) — On 2026-11-03 (`ASabale/agent-toolkit@9d469d7`) and 2026-11-04 (`ASabale/agent-toolkit@c37e045`, `ASabale/agent-toolkit@46a6538`), `CODING_STANDARDS.md`, `.git/hooks/pre-commit`, `.github/workflows/ci.yml`, `tools/wiki/lint`, and `tests/test_token_budget.py` locked the trust invariant, token budget ceilings, and historical wiki lint gates.

## Subsystems

- [Catalog and check](subsystems/catalog-and-check.md) — On 2026-11-03 (`ASabale/agent-toolkit@9d469d7`) and 2026-11-04 (`ASabale/agent-toolkit@c37e045`, `ASabale/agent-toolkit@46a6538`, `ASabale/agent-toolkit@b7f9668`, `ASabale/agent-toolkit@9fe185e`, `ASabale/agent-toolkit@7c9fd95`), `lib/catalog.py` indexed 34 verified tools and chains, added `find_items(..., limit=...)`, and supported multi-item `tk check [<name> ...]`.
- [Runner and chains](subsystems/runner-and-chains.md) — On 2026-11-03 (`ASabale/agent-toolkit@9d469d7`) and 2026-11-04 (`ASabale/agent-toolkit@c37e045`, `ASabale/agent-toolkit@46a6538`, `ASabale/agent-toolkit@b7f9668`, `ASabale/agent-toolkit@9fe185e`, `ASabale/agent-toolkit@7c9fd95`), `lib/runner.py` added whole-object `$prev`/`$step[i]` resolution, dry-run path fallback, and `chains/code.blast-radius.json`.
- [Evolver and quarantine](subsystems/evolver-and-quarantine.md) — On 2026-11-03 (`ASabale/agent-toolkit@9d469d7`) and 2026-11-04 (`ASabale/agent-toolkit@c37e045`, `ASabale/agent-toolkit@46a6538`, `ASabale/agent-toolkit@b7f9668`, `ASabale/agent-toolkit@7c9fd95`), `lib/evolver.py` added `chain_candidates` sequence mining in `evolve_report` alongside `prune_tools`.
