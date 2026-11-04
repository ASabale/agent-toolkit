---
name: toolkit
description: Low-token, self-evolving CLI toolkit that replaces MCP servers. Use to find, run, chain, or save deterministic CLI tools for external services, APIs, repos, databases, and infrastructure.
---

# Agent Toolkit (`tk`)

**Purpose**: Get the job done in **minimum turns and minimum tokens** with near-zero cognitive load. Use existing tools first; when you solve a new repeatable task with raw commands, save it back so the toolkit evolves.

## 1. Use (`Find → Run`)

1. **Find** by intent (returns matching tools + exact runnable command):
   ```bash
   tk find "<intent>"
   ```
2. **Run** by copying the returned `tk run` line and filling `--flag` values:
   ```bash
   tk run <tool> --flag "<value>"
   ```
   - Need full flag details? Run `tk info <tool>`.
   - Command failed? Run the exact `fix` command printed in `stderr`.
   - Multi-step workflow? Pipe JSON (`tk run<a> | tk run <b>`) or run a saved chain (`tk run <chain>`).

## 2. Evolve (`Save → Check`)

When `tk find` misses and you solve a repeatable or noisy multi-step task with raw CLI commands:

1. **Save** the generalized command/script (use `$TK_ARG_<FLAG>` for inputs, emit compact JSON to `stdout`):
   ```bash
   tk save <namespace>.<name> --summary "<1-line summary>" --safety <read-only|mutating|destructive> --file <script>
   ```
   Or save a multi-tool pipeline as one command:
   ```bash
   tk chain save <namespace>.<name> --summary "<1-line summary>" --steps '<json-or-names>'
   ```
2. **Verify** contract and dry-run:
   ```bash
   tk check <namespace>.<name> && tk run <namespace>.<name> --dry-run
   ```
3. **Review and prune** the catalog: `tk evolve` reports unused tools, failures, and overlap; `tk prune` archives tools you no longer want.

## Rules for Every Tool
- **Minimum tokens**: Distill outputs—strip noise, logs, and unused fields before printing to `stdout`.
- **Zero guessing**: Named `--flags` only; never positional args; never hardcode IDs, hosts, or paths.
- **No bloat**: Never wrap a single standard UNIX command 1:1; only save tools that collapse steps, filter noisy output, or enforce safety.
