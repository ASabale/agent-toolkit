# CODING_STANDARDS.md — Agent Toolkit (`tk`)

This document defines the **Pit of Success**, module contracts, and trust invariants for `agent-toolkit`. All builders and reviewers must enforce these rules without exception.

---

## 1. The Trust Invariant ("Never Break")

Agents rely on `tk` in place of MCP servers. If `tk` crashes with an unhandled traceback, emits malformed output on `stdout`, or admits a broken tool into the catalog, agent trust is lost.

1. **Zero Unhandled Tracebacks**: The `tk` entrypoint and all `lib/` modules must catch unexpected exceptions and emit a single-line JSON error on `stderr`:
   ```json
   {"error":"internal_error","why":"<message>","fix":"tk check"}
   ```
2. **`stdout` Is Sacred**:
   - For `tk run`, `tk save`, `tk chain`, `tk check --json`, and `tk evolve`, `stdout` must **always** be valid, compact JSON (`separators=(",", ":")`).
   - For `tk find` and `tk info`, `stdout` is ultra-compact human/LLM text designed for minimum tokens.
   - All errors, warnings, and diagnostics go exclusively to `stderr` as single-line JSON with `error`, `why`, and `fix`.
3. **Quarantine on Save**: `tk save` and `tk chain save` must run `check_item` before completing. If validation fails, the draft file must be removed immediately so an invalid tool or chain never pollutes the catalog.
4. **Telemetry Never Breaks Execution**: `log_event` in `lib/evolver.py` must wrap all file I/O in `try...except Exception:` so a read-only filesystem or missing directory never interrupts `tk find` or `tk run`.
5. **Zero External Dependencies**: Use Python 3.10+ standard library only (`sys`, `os`, `json`, `re`, `subprocess`, `pathlib`, `shlex`, `datetime`, `unittest`).

---

## 2. Module Seams & Exact Signatures

### 2.1 `lib/catalog.py` — Discovery, Indexing & Validation

- **`suggest_closest_item(root_dir: Path, name: str) -> dict | None`**
  Finds the closest catalog item when an agent mistypes a tool or chain name (checking `difflib.get_close_matches` against catalog keys and falling back to top `find_items(root_dir, name)` match), returning the matched item dict or `None`.
- **`parse_tool_header(path: Path) -> dict`**
  Parses `# @tk-*` lines from the top comment block of a tool file:
  ```python
  {
      "kind": "tool",
      "name": str,            # @tk-name
      "summary": str,         # @tk-summary
      "safety": str,          # @tk-safety: "read-only" | "mutating" | "destructive"
      "args": [               # @tk-arg: --flag | required|optional | string|int|float|bool | description
          {
              "flag": str,          # e.g. "--repo"
              "env_var": str,       # e.g. "TK_ARG_REPO" (strip leading --, replace - with _, upper)
              "required": bool,
              "type": str,          # "string" | "int" | "float" | "bool"
              "description": str,
              "default": str | None # extracted from "(default: X)" in description if present
          }
      ],
      "output": str,          # @tk-output
      "example": str,         # @tk-example
      "verified": str,        # @tk-verified
      "path": str,            # str(path.resolve())
  }
  ```
- **`load_chain(path: Path) -> dict`**
  Reads `chains/<name>.json` and returns a normalized dict with `"kind": "chain"`, `"name"`, `"summary"`, `"safety"`, `"args"`, `"steps"`, `"output"`, `"example"`, `"verified"`, `"path"`.
- **`discover_catalog(root_dir: Path) -> dict[str, dict]`**
  Scans `root_dir / "tools"` recursively (skipping files/dirs starting with `.` or `__`) and `root_dir / "chains" / "*.json"`. Returns `dict[name, item]` sorted by key.
- **`find_items(root_dir: Path, query: str = "", limit: int | None = None, namespace: str | None = None) -> list[dict]`**
  Empty query returns all items sorted by `name`. When `namespace` is non-empty, filters items to those whose `name` starts with `<namespace>.` (or equals `<namespace>`). Non-empty query scores tokens against `name` (exact/substring/token weight 5/3), `summary` (weight 2), and `args` (weight 1), returning matches sorted by `(-score, name)`. When `limit` is a positive `int`, slices the returned list to `[:limit]`.
