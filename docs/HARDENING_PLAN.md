# Hardening plan (amended)

This file replaces the uncommitted local `HARDENING_PLAN.md` for any work after `e482992`. Where it disagrees with `VISION.md`, `ARCHITECTURE.md`, `CODING_STANDARDS.md`, `AGENTS.md`, or `SECURITY.md`, those files win. Note the conflict in `PLAN_STATUS.md` and skip the task.

`ARCHITECTURE_REVIEW.md`, `THREAT_MODEL.md`, and `DECISIONS.md` are the design this plan executes. Do not reopen them as empty tasks.

## Rules

- Python 3.9+, stdlib only. No new packages. No `tomllib` (3.11+). JSON for any new state file. `from __future__ import annotations` on every file that uses `X | Y`.
- One task, one branch `plan/<task-id>-<slug>`, off the previous plan commit. Do not commit to `main`. Do not push unless the operator asked.
- Baseline before, proof after: `./tk check --json` and `python3 -m unittest discover -s tests` with `TK_NO_TELEMETRY=1` and a fresh `TK_STATE_DIR`. Paste the real output into `PLAN_STATUS.md`.
- If the gap is already closed, mark `ALREADY_DONE` with file and line. Do not rebuild it.
- Do not weaken or delete a test to make a change pass. Updating a test because the contract got stricter is allowed only when this plan says the contract changed.
- Do not edit `VISION.md`. Do not grow `skills/agent-toolkit/SKILL.md` (51 lines and 2700 bytes, already full).
- Do not add a file under `tools/` unless the task says so.
- Grammar stays `tk run <name> [--flag value]`. Named flags, order independent. Success is compact JSON on stdout. Failure is `{"error","why","fix"}` on stderr.
- No secrets, tokens, or personal paths in files, logs, or status output.
- `DECISIONS.md` defaults apply. Do not implement a row whose default is "do not build."
- Stop and ask before deleting user data, before breaking the existing `@tk-*` fields current tools already use, or if tests fail for an unexplained reason after two attempts.

Optional headers may be added. Required header fields stay those in `CODING_STANDARDS.md` §2.1.

## Done

| Task | Status | Commit | Notes |
|---|---|---|---|
| T0.1 baseline | DONE | `4f8c672` | `docs/BASELINE.md` |
| T0.2 audit | DONE | `583cf93` | `AUDIT.md` |
| T1.1 redact | DONE | `876d383` | check, events, stderr |
| T1.2 fix rewrite | SKIPPED | `e482992` | pinned repairs are not `tk`-only |
| T0.3 design | this branch | | review, threat model, this plan, decisions |

## Design tasks (no further docs required)

These were the review's T0.3–T0.7. They are design-only and they are written.

| Id | Design | Where |
|---|---|---|
| T0.3 | Threat model and boundaries | `THREAT_MODEL.md` |
| T0.4 | Execution gateway | `ARCHITECTURE_REVIEW.md` §3 |
| T0.5 | Permission model | `ARCHITECTURE_REVIEW.md` §3.2 and §5 |
| T0.6 | Identity and provenance | `ARCHITECTURE_REVIEW.md` §4 |
| T0.7 | Platform isolation | `ARCHITECTURE_REVIEW.md` §3.3 |

Do not implement the gateway as one change. The tasks below are the slices.

## Implementation

Depends names are task ids. Do not start a task until its Depends are `DONE` or `SKIPPED` in `PLAN_STATUS.md`.

### T1.3 Plan integrity

Depends: T0.3.

Add `plan_id` and `confirm` to the unconfirmed mutating and destructive payload. `--confirm <plan_id>` runs the tool only when the recomputed id matches. Mismatch: exit 2, `plan_mismatch`, `fix` is the current unconfirmed command.

`--yes` behavior does not change (decision D1 default). In-process `confirmed=True` does not change.

Acceptance: a flipped flag changes the id; the old id is refused; `--yes` still applies; existing dry-run tests pass. The word "authorized" does not appear in the new errors.

### T1.3b Destructive `--yes` refusal

Depends: T1.3 and an explicit human acceptance of `DECISIONS.md` D1 step 2.

Not started under the default. If accepted: destructive `--yes` exits 2 with `confirm_required` and a `--confirm` fix. Mutating `--yes` stays. Update `SECURITY.md` in the same change. Update tests to the stricter contract. Do not delete coverage of the dry-run path.

### T1.4 `@tk-needs`

Depends: T0.3.

Optional header. `tk check` reports a missing executable or env name. It does not install anything and does not confine the tool. No TOML. Skip the tool body execution only when a secret rule already skipped it (T1.1).

Acceptance: a fixture with `@tk-needs: definitely-missing-bin` fails check with `error` text that contains the missing name and a `fix`. A tool with no such header is unchanged.

### T1.5 Lint is not a sandbox

Depends: T0.7.

Read-only static lint findings are tagged so a consumer can tell them from enforcement. One sentence in `SECURITY.md`: the lint is not a sandbox; tools run as the user. `isolation` is not a word used for a lint hit.

Acceptance: a fixture that would be a lint warning still runs under `tk run` when policy allows, and the check output does not say `sandbox`.

### T1.6 Trust label

Depends: T0.6.

`tk info` reports `trust` using the table in the review §4. `@tk-verified: <date>` remains. The value `signed` does not produce trust `signed`. No signature library.

Acceptance: a tool that writes `@tk-verified: signed` is `draft` (or `check_passed` only after a real check) and the output does not claim a signature was verified.

### T1.7 Narrow fix filter

Depends: T1.2 skipped.

Reject a tool-supplied `fix` that contains a newline or a second command (`;`, unquoted `$()`). Leave these strings passing, because tests pin them: `gh auth login`, `git … && tk run git.sync`, `install it`, the prose verify hint, `TK_TIMEOUT=… tk …`, `TK_MAX_OUTPUT_BYTES=… tk … | tk run json.pick`.

