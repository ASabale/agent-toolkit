# Master-mission baseline — 2026-11-04

Read-only audit of `/Users/akshay/Development/agent-toolkit` against the master mission phases 2–7 (session text titled “MASTER MISSION: EVOLVE AGENT TOOLKIT INTO AGENT-FIRST CAPABILITY INFRASTRUCTURE”, read 2026-11-05). GitHub and `./tk` were read the same day. Wiki pages under `wiki/` are historical; code claims below are tied to this checkout’s commit unless marked `[INFERENCE]`.

## HEAD

| Fact | Evidence |
| --- | --- |
| Commit | `905c49948d8efdc52729484192681996353c6077` (`git rev-parse HEAD`, 2026-11-05). Not an ancestor of `ASabale/agent-toolkit@b580644`. On 2026-11-05 `git diff 905c499 b580644` was empty, so the tree matches pull request #198. |
| Branch | `arch/secure-seams` tracking `origin/arch/secure-seams` (`git status -sb`) |
| Dirty | Untracked `docs/` only. No staged or modified tracked files. |
| `origin/main` | `ASabale/agent-toolkit@f96bf284bdbd08513c59397a700bf6242114a335` (`git rev-parse origin/main`). This HEAD is that commit plus `d989bc8` and `905c499`. Local `main` was `7e30d46`, behind `origin/main`. |

`git log -15 --oneline` on this HEAD (newest first):