- **`format_find_output(items: list[dict]) -> str`**
  2-line format per item (minimum tokens, zero extra round-trip needed):
  ```text
  <name> [<safety>] — <summary>
    run: <example>
  ```
- **`format_info_output(item: dict) -> str`**
  Compact multi-line contract view (`name`, `kind`, `safety`, `summary`, `args`, `output`, `example`, `verified`).
- **`check_item(root_dir: Path, name_or_path: str | Path) -> dict`**
  Returns `{"name": str, "ok": bool, "errors": list[str]}`.
  Checks:
  1. File exists and (for tools) is executable (`os.access(p, os.X_OK)`).
  2. All required header fields present (`name`, `summary`, `safety` in `{"read-only", "mutating", "destructive"}`, `output`, `example`, `verified`).
  3. `example` starts with `tk run <name>` and includes every required `--flag`.
  4. Syntax check passes (`bash -n` for `sh`/`bash` shebang; `py_compile` for `python` shebang).
  5. No duplicate `--flag` names in `args`, any `(default: X)` value conforms to the declared arg `type`, and every `TK_ARG_<NAME>` referenced in the tool's non-comment script body is declared in `args` (`undeclared arg env var in script: TK_ARG_<NAME>`).
  6. Dry-run smoke check: running the tool with `TK_DRY_RUN=1` and synthetic dummy values for required flags (`"example"` for string, `"1"` for int/float, `"true"` for bool) exits `0` and produces valid JSON on `stdout`.
  7. For chains:
     - Every step's `"tool"` exists in `discover_catalog(root_dir)`.
     - Every step's `args` keys are declared `--flags` on that step's target tool (rejecting unknown step flags at check time).
     - Every required flag on step $i$'s target tool is supplied in step $i$'s `args` (or has a default), except for step $i > 0$ tools that read piped `stdin` and have zero required flags missing.
     - Every `$input.<flag>` reference in step `args` refers to a flag declared in the chain's own `args`.
     - Every `$prev` or `$prev.<path>` reference appears only in step index `>= 1` (never step `0`).
     - Every `$step[k]` or `$step[k].<path>` reference satisfies `0 <= k < i`.
     - For a step at index `>= 1` whose tool is `json.pick` or `json.query`, every key requested by `--keys` (or by a simple `{a,b}` / `a.b` `--expr` projection) must be a top-level field of the previous step's `@tk-output` `{...}` shape, with the error format `step <i> (<tool>) key '<key>' not in upstream <tool> output`; the check is skipped when the upstream `@tk-output` is not in `{...}` form.
     - Dry-run smoke check: running `run_chain(root_dir, item, dummy_required_flags, dry_run=True)` exits `0` and produces valid JSON on `stdout`.
  8. Catalog names are unique: if more than one file claims the same `name`, report `duplicate name: <name> (<path1>, <path2>)` listing every claimant path relative to `root_dir` in first-seen order. `check_all` surfaces this through `check_item` on the affected names.
  9. Name/path layout: a tool's `@tk-name` must equal `<namespace>.<file>` derived from `tools/<namespace>/<file>`; a chain's `name` must equal the `chains/<name>.json` stem. Error: `name/path mismatch: @tk-name <x> but path implies <y>`.
  10. Reserved global modifiers `--raw` and `--dry-run` must not appear in `@tk-arg` or chain `args` (`reserved flag: --raw` / `reserved flag: --dry-run`).
- **`check_all(root_dir: Path) -> dict`**
  Runs `check_item` concurrently across every item in `discover_catalog(root_dir)` (using `concurrent.futures.ThreadPoolExecutor` while preserving deterministic catalog key order) and returns `{"ok": bool, "checked": int, "results": list[dict], "errors": list[str]}`.

---

### 2.2 `lib/runner.py` — Validation, Execution & Chaining

