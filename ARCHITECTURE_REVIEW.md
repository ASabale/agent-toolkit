# Architecture review

Status: design record. No product code changes. Does not edit `VISION.md` or `ARCHITECTURE.md`.

Source: independent review applied to the tree at `e482992` (`plan/t1.2-fix-contract`), which contains the T0.1 baseline, the T0.2 audit, secret redaction (T1.1), and the skipped fix-contract rewrite (T1.2).

This review serves the objective: minimum cognitive load, minimum tokens, minimum execution time, maximum reliability, and enforceable security. A larger catalog does not serve that objective. A control that an agent cannot see, or that pretends to be stronger than it is, does not either.

## 1. What already stands

Completed work stays.

| Item | State | Evidence |
|---|---|---|
| T0.1 baseline | Done | `docs/BASELINE.md`. `tk check` 41/41. unittest 455 OK. |
| T0.2 gap audit | Done | `AUDIT.md` A1–A15. None of T1–T5 was already done. |
| T1.1 redaction | Done | `lib/redact.py`. Check, events, and stderr. Mask `***`. |
| T1.2 fix rewrite | Skipped | Pinned repairs are not `tk`-only (`gh auth login`, `git … && tk run …`). VISION and those tests win. |

`lib/guards.py` already allowlists the tool subprocess environment, rejects option-like git arguments, opens SQLite read-only, and refuses non-public HTTP targets unless `TK_ALLOW_PRIVATE_URLS=1`. `TK_TIMEOUT` (default 60s) kills the tool process group. Mutating and destructive `tk run` returns a plan unless `--yes` is present. `tk check` dry-runs mutating tools in a scratch directory. These are real controls. They are not a sandbox.

`arch/secure-seams` is an older branch that introduced much of `lib/guards.py`. That work is already on this tree. This review does not merge that branch.

## 2. Findings

### F1. Confirmation is unbound, and a hash would not fix that

`tk run` sets `confirmed` from `--yes` alone. `run_tool(..., confirmed=True)` is the in-process default, so library callers execute. The unconfirmed payload is `{"dry_run": true, "plan": [...], "apply": "tk run … --yes"}`. Nothing binds `--yes` to that plan. A plan hash would prove the later command matches the earlier plan. It would not prove the caller is allowed to run it.

Cognitive load stays low if the agent still sees one copy-pasteable command. Security improves only when that command is checked against policy, not when the flag is renamed.

### F2. Headers are claims, not trust

`@tk-safety`, `@tk-verified`, and `@tk-output` are parsed from the tool file. The tool author can write `@tk-verified: signed`. `tk check` and `tk evolve` recompute some of this (dry-run, date stamp). Nothing cryptographic checks a signature, and a date stamp is not a community review. Trust text must not skip the gateway.

### F3. Declared safety is not enforced by the OS

A `read-only` tool is still a subprocess of the user running `tk`. It inherits an allowlisted environment that includes `GH_TOKEN`, `GITHUB_TOKEN`, `SSH_AUTH_SOCK`, `HOME`, and every `TK_*` variable. It can read the filesystem the user can read, open network connections, and spawn processes. `tk check` does not run the tool under a profile that would stop those calls. Static lint can warn. It cannot confine.

### F4. There is one flat catalog

`discover_catalog` keys items by `@tk-name`. A duplicate name fails `tk check`. There is no `core` / `user` / `project` / `external` split and no `TK_HOME`. A later "project overrides core" rule would let an untrusted checkout replace `git.status` or `gh.pr-checks` without the agent noticing. That saves zero tokens and costs reliability.

### F5. Redaction is a backstop

T1.1 masks a fixed set of patterns on check output, event records, and stderr. `github_pat_` and `ASIA` keys are not in that set (`tools/sec/secret-scan` knows them; `lib/redact.py` does not). Stdout is not redacted, on purpose, so a tool can still return a value the caller asked for. `log_event` appends whatever payload a caller passes, after `redact_data`. It does not today dump `os.environ`. The allowlisted environment still places GitHub tokens in the tool process. Regexes do not make that safe.

### F6. Events are not an audit log

`log_event` opens `state/events.jsonl` with mode `"a"` and no lock. A line longer than `PIPE_BUF` can interleave across processes. Telemetry is allowed to fail open (`CODING_STANDARDS` §1.4). An audit record of "what was authorized and what was enforced" cannot fail open in the same way, or the absence of a line becomes indistinguishable from a swallowed write.

