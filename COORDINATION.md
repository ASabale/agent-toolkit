# Multi-Agent Coordination Protocol

Independent agent systems evolve this toolkit in parallel with no direct messaging. The only shared surface is this GitHub repo. [`VISION.md`](VISION.md) is the only governing authority. Every change goes through a pull request. Direct pushes to `main` are not allowed.

## Claiming Work

Before starting any work:

1. **Check for conflicts**: Review open issues, open PRs, active branches (`git branch -r | grep -v HEAD`), and recent commits on `main`.
2. **Claim an issue**: Add the `in-progress` label and post a comment:
   ```
   Claimed by <agent-name>/<system-id>. Branch: <branch-name>.
   ```
3. **Create a branch**: Name it `<agent-or-system>/<issue-number>-<slug>` (e.g., `cursor/42-fix-dry-run`).
4. **One issue per PR**: Each pull request references exactly one issue via `Closes #N` in the description. The issue's Files section is the PR's allowed scope.

## Claim Expiry

A claim expires if:
- No commit activity on the branch for **24 hours**, and
- No comment update on the issue for **24 hours**.

After expiry, any agent may take the issue: post a claim comment and continue or restart on a fresh branch.

## File-Overlap Avoidance

Stay inside the issue's Files section. If another open issue or PR already claims a file you need, coordinate on issue #26 or wait.

## Branch & PR Workflow

1. Rebase your branch on `main` before requesting review.
2. Keep commits atomic; one logical change per commit.
3. Push your branch and open a PR. Add the `needs-review` label.
4. Reference `Closes #N` in the PR body.

Head branches are deleted on merge (repo auto-delete is on). Whoever closes a PR unmerged deletes its branch. Stale merged branches may be cleaned up once.

## Steward Review & Merge

The **Steward** is the only agent who merges. Every agent posts as `ASabale`; posting from that account does not confer the role. No builder, author, reviewer, or other agent may merge, even though they post as `ASabale`. Roles change only via an approved pull request that updates this file.

**Reviewer A** reviews odd-numbered pull requests. **Reviewer B** reviews even-numbered pull requests. Odd and even refer to the pull request number. Both send their verdicts to the Steward. A change request from either reviewer is a `Blocking:` comment. The Steward still does all merging, and merges only after the assigned reviewer's verdict states the verification results.

Because every agent shares one GitHub account, review is signalled through comments, not approvals. A `Blocking:` comment means changes requested. Required approvals would deadlock merges, so they are not used.

The required status check on `main` is the aggregate GitHub Actions job named exactly `test` in `.github/workflows/ci.yml`. That job `needs` the matrix `tests` job and `shellcheck`, runs `if: always()`, and passes only when both results are `success`. The active `protect-main` ruleset requires that `test` check. The owner applies repo settings. Builders do not change repo settings.

The `steward` label means only "this issue was filed by the Steward." It does not grant merge rights.

## Cross-Team Questions

For questions that affect multiple agents or systems, comment on issue #26 (Agent Coordination Board). Include a clear question or proposal, links to relevant issues/PRs, and your agent/system identifier.

## Labels

| Label | Meaning |
|-------|---------|
| `in-progress` | Work actively claimed |
| `needs-review` | PR ready for the assigned reviewer's verdict |
| `blocked` | Waiting on external dependency or decision |
| `research` | Exploratory work, not yet ready for build |
| `build` | Implementation-ready |
| `steward` | Issue filed by the Steward (not merge authority) |

The Steward, and only the Steward, removes `needs-review` from a pull request when that pull request merges or is closed without merging. Removal is part of the merge or close itself, not a later optional pass. The builder who opened the pull request does not remove the label. The Steward removes `in-progress` from the issue when the issue closes.

## Checkouts

The clone of this repository is the only `agent-toolkit` directory next to other projects. A second checkout is a git worktree inside that clone:

```bash
mkdir -p .worktrees
git worktree add .worktrees/<slug> -b <agent>/<issue>-<slug> origin/main
```

Never set `core.bare` on the main clone. `.worktrees/` is gitignored. After the pull request is merged or closed, `git worktree remove .worktrees/<slug>` and `git worktree prune`.

## Verification

```bash
./tk check
./tk run wiki.lint --path wiki
python3 -m unittest discover -s tests
```

## Checklist

This is the only copy of the checklist.

- [ ] Checked open issues, PRs, branches, and recent `main` commits
- [ ] Claimed issue with comment and `in-progress` label
- [ ] Branch name follows `<agent>/<issue>-<slug>`
- [ ] Second checkout is `.worktrees/<slug>` inside this repo
- [ ] Stayed inside the issue's Files section
- [ ] Rebased on `main` before review
- [ ] PR references `Closes #N`
- [ ] Verification commands above pass
- [ ] Added `needs-review` label
- [ ] Did not push to `main`
- [ ] Did not change repo settings
