# AGENTS.md — Agent Toolkit

Instructions for agents designing, building, and evolving `agent-toolkit`.

## Core Mandate

Build a **harness-agnostic, self-evolving CLI toolkit** packaged as a skill so users can turn off MCP servers. Every design and implementation choice must optimize three properties simultaneously:
1. **Easy to use**: A small or local model can discover, parameterize, and run any tool deterministically on the first attempt.
2. **Easy to extend**: Any agent can author a new tool or chain existing tools in a single step without multi-file boilerplate.
3. **Easy to maintain**: Every fact has a single source of truth; `tk check` catches contract drift automatically.

## Context Pointers

- Evaluating product scope, why this replaces MCPs, or roadmap priorities → read [`VISION.md`](VISION.md).
- Designing CLI commands, module seams, tool header metadata, or JSON envelopes → read [`ARCHITECTURE.md`](ARCHITECTURE.md).
- Editing the portable agent skill consumed by external harnesses → read [`skills/toolkit/SKILL.md`](skills/toolkit/SKILL.md).

## Architectural Invariants

1. **Single-File Tool Truth**: Every tool in `tools/` is a single executable file containing its `# @tk-*` contract header and its implementation. Never introduce sidecar `.yaml` or `.json` manifest files that can drift from the script.
2. **Dumb-Model Ergonomics**:
   - All tool arguments are explicit named flags (`--key value`). Positional arguments inside tools are forbidden.
   - Flag order must never change behavior.
   - Every tool header must include at least one working, copy-pasteable `@tk-example`.
   - Error messages must output JSON to `stderr` with `error`, `why`, and `fix` (the exact corrected command or missing prerequisite).
3. **Composable I/O**:
   - `stdout` emits valid JSON by default (`{"ok": true, "data": ...}`) so tools pipe cleanly into `jq` or other `tk` tools.
   - Diagnostic logs, progress, and errors go exclusively to `stderr`.
4. **Deep Modules**: Keep the `tk` surface small (`find`, `info`, `run`, `chain`, `save`, `evolve`, `check`) and hide parsing, indexing, validation, and telemetry behind that interface.
5. **Anti-Bloat & Continuous Pruning**: Never build speculative tools. Every tool must earn its place through real usage; `tk evolve` tracks both promotion of recurring patterns and pruning/consolidation of unused or overlapping tools.
6. **Zero External Dependencies in the Core**: The core `tk` runtime must run out-of-the-box on macOS and Linux using standard system Python 3 + POSIX shell so any agent harness can clone and use it immediately.

## Workflow & Verification

1. **Before adding or changing core behavior**: Check [`ARCHITECTURE.md`](ARCHITECTURE.md) to ensure the change respects module seams and the single-file contract.
2. **Smoke verify every change**: Run the actual `tk` CLI against a real tool in `tools/` and observe both `stdout` and exit code. Unit tests never substitute for a live CLI smoke run.
3. **Done criteria for any feature or tool**:
   - `tk check` exits `0` with zero contract warnings.
   - All automated tests in `tests/` pass.
   - If the user-facing CLI surface or skill workflow changed, [`skills/toolkit/SKILL.md`](skills/toolkit/SKILL.md) is updated in the same commit.