Acceptance: the pinned tests stay green without being edited. A fixture whose stderr `fix` is `tk run demo.echo; rm -rf /` does not survive.

### T2.1 `@tk-schema`

Depends: T1.4.

Optional. Check declared output keys when the tool emits a JSON object during the existing dry-run smoke. Do not add a schema language that needs a dependency.

### T2.2 `@tk-requires`

Depends: T1.4.

Optional precondition the check can evaluate without executing a write. If it cannot be evaluated that way, skip the header and record why. Do not shell out to an unbounded command.

### T2.3 Fixtures

Depends: T2.1.

Fixture files live next to tests, not in `tools/`. They prove schema and dry-run shape.

### T2.4 State locking

Depends: T0.3.

`log_event` and any new audit append take `fcntl.flock` on a sibling lock file. JSON state uses a temp file and `os.replace` while the lock is held. Document that the lock is advisory and local to one filesystem. Do not claim `O_APPEND` is enough.

Telemetry stays fail-open. A new audit log for mutating runs fails closed (review §3.4). If T1.3 has not landed, this task still locks `events.jsonl` and does not invent the audit log early.

Acceptance: a test with two processes appending does not tear a line. A simulated lock or write error still lets `tk find` exit 0.

### T2.5 Timeout

Depends: T0.2.

`TK_TIMEOUT` already exists (default 60s, exit 1). Do not add another timer. D6 default: keep exit 1. `--timeout` is not added unless D6 is answered in favor of a flag, and then it only sets the same variable for that invocation.

Acceptance: the existing timeout test still passes. `grep` shows one timeout path.

### T3.1 Layers

Depends: a human answer to D3 that overrides the default.

Default is no directory move. If the human wants a written `docs/LAYERS.md`, write that document to match D3 and stop. Do not move tools in the same change.

### T3.2 Version and deprecation

Depends: T1.6.

A deprecated tool remains findable and says what to run instead, in one line. No second catalog.

### T3.3 `@tk-keep`

Depends: T2.4.

Optional. `tk prune --unused` skips names marked keep. Absence of the header keeps today's prune rules (50 events, chain refs, newer-than-first-run).

### T3.4 Budgets

Depends: T0.1.

Per-tool output budget stays the existing cap mechanism. Do not add a second cap.

### T3.5 Executable docs

Depends: T0.2.

A test extracts fenced `tk` commands from `README.md` only if they are already valid. Do not delete a hash or a command to make the test pass. If a block is intentionally prose, leave it and record the skip. Ask before rewriting the README.

### T4.1 Doctor

SKIPPED. Do not rebuild `tk doctor`. See D5.

### T4.2 Migrate plan

Depends: T1.3, T2.4.

A dry-run report of what a move to another machine would copy: catalog, state path, and which credentials are "already in `gh`," not the credential values. Does not copy secrets. Does not create `TK_HOME` (D2).

### T4.3 MCP adapter

Depends: T0.5, and D4. Also depends on T3.1 only if the implementation writes a user or project tool tree. The default design does not, so T3.1 is not a dependency of the default.

Default is do not build. If D4 is accepted: one generic adapter, `external.*`, untrusted, no wrapper files, annotations ignored for authorization.

### T4.4 From history

Depends: T2.4.

Suggest a tool from repeated events. Do not save it. The agent still runs `tk save`.

### T4.5 Shadow

Depends: T1.3, D7.

Not "run the tool twice in production." A comparison mode is allowed only when D7's isolator exists, or as a dry-run diff that does not execute the write. Otherwise skip.

### T4.6 Self-audit

Depends: D5 choosing a surface, plus T2.4 so the report has events to read.

Read-only. Evidence and impact on every line. No automatic edit, prune, or policy write. No `SKILL.md` growth. If the skill must mention it, replace a line; do not add one.

### T5.1 Bench scoreboard

Depends: T0.1.

Extend `bench/mcp_vs_tk.py` with the measures in review §8. Fields that were not actually measured are JSON `null`, not zeros. Label `client: scripted` unless a real harness was invoked in that run.

### T5.2 Ranking

Depends: T0.2.

Keep `_score`. Do not replace it with fuzzy search. New ranking tests may only add cases.

### T5.3 Gate evolve

Depends: T1.6.

`tk evolve` does not promote a tool whose trust computation failed. It still does not stamp destructive tools.

### T5.4 Feedback

Depends: T5.1.

A compact local record of failed runs the agent already sees in stderr. No network.

### T5.5 Contract version

Depends: T1.3.

One integer in `tk info` for the gateway fields an agent can rely on. Bump it only when a stdout field changes meaning.

## Dropped or folded

| Old idea | Where it went |
|---|---|
| Fix must start with `tk` | T1.2 skipped. T1.7 is the narrow remainder. |
| `--confirm` as authorization | T1.3 is integrity. Authorization waits on D1 (T1.3b). |
| `O_APPEND` as the lock | T2.4. |
| Project overrides core by precedence | Refused. §5 of the review. |
| `tk doctor` | T4.1 skipped. T4.6 if D5 says so. |
| Generated MCP wrappers | Refused unless D4 says otherwise, and then still one adapter. |
| Exit 124 | D6 default keeps exit 1. |
| Required bubblewrap or Seatbelt | D7 default off. |

## Done when

All tasks above are `DONE`, `SKIPPED`, or `ALREADY_DONE`, D1–D7 are either still at their defaults or explicitly answered, and a final `HARDENING_REPORT.md` quotes the acceptance output already stored in `PLAN_STATUS.md`. The report does not claim isolation the audit field does not record, and it does not claim agent usability from a scripted bench.
