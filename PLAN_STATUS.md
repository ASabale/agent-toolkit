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

## T0.2 Verify each suspected gap

status: DONE
branch: plan/t0.2-audit
baseline: tk check 41/41 ok; unittest 455 OK; wiki.lint ok (T0.1, no code since)
result: same (no product code changed)
verify-evidence: AUDIT.md A1–A15. None of T1–T5 is ALREADY_DONE. Partial only: T2.5 already has TK_TIMEOUT (default 60s, exit 1); T5.2 already has keyword _score and one ranking test.
changes: AUDIT.md added; PLAN_STATUS.md appended
acceptance-output: AUDIT.md table has rows A1–A15 with file evidence. No task marked ALREADY_DONE.
decisions: none new. Skill line-cap conflict from T0.1 still stands (skip T1.2's extra SKILL.md line).
follow-ups: T1.1 next. T2.5 must extend the existing timeout, not add a second one. T4.1 tk doctor conflicts with an older "do not rebuild doctor" note; re-check VISION.md before that task.

## T1.1 Secret scanning and redaction

status: DONE
branch: plan/t1.1-redact
baseline: tk check 41/41 ok; unittest 455 OK (T0.1)
result: tests.test_redact 5 OK; tk check on the real catalog still 41/41; full suite is the commit hook
verify-evidence: A4 was no. tools/sec/secret-scan is a manual tool and is not on the check, event, or stderr path.
changes: lib/redact.py added; lib/catalog.py check_item fails a tool or chain file that matches a secret rule and skips executing it; lib/evolver.py log_event redacts string values; lib/runner.py _failure and tk _err/_emit_streams redact stderr; tests/test_redact.py added
acceptance-output:
```
TK_NO_TELEMETRY=1 python3 -m unittest tests.test_redact -v
Ran 5 tests in 0.249s
OK

./tk check demo.leak
exit 1
{"name":"demo.leak","ok":false,"errors":["secret in file (github_token); remove the credential from the file; fix: tk check demo.leak"]}
secret_leaked False

failing run_tool with a runtime slack token:
stderr and events.jsonl contain *** and do not contain the token
ordinary why "missing --repo" unchanged
```
decisions: mask is ***; rule names only in check errors; no SKILL.md change
follow-ups: T1.2 fix contract. github_pat_ and ASIA keys are out of this rule set.

## T1.2 Harden the fix contract

status: SKIPPED
branch: plan/t1.2-fix-contract
baseline: unittest 460 OK on plan/t1.1-redact (455 plus tests.test_redact)
result: no product code changed
verify-evidence: A3 is real (`lib/runner.py` `_tool_failure` copies a tool stderr `fix`). Applying the plan's rule (fix must start with `tk ` and must not contain `;|&$`><` or a newline) fails pinned tests. `tests/test_error_hints.py` and `tests/test_gh_write_tools.py` require `gh auth login`. `tests/test_git_sync.py` requires `git … && tk run git.sync`. `tests/test_tool_sdk.py` requires a caller fix of `install it`. `tests/test_verify_flag.py` requires a prose fix containing `<`. `tests/test_runner.py` requires `TK_TIMEOUT=<n> tk …` and `TK_MAX_OUTPUT_BYTES=<n> tk … | tk run json.pick`. VISION.md wants that exact repair command. CODING_STANDARDS.md still forbids the extra SKILL.md line (51-line cap).
changes: PLAN_STATUS.md only
acceptance-output: not run; the task was skipped before commit. A trial of `safe_fix` was reverted after `tests.test_error_hints` failed on `gh auth login`.
decisions: VISION and the existing tests win. Do not add the SKILL.md line. Do not replace the current fix strings.
follow-ups: a later change can reject only a tool-supplied `fix` that adds a second command (`;`, unquoted `$()`, newline) while leaving every pinned fix string unchanged. That is narrower than this task.
