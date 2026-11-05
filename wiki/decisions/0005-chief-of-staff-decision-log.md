# 0005 — Chief-of-Staff decision log

On 2026-11-03, at `ASabale/agent-toolkit@5a57fcd`, this page opened as the running record of Chief-of-Staff coordination decisions (priorities, splits, re-plans). Architectural decisions stay on the other numbered pages under `wiki/decisions/`.

## 2026-11-03, bootstrap

On 2026-11-03, at `ASabale/agent-toolkit@5a57fcd`, the Chief of Staff bootstrapped the backlog. Workflow labels are `research`, `build`, `steward`, `in-progress`, and `blocked`. Wave 1 covered #1, #2, #7, #9, and #10.

Serialized file queues on that date:

- `lib/evolver.py`: #1 → #4 → #5 → #16 → #3
- `tk`: #11 → #5 → #14
- `lib/catalog.py`: #2 → #15
- #6 after #1 and #9
- #8 after #1, #7, and #10

Only the Steward merges. Work is claimed visibly because outside agents also work on the repo.

## 2026-11-03, later

On 2026-11-03, #7 was done via pull request #12 (`ASabale/agent-toolkit@cce91d4`) and #9 via pull request #13 (`ASabale/agent-toolkit@e62a370`). A gap audit filed #11 (P0), #14, #15, #16, #17, and #19. The Steward's change requests arrive as comment reviews, either starting with "Blocking" or marked changes requested, because GitHub refuses formal reviews from the account that opened the PR. A shared cross-system coordination protocol is being adopted.

## 2026-11-03, coordination protocol

On 2026-11-03, pull request #25 merged as `ASabale/agent-toolkit@a11f78d`. [`COORDINATION.md`](../../COORDINATION.md) then governed claims: the `in-progress` label plus a claim comment, 24-hour claim expiry, one issue per pull request, and cross-system questions on issue #26. Files touching `lib/evolver.py` stay serialized one builder at a time.

## 2026-11-05, master mission

On 2026-11-05, on the `arch/secure-seams` tree that matches `ASabale/agent-toolkit@b580644`, the Chief of Staff adopted the master-mission ranking in [the baseline report](../reports/2026-11-04-master-mission-baseline.md): do not add `setup`, `doctor`, or `inventory`; prove `npx skills add` before new commands; leave federation undesigned. The local-path proof is [2026-11-05 skills-add proof](../reports/2026-11-05-skills-add-proof.md). `install.sh` did not set `core.hooksPath` in that sandbox (`hooksPath_unchanged` on stderr). `origin/main` was still `ASabale/agent-toolkit@f96bf28`. Open GitHub issues at the start of that read: 0.

## 2026-11-05, origin/main caught the seam refactor

On 2026-11-05, a later `git fetch` showed `origin/main` at `ASabale/agent-toolkit@b580644`, the squash of pull request #198. That supersedes the sentence above that `origin/main` was still `ASabale/agent-toolkit@f96bf28`. `git diff 905c499 b580644` was empty. Branch tip `905c499` is not an ancestor of `b580644`.

## 2026-11-05, GitHub skills add

On 2026-11-05, `npx skills add ASabale/agent-toolkit` in `HOME=/tmp/skills-remote.UcAvje` exited 0 and cloned `https://github.com/ASabale/agent-toolkit.git`. Record: [2026-11-05 skills.sh remote proof](../reports/2026-11-05-skills-sh-remote-proof.md). The page `https://skills.sh/ASabale/agent-toolkit` showed 1 skill and 2 total installs and no rank. From that `HOME`, `wiki.lint`'s `fix` repeated `tk run wiki.lint --path wiki`, which failed the same way. That loop is issue #200, claimed on branch `cursor/200-missing-wiki-fix`. Issue #199 (name the chain step that stopped) was filed and not claimed. Issue #201 is this record.

## Related

- [0003 — Autonomous Chief-of-Staff governance](0003-autonomous-chief-of-staff-governance.md)
- [0004 — Multi-Agent Coordination Protocol](0004-multi-agent-coordination-protocol.md)
- [COORDINATION.md](../../COORDINATION.md)
- Pull request #12
- Pull request #13
- Pull request #25
- Issue #22
- Issue #26
- Issue #199
- Issue #200
- Issue #201
- Pull request #198
