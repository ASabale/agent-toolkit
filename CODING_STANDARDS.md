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
5. **Zero External Dependencies**: Use Python 3.9+ standard library only (`sys`, `os`, `json`, `re`, `subprocess`, `pathlib`, `shlex`, `datetime`, `unittest`). Every Python file that uses PEP 604 unions (`X | Y`), including `tk` and tools, must start with `from __future__ import annotations` so those annotations are not evaluated on 3.9.

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
      "needs": [str],         # optional @tk-needs: command name, or env:NAME
      "path": str,            # str(path.resolve())
  }
  `@tk-needs` is optional and repeatable. `tk check` reports a missing executable (`shutil.which`) or an unset `env:NAME`. It does not install the dependency and it does not start the tool. A missing-needs finding is not a sandbox.
  `@tk-schema` is optional. Names are comma-separated or `{key, key}`. `tk check` compares those names to a JSON object literal in the `TK_DRY_RUN` branch and does not start the tool. A branch with no object literal is not a schema failure. No schema library. A tool with no `@tk-schema` line is unchanged.
  `@tk-requires` is optional. `tk check` evaluates `env:NAME`, `bin:NAME`, and `file:relative/path` inside the repo. Those are reads. Any other token is skipped and recorded under `skipped` with the reason. The check does not shell out and does not write. A skip is not a failure.
  `@tk-deprecated` is optional. The tool stays in the one catalog and in `tk find`. `tk find` and `tk info` add one line naming the replacement (`tk run <name>`, or the `tk …` text already in the header). No second catalog.
  `@tk-keep` is optional. `tk prune --unused` skips that name. A tool with no `@tk-keep` line still follows the 50-event, chain-reference, and newer-than-first-run rules.
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
  2. All required header fields present (`name`, `summary`, `safety` in `{"read-only", "mutating", "destructive"}`, `output`, `example`, `verified`). Optional `@tk-needs` adds `missing executable: <name>` or `missing env: <NAME>`, each with a `fix`. `check_item` does not start the tool.
  3. `example` starts with `tk run <name>` and includes every required `--flag`.
  4. Syntax check passes (`bash -n` for `sh`/`bash` shebang; `py_compile` for `python` shebang).
  5. No duplicate `--flag` names in `args`, any `(default: X)` value conforms to the declared arg `type`, and every `TK_ARG_<NAME>` referenced in the tool's non-comment script body is declared in `args` (`undeclared arg env var in script: TK_ARG_<NAME>`).
  6. Dry-run guard, still static:
     - A `mutating` or `destructive` tool must mention `TK_DRY_RUN` on a non-comment line. Otherwise `check_item` records `<safety> tool must branch on TK_DRY_RUN`. `tk check`, `tk save`, and `tk evolve` do not start the tool. `tk run <name> --dry-run` on an unguarded writer returns `{"error":"dry_run_unsupported","why":"<safety> tool must branch on TK_DRY_RUN","fix":"tk check <name>"}` without executing it.
     - Default `tk check` does not run a dry-run or live smoke. `lint:` rows that existed only because a process ran are gone. Callers that used `tk check` as a smoke run pass `tk check <name> --verify`.
     - When `@tk-schema` is set and the `TK_DRY_RUN` branch contains a JSON object literal, each declared key must be in that object (`dry-run missing schema key: ...`).
  7. For chains:
     - Every step's `"tool"` exists in `discover_catalog(root_dir)`.
     - Every step's `args` keys are declared `--flags` on that step's target tool (rejecting unknown step flags at check time).
     - Every required flag on step $i$'s target tool is supplied in step $i$'s `args` (or has a default), except for step $i > 0$ tools that read piped `stdin` and have zero required flags missing.
     - Every `$input.<flag>` reference in step `args` refers to a flag declared in the chain's own `args`.
     - Every `$prev` or `$prev.<path>` reference appears only in step index `>= 1` (never step `0`).
     - Every `$step[k]` or `$step[k].<path>` reference satisfies `0 <= k < i`.
     - For a step at index `>= 1` whose tool is `json.pick` or `json.query`, every key requested by `--keys` (or by a simple `{a,b}` / `a.b` `--expr` projection) must be a top-level field of the previous step's `@tk-output` `{...}` shape, with the error format `step <i> (<tool>) key '<key>' not in upstream <tool> output`; the check is skipped when the upstream `@tk-output` is not in `{...}` form.
  8. Catalog names are unique. `resolve_named_item` returns one item, none, or every claimant path. It does not pick a winner. `tk check` reports `duplicate_name: <name> (<path1>, <path2>)` with those paths relative to `root_dir` in first-seen order and does not execute either file. `tk run`, `tk info`, and `tk find` for that name exit 2 with `error: duplicate_name` and the same paths in `why`. `run_tool` and `run_chain` refuse that name before any process. A chain step with that name is refused when the step is reached. `discover_catalog` still keeps the first file for unique-name dict shape only.
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
  - Validates arguments, builds the child environment with `lib.guards.tool_subprocess_env`, then rechecks `@tk-needs` and `@tk-requires` against that mapping immediately before `Popen`. A hard miss exits 1 with `declared_dependency_missing` and does not start the process. Skips do not fail the run and do not wrap stdout. Executes `item["path"]` in the caller's cwd (`cwd=None`), exports `TK_ROOT_DIR` as the toolkit root, does not change `PYTHONPATH`, enforces `TK_MAX_OUTPUT_BYTES` (default `65536` bytes; returns `error="output_too_large"` if exceeded), ensures `stdout` is compacted single-line or clean JSON, and formats any failure as a self-healing JSON error on `stderr`.
