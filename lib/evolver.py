"""Telemetry, tool/chain creation, and catalog evolution.

Public seam (CODING_STANDARDS.md §2.3):
- log_event: append-only telemetry; never raises
- save_tool / save_chain: write a draft, validate with check_item, roll back on failure
- evolve_report: promote verified-passing read-only tools and summarize friction
"""

from __future__ import annotations

import json
import os
import py_compile
import re
import stat
import subprocess
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

_SAFETY = {"read-only", "mutating", "destructive"}
_ARG_TYPES = {"string", "int", "float", "bool"}
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9][A-Za-z0-9_-]*)*$")
_VERIFIED_RE = re.compile(r"(?m)^#\s*@tk-verified\s*:.*$")
_USAGE_EVENTS = {"run", "run_ok", "tool_run", "chain_run"}
_MISS_EVENTS = {"search_miss", "miss"}
_FAIL_EVENTS = {"run_error", "error"}
_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "into",
    "json",
    "only",
    "per",
    "that",
    "the",
    "this",
    "tool",
    "tools",
    "via",
    "with",
    "when",
    "your",
}
_DUMMY = {"string": "example", "int": "1", "float": "1", "bool": "true"}


def log_event(root_dir: Path, event_type: str, payload: dict) -> None:
    """Append one JSONL telemetry record. Swallows every I/O or encoding failure."""
    try:
        root = Path(root_dir)
        state = root / "state"
        state.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
        }
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key not in {"ts", "event"}:
                    record[key] = value
        line = json.dumps(record, separators=(",", ":"), default=str)
        with (state / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        return


def save_tool(
    root_dir: Path,
    name: str,
    summary: str,
    safety: str = "read-only",
    from_cmd: str | None = None,
    file_path: str | None = None,
    args_spec: list[str] | None = None,
    force: bool = False,
) -> tuple[int, str, str]:
    """Create tools/<namespace>/<tool> and keep it only when check_item passes."""
    try:
        root = Path(root_dir)
        error = _validate_common(name, summary, safety)
        if error:
            return _failure(*error)
        specs = _normalize_arg_specs(args_spec)
        if specs is None:
            return _failure("bad_arg_spec", "each --arg must be '--flag | required|optional | type | description'", "tk save <name> --arg \"--flag | required | string | description\"")
        source, source_error = _tool_source(name, summary, safety, from_cmd, file_path, specs)
        if source_error:
            return _failure(*source_error)
        dest = _tool_dest(root, name)
        return _commit_draft(
            root,
            dest,
            source,
            force=force,
            executable=True,
            success={
                "ok": True,
                "name": name,
                "kind": "tool",
                "path": str(dest),
                "safety": safety,
            },
            saved_event="tool_saved",
            saved_payload={"name": name, "path": str(dest), "safety": safety, "kind": "tool"},
            catalog_root=root / "tools",
        )
    except Exception as exc:
        return _failure("internal_error", str(exc), "tk check")


def save_chain(
    root_dir: Path,
    name: str,
    summary: str,
    steps: list[dict],
    args: list[dict] | None = None,
    safety: str = "read-only",
    example: str | None = None,
    force: bool = False,
) -> tuple[int, str, str]:
    """Write chains/<name>.json and delete it again when check_item fails."""
    try:
        root = Path(root_dir)
        error = _validate_common(name, summary, safety)
        if error:
            return _failure(*error)
        step_error = _validate_steps(steps)
        if step_error:
            return _failure(*step_error)
        chain_args = list(args or [])
        arg_error = _validate_chain_args(chain_args)
        if arg_error:
            return _failure(*arg_error)
        example_text = example.strip() if isinstance(example, str) and example.strip() else _build_example(name, _flags_from_chain_args(chain_args))
        document = {
            "kind": "chain",
            "name": name,
            "summary": summary,
            "safety": safety,
            "args": chain_args,
            "steps": steps,
            "output": "json | Chain result",
            "example": example_text,
            "verified": "none",
        }
        text = json.dumps(document, indent=2) + "\n"
        dest = root / "chains" / f"{name}.json"
        return _commit_draft(
            root,
            dest,
            text,
            force=force,
            executable=False,
            success={
                "ok": True,
                "name": name,
                "kind": "chain",
                "path": str(dest),
                "safety": safety,
            },
            saved_event="chain_saved",
            saved_payload={"name": name, "path": str(dest), "safety": safety, "kind": "chain"},
            catalog_root=root / "chains",
        )
    except Exception as exc:
        return _failure("internal_error", str(exc), "tk check")


def evolve_report(root_dir: Path, auto_promote: bool = True) -> dict:
    """Promote unverified read-only tools that pass check_item and summarize events."""
    empty = {
        "promoted": [],
        "search_misses": [],
        "failing_tools": [],
        "unused_tools": [],
        "overlap_candidates": [],
    }
    try:
        root = Path(root_dir)
        catalog = _discover(root)
        events = _read_events(root / "state" / "events.jsonl")
        used, failed_runs, misses = _summarize_events(events)
        today = date.today().isoformat()
        promoted: list[str] = []
        failing: list[dict] = []
        for name in sorted(catalog):
            item = catalog[name]
            check = _check_item(root, item.get("path") or name)
            errors = [str(err) for err in (check.get("errors") or [])]
            if not check.get("ok"):
                if not errors:
                    errors = ["validation failed"]
            run_errors = failed_runs.get(name) or []
            if run_errors:
                errors.extend(run_errors)
            if errors:
                failing.append({"name": name, "errors": errors})
            if (
                auto_promote
                and check.get("ok")
                and item.get("kind") == "tool"
                and item.get("safety") == "read-only"
                and _is_unverified(item.get("verified"))
            ):
                path = Path(str(item.get("path") or ""))
                if path.is_file() and _promote_tool(path, today):
                    promoted.append(name)
        unused = sorted(name for name in catalog if name not in used)
        return {
            "promoted": promoted,
            "search_misses": misses,
            "failing_tools": failing,
            "unused_tools": unused,
            "overlap_candidates": _overlap_candidates(catalog),
        }
    except Exception:
        return empty


def _failure(error: str, why: str, fix: str) -> tuple[int, str, str]:
    return 1, "", _error_json(error, why, fix)


def _error_json(error: str, why: str, fix: str) -> str:
    return json.dumps({"error": error, "why": why, "fix": fix}, separators=(",", ":"))


def _validate_common(name: str, summary: str, safety: str) -> tuple[str, str, str] | None:
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        return ("invalid_name", "name must be namespace.tool using letters, numbers, dots, underscores, and hyphens", "tk save <namespace>.<tool-name> --summary \"<text>\"")
    if not isinstance(summary, str) or not summary.strip():
        return ("missing_summary", "summary is required", "tk save <name> --summary \"<text>\"")
    if safety not in _SAFETY:
        return ("invalid_safety", "safety must be read-only, mutating, or destructive", "tk save <name> --safety read-only")
    return None


def _validate_steps(steps: list[dict]) -> tuple[str, str, str] | None:
    if not isinstance(steps, list) or not steps:
        return ("empty_steps", "a chain needs at least one step", "tk chain save <name> --steps '[{\"tool\":\"<tool>\"}]'")
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or not isinstance(step.get("tool"), str) or not step.get("tool"):
            return ("invalid_step", f"step {index} needs a tool name", "tk chain save <name> --steps '[{\"tool\":\"<tool>\"}]'")
    return None


def _validate_chain_args(args: list[dict]) -> tuple[str, str, str] | None:
    if not isinstance(args, list):
        return ("bad_arg_spec", "chain args must be a list", "tk chain save <name> --steps '<json>'")
    for arg in args:
        if not isinstance(arg, dict):
            return ("bad_arg_spec", "each chain arg must be an object", "tk chain save <name> --steps '<json>'")
        flag = arg.get("flag") or arg.get("name")
        if not isinstance(flag, str) or not flag.startswith("--"):
            return ("bad_arg_spec", "chain arg flag must look like --name", "tk chain save <name> --steps '<json>'")
    return None


def _tool_source(
    name: str,
    summary: str,
    safety: str,
    from_cmd: str | None,
    file_path: str | None,
    specs: list[str],
) -> tuple[str | None, tuple[str, str, str] | None]:
    if file_path:
        source = Path(file_path)
        if not source.is_file():
            return None, ("file_not_found", f"file not found: {file_path}", "tk save <name> --file <path>")
        try:
            raw = source.read_text(encoding="utf-8")
        except OSError as exc:
            return None, ("file_not_found", str(exc), "tk save <name> --file <path>")
        if _has_tool_header(raw):
            return _overlay_tool_header(raw, name, summary, safety, specs), None
        return _render_wrapped_tool(name, summary, safety, specs, _strip_shebang(raw).rstrip() + "\n"), None
    command = from_cmd.strip() if isinstance(from_cmd, str) else ""
    if not command:
        return None, ("missing_source", "provide from_cmd or file_path", "tk save <name> --from-cmd \"<cmd>\"")
    return _render_wrapped_tool(name, summary, safety, specs, command + "\n"), None


def _render_wrapped_tool(name: str, summary: str, safety: str, specs: list[str], body: str) -> str:
    header = _header_lines(name, summary, safety, specs, _build_example(name, _required_flags(specs)))
    script = "\n".join(header) + "\n\nset -euo pipefail\n"
    script += 'if [[ "${TK_DRY_RUN:-0}" == "1" ]]; then\n'
    script += "  printf '%s\\n' '{\"dry_run\":true}'\n"
    script += "  exit 0\n"
    script += "fi\n"
    script += body
    if not script.endswith("\n"):
        script += "\n"
    return script


def _header_lines(name: str, summary: str, safety: str, specs: list[str], example: str) -> list[str]:
    lines = [
        "#!/usr/bin/env bash",
        f"# @tk-name: {name}",
        f"# @tk-summary: {summary}",
        f"# @tk-safety: {safety}",
    ]
    for spec in specs:
        lines.append(f"# @tk-arg: {spec}")
    lines.append("# @tk-output: json | Compact JSON result")
    lines.append(f"# @tk-example: {example}")
    lines.append("# @tk-verified: none")
    return lines


def _has_tool_header(text: str) -> bool:
    for line in text.splitlines()[:80]:
        stripped = line.strip()
        if stripped.startswith("#!") or stripped == "":
            continue
        if stripped.startswith("#") and "@tk-name:" in stripped:
            return True
        if not stripped.startswith("#"):
            return False
    return False


def _strip_shebang(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("#!"):
        return "\n".join(lines[1:])
    return text


def _overlay_tool_header(text: str, name: str, summary: str, safety: str, specs: list[str]) -> str:
    text = _replace_or_insert(text, "@tk-name", name)
    text = _replace_or_insert(text, "@tk-summary", summary)
    text = _replace_or_insert(text, "@tk-safety", safety)
    text = _replace_or_insert(text, "@tk-verified", "none")
    if specs:
        text = _replace_arg_block(text, specs)
        example = _build_example(name, _required_flags(specs))
        text = _replace_or_insert(text, "@tk-example", example)
    elif not _example_matches(text, name):
        text = _replace_or_insert(text, "@tk-example", _build_example(name, []))
    if "@tk-output:" not in text:
        text = _replace_or_insert(text, "@tk-output", "json | Compact JSON result")
    if not text.endswith("\n"):
        text += "\n"
    return text


def _replace_or_insert(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"(?m)^#\s*{re.escape(key)}\s*:.*$")
    line = f"# {key}: {value}"
    if pattern.search(text):
        return pattern.sub(line, text, count=1)
    lines = text.splitlines()
    insert_at = 1 if lines and lines[0].startswith("#!") else 0
    lines.insert(insert_at, line)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def _replace_arg_block(text: str, specs: list[str]) -> str:
    lines = text.splitlines()
    kept = [line for line in lines if not line.strip().startswith("# @tk-arg:")]
    arg_lines = [f"# @tk-arg: {spec}" for spec in specs]
    insert_at = 0
    for index, line in enumerate(kept):
        if line.strip().startswith("# @tk-safety:"):
            insert_at = index + 1
            break
    else:
        insert_at = 1 if kept and kept[0].startswith("#!") else 0
    kept[insert_at:insert_at] = arg_lines
    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(kept) + suffix


def _example_matches(text: str, name: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") and "@tk-example:" in stripped:
            example = stripped.split(":", 1)[1].strip()
            return example == f"tk run {name}" or example.startswith(f"tk run {name} ")
    return False


def _normalize_arg_specs(args_spec: list[str] | None) -> list[str] | None:
    if args_spec is None:
        return []
    if not isinstance(args_spec, list):
        return None
    normalized: list[str] = []
    for spec in args_spec:
        if not isinstance(spec, str):
            return None
        text = spec.strip()
        if text.startswith("@tk-arg:"):
            text = text.split(":", 1)[1].strip()
        parts = [part.strip() for part in text.split("|")]
        if len(parts) < 4:
            return None
        flag, required, typ = parts[0], parts[1], parts[2]
        description = "|".join(parts[3:]).strip()
        if not re.fullmatch(r"--[A-Za-z0-9][A-Za-z0-9-]*", flag):
            return None
        if required not in {"required", "optional"} or typ not in _ARG_TYPES or not description:
            return None
        normalized.append(f"{flag} | {required} | {typ} | {description}")
    return normalized


def _required_flags(specs: list[str]) -> list[tuple[str, str]]:
    flags: list[tuple[str, str]] = []
    for spec in specs:
        flag, required, typ, _desc = [part.strip() for part in spec.split("|", 3)]
        if required == "required":
            flags.append((flag, _DUMMY[typ]))
    return flags


def _flags_from_chain_args(args: list[dict]) -> list[tuple[str, str]]:
    flags: list[tuple[str, str]] = []
    for arg in args:
        required = arg.get("required", True)
        if required is False or required == "optional":
            continue
        flag = str(arg.get("flag") or arg.get("name"))
        typ = str(arg.get("type") or "string")
        flags.append((flag, _DUMMY.get(typ, "example")))
    return flags


def _build_example(name: str, flags: list[tuple[str, str]]) -> str:
    parts = [f"tk run {name}"]
    for flag, value in flags:
        parts.append(flag)
        parts.append(value)
    return " ".join(parts)


def _tool_dest(root: Path, name: str) -> Path:
    namespace, separator, rest = name.partition(".")
    if separator and rest:
        return root / "tools" / namespace / rest
    return root / "tools" / name


def _commit_draft(
    root: Path,
    dest: Path,
    text: str,
    *,
    force: bool,
    executable: bool,
    success: dict,
    saved_event: str,
    saved_payload: dict,
    catalog_root: Path,
) -> tuple[int, str, str]:
    if dest.exists() and not force:
        return _failure("already_exists", f"{dest.name} already exists", "pass force=True to replace it")
    previous = dest.read_bytes() if dest.exists() and dest.is_file() else None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    if executable:
        dest.chmod(0o755)
    check = _check_item(root, dest)
    if not check.get("ok"):
        _quarantine(root, dest.name, text)
        if previous is None:
            dest.unlink(missing_ok=True)
            _prune_empty_dirs(dest.parent, catalog_root)
        else:
            dest.write_bytes(previous)
            if executable:
                dest.chmod(0o755)
        errors = check.get("errors") or ["validation failed"]
        why = "; ".join(str(err) for err in errors)
        return _failure("check_failed", why, "tk check")
    log_event(root, saved_event, saved_payload)
    return 0, json.dumps(success, separators=(",", ":")), ""


def _quarantine(root: Path, filename: str, text: str) -> None:
    try:
        quarantine = root / "state" / "quarantine"
        quarantine.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename) or "draft"
        (quarantine / f"{safe}.{stamp}").write_text(text, encoding="utf-8")
    except Exception:
        return


def _prune_empty_dirs(start: Path, stop: Path) -> None:
    current = start
    stop_resolved = stop.resolve()
    while current.exists():
        if current.resolve() == stop_resolved:
            return
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _check_item(root: Path, name_or_path: str | Path) -> dict:
    catalog_result = _catalog_call("check_item", root, name_or_path)
    if isinstance(catalog_result, dict) and "ok" in catalog_result:
        errors = catalog_result.get("errors")
        if not isinstance(errors, list):
            catalog_result = dict(catalog_result)
            catalog_result["errors"] = [] if catalog_result.get("ok") else ["validation failed"]
        return catalog_result
    return _fallback_check_item(root, name_or_path)


def _discover(root: Path) -> dict[str, dict]:
    fallback = _fallback_discover(root)
    catalog_result = _catalog_call("discover_catalog", root)
    if isinstance(catalog_result, dict) and (catalog_result or not fallback):
        return catalog_result
    return fallback


def _catalog_call(fn_name: str, *args):
    try:
        import lib.catalog as catalog
    except Exception:
        return None
    fn = getattr(catalog, fn_name, None)
    if not callable(fn):
        return None
    try:
        return fn(*args)
    except Exception:
        return None


def _fallback_check_item(root: Path, name_or_path: str | Path) -> dict:
    path = _resolve_check_path(root, name_or_path)
    if path is None or not path.is_file():
        target = str(name_or_path)
        return {"name": target, "ok": False, "errors": [f"file not found: {target}"]}
    if path.suffix == ".json":
        return _check_chain_file(root, path)
    return _check_tool_file(root, path)


def _resolve_check_path(root: Path, name_or_path: str | Path) -> Path | None:
    candidate = Path(name_or_path)
    if candidate.is_file():
        return candidate
    rooted = root / candidate
    if rooted.is_file():
        return rooted
    if isinstance(name_or_path, str) and _NAME_RE.fullmatch(name_or_path):
        tool = _tool_dest(root, name_or_path)
        if tool.is_file():
            return tool
        chain = root / "chains" / f"{name_or_path}.json"
        if chain.is_file():
            return chain
    return candidate if candidate.exists() else None


def _check_tool_file(root: Path, path: Path) -> dict:
    del root
    name = path.name
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"name": name, "ok": False, "errors": [str(exc)]}
    header = _parse_tool_header(text, path)
    name = header.get("name") or name
    for field in ("name", "summary", "safety", "output", "example", "verified"):
        if not header.get(field):
            errors.append(f"missing {field}")
    if header.get("safety") and header["safety"] not in _SAFETY:
        errors.append("safety must be read-only, mutating, or destructive")
    example = header.get("example") or ""
    if example and not (example == f"tk run {name}" or example.startswith(f"tk run {name} ")):
        errors.append("example must start with tk run <name>")
    for arg in header.get("args") or []:
        if arg.get("required") and not _example_has_flag(example, arg["flag"]):
            errors.append(f"example missing {arg['flag']}")
    if not os.access(path, os.X_OK):
        errors.append("tool is not executable")
    syntax_error = _syntax_error(path, text)
    if syntax_error:
        errors.append(syntax_error)
    if not errors:
        dry_error = _dry_run_error(path, header.get("args") or [])
        if dry_error:
            errors.append(dry_error)
    return {"name": name, "ok": not errors, "errors": errors}


def _check_chain_file(root: Path, path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"name": path.stem, "ok": False, "errors": [str(exc)]}
    if not isinstance(document, dict):
        return {"name": path.stem, "ok": False, "errors": ["chain file must be a JSON object"]}
    name = document.get("name") or path.stem
    errors: list[str] = []
    for field in ("name", "summary", "safety", "output", "example", "verified"):
        if not document.get(field):
            errors.append(f"missing {field}")
    if document.get("safety") and document.get("safety") not in _SAFETY:
        errors.append("safety must be read-only, mutating, or destructive")
    example = str(document.get("example") or "")
    if example and not (example == f"tk run {name}" or example.startswith(f"tk run {name} ")):
        errors.append("example must start with tk run <name>")
    for arg in document.get("args") or []:
        if isinstance(arg, dict) and arg.get("required", True) not in {False, "optional"}:
            flag = str(arg.get("flag") or arg.get("name") or "")
            if flag and not _example_has_flag(example, flag):
                errors.append(f"example missing {flag}")
    steps = document.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("chain has no steps")
    else:
        known = set(_discover(root))
        known.discard(name)
        for index, step in enumerate(steps):
            tool = step.get("tool") if isinstance(step, dict) else None
            if not isinstance(tool, str) or not tool:
                errors.append(f"step {index} missing tool")
            elif tool not in known:
                errors.append(f"unknown tool: {tool}")
    return {"name": str(name), "ok": not errors, "errors": errors}


def _example_has_flag(example: str, flag: str) -> bool:
    return re.search(rf"(?:^|\s){re.escape(flag)}(?:\s|=|$)", example) is not None


def _syntax_error(path: Path, text: str) -> str | None:
    first = text.splitlines()[0] if text.splitlines() else ""
    if not first.startswith("#!"):
        return "missing shebang"
    if "python" in first:
        try:
            with tempfile.NamedTemporaryFile(suffix=".pyc") as compiled:
                py_compile.compile(str(path), cfile=compiled.name, doraise=True)
        except py_compile.PyCompileError as exc:
            return f"python syntax: {exc.msg}"
        return None
    shell = "bash" if "bash" in first else "sh"
    result = subprocess.run([shell, "-n", str(path)], capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "syntax error").strip().splitlines()
        return detail[-1] if detail else "syntax error"
    return None


def _dry_run_error(path: Path, args: list[dict]) -> str | None:
    env = os.environ.copy()
    env["TK_DRY_RUN"] = "1"
    for arg in args:
        if arg.get("required"):
            env[arg["env_var"]] = _DUMMY.get(arg.get("type"), "example")
    try:
        result = subprocess.run(
            [str(path)],
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"dry-run failed: {exc}"
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        return f"dry-run exited {result.returncode}{suffix}"
    try:
        json.loads(result.stdout)
    except json.JSONDecodeError:
        return "dry-run stdout is not valid JSON"
    return None


def _fallback_discover(root: Path) -> dict[str, dict]:
    items: dict[str, dict] = {}
    tools = root / "tools"
    if tools.is_dir():
        for path in tools.rglob("*"):
            if not path.is_file() or _hidden(path, tools):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            header = _parse_tool_header(text, path)
            name = header.get("name") or path.stem
            header["kind"] = "tool"
            items[name] = header
    chains = root / "chains"
    if chains.is_dir():
        for path in sorted(chains.glob("*.json")):
            if path.name.startswith("."):
                continue
            item = _chain_item(path)
            if item:
                items[item["name"]] = item
    return dict(sorted(items.items()))


def _hidden(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    return any(part.startswith(".") or part.startswith("__") for part in relative.parts)


def _parse_tool_header(text: str, path: Path) -> dict:
    fields = {
        "kind": "tool",
        "name": "",
        "summary": "",
        "safety": "",
        "output": "",
        "example": "",
        "verified": "",
        "path": str(path.resolve()),
        "args": [],
    }
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#!"):
            continue
        if stripped == "":
            if fields["name"]:
                break
            continue
        if not stripped.startswith("#"):
            break
        body = stripped[1:].strip()
        if not body.startswith("@tk-"):
            continue
        key, _, value = body.partition(":")
        value = value.strip()
        key = key.strip()
        if key == "@tk-arg":
            parsed = _parse_arg(value)
            if parsed:
                fields["args"].append(parsed)
            continue
        mapped = {
            "@tk-name": "name",
            "@tk-summary": "summary",
            "@tk-safety": "safety",
            "@tk-output": "output",
            "@tk-example": "example",
            "@tk-verified": "verified",
        }.get(key)
        if mapped:
            fields[mapped] = value
    return fields


def _parse_arg(value: str) -> dict | None:
    parts = [part.strip() for part in value.split("|")]
    if len(parts) < 4:
        return None
    flag, required, typ = parts[0], parts[1], parts[2]
    description = "|".join(parts[3:]).strip()
    if not flag.startswith("--") or required not in {"required", "optional"} or typ not in _ARG_TYPES:
        return None
    default = None
    match = re.search(r"\(default:\s*([^)]+)\)", description)
    if match:
        default = match.group(1).strip()
    env_var = "TK_ARG_" + flag[2:].replace("-", "_").upper()
    return {
        "flag": flag,
        "env_var": env_var,
        "required": required == "required",
        "type": typ,
        "description": description,
        "default": default,
    }


def _chain_item(path: Path) -> dict | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {
            "kind": "chain",
            "name": path.stem,
            "summary": "",
            "safety": "",
            "args": [],
            "steps": [],
            "output": "",
            "example": "",
            "verified": "",
            "path": str(path.resolve()),
        }
    if not isinstance(document, dict):
        return None
    return {
        "kind": "chain",
        "name": document.get("name") or path.stem,
        "summary": document.get("summary") or "",
        "safety": document.get("safety") or "",
        "args": document.get("args") or [],
        "steps": document.get("steps") or [],
        "output": document.get("output") or "",
        "example": document.get("example") or "",
        "verified": document.get("verified") or "",
        "path": str(path.resolve()),
    }


def _read_events(path: Path) -> list[dict]:
    events: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return events
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            events.append(record)
    return events


def _summarize_events(events: list[dict]) -> tuple[set[str], dict[str, list[str]], list[dict]]:
    used: set[str] = set()
    failed: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for record in events:
        event = record.get("event")
        name = _event_name(record)
        if event in _USAGE_EVENTS and name:
            used.add(name)
        elif event in _FAIL_EVENTS and name:
            why = record.get("why") or record.get("error")
            message = f"run_error: {why}" if why else "run_error"
            failed.setdefault(name, [])
            if message not in failed[name]:
                failed[name].append(message)
        elif event in _MISS_EVENTS:
            query = record.get("query") or record.get("q") or ""
            if isinstance(query, str) and query.strip():
                counts[query] = counts.get(query, 0) + 1
    misses = [{"query": query, "count": counts[query]} for query in sorted(counts, key=lambda item: (-counts[item], item))]
    return used, failed, misses


def _event_name(record: dict) -> str | None:
    for key in ("name", "tool", "item"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _is_unverified(verified: object) -> bool:
    if not isinstance(verified, str):
        return True
    return verified.strip().lower() in {"", "none", "unverified", "null"}


def _promote_tool(path: Path, today: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    updated, count = _VERIFIED_RE.subn(f"# @tk-verified: {today}", text, count=1)
    if count == 0 or updated == text:
        return False
    try:
        path.write_text(updated, encoding="utf-8")
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        return False
    return True


def _overlap_candidates(catalog: dict[str, dict]) -> list[dict]:
    names = sorted(catalog)
    tokens = {name: _tokens(name, str(catalog[name].get("summary") or "")) for name in names}
    pairs: list[dict] = []
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            shared = tokens[left] & tokens[right]
            if len(shared) < 2:
                continue
            union = tokens[left] | tokens[right]
            score = len(shared) / len(union) if union else 0
            pairs.append(
                {
                    "tools": [left, right],
                    "shared": sorted(shared),
                    "score": round(score, 3),
                }
            )
    return pairs


def _tokens(name: str, summary: str) -> set[str]:
    raw = set(re.findall(r"[a-z0-9]+", f"{name} {summary}".lower()))
    return {token for token in raw if len(token) >= 3 and token not in _STOPWORDS}