- **`parse_cli_flags(argv: list[str], item: dict | None = None) -> tuple[dict[str, str], bool, list[str]]`**
  Extracts `--dry-run` anywhere in `argv` (`dry_run: bool`), consumes `--raw` / `--raw=…` as a no-op compatibility modifier, parses `--flag value`, `--flag=value`, and standalone boolean `--flag` (`"true"`), and collects any stray positional tokens in `positional: list[str]`. When `item` is supplied, uses `item["args"]` schema so boolean flags do not swallow subsequent positional tokens and non-boolean flags accept values starting with `-` or `--` (other than `--dry-run` and `--raw`).
- **`validate_and_build_env(item: dict, flags: dict[str, str], positional: list[str], dry_run: bool) -> tuple[bool, dict[str, str], dict | None]`**
  - Rejects non-empty `positional` with `{"error": "positional_arguments_forbidden", "why": "...", "fix": item["example"]}`.
  - Rejects unknown `--flag` names not declared in `item["args"]` with `{"error": "unknown_flag", "why": "...", "fix": "..."}`. When an unknown flag is close to a declared flag (`difflib.get_close_matches`) or there is a single missing required flag, `why` names the suggested flag (`did you mean --<flag>?`) and `fix` rewrites the supplied command with the suggested flag and the caller's value so a small model recovers in 1 step.
  - Checks all required flags; if missing, constructs a copy-pasteable `fix` command that keeps already-supplied valid flags and appends `--missing <value>` placeholders.
  - Validates types (`int`, `float`, `bool`, `string`).
  - Returns `(True, env_dict, None)` with `TK_DRY_RUN="1"|"0"` and `TK_ARG_<NAME>` populated (including defaults for omitted optional flags).
- **`run_tool(root_dir: Path, item: dict, flags: dict[str, str], positional: list[str] | None = None, dry_run: bool = False, stdin_data: str | None = None) -> tuple[int, str, str]`**
  - Validates arguments, executes `item["path"]`, enforces `TK_MAX_OUTPUT_BYTES` (default `65536` bytes; returns `error="output_too_large"` if exceeded), ensures `stdout` is compacted single-line or clean JSON, and formats any failure as a self-healing JSON error on `stderr`.
