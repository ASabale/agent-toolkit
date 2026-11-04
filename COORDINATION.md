# Multi-Agent Coordination Protocol

Independent agent systems evolve this toolkit in parallel with no direct messaging. The only shared surface is this GitHub repo. This protocol prevents collisions and enables handoffs using issues, labels, branches, and commits.

## Claiming Work

Before starting any work:

1. **Check for conflicts**: Review open issues, open PRs, active branches (`git branch -r | grep -v HEAD`), and recent commits on `main`.
2. **Claim an issue**: Assign yourself, add the `in-progress` label, and post a comment:
   ```
   Claimed by <agent-name>/<system-id>. Branch: <branch-name>.
   ```
3. **Create a branch**: Name it `<agent-or-system>/<issue-number>-<slug>` (e.g., `cursor/42-fix-dry-run`).
4. **One issue per PR**: Each pull request references exactly one issue via `Closes #N` in the description.

## Claim Expiry

A claim expires if:
- No commit activity on the branch for **24 hours**, and
- No comment update on the issue in **24 hours**.

After expiry, any agent may take the issue: post a claim comment, reassign, and continue or restart on a fresh branch.

## File-Overlap Avoidance

Before editing a file, check whether another open PR already touches it:
```bash
gh pr list --state open --json number,files --jq '.[].files[].path' | sort -u
```
If overlap is unavoidable, coordinate via the pinned **Agent Coordination Board** issue or wait for the other PR to merge.

## Branch & PR Workflow

1. Rebase on `main` before requesting review.
2. Keep commits atomic; one logical change per commit.
3. Push and open a PR with the `needs-review` label.
4. Reference `Closes #N` in the PR body.

## Steward Review & Merge

A **Steward** is any agent or human with the `steward` label on an issue they filed or with explicit steward authority. Stewards:
- Review PRs against [`VISION.md`](VISION.md) and the architectural invariants in [`AGENTS.md`](AGENTS.md).
- Verify `tk check`, wiki lint, and tests pass.
- Merge when approved. **Authors never merge their own PR.**

## Cross-Team Questions

For questions that affect multiple agents or systems, comment on the pinned **Agent Coordination Board** issue. Include:
- A clear question or proposal.
- Links to relevant issues/PRs.
- Your agent/system identifier.

## Labels Reference

| Label | Meaning |
|-------|---------|
| `in-progress` | Work actively claimed |
| `needs-review` | PR ready for steward review |
| `blocked` | Waiting on external dependency or decision |
| `research` | Exploratory work, not yet ready for build |
| `build` | Implementation-ready |
| `steward` | Filed or owned by a steward |

## Quick Checklist

- [ ] Checked open issues, PRs, branches, and recent `main` commits
- [ ] Claimed issue with comment, label, and assignment
- [ ] Branch name follows `<agent>/<issue>-<slug>` pattern
- [ ] Rebased on `main` before review
- [ ] PR references `Closes #N`
- [ ] `tk check`, wiki lint, and tests pass
- [ ] Added `needs-review` label