### F7. The old plan conflates four different jobs

Static `@tk-needs` checks, `--confirm <hash>`, read-only lint, and `@tk-verified` were sequenced as if together they made execution safe. They do not. The gateway below separates them so later tasks cannot claim more than they deliver.

### F8. Productivity is measured as catalog quality

`bench/mcp_vs_tk.py` measures idle bytes, discovery bytes, output bytes, tool-call count, and estimated tokens. It does not measure first-try success, recovery without a human, or time to adapt. A scripted fixture can guard a regression. It cannot show that an agent got better.

### F9. `tk doctor` would restart a retired idea

An older constraint says not to rebuild doctor. `VISION.md` does not ask for a doctor command. `ARCHITECTURE.md` lists the CLI surface as find, run, chain, save, evolve, prune, check, and info. A new top-level command increases cognitive load. A read-only self-audit is still useful, but only as a proposed capability that does not mutate and does not ship until a human accepts the surface change (see `DECISIONS.md`).

## 3. Execution gateway

Every `tk run` and `tk chain` execution passes four stages. Stages are ordered. A later stage cannot vouch for an earlier one.

```text
plan integrity → authorization → enforcement → audit
```

| Stage | Question | Answers with | Does not answer |
|---|---|---|---|
| Plan integrity | What exactly will run? | Canonical tool name, flag map, dry-run `plan` list, `plan_id` | Whether it is allowed |
| Authorization | Which policy permits it? | Local policy decision: allow, require human, deny | What the process can touch |
| Enforcement | What can the process actually access? | The controls the OS applied on this host | The header's `@tk-safety` |
| Audit | What happened? | One record: plan_id, decision, enforced controls, result | A secret value |

### 3.1 Plan integrity

`plan_id` is the full SHA-256 hex digest of canonical JSON (`schema` 1). A tool hashes its name, the executable file bytes, normalized args, and the dry-run `plan`. A chain hashes the chain file bytes, ordered step names, each step executable's bytes, normalized chain args, and the aggregate plan. No timestamps and no absolute paths. The hash is integrity, not authorization and not a person's identity. A secret-shaped flag value is `<redacted>` in `apply` and `confirm`; the caller supplies that value again. The id still hashes the real value.

The unconfirmed response gains two fields and keeps the current ones so existing agents still see `plan` and `apply`:

```json
{"dry_run":true,"plan":["…"],"plan_id":"<64 hex chars>","apply":"tk run name --flag value --yes","confirm":"tk run name --flag value --confirm <64 hex chars>"}
```

`--confirm <plan_id>` recomputes the hash and runs only on an exact match. A mismatch exits 2 with `error` `plan_mismatch`, a `why` that names the id, and a `fix` of the current unconfirmed command. The hash is integrity. The in-process `confirmed=True` default stays, so unit tests that execute tools do not all become dry-runs.

### 3.2 Authorization

Authorization is a local decision, stored outside the tool file. Proposed store: `state/policy.json` (stdlib `json`, not TOML; Python 3.9 has no `tomllib`). Absent file means the built-in default, not "allow everything the header claims."

Default policy, until a human changes it (`DECISIONS.md` D1):

| Safety | Unconfirmed | `--confirm <matching plan_id>` | `--yes` |
|---|---|---|---|
| read-only | run | run | run |
| mutating | return plan | run | run, and stderr warns that `--yes` is not bound to a plan |
| destructive | return plan | run only if policy says human approval is satisfied by a bound confirm | do not run |

The third row is the migration the review requires. It contradicts today's `SECURITY.md`, which says `--yes` performs the change, and it contradicts tests written for that sentence. It is specified here and not implemented on this branch. Implementing it is decision D1.

Local policy may further deny a name, require a bound confirm for a read-only tool that the operator does not trust, or name an explicit override (`project.git.status` instead of `git.status`). Policy does not grant a capability the enforcement stage cannot apply.

Human approval, when policy requires it, is the bound `--confirm` typed or pasted by the operator. There is no second unbound flag.

### 3.3 Enforcement

Enforcement is whatever the operating system actually applied. The runner records the set. Honest values today, with no new dependency:

