# 0007 — skills.sh distribution and skill rename

On 2026-11-04, at `ASabale/agent-toolkit@9db88a9`, the portable skill lived at `skills/toolkit/` with frontmatter `name: toolkit`. Issue #75 recorded two breaks for [skills.sh](https://github.com/vercel-labs/skills): `npx skills add ASabale/agent-toolkit` copies only the skill folder, so an agent gets `SKILL.md` without `tk`; and the name `toolkit` collides with other skills. On 2026-11-04, `ASabale/agent-toolkit@b6f36b3` renamed the skill and added the bootstrap contract.

## Decision

Rename the skill directory and frontmatter to `agent-toolkit`. `npx skills add ASabale/agent-toolkit` (or `owner/repo#branch`, or a local path) discovers `skills/agent-toolkit/SKILL.md` and installs that name for at least one agent (Claude Code or Cursor).

## Bootstrap contract

When `tk` is not on `PATH`, `SKILL.md` tells the agent to clone or update https://github.com/ASabale/agent-toolkit into `~/.agent-toolkit` (or run that clone's `install.sh`) and then call `~/.local/bin/tk` or `~/.agent-toolkit/tk`. The steps are idempotent. After bootstrap, `tk find <query>` must succeed.

`install.sh` links `skills/agent-toolkit` to `~/.agents/skills/agent-toolkit` (and `~/.claude/skills/agent-toolkit` when `~/.claude` exists). An old `toolkit` symlink is removed; a real `toolkit` directory is left in place.

## What this page does not change

On 2026-11-04, README, ARCHITECTURE, and CODING_STANDARDS still name `skills/toolkit`. Those edits are deferred to issue #77 so this change does not collide with #61, #73, and #74.

## Related

- [0002 — Minimum cognitive load and tokens](0002-minimum-cognitive-load-and-tokens.md)
- Issue #75
- Issue #77