- **`run_chain(root_dir: Path, chain_item: dict, flags: dict[str, str], positional: list[str] | None = None, dry_run: bool = False) -> tuple[int, str, str]`**
  - Validates chain flags, resolves `$input.<arg>`, `$prev` (whole JSON), `$prev.<path>`, `$step[i]` (whole JSON), and `$step[i].<path>` across `steps` (with dry-run fallback when `dry_run=True` and a step's synthetic dry-run payload omits a nested field), pipes each step's JSON `stdout` into the next step's `stdin_data`, and halts on first error.

---

### 2.3 `lib/evolver.py` — Telemetry, Creation & Pruning

- **`log_event(root_dir: Path, event_type: str, payload: dict) -> None`**
  Appends `{"ts": ..., "event": event_type, ...}` to `state/events.jsonl` (or `Path(os.environ["TK_STATE_DIR"]) / "events.jsonl"` when set). Skips writing when `TK_NO_TELEMETRY` is set to `"1"` or `"true"`. Never raises.
- **`save_tool(root_dir: Path, name: str, summary: str, safety: str = "read-only", from_cmd: str | None = None, file_path: str | None = None, args_spec: list[str] | None = None, force: bool = False) -> tuple[int, str, str]`**
  Creates `tools/<namespace>/<tool-name>` with complete `# @tk-*` headers (automatically inferring `@tk-arg` declarations for any `TK_ARG_<NAME>` that the script in `from_cmd` or `file_path` actually reads via shell `$TK_ARG_<NAME>` / `${TK_ARG_<NAME>...}` or Python `environ`/`getenv`, matching `tk check`'s undeclared-arg rule; bare mentions inside string literals or comments are ignored; `${TK_ARG_<NAME>:-default}` yields an optional arg with that default; already-declared names in `args_spec` or headers are preserved), sets `0o755`, runs `check_item`, rolls back on failure, logs `tool_saved`, and returns `(0, compact_json, "")`.
- **`save_chain(root_dir: Path, name: str, summary: str, steps: list[dict], args: list[dict] | None = None, safety: str = "read-only", example: str | None = None, force: bool = False) -> tuple[int, str, str]`**
  Writes `chains/<name>.json`, validates via `check_item`, rolls back on failure, logs `chain_saved`, and returns `(0, compact_json, "")`.
- **`evolve_report(root_dir: Path, auto_promote: bool = True) -> dict`**
  Analyzes `state/events.jsonl` + catalog (importing `discover_catalog` and `check_item` directly from `lib.catalog` without duplicated fallback parsers): auto-promotes unverified `read-only` tools and chains that pass `check_item` (updating `@tk-verified` / `"verified"` to today's YYYY-MM-DD), and reports `promoted`, `search_misses`, `failing_tools`, `unused_tools`, `overlap_candidates` (excluding structural stopwords, skipping chain-to-step pairs, and requiring `>= 2` shared domain tokens with Jaccard `score >= 0.35` within the same namespace or `>= 0.50` across namespaces), and `chain_candidates` (ordered `[tool_a, tool_b]` pairs that appear consecutively in successful `run_ok` events `>= 2` times where `tool_a != tool_b` and no existing chain already starts with `[tool_a, tool_b]`, returning `[{"steps": [tool_a, tool_b], "count": n, "suggested_chain": str}]` sorted by `(-count, tool_a, tool_b)`).
- **`prune_tools(root_dir: Path, names: list[str], dry_run: bool = False) -> tuple[int, str, str]`**
  Retires named tools or chains from `tools/` or `chains/` by moving them into `state/archive/<timestamp>-<name>` (when `dry_run=False`), logging `tool_pruned`, and returning `(0, compact_json, "")` with `{"pruned": [...], "archived_to": [...], "dry_run": bool}`.
  **Safety Invariant**: If any target tool is referenced as a step inside an active chain (that is not itself in `names`), `prune_tools` must refuse to break the chain and return `(2, "", error_json)` with `error="tool_in_use_by_chain"`.

---

### 2.4 `./tk` — CLI Entrypoint

Supports:
- `tk find [query] [--namespace <ns>] [--limit <n>]` — non-empty query defaults to 5 items (explicit `--limit N` overrides; empty query is uncapped); zero matches for a non-empty query log `search_miss` and write one stderr JSON line `{"error":"no_match","why":"no tool or chain matches '<query>'","fix":"tk find"}` (`fix` is `tk find --namespace <ns>` when the first query token is an existing namespace)
- `tk info <name>`
- `tk run <name> [--flag value ...] [--dry-run]`
- `tk chain run <name> [--flag value ...] [--dry-run]` (also runnable directly via `tk run <chain-name>`)
- `tk chain save <name> --summary "<text>" --steps '<json-or-space-list>' [--safety <tier>]`
- `tk save <name> --summary "<text>" [--safety <tier>] [--from-cmd "<cmd>" | --file <path>] [--arg "<spec>" ...] [--force]`
- `tk check [<name> ...] [--json]`
- `tk evolve [--no-promote]`
- `tk prune [<name> ...] [--unused] [--dry-run]`

---

## 3. Token Budget, Wiki Integrity & Multi-Agent Sync Gates

1. **Idle Skill Ceiling**: `skills/toolkit/SKILL.md` must never exceed `45` lines or `1,800` bytes.
2. **Discovery Line Ceiling**: Every item in `tk find` output must be exactly 2 lines (`<name> [<safety>] — <summary>` and `  run: <example>`), with each line `<= 140` characters.
3. **Historical Wiki Integrity (`wiki.lint`)**: Every file under `wiki/` (except `wiki/index.md`) must be linked from `wiki/index.md`, every relative link in `wiki/**/*.md` must resolve on disk, and every wiki page must contain dated (`YYYY-MM-DD`) and commit-cited (`@<sha>`) historical claims.
4. **Remote Multi-Agent Sync**: Because multiple agents work on this repo concurrently, on `main` run `git pull --rebase --autostash origin main` before launching a build wave. On a feature branch, run `tk run git.sync --repo .` to rebase onto `origin/main` and push the branch, before launching a build wave and again before pushing.
