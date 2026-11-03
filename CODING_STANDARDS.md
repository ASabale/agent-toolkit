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
- **`find_items(root_dir: Path, query: str = "") -> list[dict]`**
  Empty query returns all items sorted by `name`. Non-empty query scores tokens against `name` (exact/substring/token weight 5/3), `summary` (weight 2), and `args` (weight 1), returning matches sorted by `(-score, name)`.
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
  5. Dry-run smoke check: running the tool with `TK_DRY_RUN=1` and synthetic dummy values for required flags (`"example"` for string, `"1"` for int/float, `"true"` for bool) exits `0` and produces valid JSON on `stdout`.
  6. For chains: every step's `"tool"` exists in `discover_catalog(root_dir)`.
- **`check_all(root_dir: Path) -> dict`**
  Runs `check_item` across every item in `discover_catalog(root_dir)` and returns `{"ok": bool, "checked": int, "results": list[dict], "errors": list[str]}`.

---

### 2.2 `lib/runner.py` — Validation, Execution & Chaining

- **`parse_cli_flags(argv: list[str]) -> tuple[dict[str, str], bool, list[str]]`**
  Extracts `--dry-run` anywhere in `argv` (`dry_run: bool`), parses `--flag value`, `--flag=value`, and standalone boolean `--flag` (`"true"`), and collects any stray positional tokens in `positional: list[str]`.
- **`validate_and_build_env(item: dict, flags: dict[str, str], positional: list[str], dry_run: bool) -> tuple[bool, dict[str, str], dict | None]`**
  - Rejects non-empty `positional` with `{"error": "positional_arguments_forbidden", "why": "...", "fix": item["example"]}`.
  - Rejects unknown `--flag` names not declared in `item["args"]` with `{"error": "unknown_flag", "why": "...", "fix": item["example"]}`.
  - Checks all required flags; if missing, constructs a copy-pasteable `fix` command that keeps already-supplied valid flags and appends `--missing <value>` placeholders.
  - Validates types (`int`, `float`, `bool`, `string`).
  - Returns `(True, env_dict, None)` with `TK_DRY_RUN="1"|"0"` and `TK_ARG_<NAME>` populated (including defaults for omitted optional flags).
- **`run_tool(root_dir: Path, item: dict, flags: dict[str, str], positional: list[str] | None = None, dry_run: bool = False, stdin_data: str | None = None) -> tuple[int, str, str]`**
  - Validates arguments, executes `item["path"]`, ensures `stdout` is compacted single-line or clean JSON, and formats any failure as a self-healing JSON error on `stderr`.
- **`run_chain(root_dir: Path, chain_item: dict, flags: dict[str, str], positional: list[str] | None = None, dry_run: bool = False) -> tuple[int, str, str]`**
  - Validates chain flags, resolves `$input.<arg>`, `$prev.<path>`, and `$step[i].<path>` across `steps`, pipes each step's JSON `stdout` into the next step's `stdin_data`, and halts on first error.

---

### 2.3 `lib/evolver.py` — Telemetry, Creation & Pruning

- **`log_event(root_dir: Path, event_type: str, payload: dict) -> None`**
  Appends `{"ts": ..., "event": event_type, ...}` to `state/events.jsonl`. Never raises.
- **`save_tool(root_dir: Path, name: str, summary: str, safety: str = "read-only", from_cmd: str | None = None, file_path: str | None = None, args_spec: list[str] | None = None, force: bool = False) -> tuple[int, str, str]`**
  Creates `tools/<namespace>/<tool-name>` with complete `# @tk-*` headers, sets `0o755`, runs `check_item`, rolls back on failure, logs `tool_saved`, and returns `(0, compact_json, "")`.
- **`save_chain(root_dir: Path, name: str, summary: str, steps: list[dict], args: list[dict] | None = None, safety: str = "read-only", example: str | None = None, force: bool = False) -> tuple[int, str, str]`**
  Writes `chains/<name>.json`, validates via `check_item`, rolls back on failure, logs `chain_saved`, and returns `(0, compact_json, "")`.
- **`evolve_report(root_dir: Path, auto_promote: bool = True) -> dict`**
  Analyzes `state/events.jsonl` + catalog: auto-promotes unverified `read-only` tools that pass `check_item` (updating `@tk-verified` to today's YYYY-MM-DD), and reports `promoted`, `search_misses`, `failing_tools`, `unused_tools`, and `overlap_candidates`.

---

### 2.4 `./tk` — CLI Entrypoint

Supports:
- `tk find [query]`
- `tk info <name>`
- `tk run <name> [--flag value ...] [--dry-run]`
- `tk chain run <name> [--flag value ...] [--dry-run]` (also runnable directly via `tk run <chain-name>`)
- `tk chain save <name> --summary "<text>" --steps '<json-or-space-list>' [--safety <tier>]`
- `tk save <name> --summary "<text>" [--safety <tier>] [--from-cmd "<cmd>" | --file <path>] [--arg "<spec>" ...] [--force]`
- `tk check [name] [--json]`
- `tk evolve [--no-promote]`
