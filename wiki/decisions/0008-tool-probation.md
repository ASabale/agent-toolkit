# 0008 — Tool probation

On 2026-11-03, `ASabale/agent-toolkit@5a57fcd` added five tools with no cited `search_miss`, `run_error`, issue, or real task: `code.todos`, `fs.read-slice`, `json.diff`, `sec.secret-scan`, and `docker.ps-digest`. Issue #29 assessed that direct push. Issue #86 is the leftover policy. The mechanism is already on `main`: pull request #65 (`ASabale/agent-toolkit@d09087a`) keeps `unused_tools` empty below 50 run observations, and pull request #72 (`ASabale/agent-toolkit@2ed72de`) promotes a read-only item only after a `run_ok`.

## Decision

A pull request that adds a tool or chain cites its origin (a `search_miss` or `run_error` event, an issue, or a real task). The new tool ships `# @tk-verified: none`. A new chain ships `"verified": "none"`.

The five uncited tools stay in the catalog under this policy. Once telemetry is sufficient they appear under `unused_tools` in `tk evolve --no-promote`. The next `tk prune --unused` archives each of them that still has no `run_ok`.

On 2026-11-04, issue #86 also set the harness-duplicate admission test, recorded in [`CODING_STANDARDS.md`](../../CODING_STANDARDS.md) §4.2. A new tool distills an external service, database, or daemon (`gh`, `sql`, `http`, `docker`, `vercel`), or it collapses at least three local shell commands into one low-token JSON payload (`git.branch-digest`, `py.test-digest`, `git.sync`). Single-file reading, regex code search, directory listing, and AST symbol lookup stay with the harness (`Read`, `Grep`, `Glob`, `LSP`). `fs.read-slice`, `code.search`, `code.todos`, and `md.section` are the shapes that fail that test.

## What sufficient telemetry means

On 2026-11-04, `lib/evolver.py` at `ASabale/agent-toolkit@aad3e9e` leaves `unused_tools` empty until `state/events.jsonl` contains at least 50 `run_ok` or `run_error` events (`MIN_UNUSED_RUN_EVENTS`). Below that threshold `tk evolve --no-promote` sets `unused_reason` to `insufficient_telemetry`, and `tk prune --unused` exits 2 with `error` `insufficient_telemetry`, `why` `<n> run events < 50`, and `fix` `tk evolve --no-promote`.

At or above that threshold, `unused_tools` lists catalog names that have no usage event and whose file mtime is on or before the first `run_ok` or `run_error` timestamp. A usage event is `run`, `run_ok`, `tool_run`, or `chain_run`. A `run_error` leaves the name on the list. A tool whose file mtime is after that first run observation stays off the list.

## Verified on main

On 2026-11-04, against `ASabale/agent-toolkit@aad3e9e`, the five tools were the catalog names in `tools/code/todos`, `tools/fs/read-slice`, `tools/json/diff`, `tools/sec/secret-scan`, and `tools/docker/ps-digest`. `ASabale/agent-toolkit@2447b36` leaves `lib/evolver.py`, `./tk`, and those five files byte-identical with `ASabale/agent-toolkit@aad3e9e`, so the listing below is the behavior on that `main`. No chain file named any of them. `ASabale/agent-toolkit@7001f67` had deleted `chains/sec.repo-hygiene.json`, the chain that used to call `sec.secret-scan`, so `tk prune --unused` has no live chain holding these names.

With `TK_STATE_DIR` set to a log of 49 `run_ok` events for `wiki.lint`, timestamped after those files' mtimes, `tk evolve --no-promote` returned `unused_tools` `[]` and `unused_reason` `insufficient_telemetry`. One more `run_ok` for `wiki.lint` (50 run events) placed all five names in `unused_tools`. A further `run_ok` named `code.todos` removed only `code.todos`. A `run_error` named `json.diff` left `json.diff` in the list. `tk prune --unused --dry-run` on the 50-event log exited 0 with `dry_run` `true` and included all five names in `pruned`. The same command on the 49-event log exited 2 with `why` `49 run events < 50`.

A `run_ok` before that prune drops the name from `unused_tools`, so the prune leaves the tool in place. Without a `run_ok` (and without another usage event), the next `tk prune --unused` archives it.

## Related

- [0003 — Autonomous Chief-of-Staff governance](0003-autonomous-chief-of-staff-governance.md)
- [Evolver and quarantine](../subsystems/evolver-and-quarantine.md)
- [`VISION.md`](../../VISION.md)
- [`CODING_STANDARDS.md`](../../CODING_STANDARDS.md)
- Issue #5
- Issue #16
- Issue #29
- Issue #86
- Pull request #65
- Pull request #72
