# AGENTS.md — Agent Toolkit

Instructions for agents designing, building, and evolving `agent-toolkit`.

## Core Purpose & Mandate

**Purpose**: Help agents **get the job done** with **minimum cognitive load** and **minimum tokens**, while making the toolkit effortless to use and evolve.

Every agent touching this repository must uphold four non-negotiable laws:
1. **Minimize Cognitive Load**: The toolkit must be immediately obvious to any model (including small/local models). One uniform command grammar, zero ordering traps, and errors that give the exact command to run next.
2. **Minimize Token Spend**: Every extra turn, long help text, or unfiltered API payload wastes context. Optimize discovery (`tk find` gives the runnable command immediately), keep `SKILL.md` razor-thin, and ensure every tool emits distilled, minimum-token output.
3. **Make Evolution Effortless**: Creating a tool (`tk save`) or chaining tools (`tk chain`) takes one step in a single file with zero sidecar boilerplate.
4. **Stay Lean**: Continuously consolidate overlapping tools and prune unused ones with `tk prune [--unused] [--dry-run]` so the toolkit never bloats.

## Context Pointers

- Evaluating product scope, why this replaces MCPs, or core principles → read [`VISION.md`](VISION.md).
- Designing CLI commands, module seams, tool header metadata, or token budgets → read [`ARCHITECTURE.md`](ARCHITECTURE.md).
- Editing the portable agent skill consumed by external harnesses → read [`skills/agent-toolkit/SKILL.md`](skills/agent-toolkit/SKILL.md).
- Multi-agent coordination (claiming work, avoiding collisions, steward review) → read [`COORDINATION.md`](COORDINATION.md).

## Architectural Invariants

1. **Single-File Tool Truth**: Every tool in `tools/` is a single executable file containing its `# @tk-*` contract header and its implementation. Never introduce sidecar `.yaml` or `.json` manifest files that can drift from the script.
2. **Zero-Friction Discovery (`Find → Run`)**:
   - `tk find "<intent>"` must return the matching tool's summary *and* its copy-pasteable `tk run` example in 2 lines so agents execute in 2 steps (`find → run`), not 3 (`find → info → run`).
3. **Dumb-Model Ergonomics**:
   - All tool arguments are explicit named flags (`--key value`). Positional arguments inside tools are forbidden.
   - Flag order must never change behavior.
   - Error messages on `stderr` must include `error`, `why`, and a copy-pasteable `fix` command.
4. **Minimum-Token Composable Output**:
   - Tools are **distillers**, not raw API mirrors. Strip noise and emit compact JSON on `stdout` containing only the fields an agent needs to make a decision or pipe to the next tool.
   - Diagnostic logs and errors go exclusively to `stderr`.
5. **Deep Modules**: Keep the `tk` surface small (`find`, `run`, `chain`, `save`, `evolve`, `prune`, `check`, `info`) and hide parsing, indexing, validation, and telemetry behind that interface.
6. **Anti-Bloat & Continuous Pruning**: Never build speculative tools. Every tool must earn its place through real usage; `tk evolve` tracks both promotion of recurring patterns and pruning/consolidation of unused or overlapping tools.
7. **Zero External Dependencies in the Core**: The core `tk` runtime must run out-of-the-box on macOS and Linux using standard system Python 3 + POSIX shell so any agent harness can clone and use it immediately.

## Workflow & Verification

1. **Always Pull Latest First (Remote Multi-Agent Sync)**: Multiple agents work on `ASabale/agent-toolkit` concurrently. On `main`, run `git pull --rebase --autostash origin main` before starting work. On a feature branch, run `tk run git.sync --repo .` to rebase onto `origin/main` and push the branch, both before starting work and again before committing. Never push to `main`; every change goes through a PR (see COORDINATION.md).
2. **Before adding or changing core behavior**: Check [`ARCHITECTURE.md`](ARCHITECTURE.md) and [`CODING_STANDARDS.md`](CODING_STANDARDS.md) to ensure the change respects module seams and the single-file contract.
3. **Smoke verify every change**: Run the actual `tk` CLI against a real tool in `tools/` and observe both `stdout` and exit code. Unit tests never substitute for a live CLI smoke run.
4. **Done criteria for any feature or tool**:
   - `tk check` exits `0` with zero contract warnings.
   - All automated tests in `tests/` pass.
   - If the user-facing CLI surface or skill workflow changed, [`skills/agent-toolkit/SKILL.md`](skills/agent-toolkit/SKILL.md) is updated in the same commit.
5. **Read usage feedback before new work**: Open issues with the `feedback` label (filed through [`.github/ISSUE_TEMPLATE/feedback.yml`](.github/ISSUE_TEMPLATE/feedback.yml)) are reports from people using `tk`. Read them. Incorporate one only when it serves the three pillars in [`VISION.md`](VISION.md). If it does not, close it and name the pillar it breaks. Do not turn a wish into a speculative tool.
