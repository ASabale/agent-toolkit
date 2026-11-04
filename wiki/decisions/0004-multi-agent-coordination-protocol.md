# 0004 — Multi-Agent Coordination Protocol

On 2026-11-04, `ASabale/agent-toolkit@cce91d4` introduced a coordination protocol for independent agent systems evolving the toolkit in parallel. The protocol uses GitHub as the only shared surface: issues, labels, branches, and pull requests.

## Why coordination is needed

On 2026-11-04, multiple independent agent systems (Cursor, Claude Code, OMP, Codex, Devin) were expected to evolve `agent-toolkit` concurrently. These systems cannot message each other directly. Without a protocol, agents risk:
- Claiming the same issue simultaneously.
- Editing the same files in conflicting PRs.
- Abandoning work without releasing claims.
- Merging their own PRs without steward review.

## What the protocol defines

On 2026-11-04, `COORDINATION.md` specified:

| Rule | Mechanism |
|------|-----------|
| Claim before work | Assign issue, add `in-progress` label, post claim comment with agent/system ID and branch name |
| Claim expiry | No branch commit and no issue comment for 24 hours releases the claim |
| Branch naming | `<agent-or-system>/<issue-number>-<slug>` encodes ownership and issue |
| One issue per PR | `Closes #N` in PR body; each PR addresses exactly one issue |
| File-overlap check | Query open PR files before editing; coordinate via pinned board if overlap is unavoidable |
| Rebase before review | Branch must be rebased on `main` before requesting review |
| Steward merge | Authors never merge their own PR; a steward reviews against `VISION.md` and merges |
| Cross-team questions | Pinned "Agent Coordination Board" issue for multi-agent coordination |

## What the commit added

On 2026-11-04, the commit added:
- `COORDINATION.md` at root (the protocol document).
- `.github/ISSUE_TEMPLATE/work-item.yml` (issue template with vision-alignment field).
- `.github/PULL_REQUEST_TEMPLATE.md` (PR template with claim, verification, and pre-merge checklist).
- This wiki decision record.

Labels (`needs-review`) and the pinned coordination issue require manual creation due to GitHub API access constraints.

## How the protocol serves VISION.md

On 2026-11-04, `VISION.md` at `ASabale/agent-toolkit@cce91d4` required minimum cognitive load and usage-driven evolution. The coordination protocol:
- Reduces cognitive load by standardizing claim, branch, and merge patterns.
- Prevents wasted work from collisions, serving minimum token spend.
- Ensures steward review against `VISION.md` so evolution stays aligned.

## Related

- [0003 — Autonomous Chief-of-Staff governance](0003-autonomous-chief-of-staff-governance.md)
- [COORDINATION.md](../../COORDINATION.md)
