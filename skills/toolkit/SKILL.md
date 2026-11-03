---
name: toolkit
description: Self-evolving CLI toolkit that replaces MCP servers. Use when executing external service actions, querying APIs or infrastructure, chaining multi-step CLI workflows, or saving a repeatable command/script as a reusable tool.
---

# Agent Toolkit (`tk`)

Deterministic CLI toolkit for executing, chaining, and evolving operational tools without MCP context bloat.

## Use Loop: Find → Inspect → Run

Follow these three steps in order. Never guess tool names or flags.

1. **Find** a tool or chain matching your intent:
   ```bash
   tk find "<intent keywords>"
   ```
   *Done when*: you have a matching tool name from the results, or `tk find` reports no match (proceed to **Evolve Loop** below if you solve the task with raw commands).

2. **Inspect** the tool's contract and copyable example:
   ```bash
   tk info <tool-name>
   ```
   *Done when*: you know every `required` flag, the safety tier (`read-only`, `mutating`, `destructive`), and have a copy-pasteable `@tk-example`.

3. **Run** (or pipe) the tool with explicit named flags:
   ```bash
   tk run <tool-name> --flag "<value>"
   ```
   *Done when*: the command exits `0` and returns `"ok": true` on `stdout`. On non-zero exit, read the `fix` field in the `stderr` JSON and run the corrected command.

## Chaining Tools

- **One-off pipeline**: Pass `--raw` to unwrap the JSON envelope and pipe into `jq` or another `tk run` call:
  ```bash
  tk run <tool-a> --flag val --raw | tk run <tool-b> --from-stdin
  ```
- **Saved multi-step chain**: When a pipeline of 2+ tools will run again, save it as a deterministic chain so future runs take a single command:
  ```bash
  tk chain save <chain-name> --description "<what it does>" <step-1> <step-2>
  ```

## Evolve Loop: Capture → Generalize → Check

Whenever you solve a non-trivial task using raw CLI commands (`curl`, `gh`, `aws`, `kubectl`, `psql`, `python3`, etc.) or notice a missing capability, leave the toolkit stronger than you found it:

1. **Generalize** the working command or script: replace hardcoded IDs, paths, hosts, and branches with `$TK_ARG_<NAME>` variables.
2. **Save** the tool into `tools/<namespace>/<name>` (using `tk save` or copying [`tools/.template`](../../tools/.template)):
   ```bash
   tk save <namespace>.<name> --summary "<one-line summary>" --safety <read-only|mutating|destructive> --file <script-path>
   ```
   *Done when*: the single-file tool exists in `tools/` with complete `# @tk-*` headers and a real `@tk-example`.
3. **Check** the tool contract:
   ```bash
   tk check <namespace>.<name>
   ```
   *Done when*: `tk check` exits `0` and `tk run <namespace>.<name> --dry-run` succeeds.

## Reference Pointers

- Full vision and MCP replacement philosophy → [`VISION.md`](../../VISION.md)
- Single-file `# @tk-*` header spec and JSON envelope schema → [`ARCHITECTURE.md`](../../ARCHITECTURE.md)
- Canonical single-file tool template → [`tools/.template`](../../tools/.template)
