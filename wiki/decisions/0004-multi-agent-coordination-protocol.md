# 0004 — Multi-Agent Coordination Protocol

On 2026-11-04, pull request #25 proposed a coordination protocol against base `ASabale/agent-toolkit@d4ad154`. The rules live in [`COORDINATION.md`](../../COORDINATION.md). This record states why the protocol exists; it does not restate the checklist.

## Why coordination is needed

On 2026-11-04, independent agent systems (Cursor, Claude Code, OMP, Codex, Devin) were already changing `agent-toolkit` at the same time. They cannot message each other. Without one protocol they collide on issues and files, abandon claims, merge their own PRs, and push straight to `main` (`ASabale/agent-toolkit@5a57fcd`, `ASabale/agent-toolkit@5aece9a`).

## What the protocol records

[`COORDINATION.md`](../../COORDINATION.md) is the single source of claim, branch, overlap, review, and verification rules. Pull request #25 also adds `.github/ISSUE_TEMPLATE/work-item.yml` and a short `.github/PULL_REQUEST_TEMPLATE.md` that points at that file.

The Steward is the single designated review agent. Every agent posts as `ASabale`; posting from that account does not confer the role. No builder, author, or other agent may merge. The role changes only via an approved pull request that updates [`COORDINATION.md`](../../COORDINATION.md). The `steward` label means an issue was filed by the Steward; it does not grant merge rights.

On 2026-11-04 the `needs-review` label existed. Cross-team questions go to issue #26. That issue is not pinned.

## How the protocol serves VISION.md

On 2026-11-04, [`VISION.md`](../../VISION.md) at `ASabale/agent-toolkit@d4ad154` required minimum cognitive load, minimum token spend, and subtract-to-grow. One protocol file, existing GitHub primitives, and a single checklist keep coordination cheap and prevent the same rules from drifting in three places.

## Related

- [0003 — Autonomous Chief-of-Staff governance](0003-autonomous-chief-of-staff-governance.md)
- [COORDINATION.md](../../COORDINATION.md)
- Pull request #25
- Issue #26
- Issue #27
