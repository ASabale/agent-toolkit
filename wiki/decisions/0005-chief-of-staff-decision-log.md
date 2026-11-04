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

## Related

- [0003 — Autonomous Chief-of-Staff governance](0003-autonomous-chief-of-staff-governance.md)
- [0004 — Multi-Agent Coordination Protocol](0004-multi-agent-coordination-protocol.md)
- [COORDINATION.md](../../COORDINATION.md)
- Pull request #12
- Pull request #13
- Pull request #25
- Issue #22
- Issue #26
