# Architecture: Agent Toolkit

`agent-toolkit` is structured around four **deep modules** with narrow interfaces and strict locality. Every seam is designed to **minimize model cognitive load** and **minimize token consumption**: callers learn one tiny CLI surface, take the fewest possible turns, and receive distilled, low-token outputs.

```mermaid
flowchart LR
    Agent["Agent (Any Harness)"] -->|reads compact pointer| Skill["skills/toolkit/SKILL.md"]
    Agent -->|"1. tk find → 2. tk run"| CLI["1. Dispatcher (tk)"]
    CLI --> Catalog["2. Single-File Tool Index (tools/)"]
    CLI --> ChainEngine["3. Composition Engine (chains/)"]
    CLI --> Telemetry["4. Evolution Loop (state/events.jsonl)"]
    Telemetry -->|"tk evolve (promote & prune)"| Catalog
```

---

## 1. Dispatcher Module (`tk`)

### Token & Turn Budget Rules

1. **Two-Step Execution (`find → run`)**: `tk find` returns each matching tool's 1-line summary *plus* its copy-pasteable `tk run` usage line. Agents go straight from `tk find` to `tk run` without burning an extra turn on `tk info`.
2. **Distilled Output**: Tools emit compact JSON directly on `stdout` without wrapper ceremony, capped to high-signal fields so tool outputs never flood the context window.
3. **Self-Healing Errors**: Missing or invalid flags emit a compact JSON error on `stderr` containing the exact `fix` command to run.

### Interface

| Subcommand | Nature | Contract |
|---|---|---|
| `tk find [query]` | Consumer | Ranks matching tools/chains (or lists all if `[query]` omitted) with inline `tk run` usage; logs a `miss` event if empty. |
| `tk run <name> [--flag val ...]` | Consumer | Validates flags against the tool header, executes the tool, emits distilled JSON on `stdout`, and logs telemetry. |
| `tk info <name>` | Consumer (Optional) | Prints full argument table and safety details only when deeper inspection is needed. |
| `tk chain <name> [steps...]` | Consumer / Evolver | Runs or saves a deterministic pipeline where step $N$'s JSON output feeds step $N+1$. |
| `tk save <name> ...` | Evolver | Turns a working command or script into a single-file tool in `tools/` and validates it with `tk check`. |
| `tk evolve` | Evolver | Inspects `state/events.jsonl` to promote recurring patterns and prune/consolidate unused or overlapping tools. |
| `tk check [name]` | Maintainer | Validates header completeness, flag parity, dry-run support, and output compactness. |

### Global Modifiers (Order-Independent)
- `--dry-run`: Prints the resolved command/pipeline without mutating state.

---

## 2. Single-File Tool Contract (`tools/`)

### Why Single-File?
Sidecar manifests (`.yaml` + `.sh`) inevitably drift. In `agent-toolkit`, **the executable file is the manifest**. The indexer parses `# @tk-*` directives from the top comment block of any executable file under `tools/<namespace>/<tool-name>`.

### Header Specification

```bash
#!/usr/bin/env bash
# @tk-name: gh.pr-checks
# @tk-summary: Fetch failing and pending CI checks for a GitHub pull request
# @tk-safety: read-only
# @tk-arg: --repo | required | string | Repository in owner/name format
# @tk-arg: --pr   | required | int    | Pull request number
# @tk-output: json | Array of {name, status, conclusion, url}
# @tk-example: tk run gh.pr-checks --repo cli/cli --pr 123
# @tk-verified: 2026-11-03
```

### Runtime Environment Passed to Tools
Before invoking a tool script, `tk run` parses and validates all `@tk-arg` flags and injects them as normalized environment variables (`TK_ARG_<UPPER_NAME>`, plus `TK_DRY_RUN=0|1`). Tools never need to write fragile `getopts` or `argparse` boilerplate—the dispatcher handles validation and help generation for every language (`.sh`, `.py`, `.ts`).

---

## 3. Composition Engine (`chains/`)

Agents chain tools in two ways:

1. **Ad-hoc UNIX Pipes**:
   ```bash
   tk run gh.pr-checks --repo owner/repo --pr 42 | jq '.[] | select(.conclusion == "failure")'
   ```
2. **Saved Deterministic Chains (`chains/<name>.json`)**:
   A declarative list of steps where outputs map cleanly into downstream `--flag` inputs via JSONPath/jq expressions. Once saved, a chain appears in `tk find` identically to an atomic tool—collapsing multi-step workflows into one deterministic call for smaller models.

---

## 4. Evolution Loop (`state/` & `tk evolve`)

The toolkit evolves from real agent work rather than speculative upfront design:

1. **Observe (`state/events.jsonl`)**:
   - `search_miss`: Agent searched `tk find` for an intent not yet covered.
   - `run_error`: Tool failed or rejected arguments.
   - `tool_saved`: Agent created a draft tool via `tk save` (`@tk-verified: none`).
2. **Verify (`tk check`)**:
   - Checks header fields, required flag coverage, output compactness, and `--dry-run` behavior.
3. **Promote (`tk evolve`)**:
   - **Read-only (`@tk-safety: read-only`)**: Auto-verified via live/smoke execution and marked `@tk-verified: <date>`.
   - **Mutating (`@tk-safety: mutating`)**: Verifies `--dry-run` output and prompts human/agent confirmation before marking verified.
   - **Destructive (`@tk-safety: destructive`)**: Requires explicit human sign-off and mandatory `--dry-run` support.
4. **Consolidate & Prune (`tk evolve`)**:
   - Flags zero-use or superseded tools for removal and merges overlapping tools so the catalog stays small and low-token.
