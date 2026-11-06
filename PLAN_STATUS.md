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

## T0.3 Architecture review and threat model

status: DONE
branch: plan/t0.3-architecture-review
baseline: no product code since T1.1; unittest 460 OK was the T1.1 commit hook; T1.2 changed no product code
result: design only. Gateway, trust, namespaces, secrets, MCP, isolation, and self-audit are specified. No enforcement was added.
verify-evidence: `lib/runner.py` `_safe_write_result` still returns dry_run/plan/apply and `_apply_command` still appends `--yes`. `lib/guards.py` `tool_subprocess_env` is an allowlist, not a jail. `lib/evolver.py` `log_event` appends with no lock. `SECURITY.md` still says `--yes` performs the write. `CODING_STANDARDS.md` §2.1 header fields unchanged.
changes: ARCHITECTURE_REVIEW.md, THREAT_MODEL.md, DECISIONS.md, docs/HARDENING_PLAN.md, PLAN_STATUS.md
acceptance-output: not a behavior change. The amended plan is `docs/HARDENING_PLAN.md`. Human decisions are `DECISIONS.md` D1–D7. Defaults leave `--yes`, the catalog layout, MCP import, self-audit, and OS isolation unimplemented.
decisions: VISION and the existing `@tk-*` contract stay. Plan hash is integrity, not authorization. Destructive `--yes` removal waits on D1. No `tomllib`. No `TK_HOME`. No silent project override. `tk doctor` stays unbuilt. T0.4–T0.7 are the sections of this review, not extra branches. `arch/secure-seams` was not merged; its guard work is already on this tree.
follow-ups: next implementation is T1.3 plan integrity only, on a new branch. Do not start T1.3b, T4.3, T4.6, or an isolator until the matching decision in DECISIONS.md is accepted. T1.7 is the narrow fix filter left over from T1.2.

## T1.3 Plan integrity

status: DONE
branch: plan/t1.3-plan-integrity
baseline: unittest 460 OK on plan/t1.1-redact; tk check 41/41
result: unittest 467 OK (460 plus tests.test_plan_id 7); tk check 41/41; wiki.lint ok
verify-evidence: a changed `--path` changes `plan_id`. A stale `--confirm` exits 2 with `plan_mismatch` and does not create the file. A matching `--confirm` through `tk run` creates the file and returns `{}`. `--yes` still executes. `apply` still ends with `--yes`. New error text does not say the run was permitted by the hash.
changes: lib/runner.py adds `plan_id` and `confirm` on the unconfirmed write payload and checks `--confirm`; tk passes `confirm_id`; lib/catalog.py reserves `--confirm`; tests/test_plan_id.py added
acceptance-output:
```
TK_NO_TELEMETRY=1 TK_STATE_DIR=$(mktemp -d) python3 -m unittest tests.test_plan_id tests.test_safe_writes tests.test_gh_write_tools -v
Ran 23 tests in 3.915s
OK

TK_NO_TELEMETRY=1 TK_STATE_DIR=$(mktemp -d) python3 -m unittest discover -s tests
Ran 467 tests in 163.823s
OK

TK_NO_TELEMETRY=1 ./tk check --json
ok true, checked 41, errors []

TK_NO_TELEMETRY=1 ./tk run wiki.lint --path wiki
{"ok": true}
```
decisions: `plan_id` checks that the later command matches the dry-run plan. It does not change `--yes` (D1 default). In-process `confirmed=True` still executes. No SKILL.md change.
follow-ups: T1.3b waits on an explicit D1 acceptance. Do not start T4.3, T4.6, or an isolator until that decision row is accepted. T1.7 can follow and does not share these lines.

## T1.4 `@tk-needs`

