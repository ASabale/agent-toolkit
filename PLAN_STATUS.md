# Hardening plan status

Source plan: local `HARDENING_PLAN.md` (not committed). Executor notes only. Append task blocks below.

## Decisions made

- Baseline file is `docs/BASELINE.md` because `docs/` already exists. The plan's fallback root `BASELINE.md` was not used.
- Branch names follow the plan (`plan/<task-id>-<slug>`). `COORDINATION.md` asks for `<agent>/<issue>-<slug>` and `Closes #N`. No open issue covers this plan. Conflict noted; measurement was not skipped.
- `CODING_STANDARDS.md` §3 caps `skills/agent-toolkit/SKILL.md` at 51 lines and 2700 bytes. The file is already 51 lines. The plan's "10 lines per task" budget and T1.2's extra skill line lose. Do not grow `SKILL.md`. Later skill edits must replace existing lines or be skipped.
- `py39` and `shellcheck` were not part of this baseline run.

## T0.1 Measure the current state

status: DONE
branch: plan/t0.1-baseline
baseline: tk check 41/41 ok; unittest 455 OK; wiki.lint ok
result: same (no code changed)
verify-evidence: not a gap task
changes: docs/BASELINE.md added (numbers only); PLAN_STATUS.md added
acceptance-output:
```
./tk check --json
exit 0
{"ok": true, "checked": 41, "errors": []}
real 1.54s

python3 -m unittest discover -s tests
Ran 455 tests in 211.314s
OK
real 211.44s

./tk run wiki.lint --path wiki
{"ok": true}
real 1.65s

SKILL.md: 51 lines, 397 words, 2625 bytes, token_est 556
tools: 39  chains: 2
tk find "": 6156 chars
tk find "failing checks": 320 chars
tk find "git blame": 729 chars
tk find "search code": 777 chars
```
decisions: docs/BASELINE.md path; suite includes wiki.lint from ci.yml
follow-ups: T0.2 audit; local py39 and shellcheck not run