- `env_allowlist` — `tool_subprocess_env` already does this.
- `timeout` — `TK_TIMEOUT` already does this.
- `output_cap` — existing stdout cap.
- `scratch_cwd` — `tk check` dry-run only, not `tk run`.
- `network_public` — only tools that call `public_url_error`.
- `sqlite_ro` — only tools that call `sqlite_ro_uri`.

`isolation` is `none` unless a platform profile was applied. The result object and the audit record say so. A lint warning is never reported as `isolation`.

Optional isolators, used only when the binary exists and the operator opted in (`TK_ISOLATION=seatbelt` or `TK_ISOLATION=bwrap`):

| Host | Mechanism | Confine | Limitation |
|---|---|---|---|
| macOS | `sandbox-exec` with a generated Seatbelt profile | filesystem reads outside an allowlist, some network | Profile language is legacy. Not a promise Apple will keep it. |
| Linux | `bwrap` if installed | filesystem and process namespace | Not installed by default. Not required. |
| Linux | `unshare` from util-linux | user and mount namespace, when permitted | Many CI kernels block it. |
| either | Landlock, seccomp | finer syscall and path policy | Not in the Python 3.9 stdlib. Out of scope until the stdlib can express it or a human accepts a dependency. |

If the requested isolator is missing, `tk run` fails closed for that invocation with `error` `isolation_unavailable`, `why` naming the host and the missing tool, and `fix` `TK_ISOLATION=none tk run …` only when policy allows `none`. The default remains `TK_ISOLATION` unset, meaning today's behavior plus an explicit `isolation: none` in the audit record. Silent fallback to "looks sandboxed" is forbidden.

This keeps execution time unchanged for the common path. Agents do not learn a new grammar until they opt in.

### 3.4 Audit

Telemetry (`search_miss`, `run_ok`, `run_error`) stays fail-open so a read-only `state/` cannot break `tk find`.

A separate append-only `state/audit.jsonl` records gateway decisions for mutating and destructive runs, and for any run where isolation was requested. Required fields: `ts`, `plan_id`, `name`, `decision` (`dry_run`, `allow`, `deny`), `via` (`policy`, `confirm`, `yes`, `unconfirmed`), `enforced` (list of control names), `isolation` (`none` or the mechanism), `exit`. No environment values, no raw flag values that matched a secret rule, no command line that still contains a secret. `redact_data` runs first.

Writes take an exclusive `fcntl.flock` on `state/audit.lock`, then append. `O_APPEND` alone is not the design: JSONL lines exceed `PIPE_BUF`, and NFS locking is best-effort. The record states `lock: flock`. If the lock or the write fails, a mutating or destructive run is denied (`audit_failed`), because an unrecorded write is not an authorized write. Read-only telemetry keeps today's swallow-on-error behavior.

JSON maps that must be updated atomically (`policy.json`, approval stamps) use a temp file in the same directory and `os.replace`. The lock is held across the replace.

## 4. Trust model

Trust is a label `tk` computes. It is not a string the tool file is allowed to invent. None of these labels skip authorization or enforcement.

| Label | How it is established | How it is checked |
|---|---|---|
| `draft` | `@tk-verified` is `none`, missing, or not a date. `tk save` writes this. | Parser. |
| `check_passed` | Latest `tk check <name>` exited 0 on this file's bytes. | Re-run the check, or compare a stored hash of the file to the hash taken when the check passed. A date in the header is not sufficient. |
| `locally_approved` | Operator recorded an approval in `state/approvals.json` for that file hash. | `tk` reads the state file. The tool cannot stamp this on itself. |
| `community` | File content matches a commit on the trusted remote's default branch. | `git` object id. A fork's local edit is not `community` until it is on that branch. |
| `signed` | Detached signature over the file bytes verifies against a key the operator already trusts. | Not implemented. No new dependency in this program. Reserved so `@tk-verified: signed` cannot impersonate it. |

`@tk-verified: <YYYY-MM-DD>` remains the existing promotion stamp for mutating tools (`tk check --verify`) and the human PR stamp for destructive tools. The review does not delete that field. New output calls it `verified_on`, a date, and reports `trust` separately. A tool that writes `signed` in the date field stays `draft` plus a check error.

Execution privilege comes from policy (section 3.2) and from the controls in section 3.3. A `community` tool with `@tk-safety: read-only` that shells out to `rm` is still not confined.