status: DONE
branch: plan/t1.4-needs
baseline: unittest 467 OK; tk check 41/41 (T1.3)
result: optional header. A missing command or `env:NAME` is an error with a `fix`. The tool body still runs. Nothing is installed.
verify-evidence: fixture `@tk-needs: definitely-missing-bin` fails check and names that token plus `fix:`. A tool with no `@tk-needs` line stays ok. `sh` plus a set `env:TK_NEEDS_PRESENT` stays ok. A missing need does not hide a dry-run JSON failure.
changes: lib/catalog.py parses `@tk-needs` and reports `missing executable` / `missing env`; CODING_STANDARDS.md documents the optional field; tests/test_catalog.py
acceptance-output:
```
TK_NO_TELEMETRY=1 TK_STATE_DIR=$(mktemp -d) python3 -m unittest tests.test_catalog tests.test_plan_id -q
Ran 48 tests in 3.517s
OK

TK_NO_TELEMETRY=1 TK_STATE_DIR=$(mktemp -d) python3 -m unittest discover -s tests -q
Ran 471 tests in 162.459s
OK

TK_NO_TELEMETRY=1 ./tk check --json
{"ok": true, "checked": 41, "errors": []}
```
decisions: bare token is a PATH command; `env:NAME` is an environment variable. No TOML. No confinement. This branch is stacked on `plan/t1.3-plan-integrity` and is not merged to `main` (issue #222).
follow-ups: T2.1 and T2.2 depend on this header. T1.5 is independent.

## T1.5 Lint is not a sandbox

status: DONE
branch: plan/t1.5-lint
baseline: unittest 471 OK; tk check 41/41 (T1.4)
result: a read-only stdout finding is tagged `lint:`. `tk run` still executes the tool. `SECURITY.md` says the lint is not a sandbox and tools run as the user.
verify-evidence: the fixture prints plain text after a JSON dry-run. `tk check` reports `lint:` and does not say `sandbox` or `isolation`. Deleting the marker and calling `run_tool` creates it again. Real catalog check JSON does not contain `sandbox`.
changes: lib/catalog.py tags the read-only live JSON finding and adds a `lint` list; SECURITY.md one sentence; tests/test_catalog.py
acceptance-output:
```
TK_NO_TELEMETRY=1 python3 -m unittest tests.test_catalog.CheckItemTests.test_read_only_lint_is_not_a_sandbox_and_run_still_executes tests.test_catalog.CheckItemTests.test_check_item_accepts_valid_tool -q
Ran 2 tests in 0.321s
OK

TK_NO_TELEMETRY=1 ./tk check --json
ok true, checked 41, errors [], sandbox False
```
decisions: only the read-only live JSON finding is tagged `lint`. Header and dry-run failures stay enforcement errors. The tag is not a sandbox and the field is not named isolation. Not merged to `main` (issue #223).
follow-ups: T1.6 trust label is next and does not share these lines.

## T2.1 `@tk-schema`

status: DONE
branch: plan/t2.1-schema
baseline: unittest 472 OK on plan/t1.5-lint (380c1ca); tk check 41/41
result: optional header. Dry-run JSON objects must contain each declared top-level key. No schema package. Tools with no header are unchanged.
verify-evidence: `@tk-schema: ok` passes when the object has `ok`. `@tk-schema: {ok, count}` fails and names `count` plus a `fix`.
changes: lib/catalog.py parses `@tk-schema` and checks keys after the existing dry-run smoke; CODING_STANDARDS.md; tests/test_catalog.py
acceptance-output:
```
TK_NO_TELEMETRY=1 python3 -m unittest tests.test_catalog.CheckItemTests.test_schema_keys_are_required_on_dry_run_object tests.test_catalog.CheckItemTests.test_schema_reports_a_missing_dry_run_key tests.test_catalog.CheckItemTests.test_check_item_accepts_valid_tool -v
Ran 3 tests in 0.427s
OK
```
decisions: keys are presence checks only. Braces reuse `output_keys`. Not merged to `main` (issue #226).
follow-ups: T2.2 `@tk-requires` depends on T1.4 and does not share the dry-run key check.

## T2.2 `@tk-requires`

status: DONE
branch: plan/t2.2-requires
baseline: plan/t2.1-schema at e32875c
result: optional header. `env:`, `bin:`, and `file:` (relative, inside the repo) are reads. Any other token is skipped and named under `skipped`. A skip is not a failure. No shell.
verify-evidence: `env:PATH, bin:python3, file:tools/demo/echo` passes. A missing file fails and includes `fix:`. `rm <marker>` is skipped, the marker is not created, and `ok` stays true.
changes: lib/catalog.py; CODING_STANDARDS.md; tests/test_catalog.py
acceptance-output:
```
TK_NO_TELEMETRY=1 python3 -m unittest tests.test_catalog.CheckItemTests.test_requires_file_inside_repo_passes tests.test_catalog.CheckItemTests.test_requires_missing_file_fails tests.test_catalog.CheckItemTests.test_requires_shell_is_skipped_not_run tests.test_catalog.CheckItemTests.test_check_item_accepts_valid_tool -v
Ran 4 tests in 0.612s
OK
TK_NO_TELEMETRY=1 ./tk check --json
ok true, checked 41, errors 0
```
decisions: a skip is recorded, not turned into a lint or a sandbox. Not merged to `main` (issue #227).
follow-ups: T2.3 fixtures depend on T2.1.

## T2.4 State locking

status: DONE
branch: plan/t2.4-lock
baseline: plan/t2.2-requires at 4c35be6
result: telemetry and audit appends take an advisory flock on a sibling lock. JSON state is written to a temp file and replaced while state.lock is held. The lock is local to one filesystem. O_APPEND is not the lock. Telemetry still swallows errors. A mutating run with no audit line is denied with audit_failed and does not start.
verify-evidence: two processes wrote 60 JSON lines with none torn. tk find env exited 0 when TK_STATE_DIR was a file. A mutating tool did not create its marker when the audit write failed. policy.json replace left no temp file.
changes: lib/evolver.py; lib/runner.py; SECURITY.md; tests/test_state_lock.py
acceptance-output:
```
TK_NO_TELEMETRY=1 python3 -m unittest tests.test_state_lock tests.test_runner tests.test_git_sync -v
Ran 51 tests in 11.950s
OK
```
decisions: isolation on the audit line is none. Not merged to main (issue #229).
follow-ups: T2.5 keeps the one TK_TIMEOUT path.

## T3.3 `@tk-keep`

status: DONE
branch: plan/t3.3-keep
baseline: plan/t2.4-lock at bb1b223
result: optional header. `tk prune --unused` skips a name with `@tk-keep`. A tool with no header is still unused after 50 run events when it is older than the first run and not referenced by a chain.
verify-evidence: `lab.held` is absent from `unused_tools`. `lab.stale` is present. `run_events` stays 50.
changes: lib/catalog.py; lib/evolver.py; CODING_STANDARDS.md; tests/test_keep.py
acceptance-output:
```
TK_NO_TELEMETRY=1 python3 -m unittest tests.test_keep -v
Ran 1 test in 0.287s
OK
```
decisions: chain protection and the newer-than-first-run rule are unchanged. Not merged to `main` (issue #233).
follow-ups: T3.4 does not add a second output cap.
