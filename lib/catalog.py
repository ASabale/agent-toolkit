"""Discovery, indexing, and validation for agent-toolkit tools and chains.

Zero third-party dependencies. Public functions catch unexpected failures and
return empty or error-shaped values instead of raising.
"""

from __future__ import annotations

import concurrent.futures
import difflib
import json
import os
import py_compile
import re
import shlex
import subprocess
import tempfile
from pathlib import Path

_SAFETY = {"read-only", "mutating", "destructive"}
_TYPES = {"string", "int", "float", "bool"}
_DEFAULT_RE = re.compile(r"\(default:\s*([^)]*)\)", re.IGNORECASE)


def _empty_tool(path: Path) -> dict:
    try:
        resolved = str(path.resolve()) if path.exists() else str(path)
    except OSError:
        resolved = str(path)
    return {
        "kind": "tool",
        "name": "",
        "summary": "",
        "safety": "",
        "args": [],
        "output": "",
        "example": "",
        "verified": "",
        "path": resolved,
    }


def _empty_chain(path: Path) -> dict:
    item = _empty_tool(path)
    item["kind"] = "chain"
    item["steps"] = []
    return item


def _parse_arg(spec: str) -> dict:
    parts = [part.strip() for part in spec.split("|")]
    flag = parts[0] if parts else ""
    requirement = parts[1].lower() if len(parts) > 1 else ""
    typ = parts[2].lower() if len(parts) > 2 else ""
    description = " | ".join(parts[3:]).strip() if len(parts) > 3 else ""
    default = None
    match = _DEFAULT_RE.search(description)
    if match:
        default = match.group(1).strip()
    env_var = "TK_ARG_" + flag.lstrip("-").replace("-", "_").upper()
    return {
        "flag": flag,
        "env_var": env_var,
        "required": requirement == "required",
        "type": typ,
        "description": description,
        "default": default,
    }


def _normalize_arg(raw) -> dict:
    if isinstance(raw, str):
        return _parse_arg(raw)
    if isinstance(raw, dict):
        if "flag" in raw and isinstance(raw.get("flag"), str) and "type" in raw:
            flag = str(raw.get("flag") or "")
            description = str(raw.get("description") or "")
            default = raw.get("default", None)
            if default is None:
                match = _DEFAULT_RE.search(description)
                if match:
                    default = match.group(1).strip()
            elif default is not None:
                default = str(default)
            return {
                "flag": flag,
                "env_var": str(raw.get("env_var") or ("TK_ARG_" + flag.lstrip("-").replace("-", "_").upper())),
                "required": bool(raw.get("required")),
                "type": str(raw.get("type") or ""),
                "description": description,
                "default": default,
            }
        return _parse_arg(str(raw.get("spec") or raw.get("flag") or ""))
    return _parse_arg("")