## 5. Capability namespaces

Names stay flat in the grammar (`tk run <name>`), which is what small models already learn. Resolution is not flat.

| Prefix | Meaning | Who may add one |
|---|---|---|
| `core.` | Shipped in this repository under `tools/` and reviewed on the trusted branch. | Maintainers, by PR. |
| `user.` | Operator's own tools, outside the project checkout. | Operator. Directory is decision D2. Not created by this review. |
| `project.` | Tools that belong to the repository being operated on, not to the toolkit. | That repository. |
| `external.` | Imported from an MCP server or another untrusted pack. | Import flow. Untrusted until policy says otherwise. |

Rules:

1. An existing catalog name does not change meaning because a project file appeared. `tk run gh.pr-checks` resolves to the toolkit tool. A project file that wants the same job is `project.gh.pr-checks` and is selected only when the agent names it, or when `state/policy.json` contains an explicit override for that name.
2. Overrides are printed in `tk find` and `tk info` (`override: project.gh.pr-checks`). A silent replacement is a bug.
3. `external.*` starts with trust `draft`, safety treated as `destructive` for authorization purposes until `tk check` has passed and policy allows a lower class. MCP annotations are not consulted for that decision.
4. Import prefers one generic adapter (`tk run external.mcp --server <name> --tool <name>`) over a generated executable per remote tool. Generated wrappers add catalog rows, idle discovery cost, and a shadowing surface. Decision D4.

Current tools keep their present names (`gh.pr-checks`, not `core.gh.pr-checks`). Renaming the catalog would break every example and every saved chain. `core` is the resolution class of "this file is the one on the trusted branch," not a mandatory rename. Decision D3 covers any later move of files into layer directories.

## 6. Secrets

Priority order. Redaction is last.

1. Do not write environment values into `events.jsonl`, `audit.jsonl`, stdout, or stderr. `log_event` must keep refusing to accept `os.environ` dumps. A payload key named `env` is dropped.
2. Do not put credentials in argv. Tools keep using `gh`'s existing login and the allowlisted environment. New tools do not grow `--token`.
3. Credential use stays in the helper that needs it (`gh`, `ssh-agent`). The runner does not copy those values into the plan, the audit record, or the `fix` string.
4. T1.1 redaction stays on check output, events, and stderr. Extend the rule list only with tests that build the secret at runtime. `github_pat_` and `ASIA` are a follow-up, not a claim of coverage.
5. State stays local (`TK_STATE_DIR` or `state/`). Nothing in this program uploads telemetry.

Stdout stays unredacted. Distilled tool output is the product. Redacting it would hide the value the agent asked for and would not be enforceable security.

## 7. MCP imports

An MCP tool definition is untrusted input: name, description, and schema can ask an agent to do something the description does not say.

The adapter, when a human allows the work (D4):

- Does not generate a file under `tools/` per remote tool.
- Resolves as `external.*`.
- Runs through the gateway. Default authorization is deny for anything the remote marks as writing, and deny for network targets `public_url_error` would reject.
- Prints the remote name and the local policy decision in `tk info`, in a few lines, so discovery tokens stay small.
- Depends on the layer decision only if it writes into a user directory. The generic adapter does not. Task dependency: T4.3 depends on this section and on D4, not on a user-layer migration, unless an implementation chooses files on disk. If it does, it also depends on D2 and D3.

## 8. Agent productivity

The benchmark gains the following measures. A scripted client may emit them for regression tests. The report labels that client `scripted`. Numbers from a scripted client are not agent usability.

| Measure | What it is | Scripted stand-in |
|---|---|---|
| First-attempt success | The task finished on the first `tk run` that followed `tk find`, with no human edit. | Fixture exit code. Not a substitute. |
| Discovery turns | `tk find` and `tk info` calls before the successful run. | Countable in the fixture. |
| Tokens | Bytes/4 remains the estimate already in `bench/mcp_vs_tk.py`. | Keep. |
| Tool calls per success | `tk run` count on the successful path only. | Countable. |
| Recovery | A failed run whose stderr `fix` the client executed, then succeeded, with no human. | Countable only if the client is real. |
| Reliability | Fraction of runs with the same plan_id that exited 0. | Countable. |
| Policy violations | Gateway `deny` records. | Countable once the audit log exists. |
| Adapt time | Wall time from a fresh `TK_STATE_DIR` to the first successful task. | A fresh directory measures install and discovery cost, not learning. |

