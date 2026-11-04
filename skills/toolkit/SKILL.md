---
name: toolkit
description: Low-token CLI toolkit that replaces MCP servers. Find, run, chain, or save tools for services, APIs, repos, databases, and infrastructure.
---

# Agent Toolkit (`tk`)

**Purpose**: Minimum turns and tokens. Use an existing tool first. When raw commands solve a repeatable task, save it so the toolkit evolves.

## 1. Use (`Find → Run`)

1. **Find** by intent (matching tools plus a runnable command):
   ```bash
   tk find "<intent>"
   ```
2. **Run** that line with real `--flag` values:
   ```bash
   tk run <tool> --flag "<value>"
   ```
   - Flag details: `tk info <tool>`.
   - On failure, run the `fix` command from `stderr`.
   - If output has `next`, run it for more.
   - Multi-step: pipe JSON (`tk run <a> | tk run <b>`) or `tk run <chain>`.

## 2. Evolve (`Save → Check`)

When `tk find` misses and raw CLI solved a repeatable task:

1. **Save** (`$TK_ARG_<FLAG>` inputs, compact JSON on `stdout`):
   ```bash
   tk save <namespace>.<name> --summary "<1-line summary>" --safety <read-only|mutating|destructive> --file <script>
   ```
   Or a pipeline:
   ```bash
   tk chain save <namespace>.<name> --summary "<1-line summary>" --steps '<json-or-names>'
   ```
2. **Verify**:
   ```bash
   tk check <namespace>.<name> && tk run <namespace>.<name> --dry-run
   ```
3. **Prune**: `tk evolve` reports unused tools, failures, and overlap; `tk prune` archives what you drop.

## Rules for Every Tool
- **Minimum tokens**: distill `stdout`; drop logs and unused fields.
- **Zero guessing**: named `--flags` only; no positional args; no hardcoded IDs, hosts, or paths.
- **No bloat**: do not wrap one UNIX command; save tools that collapse steps, filter noise, or enforce safety.