- **`run_chain(root_dir: Path, chain_item: dict, flags: dict[str, str], positional: list[str] | None = None, dry_run: bool = False) -> tuple[int, str, str]`**
  - Validates chain flags, resolves `$input.<arg>`, `$prev` (whole JSON), `$prev.<path>`, `$step[i]` (whole JSON), and `$step[i].<path>` by calling `lib.chainref.resolve_expr` (with dry-run fallback when `dry_run=True` and a step's synthetic dry-run payload omits a nested field), pipes each step's JSON `stdout` into the next step's `stdin_data`, and halts on first error: a step failure prefixes `why` with `chain <name> stopped at step <i>/<n> (<tool>): ` (1-based `i`) and leaves `error` and `fix` as the failing step's values. Later steps do not run. Check-time reading of the same syntax is `lib.chainref.static_ref_error`.

---

### 2.3 `lib/evolver.py` — Telemetry, Creation & Pruning

- **`log_event(root_dir: Path, event_type: str, payload: dict) -> None`**
  Appends `{"ts": ..., "event": event_type, ...}` to `state/events.jsonl` (or `Path(os.environ["TK_STATE_DIR"]) / "events.jsonl"` when set). Skips writing when `TK_NO_TELEMETRY` is set to `"1"` or `"true"`. Never raises.
- **`save_tool(root_dir: Path, name: str, summary: str, safety: str = "read-only", from_cmd: str | None = None, file_path: str | None = None, args_spec: list[str] | None = None, force: bool = False) -> tuple[int, str, str]`**
  Creates `tools/<namespace>/<tool-name>` with complete `# @tk-*` headers (automatically inferring `@tk-arg` declarations only when `from_cmd` or `file_path` reads a `TK_ARG_<NAME>` that is not already declared in `args_spec` or headers: shell `$TK_ARG_<NAME>` or `${TK_ARG_<NAME>...}`, or Python `environ` / `getenv`. A bare mention in a comment or string literal is ignored. `${TK_ARG_<NAME>:-default}` infers an optional arg with that default. This is the same read rule `tk check` uses for undeclared arg env vars.), sets `0o755`, runs `check_item`, rolls back on failure, logs `tool_saved`, and returns `(0, compact_json, "")`.
- **`save_chain(root_dir: Path, name: str, summary: str, steps: list[dict], args: list[dict] | None = None, safety: str = "read-only", example: str | None = None, force: bool = False) -> tuple[int, str, str]`**
  Writes `chains/<name>.json`, validates via `check_item`, rolls back on failure, logs `chain_saved`, and returns `(0, compact_json, "")`.
- **`evolve_report(root_dir: Path, auto_promote: bool = True) -> dict`**
  Analyzes `state/events.jsonl` + catalog (importing `discover_catalog` and `check_item` directly from `lib.catalog` without duplicated fallback parsers): auto-promotes unverified `read-only` tools and chains that pass `check_item` and have at least one `run_ok` event in `state/events.jsonl` (updating `@tk-verified` / `"verified"` to today's YYYY-MM-DD), and reports `promoted`, `awaiting_live_run` (unverified `read-only` items that pass `check_item` but have no `run_ok`), `search_misses`, `failing_tools`, `unused_tools`, `overlap_candidates` (excluding structural stopwords, skipping chain-to-step pairs, and requiring `>= 2` shared domain tokens with Jaccard `score >= 0.35` within the same namespace or `>= 0.50` across namespaces), and `chain_candidates` (ordered `[tool_a, tool_b]` pairs that appear consecutively in successful `run_ok` events `>= 2` times where `tool_a != tool_b` and no existing chain already starts with `[tool_a, tool_b]`, returning `[{"steps": [tool_a, tool_b], "count": n, "suggested_chain": str}]` sorted by `(-count, tool_a, tool_b)`). `unused_tools` stays empty until `state/events.jsonl` contains at least 50 `run_ok` or `run_error` events (`MIN_UNUSED_RUN_EVENTS`). Below that threshold the report includes telemetry (`{events, run_events, first_ts}`) and `unused_reason` `"insufficient_telemetry"`. At or above the threshold, `unused_tools` lists catalog names with no usage event whose file mtime is on or before the first `run_ok`/`run_error` timestamp; a tool created after that first run event is omitted. A `mutating` or `destructive` item is never stamped here, with or without a `run_ok`.
- **`verify_item(root_dir: Path, name: str) -> tuple[int, dict]`**
  Explicit verification used by `tk check <name> --verify`. `check_item` must pass; otherwise `(1, {"error":"check_failed","why":"<errors>","fix":"tk check <name>"})`. On success it calls `run_tool` or `run_chain` and returns that JSON. It does not call the tool file itself and it does not rewrite `@tk-verified`. A read-only tool or chain passes `dry_run=False` and `confirmed=True`. A mutating or destructive tool, and a chain that writes, passes `dry_run=True` and `confirmed=False`, so the runner sets `TK_DRY_RUN=1` before `Popen`. `tk check --verify` and `tk check a b --verify` never call this; the CLI exits 2 with `fix` `tk check <name> --verify`.
- **`prune_tools(root_dir: Path, names: list[str], dry_run: bool = False) -> tuple[int, str, str]`**
  Retires named tools or chains from `tools/` or `chains/` by moving them into `state/archive/<timestamp>-<name>` (when `dry_run=False`), logging `tool_pruned`, and returning `(0, compact_json, "")` with `{"pruned": [...], "archived_to": [...], "dry_run": bool}`.
  **Safety Invariant**: If any target tool is referenced as a step inside an active chain (that is not itself in `names`), `prune_tools` must refuse to break the chain and return `(2, "", error_json)` with `error="tool_in_use_by_chain"`. `tk prune --unused` (including with `--dry-run`) calls `evolve_report` with `auto_promote` false and, when `run_events` is below that 50-event minimum, exits 2 with error `"insufficient_telemetry"`, why `"<n> run events < <minimum>"`, and fix `"tk evolve --no-promote"`. An explicit `tk prune <name>` does not use that gate.

---

### 2.4 `lib/tool_sdk.py` — Opt-in helpers for Python tools

Stdlib only, with a 110-line budget (`len(source.splitlines()) <= 110`). Python tools may import it; the tool stays a single file. The Python example in `tools/.template` does `sys.path.insert(0, str(Path(__file__).resolve().parents[2]))` before `from lib.tool_sdk import ...`, which assumes the tool lives at `tools/<ns>/<file>.py`. Allowed imports are `json`, `os`, `signal`, `subprocess`, `sys`, `pathlib`, and `__future__`.

- **`emit(payload, code=0) -> int`**
  Writes one compact JSON line (`json.dumps(payload, separators=(",", ":"))` plus `\n`) to stdout when `code` is 0 and to stderr otherwise. Returns `code`.
- **`fail(error, why, fix, code=1) -> int`**
  `emit({"error": error, "why": why, "fix": fix}, code)`.
- **`is_dry_run() -> bool`**
  True only when `os.environ.get("TK_DRY_RUN", "0") == "1"`.
- **`dry_run_ok(**fields) -> int`**
  `emit({"dry_run": True, **fields})` (stdout, code 0).
- **`dry_run_plan(plan, **fields) -> int`**
  `emit({"dry_run": True, "plan": plan, **fields})` (stdout, code 0). A writer honored by `tk check <name> --verify` returns the runner's dry-run JSON. That command does not stamp the tool.
- **`arg_str(name, default="") -> str`**
  Reads `TK_ARG_<NAME>`. A `name` that starts with `TK_ARG_` is the env key; otherwise the key is `TK_ARG_` plus `name` with leading `-` stripped, `-` replaced by `_`, and the remainder uppercased. An unset or empty value returns `default`.
- **`arg_int(name, default, *, min_val=1, fix) -> int`**
  Uses the same env key as `arg_str`. An unset or empty value uses `str(default)`. A non-int, or a value `< min_val`, raises `SystemExit` with code 2 after `fail("invalid_flag", why, fix, 2)`. `why` is `<label> is not an int: <raw>` or `<label> must be >= <min_val>`. `label` is `name` with leading `-` stripped, a `TK_ARG_` prefix removed, `_` replaced by `-`, then lowercased. `fix` is required.
- **`paginate(items, limit, key="items", **extra) -> dict`**
  Copies `items` with `list(items)`, keeps `seq[:max(0, int(limit))]`, and always sets integer `count` (length of the kept slice) and integer `truncated` (`max(0, len(seq) - int(limit))`). The return is `{**extra, key: kept, "count": count, "truncated": truncated}`, so `count` and `truncated` overwrite extra fields of the same name.
- **`run_cmd(cmd, *, timeout=30, fix, error_code="cmd_failed", cwd=None)`**
  Runs `cmd` with `subprocess.Popen(..., stdout=PIPE, stderr=PIPE, text=True, cwd=cwd, start_new_session=True)`. `FileNotFoundError` exits 1 with `error` `not_found` and `why` naming `exc.filename` or `cmd[0]`. On `subprocess.TimeoutExpired`, kills that process group with `SIGKILL` (`os.killpg(proc.pid, signal.SIGKILL)`) and exits 1 with `error` `timeout` and `why` `command timed out after <timeout>s`. A non-zero status exits 1 with `error` set to the `error_code` argument (default `"cmd_failed"`) and `why` from stripped stderr, else stdout, else `exited <code>`. When `cmd` is non-empty, `Path(cmd[0]).name == "gh"`, and that `why` contains `auth login`, `not logged`, `not authenticated`, `http 401`, or `bad credentials` (case-insensitive), `fix` is `gh auth login` instead of the caller's `fix`. Success returns `subprocess.CompletedProcess`.
- **`run_main(fn, *, default_fix)`**
  Exits with the int `fn()` returns. A `SystemExit` raised by `fn` propagates unchanged, so `arg_int`'s code 2 is kept. `FileNotFoundError` exits 1 as `not_found`, `subprocess.TimeoutExpired` exits 1 as `timeout` (`why` includes `exc.timeout`), and any other `Exception` exits 1 as `internal_error` with `why` `str(exc)`. Those three mapped failures use `default_fix`.

---

### 2.5 `./tk` — CLI Entrypoint

Supports:
- `tk find [query] [--namespace <ns>] [--limit <n>]` — non-empty query defaults to 5 items (explicit `--limit N` overrides; empty query is uncapped); zero matches for a non-empty query log `search_miss` and write one stderr JSON line `{"error":"no_match","why":"no tool or chain matches '<query>'","fix":"tk find"}` (`fix` is `tk find --namespace <ns>` when the first query token is an existing namespace)
- `tk info <name>`
- `tk run <name> [--flag value ...] [--dry-run]`
- `tk chain run <name> [--flag value ...] [--dry-run]` (also `tk chain <name> [--flag value ...]`, which runs when no later token is a positional step: a step is not a flag and was not consumed as a flag value. `--dry-run`, `--yes`, and `--force` do not consume the next token; other flags do unless written `--flag=value`. Also `tk run <chain-name>`)
- `tk chain <name> '<tool>' ['<tool> --flag value' ...]` — same file as `tk chain save`; omitted `--summary` joins the raw step strings with ` → `. Optional `--summary`, `--safety`, `--example`, `--force`.
- `tk chain save <name> --summary "<text>" --steps '<json-or-space-list>' [--safety <tier>]`
- `tk save <name> --summary "<text>" [--safety <tier>] [--from-cmd "<cmd>" | --file <path>] [--arg "<spec>" ...] [--force]`
- `tk check [<name> ...] [--json]` and `tk check <name> --verify`
- `tk evolve [--no-promote]`
- `tk prune [<name> ...] [--unused] [--dry-run]`

---

## 3. Token Budget, Wiki Integrity & Multi-Agent Sync Gates

1. **Idle Skill Ceiling**: `skills/agent-toolkit/SKILL.md` must never exceed `51` lines or `2,700` bytes. The room above the original 45-line / 1,800-byte cap is the migrate-off-MCP section and the one-line Feedback issue pointer added on 2026-11-04.
2. **Discovery Line Ceiling**: Every item in `tk find` output must be exactly 2 lines (`<name> [<safety>] — <summary>` and `  run: <example>`), with each line `<= 140` characters.
3. **Historical Wiki Integrity (`wiki.lint`)**: Every file under `wiki/` (except `wiki/index.md`) must be linked from `wiki/index.md`, every relative link in `wiki/**/*.md` must resolve on disk, and every wiki page must contain dated (`YYYY-MM-DD`) and commit-cited (`@<sha>`) historical claims.
4. **Remote Multi-Agent Sync**: Because multiple agents work on this repo concurrently, on `main` run `git pull --rebase --autostash origin main` before launching a build wave. On a feature branch, run `tk run git.sync --repo .` to rebase onto `origin/main` and push the branch, before launching a build wave and again before pushing.

---

## 4. Tool Admission

[`VISION.md`](VISION.md) Pillar III: tools are born from real usage friction, and every iteration subtracts as well as adds. A pull request that adds a tool under `tools/` or a chain under `chains/` follows both rules in this section. Probation already runs in `lib/evolver.py` (issue #5, pull request #65; issue #16, pull request #72). The five uncited tools and the `unused_tools` check are recorded in [0008 — Tool probation](wiki/decisions/0008-tool-probation.md).

### 4.1 Born from

The pull request description cites an origin for each new tool or chain. An origin is a `search_miss` event, a `run_error` event, an issue, or a real task. The new tool file ships this header line:

```
# @tk-verified: none
```

A new chain ships `"verified": "none"`. `tk evolve` promotes a read-only item after `check_item` passes and a `run_ok` is in `state/events.jsonl`. Until that `run_ok`, `tk evolve --no-promote` lists the item in `awaiting_live_run`.

### 4.2 No harness-duplicate tools

Do not build a tool that merely wraps single-file reading, regex code search, directory listing, or AST symbol lookup (`fs.read-slice`, `code.search`, `code.todos`, `md.section`). Claude Code, Cursor, OMP, and Codex already provide native `Read`, `Grep` (`ripgrep`), `Glob`, and `LSP`.

Every new tool in `tools/` passes one admission test:

1. It distills an external service, database, or daemon (`gh`, `sql`, `http`, `docker`, `vercel`) so an MCP server can be turned off, or
2. It collapses `>= 3` local shell commands into a single low-token JSON payload (`git.branch-digest`, `py.test-digest`, `git.sync`).
