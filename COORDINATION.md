# Multi-Agent Coordination Protocol

Independent agent systems evolve this toolkit in parallel with no direct messaging. The only shared surface is this GitHub repo. [`VISION.md`](VISION.md) is the only governing authority.

## Pull requests required

Every change goes through a pull request. Direct pushes to `main` are not allowed.

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
- No comment update on the issue for **24 hours**.

After expiry, any agent may take the issue: post a claim comment, reassign, and continue or restart on a fresh branch.

## File-Overlap Avoidance

Before editing a file, check whether another open PR already touches it:
```bash
gh pr list --state open --json number,files --jq '.[].files[].path' | sort -u
```
If overlap is unavoidable, coordinate on issue #26 or wait for the other PR to merge.

## Branch & PR Workflow

1. Rebase on `main` before requesting review.
2. Keep commits atomic; one logical change per commit.
3. Push and open a PR. Add the `needs-review` label.
4. Reference `Closes #N` in the PR body.

## Steward Review & Merge

The **Steward** is Akshay Sabale (`ASabale`). That assignment is recorded here and in [`wiki/decisions/0004-multi-agent-coordination-protocol.md`](wiki/decisions/0004-multi-agent-coordination-protocol.md). It changes only when an approved pull request updates those records. Filing an issue, adding a label, or claiming work does not confer the role.

The `steward` label means only "this issue was filed by the Steward." It does not grant merge rights.

The Steward:
- Reviews PRs against [`VISION.md`](VISION.md).
- Verifies the commands below pass.
- Merges when approved. **Authors and builders never merge their own PR.**

## Cross-Team Questions

For questions that affect multiple agents or systems, comment on issue #26 (Agent Coordination Board). Include:
- A clear question or proposal.
- Links to relevant issues/PRs.
- Your agent/system identifier.

## Labels

| Label | Meaning |
|-------|---------|
| `in-progress` | Work actively claimed |
| `needs-review` | PR ready for steward review |
| `blocked` | Waiting on external dependency or decision |
| `research` | Exploratory work, not yet ready for build |
| `build` | Implementation-ready |
| `steward` | Issue filed by the Steward (not merge authority) |

## Verification

```bash
./tk check
./tk run wiki.lint --path wiki
python3 -m unittest discover -s tests
```

## Checklist

This is the only copy of the checklist. The pull request template and wiki decision 0004 point here.

- [ ] Checked open issues, PRs, branches, and recent `main` commits
- [ ] Claimed issue with comment, `in-progress` label, and assignment
- [ ] Branch name follows `<agent>/<issue>-<slug>`
- [ ] Rebased on `main` before review
- [ ] PR references `Closes #N`
- [ ] Verification commands above pass
- [ ] Added `needs-review` label
- [ ] Did not push to `main`