def parse_tool_header(path: Path) -> dict:
    """Parse the leading ``# @tk-*`` comment block of a tool file."""
    path = Path(path)
    item = _empty_tool(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return item
    try:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#!"):
                continue
            if not stripped.startswith("#"):
                break
            body = stripped[1:].strip()
            if not body.startswith("@tk-"):
                continue
            key, _, value = body.partition(":")
            key = key.strip()
            value = value.strip()
            if key == "@tk-name":
                item["name"] = value
            elif key == "@tk-summary":
                item["summary"] = value
            elif key == "@tk-safety":
                item["safety"] = value
            elif key == "@tk-arg":
                item["args"].append(_parse_arg(value))
            elif key == "@tk-output":
                item["output"] = value
            elif key == "@tk-example":
                item["example"] = value
            elif key == "@tk-verified":
                item["verified"] = value
    except Exception:
        return item
    return item


def load_chain(path: Path) -> dict:
    """Load ``chains/<name>.json`` into the shared catalog item shape."""
    path = Path(path)
    item = _empty_chain(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return item
    except Exception:
        return item
    if not isinstance(data, dict):
        return item
    try:
        item["name"] = str(data.get("name") or "")
        item["summary"] = str(data.get("summary") or "")
        item["safety"] = str(data.get("safety") or "")
        item["output"] = str(data.get("output") or "")
        item["example"] = str(data.get("example") or "")
        item["verified"] = str(data.get("verified") or "")
        raw_args = data.get("args") or []
        item["args"] = [_normalize_arg(arg) for arg in raw_args] if isinstance(raw_args, list) else []
        steps = data.get("steps") or []
        item["steps"] = steps if isinstance(steps, list) else []
    except Exception:
        return _empty_chain(path)
    return item


def _hidden_part(part: str) -> bool:
    return part.startswith(".") or part.startswith("__")


def discover_catalog(root_dir: Path) -> dict[str, dict]:
    """Scan ``tools/`` recursively and ``chains/*.json``. Keys are sorted."""
    root_dir = Path(root_dir)
    items: dict[str, dict] = {}
    try:
        tools_dir = root_dir / "tools"
        if tools_dir.is_dir():
            for path in sorted(tools_dir.rglob("*")):
                try:
                    relative = path.relative_to(tools_dir)
                except ValueError:
                    continue
                if any(_hidden_part(part) for part in relative.parts):
                    continue
                if not path.is_file():
                    continue
                item = parse_tool_header(path)
                key = item["name"] or relative.as_posix()
                items[key] = item
        chains_dir = root_dir / "chains"
        if chains_dir.is_dir():
            for path in sorted(chains_dir.glob("*.json")):
                if _hidden_part(path.name) or not path.is_file():
                    continue
                item = load_chain(path)
                key = item["name"] or path.name
                items[key] = item
    except Exception:
        return dict(sorted(items.items()))
    return dict(sorted(items.items()))


def _arg_blob(item: dict) -> str:
    parts: list[str] = []
    for arg in item.get("args") or []:
        if not isinstance(arg, dict):
            parts.append(str(arg))
            continue
        parts.append(str(arg.get("flag") or ""))
        parts.append(str(arg.get("description") or ""))
    return " ".join(parts).lower()


def _name_segments(name: str) -> set[str]:
    return {part for part in re.split(r"[.\-_]+", name) if part}


def _score(item: dict, query: str) -> int:
    """Score query tokens: name exact 5 / substring 3, summary 2, args 1."""
    tokens = [tok for tok in query.lower().split() if tok]
    if not tokens:
        return 0
    name = str(item.get("name") or "").lower()
    summary = str(item.get("summary") or "").lower()
    args = _arg_blob(item)
    segments = _name_segments(name)
    score = 0
    for token in tokens:
        if token == name or token in segments:
            score += 5
        elif token in name:
            score += 3
        if token in summary:
            score += 2
        if token in args:
            score += 1
    return score


def find_items(
    root_dir: Path,
    query: str = "",
    limit: int | None = None,
    namespace: str | None = None,
) -> list[dict]:
    """Return catalog items matching ``query``, best score then name.

    A positive ``limit`` keeps only the first matches. A non-empty
    ``namespace`` keeps names equal to that namespace or under it.
    """
    try:
        catalog = discover_catalog(root_dir)
        items = list(catalog.values())
        ns = str(namespace or "").strip().lower().rstrip(".")
        if ns:
            items = [item for item in items if _in_namespace(item, ns)]
        if not str(query or "").strip():
            ranked = sorted(items, key=lambda item: str(item.get("name") or ""))
        else:
            scored = []
            for item in items:
                score = _score(item, query)
                if score > 0:
                    scored.append((score, str(item.get("name") or ""), item))
            scored.sort(key=lambda row: (-row[0], row[1]))
            ranked = [row[2] for row in scored]
        if isinstance(limit, int) and limit > 0:
            return ranked[:limit]
        return ranked
    except Exception:
        return []


def _in_namespace(item: dict, namespace: str) -> bool:
    name = str(item.get("name") or "").lower()
    return name == namespace or name.startswith(f"{namespace}.")


_SHELL_ARG_RE = re.compile(
    r"(?:\$\{TK_ARG_([A-Z][A-Z0-9_]*)|\$TK_ARG_([A-Z][A-Z0-9_]*))\b"
)
_PY_ARG_RE = re.compile(
    r"""(?:environ\.get|getenv|environ)\s*[\(\[]\s*['"]TK_ARG_([A-Z][A-Z0-9_]*)['"]"""
)


def _strip_unquoted_comment(line: str) -> str:
    """Drop a trailing `# ...` comment that is outside quotes."""
    out: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(line):
        char = line[index]
        if quote:
            out.append(char)
            if char == "\\" and quote == '"' and index + 1 < len(line):
                out.append(line[index + 1])
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            out.append(char)
            index += 1
            continue
        if char == "#":
            break
        out.append(char)
        index += 1
    return "".join(out)


def _referenced_arg_names(line: str) -> set[str]:
    code = _strip_unquoted_comment(line)
    found: set[str] = set()
    for braced, bare in _SHELL_ARG_RE.findall(code):
        found.add(braced or bare)
    found.update(_PY_ARG_RE.findall(code))
    return found


def _undeclared_arg_env_errors(path: Path, item: dict) -> list[str]:
    declared = {
        str(arg.get("env_var"))
        for arg in (item.get("args") or [])
        if isinstance(arg, dict) and arg.get("env_var")
    }
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found: set[str] = set()
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        found.update(_referenced_arg_names(line))
    return [
        f"undeclared arg env var in script: TK_ARG_{name}"
        for name in sorted(found)
        if f"TK_ARG_{name}" not in declared
    ]


def suggest_closest_item(root_dir: Path, name: str) -> dict | None:
    """Return the closest catalog item for a mistyped name, or None."""
    try:
        catalog = discover_catalog(root_dir)
        matches = difflib.get_close_matches(name, catalog.keys(), n=1, cutoff=0.45)
        if matches:
            return catalog[matches[0]]
        tokens = [tok for tok in re.split(r"[.\-_]+", name) if tok]
        if not tokens:
            return None
        found = find_items(root_dir, " ".join(tokens))
        return found[0] if found else None
    except Exception:
        return None


def format_find_output(items: list[dict]) -> str:
    """Two lines per item: name/safety/summary, then the run example."""
    try:
        lines: list[str] = []
        for item in items:
            name = item.get("name") or ""
            safety = item.get("safety") or ""
            summary = item.get("summary") or ""
            example = item.get("example") or ""
            lines.append(f"{name} [{safety}] — {summary}")
            lines.append(f"  run: {example}")
        if not lines:
            return ""
        return "\n".join(lines) + "\n"
    except Exception:
        return ""


def format_info_output(item: dict) -> str:
    """Compact multi-line contract: name, kind, safety, summary, args, output, example, verified."""
    try:
        lines = [
            f"name: {item.get('name') or ''}",
            f"kind: {item.get('kind') or ''}",
            f"safety: {item.get('safety') or ''}",
            f"summary: {item.get('summary') or ''}",
            "args:",
        ]
        for arg in item.get("args") or []:
            if not isinstance(arg, dict):
                lines.append(f"  {arg}")
                continue
            requirement = "required" if arg.get("required") else "optional"
            lines.append(
                f"  {arg.get('flag') or ''} | {requirement} | {arg.get('type') or ''} | {arg.get('description') or ''}"
            )
        lines.append(f"output: {item.get('output') or ''}")
        lines.append(f"example: {item.get('example') or ''}")
        lines.append(f"verified: {item.get('verified') or ''}")
        return "\n".join(lines) + "\n"
    except Exception:
        return ""


def _interpreter(path: Path) -> str | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            first = handle.readline().strip().lower()
    except OSError:
        return None
    if not first.startswith("#!"):
        return None
    if "python" in first:
        return "python"
    # bash and sh, including `#!/usr/bin/env bash`.
    if re.search(r"(^|[/\s])(bash|sh)(\s|$)", first[2:]):
        return "shell"
    return "other"


def _dummy(typ: str) -> str:
    if typ in {"int", "float"}:
        return "1"
    if typ == "bool":
        return "true"
    return "example"


def _flag_present(tokens: list[str], flag: str) -> bool:
    return any(token == flag or token.startswith(flag + "=") for token in tokens)


def _flag_has_value(tokens: list[str], flag: str) -> bool:
    for index, token in enumerate(tokens):
        if token == flag:
            if index + 1 >= len(tokens):
                return False
            nxt = tokens[index + 1]
            return bool(nxt) and not nxt.startswith("--")
        if token.startswith(flag + "="):
            return bool(token.split("=", 1)[1])
    return False


def _example_ok(name: str, example: str, args: list[dict]) -> list[str]:
    errors: list[str] = []
    text = (example or "").strip()
    prefix = f"tk run {name}"
    if not name or not (text == prefix or text.startswith(prefix + " ")):
        errors.append(f"example must start with 'tk run {name}'")
    try:
        tokens = shlex.split(text)
    except ValueError as exc:
        errors.append(f"example is not a valid command: {exc}")
        return errors
    for arg in args:
        if not arg.get("required"):
            continue
        flag = str(arg.get("flag") or "")
        if not flag:
            continue
        if not _flag_present(tokens, flag):
            errors.append(f"example missing required flag {flag}")
            continue
        if str(arg.get("type") or "string") == "bool":
            continue
        if not _flag_has_value(tokens, flag):
            errors.append(f"example missing value for required flag {flag}")
    return errors


def _syntax_error(path: Path) -> str | None:
    kind = _interpreter(path)
    if kind is None:
        return "syntax: missing shebang"
    if kind == "other":
        return "syntax: unsupported shebang"
    if kind == "shell":
        try:
            proc = subprocess.run(
                ["bash", "-n", str(path)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"syntax: {exc}"
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "bash -n failed").strip().splitlines()
            return "syntax: " + (detail[0] if detail else "bash -n failed")
        return None
    try:
        with tempfile.NamedTemporaryFile(prefix="tk-pyc-", delete=False) as handle:
            cfile = handle.name
        try:
            py_compile.compile(str(path), cfile=cfile, doraise=True)
        finally:
            try:
                os.unlink(cfile)
            except OSError:
                pass
    except py_compile.PyCompileError as exc:
        return f"syntax: {exc}"
    except Exception as exc:
        return f"syntax: {exc}"
    return None


def _dry_run_error(path: Path, args: list[dict]) -> str | None:
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("TK_ARG_") or key == "TK_DRY_RUN":
            env.pop(key, None)
    env["TK_DRY_RUN"] = "1"
    for arg in args:
        if arg.get("required"):
            env_var = str(arg.get("env_var") or "")
            if env_var:
                env[env_var] = _dummy(str(arg.get("type") or "string"))
    try:
        proc = subprocess.run(
            [str(path)],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
            cwd=str(path.parent),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "dry-run timed out"
    except OSError as exc:
        return f"dry-run failed: {exc}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        suffix = (": " + detail[0]) if detail else ""
        return f"dry-run exited {proc.returncode}{suffix}"
    stdout = proc.stdout.strip()
    if not stdout:
        return "dry-run produced empty stdout; expected JSON"
    try:
        json.loads(stdout)
    except json.JSONDecodeError as exc:
        return f"dry-run stdout is not valid JSON: {exc.msg}"
    return None


def _default_matches(typ: str, default: str) -> bool:
    if typ == "int":
        return re.fullmatch(r"[+-]?\d+", default) is not None
    if typ == "float":
        return re.fullmatch(r"[+-]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[eE][+-]?\d+)?", default) is not None
    if typ == "bool":
        return default.strip().lower() in {"true", "false", "1", "0", "yes", "no"}
    return True


def _header_errors(item: dict) -> list[str]:
    errors: list[str] = []
    for field in ("name", "summary", "safety", "output", "example", "verified"):
        if not str(item.get(field) or "").strip():
            errors.append(f"missing header: {field}")
    safety = str(item.get("safety") or "")
    if safety and safety not in _SAFETY:
        errors.append(f"invalid safety: {safety}")
    seen_flags: set[str] = set()
    for arg in item.get("args") or []:
        if not isinstance(arg, dict):
            errors.append("invalid arg")
            continue
        flag = str(arg.get("flag") or "")
        if not flag.startswith("--"):
            errors.append(f"invalid arg flag: {flag or '(empty)'}")
        elif flag in seen_flags:
            errors.append(f"duplicate arg flag: {flag}")
        else:
            seen_flags.add(flag)
        typ = str(arg.get("type") or "")
        if typ not in _TYPES:
            errors.append(f"invalid arg type for {flag or '(empty)'}: {typ or '(empty)'}")
        default = arg.get("default")
        if default is not None and typ in {"int", "float", "bool"} and not _default_matches(typ, str(default)):
            label = flag if flag.startswith("--") else f"--{flag.lstrip('-') or 'empty'}"
            errors.append(f"invalid default for {label}: {default} is not {typ}")
    return errors


def _resolve(root_dir: Path, name_or_path: str | Path) -> tuple[Path | None, dict | None, str | None]:
    """Return path, preloaded item (chains), and a not-found message."""
    if isinstance(name_or_path, Path):
        path = name_or_path
        if path.is_file():
            return path, None, None
        return None, None, f"file not found: {path}"
    text = str(name_or_path)
    direct = Path(text)
    if direct.is_file():
        return direct, None, None
    under_root = root_dir / text
    if under_root.is_file():
        return under_root, None, None
    catalog = discover_catalog(root_dir)
    item = catalog.get(text)
    if item is None:
        return None, None, f"not in catalog: {text}"
    path = Path(item["path"])
    if not path.is_file():
        return None, None, f"file not found: {path}"
    return path, item, None


_CHAIN_INPUT_REF = re.compile(r"^\$input\.([A-Za-z0-9_-]+)$")
_CHAIN_STEP_REF = re.compile(r"^\$step\[(-?\d+)\](?:\..*)?$")


def _parse_output_keys(output: str) -> set[str] | None:
    """Extract top-level field names from an @tk-output like ``json | {a, b:[...], c}``.

    Returns the set of key names if the output has a ``{...}`` shape, or None
    if it doesn't (which means the check should be skipped, not failed).
    """
    text = output.strip()
    if "|" in text:
        text = text.split("|", 1)[1].strip()
    if not text.startswith("{"):
        return None
    depth = 0
    end = -1
    for idx, char in enumerate(text):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = idx
                break
    if end < 0:
        return None
    inner = text[1:end]
    keys: set[str] = set()
    depth = 0
    start = 0
    for idx, char in enumerate(inner):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            segment = inner[start:idx].strip()
            if segment:
                key = segment.split(":")[0].split("[")[0].strip()
                if key:
                    keys.add(key)
            start = idx + 1
    segment = inner[start:].strip()
    if segment:
        key = segment.split(":")[0].split("[")[0].strip()
        if key:
            keys.add(key)
    return keys if keys else None


def _pick_query_key_errors(
    index: int,
    tool_name: str,
    step_args: dict,
    upstream_output: str,
    upstream_name: str,
) -> list[str]:
    """Validate json.pick/json.query keys against upstream @tk-output."""
    errors: list[str] = []
    upstream_keys = _parse_output_keys(upstream_output)
    if upstream_keys is None:
        return errors

    if tool_name == "json.pick":
        raw_keys = str(step_args.get("keys") or step_args.get("--keys") or "")
        requested = {key.strip() for key in raw_keys.split(",") if key.strip()}
        for key in sorted(requested):
            if key not in upstream_keys:
                errors.append(
                    f"step {index} (json.pick) key '{key}' not in upstream {upstream_name} output"
                )

    elif tool_name == "json.query":
        raw_expr = str(step_args.get("expr") or step_args.get("--expr") or "")
        expr = raw_expr.strip()
        if expr.startswith("{") and "}" in expr:
            end = expr.index("}")
            inner = expr[1:end]
            requested = {key.strip() for key in inner.split(",") if key.strip()}
            for key in sorted(requested):
                if key not in upstream_keys:
                    errors.append(
                        f"step {index} (json.query) key '{key}' not in upstream {upstream_name} output"
                    )
        elif expr and not expr.startswith("["):
            first_key = expr.split(".")[0].split("[")[0].strip()
            if first_key and first_key not in upstream_keys:
                errors.append(
                    f"step {index} (json.query) key '{first_key}' not in upstream {upstream_name} output"
                )

    return errors


def _flag_name(key: object) -> str:
    text = str(key)
    return text if text.startswith("--") else f"--{text}"


def _bare_arg_name(flag: str) -> str:
    bare = flag[2:] if flag.startswith("--") else flag.lstrip("-")
    return bare.replace("-", "_")


def _chain_wiring_errors(item: dict, catalog: dict) -> list[str]:
    """Static flag and reference checks for each chain step."""
    errors: list[str] = []
    declared_inputs = {
        _bare_arg_name(str(arg.get("flag") or ""))
        for arg in (item.get("args") or [])
        if isinstance(arg, dict)
    }
    steps = item.get("steps") or []
    if not isinstance(steps, list):
        return errors
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        tool_name = step.get("tool")
        tool = catalog.get(tool_name) if tool_name else None
        if not tool_name or tool is None:
            continue
        if tool.get("kind") == "chain":
            errors.append(f"step {index} ({tool_name}) cannot target a chain")
            continue
        declared: dict[str, dict] = {}
        for arg in tool.get("args") or []:
            if isinstance(arg, dict) and arg.get("flag"):
                declared[str(arg["flag"])] = arg
        raw = step.get("args") or {}
        if not isinstance(raw, dict):
            errors.append(f"step {index} ({tool_name}) args must be an object")
            continue
        present: set[str] = set()
        for key, val in raw.items():
            flag = _flag_name(key)
            present.add(flag)
            if flag not in declared:
                errors.append(f"step {index} ({tool_name}) unknown flag: {flag}")
            if not isinstance(val, str):
                continue
            text = val.strip()
            input_match = _CHAIN_INPUT_REF.fullmatch(text)
            if input_match and _bare_arg_name(input_match.group(1)) not in declared_inputs:
                errors.append(f"step {index} unresolved input reference: {text}")
            if (text == "$prev" or text.startswith("$prev.")) and index == 0:
                errors.append(f"step 0 cannot reference $prev: {text}")
            step_match = _CHAIN_STEP_REF.fullmatch(text)
            if step_match:
                ref = int(step_match.group(1))
                if ref < 0 or ref >= index:
                    errors.append(f"step {index} invalid step reference: {text}")
        for flag, arg in declared.items():
            if arg.get("required") and arg.get("default") is None and flag not in present:
                errors.append(f"step {index} ({tool_name}) missing required flag: {flag}")
        if tool_name in {"json.pick", "json.query"} and index > 0:
            prev_step = steps[index - 1]
            prev_tool_name = prev_step.get("tool") if isinstance(prev_step, dict) else None
            prev_tool = catalog.get(prev_tool_name) if prev_tool_name else None
            if prev_tool:
                upstream_output = str(prev_tool.get("output") or "")
                errors.extend(
                    _pick_query_key_errors(index, tool_name, raw, upstream_output, prev_tool_name)
                )
    return errors


def _chain_dry_run_error(root_dir: Path, item: dict) -> str | None:
    from lib.runner import run_chain

    flags: dict[str, str] = {}
    for arg in item.get("args") or []:
        if isinstance(arg, dict) and arg.get("required") and arg.get("flag"):
            flags[str(arg["flag"])] = _dummy(str(arg.get("type") or "string"))
    rc, stdout, err = run_chain(root_dir, item, flags, dry_run=True)
    if rc != 0:
        return f"chain dry-run failed: {err}"
    text = stdout.strip()
    if not text:
        return "chain dry-run produced invalid JSON"
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return "chain dry-run produced invalid JSON"
    return None


def _is_chain_path(root_dir: Path, path: Path) -> bool:
    if path.suffix.lower() != ".json":
        return False
    try:
        path.resolve().relative_to((root_dir / "chains").resolve())
        return True
    except (OSError, ValueError):
        return False


def check_item(root_dir: Path, name_or_path: str | Path) -> dict:
    """Validate one tool or chain. Always returns ``name``, ``ok``, ``errors``."""
    root_dir = Path(root_dir)
    label = str(name_or_path)
    try:
        path, preloaded, missing = _resolve(root_dir, name_or_path)
        if path is None or missing:
            return {"name": label, "ok": False, "errors": [missing or "file not found"]}
        is_chain = (preloaded or {}).get("kind") == "chain" or _is_chain_path(root_dir, path)
        item = preloaded if preloaded is not None else (load_chain(path) if is_chain else parse_tool_header(path))
        name = str(item.get("name") or path.stem)
        errors: list[str] = []
        if not is_chain and not os.access(path, os.X_OK):
            errors.append(f"not executable: {path}")
        errors.extend(_header_errors(item))
        errors.extend(_example_ok(str(item.get("name") or ""), str(item.get("example") or ""), item.get("args") or []))
        if not is_chain:
            errors.extend(_undeclared_arg_env_errors(path, item))
            syntax = _syntax_error(path)
            if syntax:
                errors.append(syntax)
            elif os.access(path, os.X_OK):
                dry = _dry_run_error(path, item.get("args") or [])
                if dry:
                    errors.append(dry)
        else:
            catalog = discover_catalog(root_dir)
            steps = item.get("steps") or []
            if not isinstance(steps, list):
                errors.append("chain steps must be a list")
            else:
                for index, step in enumerate(steps):
                    tool_name = step.get("tool") if isinstance(step, dict) else None
                    if not tool_name:
                        errors.append(f"step {index} missing tool")
                    elif tool_name not in catalog:
                        errors.append(f"step {index} tool not in catalog: {tool_name}")
                errors.extend(_chain_wiring_errors(item, catalog))
            if not errors:
                dry = _chain_dry_run_error(root_dir, item)
                if dry:
                    errors.append(dry)
        return {"name": name, "ok": not errors, "errors": errors}
    except Exception as exc:
        return {"name": label, "ok": False, "errors": [f"internal_error: {exc}"]}


def check_all(root_dir: Path) -> dict:
    """Run ``check_item`` on every catalog entry."""
    root_dir = Path(root_dir)
    try:
        catalog = discover_catalog(root_dir)
        names = list(catalog)
        workers = min(8, max(1, len(catalog)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda name: check_item(root_dir, name), names))
        errors = [f"{result['name']}: {err}" for result in results for err in result["errors"]]
        return {
            "ok": all(result["ok"] for result in results) if results else True,
            "checked": len(results),
            "results": results,
            "errors": errors,
        }
    except Exception as exc:
        return {
            "ok": False,
            "checked": 0,
            "results": [],
            "errors": [f"internal_error: {exc}"],
        }
