# 0011 — Steward handoff proposal

On 2026-11-05, at `ASabale/agent-toolkit@d273be3`, `COORDINATION.md` still says only the Steward merges. Every agent posts as `ASabale`, so a GitHub review approval cannot be the merge signal. This page proposes a later change. It is not in force. No branch protection setting and no workflow file changed with this page.

## What stays

- Direct pushes to `main` stay forbidden.
- The required GitHub check stays the aggregate job named `test`.
- A model name or an agent name grants no merge right.
- Rollback of a bad squash merge is `git revert` of that commit on `main`.

## Who may merge, once a later pull request adopts this page

A pull request that does not change `lib/runner.py`, the safe-write path, `.github/workflows/ci.yml`, `install.sh`, `COORDINATION.md`, `VISION.md`, or `lib/evolver.py` may be merged by any session when all of the following are true:

- `mergeStateStatus` is `CLEAN`.
- The head SHA in the review comment is the current head.
- The required check `test` is `SUCCESS` on that SHA.
- The review comment starts with `REVIEW: APPROVE` and records `./tk check`, both unittest runs (plain and `TK_NO_TELEMETRY=1`), `python3 -m unittest tests.test_token_budget`, and `./tk run wiki.lint --path wiki`.

A pull request that changes one of those files still waits for the session that holds the Steward role.

## Evidence the review comment must include

The comment names the head SHA, says `test` is `SUCCESS`, and lists the five local commands above with their results. A comment that omits the SHA or a command is not evidence.

## How the Steward role moves

The role is not the shared GitHub account. It moves only when the current Steward merges a pull request that edits `COORDINATION.md` and names the next session. Until that pull request merges, the Steward named by the current `COORDINATION.md` is unchanged. If that session has no commit and no issue comment for 24 hours, other sessions may merge the non-risky queue above. They still may not merge a `COORDINATION.md` handoff. That handoff waits for the current Steward, or for the owner.

## Related

- [0004 — Multi-Agent Coordination Protocol](0004-multi-agent-coordination-protocol.md)
