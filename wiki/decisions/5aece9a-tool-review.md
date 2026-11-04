# 5aece9a — Tool review

On 2026-11-03, `ASabale/agent-toolkit@5aece9a` (direct push, no pull request) added `tools/git/sync`, `tools/gh/pr-diff-digest`, `tools/http/health-probe`, `tools/data/csv-digest`, and `chains/gh.pr-overview.json`. No issue and no `search_miss` predated that commit. On 2026-11-04, the review recorded at `ASabale/agent-toolkit@a315a0a` ([issue #129 comment](https://github.com/ASabale/agent-toolkit/issues/129#issuecomment-6623156740)) measured a cold start: `tk evolve --no-promote` on a fresh checkout reported `telemetry.events: 0` and `unused_reason: insufficient_telemetry`.

## Decision

| Item | Origin | Cold start | Distilled bytes (measured 2026-11-04 at `ASabale/agent-toolkit@a315a0a`) | Call |
| --- | --- | --- | --- | --- |
| `tools/git/sync` | `ASabale/agent-toolkit@5aece9a`; no issue; no `search_miss` | `telemetry.events: 0` | Not measured (mutating). | **Keep.** On 2026-11-04, `AGENTS.md` at `ASabale/agent-toolkit@ddc9da4` mandated `tk run git.sync --repo .` on a feature branch, so this tool stayed off [#86](https://github.com/ASabale/agent-toolkit/issues/86) probation. Fixes: [#128](https://github.com/ASabale/agent-toolkit/issues/128) (dry-run on `main` must refuse), [#148](https://github.com/ASabale/agent-toolkit/issues/148) (runnable `on_base` hint and `not_a_repo` under `--dry-run`), [#31](https://github.com/ASabale/agent-toolkit/issues/31) (re-stamp `@tk-verified` via `--verify`), [#106](https://github.com/ASabale/agent-toolkit/issues/106) (`--repo .` follows the caller cwd). |
| `tools/gh/pr-diff-digest` | `ASabale/agent-toolkit@5aece9a`; no issue; no `search_miss` | `telemetry.events: 0` | 3,706 B from a 69,389 B `git show 5aece9a` diff (5 hunk headers per file, 30 files). | **Keep, on [#86](https://github.com/ASabale/agent-toolkit/issues/86) probation.** On 2026-11-04 the [#86](https://github.com/ASabale/agent-toolkit/issues/86) rule said to prune it if it was still under `unused_tools` once telemetry was sufficient. Fixes: [#149](https://github.com/ASabale/agent-toolkit/issues/149) (drop undeclared `TK_GH_BIN`), [#107](https://github.com/ASabale/agent-toolkit/issues/107) (boolean `truncated` carried no omitted count). |
| `tools/http/health-probe` | `ASabale/agent-toolkit@5aece9a`; no issue; no `search_miss` | `telemetry.events: 0` | 196 B for one URL. | **Keep, on [#86](https://github.com/ASabale/agent-toolkit/issues/86) probation.** On 2026-11-04 the [#86](https://github.com/ASabale/agent-toolkit/issues/86) rule said to prune it if it was still under `unused_tools` once telemetry was sufficient. |
| `tools/data/csv-digest` | `ASabale/agent-toolkit@5aece9a`; no issue; no `search_miss` | `telemetry.events: 0` | 1,443 B from a 5,000-row CSV of 439,282 B. | **Keep, on [#86](https://github.com/ASabale/agent-toolkit/issues/86) probation.** On 2026-11-04 the [#86](https://github.com/ASabale/agent-toolkit/issues/86) rule said to prune it if it was still under `unused_tools` once telemetry was sufficient. Fixes: [#151](https://github.com/ASabale/agent-toolkit/issues/151) (cap sample cells), [#107](https://github.com/ASabale/agent-toolkit/issues/107) (boolean `truncated`). |
| `chains/gh.pr-overview.json` | `ASabale/agent-toolkit@5aece9a`; no issue; no `search_miss` | `telemetry.events: 0` | 3,688 B versus 3,706 B from `gh.pr-diff-digest` on the same diff. The chain's `json.pick` only dropped `truncated`, and `--limit` returned `unknown_flag`. | **Retire.** On 2026-11-04 the review at `ASabale/agent-toolkit@a315a0a` called retire ([#150](https://github.com/ASabale/agent-toolkit/issues/150), also [#107](https://github.com/ASabale/agent-toolkit/issues/107) for the hidden boolean `truncated`). Later on 2026-11-04, #150 closed and `ASabale/agent-toolkit@ad02745` deleted `chains/gh.pr-overview.json`. |

On 2026-11-04, `git.sync` was the workflow exception. The other three kept tools (`pr-diff-digest`, `health-probe`, `csv-digest`) fell under the rule in [0008 — Tool probation](0008-tool-probation.md): once telemetry was sufficient they would appear under `unused_tools` in `tk evolve --no-promote`, and the next `tk prune --unused` would archive each one that still had no `run_ok`.

## Related

- [0008 — Tool probation](0008-tool-probation.md)
- Issue #86
- Issue #31
- Issue #106
- Issue #107
- Issue #128
- Issue #148
- Issue #149
- Issue #150
- Issue #151
- Issue #129
