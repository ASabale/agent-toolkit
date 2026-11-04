# Chief-of-Staff historical wiki

On 2026-11-03 this index listed every page under `wiki/`. Claims on those pages carry a date and, when they describe code or repository state, a commit (`ASabale/agent-toolkit@<sha>`). See [Autonomous Chief-of-Staff governance](decisions/0003-autonomous-chief-of-staff-governance.md).

## Decisions

- [0001 — Clean-slate single-file contract](decisions/0001-clean-slate-single-file-contract.md) — On 2026-11-03, `ASabale/agent-toolkit@4b0e69c` rejected sidecar manifests and `cli-harness` ordering traps in favor of one executable file per tool.
- [0002 — Minimum cognitive load and tokens](decisions/0002-minimum-cognitive-load-and-tokens.md) — On 2026-11-03, `ASabale/agent-toolkit@d4c16aa` shortened the skill from Find → Inspect → Run to Find → Run and restated the token budget in the docs.
- [0003 — Autonomous Chief-of-Staff governance](decisions/0003-autonomous-chief-of-staff-governance.md) — On 2026-11-03 (`ASabale/agent-toolkit@9d469d7`) and 2026-11-04 (`ASabale/agent-toolkit@c37e045`, `ASabale/agent-toolkit@46a6538`, `ASabale/agent-toolkit@5aece9a`), `CODING_STANDARDS.md`, `.git/hooks/pre-commit`, `.github/workflows/ci.yml`, `tools/wiki/lint`, and `tools/git/sync` locked the trust invariant, token budget ceilings, historical wiki lint gates, and multi-agent remote sync.

## Subsystems

- [Catalog and check](subsystems/catalog-and-check.md) — On 2026-11-03 (`ASabale/agent-toolkit@9d469d7`) and 2026-11-04 (`ASabale/agent-toolkit@c37e045`, `ASabale/agent-toolkit@46a6538`, `ASabale/agent-toolkit@b7f9668`, `ASabale/agent-toolkit@9fe185e`, `ASabale/agent-toolkit@7c9fd95`, `ASabale/agent-toolkit@5a57fcd`, `ASabale/agent-toolkit@5aece9a`), `lib/catalog.py` indexed 45 verified tools and chains, added `--namespace` filtering and `TK_ARG_*` script-to-header parity checks, and parallelized `check_all` via `ThreadPoolExecutor`.
- [Runner and chains](subsystems/runner-and-chains.md) — On 2026-11-03 (`ASabale/agent-toolkit@9d469d7`) and 2026-11-04 (`ASabale/agent-toolkit@c37e045`, `ASabale/agent-toolkit@46a6538`, `ASabale/agent-toolkit@b7f9668`, `ASabale/agent-toolkit@9fe185e`, `ASabale/agent-toolkit@7c9fd95`, `ASabale/agent-toolkit@5a57fcd`, `ASabale/agent-toolkit@5aece9a`), `lib/runner.py` executed 7 verified chains including `sec.repo-hygiene` and `gh.pr-overview`.
- [Evolver and quarantine](subsystems/evolver-and-quarantine.md) — On 2026-11-03 (`ASabale/agent-toolkit@9d469d7`) and 2026-11-04 (`ASabale/agent-toolkit@c37e045`, `ASabale/agent-toolkit@46a6538`, `ASabale/agent-toolkit@b7f9668`, `ASabale/agent-toolkit@7c9fd95`, `ASabale/agent-toolkit@5a57fcd`, `ASabale/agent-toolkit@5aece9a`), `lib/evolver.py` added `TK_ARG_*` auto-inference in `save_tool` and `run_error` adjacency reset in `chain_candidates`.
