# Threat model

Design record for the tree at `e482992`. Scope is `tk` on the machine where an agent invokes it: the dispatcher, `lib/`, `tools/`, `chains/`, and `state/`. There is no account, registry, or remote tool download (`SECURITY.md`).

This document names attackers, what they can already do, and which control actually reduces that. A control that only relabels the same behavior is listed as a non-mitigation.

## Assets

| Asset | Why it matters |
|---|---|
| User files and git working trees | Tools run as the user, in the caller's cwd. |
| Credentials in the environment and agent sockets | `GH_TOKEN`, `GITHUB_TOKEN`, `SSH_AUTH_SOCK`, `gh` keyring. |
| The catalog the agent trusts | `tk find` output is what a small model will run. |
| `state/events.jsonl` and any future audit log | History of queries, failures, and (if misbuilt) secrets. |
| The toolkit clone | A local edit changes the next `tk run` for every agent using that clone. |

## Actors

| Actor | Capability |
|---|---|
| The agent | Runs `tk` with the user's uid. Follows `fix` strings. Can be talked into a bad flag value. |
| A tool author | Writes a single file under `tools/` or `chains/`, including headers. |
| A project the agent is editing | Can contain files the agent is told to save as tools, or a future project overlay. |
| An MCP server the operator chooses to import | Supplies names, descriptions, and schemas. Not running inside `tk` until an adapter exists. |
| Another local user | Out of scope where the OS already isolates home directories. In scope for world-readable `state/` and for a toolkit clone on a shared disk. |
| A remote network peer | In scope only for tools that open HTTP or git remotes. |

Not in scope: a kernel exploit, a malicious Python interpreter on `PATH`, or a human who already has the operator's shell. `tk` cannot confine those.

## Trust boundaries

```text
agent text
    → tk argv
        → header parse and flag validation
            → policy decision          (not implemented; today: --yes or dry-run)
                → subprocess as the user
                    → filesystem, network, other processes
```

The header parse is inside the attacker's data if the attacker wrote the tool. The subprocess is outside `tk`'s address space and inside the user's privileges. That is the boundary that matters. Everything before it is filtering.

Today the boundary is crossed with:

- an allowlisted environment (`tool_subprocess_env`)
- a timeout (`TK_TIMEOUT`, default 60s)
- an output cap
- a dry-run gate for mutating and destructive tools unless `--yes`
- per-tool checks where a tool calls them (git token shape, public URL, read-only SQLite)

There is no filesystem jail, no network jail, and no syscall filter on `tk run`.

## Threats

### T1. Unbound confirmation

A mutating tool returns a plan. The agent, or a second prompt, runs the same name with `--yes` and different flags. The first plan is not what runs.

Current mitigation: the agent must include `--yes`, and tests cover the dry-run default for `tk run`. This stops an accidental first invocation. It does not bind the approval to the plan.

Residual risk: high for destructive tools, because the published contract treats `--yes` as approval of whatever the new argv says.

Intended mitigation: `plan_id` over canonical name, flags, and plan (`ARCHITECTURE_REVIEW.md` §3.1). `--confirm` must match. `--yes` stops authorizing destructive runs only after decision D1. Until then this threat stays open. A hash without that policy change does not close it.

### T2. Tool file declares itself safe

`@tk-safety: read-only` on a script that deletes files, or `@tk-verified: signed` on a script nobody signed.

Current mitigation: `tk check` requires a `TK_DRY_RUN` branch for mutating and destructive headers, and smoke-runs them in a scratch directory. Read-only tools are also smoke-run, but a hostile read-only tool is not confined by that smoke run. The verified field is a date the promoter writes.

Residual risk: a read-only classification is a claim. Check smoke can be satisfied by a script that is benign only when `TK_DRY_RUN=1`.

Non-mitigation: more header keys (`@tk-needs`, `@tk-schema`, `@tk-keep`) that the same author writes.

Intended mitigation: trust labels computed by `tk` (§4 of the review). Enforcement that does not consult the header for privilege. Lint stays, labeled as lint.

### T3. Secret in a file, an event, or stderr

A token committed inside a tool, or interpolated into `why` / `fix`, is replayed into the agent's context and into `state/events.jsonl`.

Current mitigation: T1.1 `secret_hits` blocks `tk check` from executing that file and reports the rule name. `redact_data` runs on event records. `tk` redacts stderr. Rules cover a GitHub token prefix, `AKIA`, `Bearer`, a PEM begin line, a Slack token prefix, and a `token|key|password=` assignment. Overlap keeps the earlier rule.

Residual risk: `github_pat_` and `ASIA` are not in `lib/redact.py`. Stdout is not redacted. The tool process still receives `GH_TOKEN` when it is set. A novel secret shape is not masked. Regex redaction is not a guarantee.

Intended mitigation: do not log environment values, do not add `--token` flags, keep credentials in `gh` and ssh-agent, extend rules only with tests. Redaction remains defense in depth.

### T4. Argument and environment injection

Flag values reach the environment as `TK_ARG_*` and sometimes a shell. A value starting with `-` can become a git option. A fix string can carry a second command.

Current mitigation: `safe_git_token` / `safe_git_path`, `shlex.quote` on runner-built fix commands, public URL checks, read-only SQLite URIs. T1.2's "fix must start with `tk`" was skipped because real repairs are `gh auth login` and `git … && tk run git.sync`.

