---
name: agent-toolkit
description: Find, run, chain, or save a tk CLI tool instead of an MCP server or a one-off script. Use when asked to "call this API", "query the repo", "hit the database", "check CI", "wrap this command", or "find a tool for X".
---

# Agent Toolkit (`tk`)

Existing tool first. Save one only after a raw command solved a repeatable task.

## 0. Bootstrap (if `tk` is missing)

Clone or update, then install. Re-running is safe:

```bash
git clone --depth 1 https://github.com/ASabale/agent-toolkit.git ~/.agent-toolkit || git -C ~/.agent-toolkit pull --ff-only
~/.agent-toolkit/install.sh
export PATH="$HOME/.local/bin:$PATH"
```

Or call `~/.agent-toolkit/tk` directly.

## 1. Find → Run

1. **Find**: `tk find "<intent>"` (match plus a runnable command).
2. **Run** that line: `tk run <tool> --flag "<value>"`.
   `tk info <tool>` for flags. On failure, run `fix` from `stderr`. If output has `next`, run it. Pipe JSON or `tk run <chain>` for multi-step.

"Open PRs on this repo" → `tk find "pull requests"`, then the printed `tk run` line.

## 2. Save → Check

When `tk find` misses:

1. **Save** (`$TK_ARG_<FLAG>` inputs, compact JSON on `stdout`): `tk save <namespace>.<name> --summary "<1-line summary>" --safety <read-only|mutating|destructive> --file <script>`
   Or: `tk chain save <namespace>.<name> --summary "<1-line summary>" --steps '<json-or-names>'`
2. **Verify**: `tk check <namespace>.<name> && tk run <namespace>.<name> --dry-run`
3. **Prune**: `tk evolve` reports unused, failures, overlap; `tk prune` archives drops.

## Rules
- Distill `stdout`. Named `--flags` only; no positional args; no hardcoded IDs, hosts, or paths.
- Do not wrap one UNIX command; save tools that collapse steps, filter noise, or enforce safety.