Real harness numbers (OMP, Claude Code, Cursor, Codex, or Devin) are recorded only when that harness was actually invoked. Missing numbers stay missing.

## 9. `tk self-audit` (proposal only)

Not implemented. Decision D5.

A read-only report the agent can request. It does not write tools, edit headers, prune, or change policy.

It lists, each line with evidence and a one-line impact:

- Capabilities present (`tk find` names).
- Duplicate summaries or overlapping flags (same evidence `tk evolve` would use).
- Repeated `search_miss` queries with no later `tool_saved`.
- Tools whose recent `run_error` rate is high.
- Tools authorized more broadly than their last successful use (policy allows destructive; events show only read-only calls). This is a hint, not a confinement check.
- Missing executables named by `@tk-needs`, once that header exists.
- A core tool that already does the job a `search_miss` is asking for.

Output is compact JSON on stdout. It does not apply a recommendation. Changes go through `tk save`, `tk check`, `tk evolve`, and the gateway.

The smallest surface that does not add a subcommand is `tk check --audit` or a read-only tool `meta.self-audit`. Both still need D5, because `ARCHITECTURE.md` and the skill are the contract agents memorize. This review does not grow `SKILL.md` (51 lines, 2700 bytes, already full).

## 10. Corrections to the old task list

| Old task | Correction |
|---|---|
| T1.2 fix must start with `tk` | Stays skipped. A narrower filter may reject a second command in a tool-supplied `fix` while leaving pinned repairs intact. |
| T1.3 `--confirm` replaces the safety story | Split. Plan id is integrity (section 3.1). Authorization is section 3.2. `--yes` on destructive waits on D1. |
| T1.4 `@tk-needs` | Optional header. Presence check only. Not enforcement. No TOML. |
| T1.5 read-only lint | Keep, and print that it is not a sandbox. `SECURITY.md` gets one sentence when the lint lands. |
| T1.6 provenance tiers | Use section 4. Do not trust `@tk-verified: signed`. |
| T2.4 file lock via `O_APPEND` | Use `fcntl.flock` plus `os.replace`. Say when the lock is only advisory. |
| T2.5 timeout | Extend `TK_TIMEOUT`. Do not add a second timer. Exit 124 vs exit 1 is decision D6. |
| T3.1 layer directories | Do not move files until D3. Prefix rules in section 5 can ship without a move. |
| T4.1 `tk doctor` | Do not build. Self-audit is section 9 and D5. |
| T4.3 MCP wrappers | Generic adapter, untrusted `external.*`, D4. Depends on section 7. Depends on D3 only if it writes a user or project tree. |
| T5.x benches | Add section 8 measures. Keep the existing `_score` ranking. Label scripted clients. |

Python 3.9: no `tomllib`, no PEP 604 evaluation without `from __future__ import annotations`, no new packages. Policy and approvals are JSON.

## 11. What this review refuses to call progress

- A new tool whose job is already done by `gh`, `git`, or an existing `tk` tool.
- A sandbox claim backed by a linter.
- A plan hash described as permission.
- A self-declared verified or signed header.
- A project file that silently replaces a trusted name.
- A benchmark number produced by a fake agent and reported as usability.
- Growth of `SKILL.md`.

## 12. Implementation order after this document

Smallest changes that a later branch can prove with tests. None of them start on this branch.

1. Plan id and `--confirm` match check. `--yes` behavior unchanged until D1. Tests for mismatch and for the existing `--yes` path.
2. Audit record for mutating runs, with `fcntl` and `isolation: none`. Fail closed only for those runs.
3. `@tk-needs` as a non-executing check, errors naming the missing program.
4. Lint findings tagged `lint`, never `sandbox`.
5. Trust label computed beside the existing date stamp, without a new signature dependency.
6. Namespace resolution that refuses silent override. No directory move.
7. Benchmark fields that stay `null` when no real harness ran.
8. Destructive `--yes` removal only after D1.
9. Optional `sandbox-exec` / `bwrap` only after the audit record can say which one ran.
10. MCP adapter only after D4.
11. Self-audit only after D5.