Residual risk: a tool-supplied `fix` is copied through when it already has `error` / `why` / `fix`. A second command inside that string still reaches the agent, who may run it. That is model-level, not process-level.

Intended mitigation, narrow: reject a tool-supplied `fix` that adds a command separator or a newline, without rewriting pinned repairs. Not a sandbox.

### T5. Catalog shadowing

If project or imported tools can take the same name as a toolkit tool, `tk find` and `tk run` will execute the untrusted one.

Current mitigation: one catalog, duplicate names fail `check_item`. No project overlay exists. This threat is latent. The old plan's project-over-user-over-core precedence would make it real.

Intended mitigation: `core` / `user` / `project` / `external` resolution with no silent replacement (`ARCHITECTURE_REVIEW.md` §5). Explicit override in `tk find` output.

### T6. MCP description is not the behavior

A remote tool's description says "read an issue." The call posts a comment or sends the prompt to another host.

Current mitigation: there is no MCP importer. The threat is future work.

Intended mitigation: one generic `external.*` adapter, default deny for writes, `public_url_error` on its URLs, no generated wrapper per tool. Annotations are ignored for authorization. Decision D4 before any of that is built.

### T7. Concurrent state corruption

Two `tk` processes append `events.jsonl`. A torn line breaks the next `tk evolve` parse. A non-atomic policy write could persist a half-written allow rule.

Current mitigation: telemetry failures are swallowed so `tk` still runs. That protects availability of the command, not integrity of the log.

Residual risk: torn JSONL, lost lines, and (once policy exists) a torn allow.

Intended mitigation: `fcntl.flock` around audit appends; `os.replace` for JSON state. Document that the lock is local-filesystem and advisory. Do not treat `O_APPEND` as sufficient. Mutating runs fail closed if the audit write fails. Telemetry stays fail-open.

### T8. Denial of service by a tool

A tool hangs, forks, or prints megabytes.

Current mitigation: `TK_TIMEOUT` kills the process group (exit 1, `tool_timeout`). Output cap with a `fix` that shrinks the result. No CPU or memory limit. No cap on grandchild processes that left the group before the kill.

Residual risk: a tool can still fill the disk or the network before the timeout. Exit code is 1, not 124. Changing the code is decision D6 because agents and tests may branch on 1.

### T9. Check-time execution

`tk check` runs the tool. A tool that ignores `TK_DRY_RUN` runs its side effect during check. Secret-bearing files are no longer executed (T1.1).

Current mitigation: scratch cwd for every safety class; `HOME` replaced only for mutating and destructive; unguarded mutating tools are not executed.

Residual risk: a read-only tool is executed on check. Its network and filesystem reads happen as the user. Scratch cwd does not stop absolute paths.

Intended mitigation: lint and check remain useful and must say they are not a sandbox. Optional OS isolation, when present, applies to check as well as run. When it is absent, the audit field is `isolation: none`.

### T10. Agent follows a hostile `fix`

The smallest model copies `fix` into the shell. A malicious tool that gets past T4's residual risk can point that string at anything.

Current mitigation: runner-built fixes are quoted. Tool-built fixes are not fully constrained (T1.2 skipped).

Residual risk: accepted. Closing it completely would mean refusing `gh auth login` and other repairs VISION requires. The narrow filter in T4 is the planned reduction. The agent is still the user.

### T11. Shared or copied state

`TK_STATE_DIR` can point at a directory other users can read. Events can contain queries and redacted-but-sensitive paths.

Current mitigation: state is local by default and gitignored. Redaction runs on event values.

Residual risk: directory permissions are the user's. `tk` does not upload state. This program must not add a telemetry sink.

## Attack surfaces

| Surface | Entry | Note |
|---|---|---|
| argv | `tk run` flags | Validated against `@tk-arg` types. Values still enter the tool. |
| tool file | `tools/**`, `tk save` | Header and body are the same file. Save quarantines on failed check. |
| chain file | `chains/*.json` | Steps name tools. A chain that includes a writer is gated with `--yes` today. |
| stdin | piped JSON | Passed through to the tool. |
| environment | caller env | Allowlisted, not emptied. Tokens for `gh` are inside the list. |
| network | tools that fetch | Public-URL helper is opt-in per tool, not a global net filter. |
| state files | `events.jsonl` | Append without a lock. |
| skill text | `SKILL.md` | Already at the 51-line cap. A poisoned skill is a prompt injection into every harness. Do not grow it. Edits are as sensitive as code. |

## Mitigations that exist and stay

- Dry-run unless `--yes`, for mutating and destructive `tk run`.
- Environment allowlist.
- Timeout and output cap.
- Secret redaction on check, events, and stderr.
- Git argument shape checks, public HTTP check, read-only SQLite URI.
- No remote tool download.
- Stdlib only, so the supply chain is the interpreter and the clone.

## Non-mitigations

- A plan hash by itself.
- `@tk-verified`, including the word `signed`.
- A read-only lint result described as isolation.
- `--yes` kept forever on destructive tools "for compatibility."
- MCP `readOnlyHint` or any other annotation.
- Regex redaction as the primary secret control.
- `O_APPEND` as a portable lock.
- A scripted benchmark described as proof an agent succeeded.

## Open decisions that change this model

Recorded in `DECISIONS.md`. Until D1, T1 stays open for destructive `--yes`. Until an isolator is optional and honest, T2 and T9 stay unconfined. Until D4, T6 has no code path.