- `905c499` fix: defer guard-test annotations for Python 3.9
- `d989bc8` refactor: share chain references and tool input guards
- `f96bf28` docs(#166): tools run in the caller's cwd with `TK_ROOT_DIR` (#197) — tip of `origin/main`
- `7aedd05` feat(#96): accept the VISION `tk chain` name step form (#196)
- `63a0f13` feat(#82): accept postgres URLs in `sql.query` and `sql.schema` (#195)
- `b223a24` feat(#103): add `gh.comment` and `gh.label` (#194)
- `9b63e2a` docs(#162): cite squash commits that are on main (#193)
- `f566a76` docs: remove the cross-toolkit comparison from `VISION.md` (#192)
- `3997002` fix(#95): every error hint is a runnable command (#191)
- `fee45ad` feat(#84): mutating tools return their plan unless `--yes` (#190)
- `19539f6` feat(#31): stamp mutating tools with `tk check --verify` (#189)
- `04844f8` fix(#107): emit integer truncated counts so the runner injects next (#188)
- `2184f6d` fix(#102): drop `tk find` queries whose only hit is a namespace (#187)
- `80dc937` docs(#140): describe `http.json-get` keys, cap, and `--max-bytes 0` (#186)
- `2ca3ccb` fix: run on Python 3.9 and accept usage feedback (#174)

`905c499` and `d989bc8` are on this branch, not on `origin/main` as of this read.

## What works

- Grammar in force on this tree: subcommands are exactly `find`, `info`, `run`, `chain`, `save`, `check`, `evolve`, `prune`. `./tk --help` (2026-11-05) printed `{"error":"usage","why":"subcommands: find, info, run, chain, save, check, evolve, prune","fix":"tk find"}`. `setup`, `doctor`, and `inventory` are absent as subcommands. `env.check` is a catalog tool, not a `tk` subcommand.
- `./tk check` exited 0. Stdout `{"ok":true,"checked":41,...}` with keys `ok`, `checked`, `results`, `errors`. Stderr was empty (0 bytes). No `warnings` field. Every result had `ok: true`. Warning count: 0.
- Catalog names in that check (41): 39 tools and 2 chains (`gh.triage-pr`, `git.repo-audit`). `tools/` has 19 namespace directories and 76 non-dot files (Python `os.walk`, 2026-11-05). `chains/` has `gh.triage-pr.json`, `git.repo-audit.json`, and `.gitkeep` (2 chain documents).
- Chains pass step data. `run_chain` in `lib/runner.py` keeps `prev` and `outputs`, resolves each step arg with `resolve_expr` (`lib/chainref.py`), then calls `run_tool(..., stdin_data=None if prev is None else last_stdout)`. `resolve_expr` accepts `$input.<flag>`, `$prev`, `$prev.<path>`, `$step[i]`, and `$step[i].<path>`. `chains/gh.triage-pr.json` uses `$input.repo` and `$input.pr`, then `json.pick` (that tool reads stdin: `tools/json/pick`). `chains/git.repo-audit.json` uses `$input.repo` / `$input.limit`, then `json.query` (stdin: `tools/json/query`).
- Safe writes and verification are written into current docs, not only the wiki: `ARCHITECTURE.md` describes `tk check <name> --verify` tiers and `--yes` behavior; `wiki/decisions/0009-verification-tiers.md` and `0010-safe-writes-by-default.md` record the same decisions (issues #31 and #84, commits on `origin/main`: `19539f6`, `fee45ad`).
- Skill path on this tree is `skills/agent-toolkit/SKILL.md` (51 lines). `skills/toolkit` is not in `skills/` (only `agent-toolkit/`). `README.md` (94), `VISION.md` (84), `ARCHITECTURE.md` (103), `CODING_STANDARDS.md` (206), and `COORDINATION.md` (104) all point at `skills/agent-toolkit`, not `skills/toolkit`. Decision 0007’s sentence that README still names `skills/toolkit` describes `ASabale/agent-toolkit@69f66c7` on 2026-11-04 and does not match this tree.
- `README.md` quick start is clone, `./install.sh`, `tk find wiki`, `tk run wiki.lint --path wiki`, plus `npx skills add ASabale/agent-toolkit`. License line: MIT (`LICENSE` exists). `SKILL.md` tells a missing-`tk` agent to clone into `~/.agent-toolkit` and run `install.sh` (decision 0007 bootstrap).

## Strong

- One flat grammar and find-then-run, restated the same way in `VISION.md`, `README.md` “For agents”, and `SKILL.md`.
- Single-file `# @tk-*` tools, no sidecar YAML (`VISION.md` pillar II; `ARCHITECTURE.md` §2).
- Errors are `{"error","why","fix"}` with a runnable `fix` (`CODING_STANDARDS.md` §1; commit `3997002`).
- Mutating work stays a plan until `--yes` (`fee45ad`; decision 0010; `SKILL.md` line 41).
- Read-only promotion needs a live `run_ok`; mutating stamps go through `tk check --verify`; destructive stays human sign-off (decision 0009; `19539f6`).
- Stdlib-only Python 3.9+ with `from __future__ import annotations` (`CODING_STANDARDS.md` §1.5; `905c499` on this branch).
- Chain engine already does input refs plus stdin, so phase 4 does not need a new composition language.

## Incomplete

- Phase 2 acceptance (clean disposable install, unfamiliar agent, sample run, save path) was not executed in this baseline. `[INFERENCE]` Docs describe the path; they are not a clean-environment test.
- Phase 6 (portable packs, written sharing model, no central server) has no federation design page in `wiki/` (search for `federation` under `wiki/` on 2026-11-05: no matches). Sharing that exists is git plus `npx skills add` copying the skill folder (decision 0007).
- Phase 7: no `SECURITY.md`. `README.md` does not say “platform” or “Python 3.9” (those words are in `CODING_STANDARDS.md` §1.5 and `install.sh` as summarized by `README.md`: `python3` required, `gh` optional). No release-process file was listed beside `LICENSE`.
- Decision 0008 still names five tools that fail the harness-duplicate admission test (`code.todos`, `fs.read-slice`, `json.diff`, `sec.secret-scan`, `docker.ps-digest`). All five are still in the `tk check` catalog on this HEAD. Prune waits for 50 `run_ok`/`run_error` events.
- Only two saved chains remain after 2026-11-04 deletions recorded in `wiki/subsystems/runner-and-chains.md` (`7001f67`, `98bb7ac`, `ad02745`). Phase 4’s “realistic workflows” are those two files, not a broader suite.
- `pytest` was not feasible: `/opt/homebrew/opt/python@3.14/bin/python3.14` reported `No module named pytest` (exit 1, 2026-11-05). Pass/fail counts: not collected. The repo’s own gate is `python3 -m unittest` (`COORDINATION.md` Verification), which this baseline did not run.

## Unreliable

- This working tree is not `origin/main`. Behavior of `d989bc8` and `905c499` is unreleased relative to `f96bf28`.
- `wiki/index.md` and `wiki/subsystems/runner-and-chains.md` still narrate deleted chains and older SHAs. Treat them as history, not as the catalog (`tk check` is the catalog).
- Decision 0007’s “README still names `skills/toolkit`” is stale against this HEAD (see What works).
- GitHub on 2026-11-05, account `ASabale`, repo `ASabale/agent-toolkit`: `gh issue list --state open` and the REST issues API both returned 0 open issues. Open PRs: 0 (`gh pr list --state open`). No `in-progress` claims. Recently closed issues include #166, #162, #178–#181 (closed 2026-11-04). A zero open backlog is a tracker fact, not proof the mission is done. `[INFERENCE]` Older local notes that still name open issues #11, #24, #34 are stale against this API read.
- `./tk --help` exits through the usage error object. That is the contract, not a missing binary, but it is a poor first hint if an agent expects a human usage page.

## Complicated

- Three safety tiers, two verifiers (`tk check` smoke vs `tk check --verify` vs `tk evolve`), and a 50-event unused threshold (`ARCHITECTURE.md` §1 and §4; decisions 0008 and 0009). A small model must follow `SKILL.md`, not the architecture page.
- Chain authoring has two spellings that both write a chain file: `tk chain <name> '<step>'` and `tk chain save` (`ARCHITECTURE.md` §1; `SKILL.md` §2; commit `7aedd05` on `origin/main`).
- `VISION.md` still shows a pipe example `tk run gh-pr-list | jq ... | tk run slack-notify` (pillar II). Those names are not in the 41-item catalog. `[INFERENCE]` Illustrative, not a shipped workflow.
- In-process `run_tool` / `run_chain` still execute when `confirmed` is not false; only the CLI withholds `--yes` (decision 0010). Callers of the library do not get the CLI gate.
- Coordination (`COORDINATION.md`) is a full steward/reviewer protocol. With zero open issues it does not currently point a builder at a next ticket.

## Adoption blockers

- `npx skills add` installs the skill folder, not `tk` (decision 0007, 2026-11-04). The agent must clone `~/.agent-toolkit` and run `install.sh`. That second step is in `SKILL.md` and was not re-tested here.
- Skills.sh directory listing and rank were not queried. Do not treat the README badge as proof of listing (phase 7 text: do not claim listing until verified).
- No `tk setup` / `tk doctor` / `tk inventory`. Mission phase 2 says not to add them without a demonstrated gap. `tk check` plus `env.check` are the existing substitutes.
- Unreleased branch `arch/secure-seams` is what this directory runs. An external agent that clones default `main` gets `f96bf28`, not `905c499`.

## Preserve

- Do not add subcommands until a clean-env session shows `tk check` and `env.check` are insufficient (phase 2: reuse existing commands).
- Keep `skills/agent-toolkit` (51-line pointer). Do not restore `skills/toolkit`.
- Keep single-file tools, distilled JSON, `fix` as a runnable command, `--yes` for mutating CLI runs, and verification tiers in decisions 0009 and 0010.
- Keep chain references in `lib/chainref.py` (`resolve_expr`) and stdin forwarding in `run_chain`. Commit `d989bc8` on this branch is specifically “share chain references and tool input guards”.
- Keep the 50-event probation gate (decision 0008) rather than inventing a second prune policy.
- Federation stays undesigned until a pack needs to move without a git clone (phase 6: no central infrastructure).

## Ranked gaps

### P0 — Clean first-time install is undocumented by a run

- Problem: Phase 2 and phase 7 both require a disposable `npx skills add ASabale/agent-toolkit` plus bootstrap plus one `tk run`. This baseline did not do that.
- Files: `skills/agent-toolkit/SKILL.md`, `install.sh`, `README.md`. No code change until a run fails.
- Acceptance: From an empty home (or a temp `HOME`), skills add, clone or `install.sh`, `tk find`, one read-only `tk run`, and `tk check` all succeed; note the Skills.sh page only if the live page was opened.
- Risk: Low if the test is read-only. A failed bootstrap is the adoption bug; fixing it blindly is the risk.

### P1 — `origin/main` is not this HEAD

- Problem: `arch/secure-seams` (`905c499`, `d989bc8`) is unmerged. External clones do not get the Python 3.9 annotation deferral or the shared chain-reference refactor.
- Files: whatever those two commits touch (not re-diffed here). Release path is a PR onto `main`, not more local commits.
- Acceptance: `origin/main` contains those commits or an explicit decision that they stay off main. `./tk check` on the merged SHA exits 0.
- Risk: Merging a seam refactor without the unittest gate in `COORDINATION.md`.

### P1 — Probation tools still shipped

- Problem: Five tools decision 0008 says fail the harness-duplicate test are still catalog entries (`code.todos`, `fs.read-slice`, `json.diff`, `sec.secret-scan`, `docker.ps-digest`). `tk prune --unused` will not remove them until 50 run events.
- Files: `tools/code/todos`, `tools/fs/read-slice`, `tools/json/diff`, `tools/sec/secret-scan`, `tools/docker/ps-digest`, `lib/evolver.py` (`MIN_UNUSED_RUN_EVENTS` per decision 0008).
- Acceptance: Either a cited `run_ok` keeps each one, or a human PR archives the ones that still have no origin. Do not lower the 50-event floor in the same change.
- Risk: Deleting `sec.secret-scan` or `json.diff` while a local chain or doc still names them. Live chains on this HEAD do not call them (`gh.triage-pr`, `git.repo-audit` only).

### P2 — Phase 7 surface

- Problem: No supported-platform line in `README.md`, no security guidance page, no recorded release check beyond CI text in `COORDINATION.md`.
- Files: `README.md` (and a security note only if phase 7 is in scope). Not a new `tk` command.
- Acceptance: README states Python 3.9+, the OS the maintainer actually ran, MIT, and “mutating tools no-op until `--yes`” in one short troubleshooting block. Security page stays a short threat note (secrets not written into tools; `TK_DRY_RUN`; no central server).
- Risk: Duplicating `CODING_STANDARDS.md`. Keep it to what an external agent needs before clone.

### P2 — Composition proof is two chains

- Problem: The engine works (`run_chain` / `resolve_expr` / stdin). The catalog only demonstrates CI triage and a git-log reshape. Phase 4 asks for a realistic multi-capability workflow, not more engine.
- Files: `chains/*.json` only after a real repeated task exists (VISION: no speculative tools).
- Acceptance: One new chain whose steps are already-shipped tools, with `$input` / `$prev` or stdin, `verified` not stamped until `tk check` and a live `run_ok`.
- Risk: Another near-duplicate of `json.pick` / `json.query` (the `no_op_chain` class in decision history at `ASabale/agent-toolkit@98bb7ac`).

### Later — Federation

- Problem: Phase 6 and mission §10 are local-first. Nothing in this tree is a pack index or a remote registry.
- Files: none until a second installation must share a tool without cloning the whole repo.
- Acceptance: A written compatibility note (skill name `agent-toolkit`, header contract, chain JSON) before any protocol.
- Risk: A central service would violate the mission’s “no central infrastructure without demonstrated need.”

## Recommended next slice

Do not add `setup`, `doctor`, or `inventory`.

Smallest high-value change: one disposable-environment run of `npx skills add ASabale/agent-toolkit`, then the `SKILL.md` bootstrap, then `tk find` and `tk run wiki.lint` (or another read-only tool). Record pass/fail in a follow-up note. Change `install.sh` or `SKILL.md` only where that run fails. Land or drop `arch/secure-seams` (`905c499`) relative to `origin/main` before any new feature, because the public default branch is still `f96bf28`.

`python3 -m pytest` could not run here. The next verifier should use `COORDINATION.md`: `./tk check` (already exit 0, 0 warnings, 41 checked on `905c499`) and `TK_NO_TELEMETRY=1 python3 -m unittest discover -s tests`.
