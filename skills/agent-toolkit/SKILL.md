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
   Or: `tk chain <name> '<step>'` (same file as `tk chain save <namespace>.<name> --steps '<json>'`)
2. **Verify**: `tk check <namespace>.<name> && tk run <namespace>.<name> --dry-run`
3. **Prune**: `tk evolve` reports unused, failures, overlap; `tk prune` archives drops.

## Rules
- Distill `stdout`. Named `--flags` only; no positional args; no hardcoded IDs. Do not wrap one UNIX command.
- A mutating tool returns its plan unless you pass `--yes`.

## 3. Migrate off MCP

One real task, one file. Do not paste an MCP schema or a yaml sidecar into the repo.

1. `tk find "<intent>"`. If a tool hits, run it and turn that MCP off.
2. Otherwise save a command that already worked and prints one JSON value: `tk save <ns>.<name> --summary "<one line>" --from-cmd "<command>"`. Plain text is refused.
3. Named `--flag value` only. No positional args, no `--instance` ordering, and no secrets, hosts, or paths written into the file.
4. `tk check <ns>.<name>`. A mutating tool must pass `tk run <ns>.<name> --dry-run` and include `"dry_run": true` before you delete the old MCP entry or the yaml-plus-script pair.
5. Hit friction worth keeping? Open a Feedback issue: `https://github.com/ASabale/agent-toolkit/issues/new?template=feedback.yml`. Say what you ran and what happened. Agents keep it only when it fits `VISION.md`.
