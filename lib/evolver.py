"""Telemetry, tool/chain creation, and catalog evolution.

Public seam (CODING_STANDARDS.md §2.3):
- log_event: append-only telemetry; never raises
- save_tool / save_chain: write a draft, validate with check_item, roll back on failure
- evolve_report: promote verified-passing read-only tools and chains and summarize friction
- prune_tools: archive tools or chains, refusing to break a live chain
"""

from __future__ import annotations

import json
import os
import re
import shlex
import stat
from datetime import date, datetime, timezone
from pathlib import Path

_SAFETY = {"read-only", "mutating", "destructive"}
_ARG_TYPES = {"string", "int", "float", "bool"}
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9][A-Za-z0-9_-]*)*$")
_VERIFIED_RE = re.compile(r"(?m)^#\s*@tk-verified\s*:.*$")
_USAGE_EVENTS = {"run", "run_ok", "tool_run", "chain_run"}
_ERROR_EVENTS = {"run_error", "error"}
_OPTIONAL_ARG_RE = re.compile(r"\$\{TK_ARG_([A-Z][A-Z0-9_]*):-([^}]*)\}")
_BARE_ARG_RE = re.compile(r"\bTK_ARG_([A-Z][A-Z0-9_]*)\b")
_MISS_EVENTS = {"search_miss", "miss"}
_FAIL_EVENTS = {"run_error", "error"}
_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "into",
    "check",
    "count",
    "digest",
    "file",
    "files",
    "get",
    "info",
    "json",
    "list",
    "only",
    "path",
    "per",
    "repo",
    "run",
    "status",
    "that",
    "the",
    "this",
    "tool",
    "tools",
    "tree",
    "via",
    "with",
    "when",
    "working",
    "your",
}
_DUMMY = {"string": "example", "int": "1", "float": "1", "bool": "true"}


def _telemetry_disabled() -> bool:
    return os.environ.get("TK_NO_TELEMETRY", "").strip().lower() in {"1", "true", "yes"}


def _state_dir(root: Path) -> Path:
    raw = os.environ.get("TK_STATE_DIR")
    if raw is not None and raw.strip():
        return Path(raw)
    return root / "state"


def log_event(root_dir: Path, event_type: str, payload: dict) -> None:
    """Append one JSONL telemetry record. Swallows every I/O or encoding failure."""
    if _telemetry_disabled():
        return
    try:
        state = _state_dir(Path(root_dir))
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
        specs = _specs_with_inferred(from_cmd, file_path, specs)
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
            already_exists_fix=_save_tool_force_hint(name, summary, safety, from_cmd, file_path, args_spec),
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
            already_exists_fix=_save_chain_force_hint(name, summary, safety, steps, chain_args),
        )
    except Exception as exc:
        return _failure("internal_error", str(exc), "tk check")


def prune_tools(root_dir: Path, names: list[str], dry_run: bool = False) -> tuple[int, str, str]:
    """Archive named tools or chains. Refuse when a kept chain still references a target."""
    try:
        root = Path(root_dir)
        catalog = _discover(root)
        ordered: list[str] = []
        seen: set[str] = set()
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            if name not in catalog:
                return 2, "", _error_json("not_found", f"{name} is not in the catalog", "tk find")
            ordered.append(name)
        blockers: list[tuple[str, str]] = []
        for item in catalog.values():
            if item.get("kind") != "chain" or item.get("name") in seen:
                continue
            chain_name = str(item.get("name") or "")
            for step in item.get("steps") or []:
                tool = step.get("tool") if isinstance(step, dict) else None
                if isinstance(tool, str) and tool in seen:
                    blockers.append((tool, chain_name))
        if blockers:
            why = "; ".join(f"{tool} is used by {chain}" for tool, chain in blockers)
            chains = sorted({chain for _, chain in blockers})
            fix = "tk prune " + " ".join([*chains, *ordered])
            return 2, "", _error_json("tool_in_use_by_chain", why, fix)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        pruned: list[str] = []
        archived: list[str] = []
        for name in ordered:
            src = Path(str(catalog[name].get("path") or ""))
            dest = _state_dir(root) / "archive" / f"{stamp}-{name}"
            archived.append(str(dest))
            pruned.append(name)
            if dry_run:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dest)
            if catalog[name].get("kind") == "tool":
                _prune_empty_dirs(src.parent, root / "tools")
            log_event(root, "tool_pruned", {"name": name, "archived_to": str(dest), "dry_run": False})
        payload = {"pruned": pruned, "archived_to": archived, "dry_run": bool(dry_run)}
        return 0, json.dumps(payload, separators=(",", ":")), ""
    except Exception as exc:
        return _failure("internal_error", str(exc), "tk check")


def evolve_report(root_dir: Path, auto_promote: bool = True) -> dict:
    """Promote unverified read-only tools and chains that pass check_item."""
    empty = {
        "promoted": [],
        "search_misses": [],
        "failing_tools": [],
        "unused_tools": [],
        "overlap_candidates": [],
        "chain_candidates": [],
    }
    try:
        root = Path(root_dir)
        catalog = _discover(root)
        events = _read_events(_state_dir(root) / "events.jsonl")
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
                and item.get("safety") == "read-only"
                and _is_unverified(item.get("verified"))
            ):
                path = Path(str(item.get("path") or ""))
                kind = item.get("kind")
                if kind == "tool" and path.is_file() and _promote_tool(path, today):
                    promoted.append(name)
                elif kind == "chain" and path.is_file() and _promote_chain(path, today):
                    promoted.append(name)
        unused = sorted(name for name in catalog if name not in used)
        return {
            "promoted": promoted,
            "search_misses": misses,
            "failing_tools": failing,
            "unused_tools": unused,
            "overlap_candidates": _overlap_candidates(catalog),
            "chain_candidates": _chain_candidates(catalog, events),
        }
    except Exception:
        return empty


def _quoted_cli(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def _arg_cli_parts(specs: list[str] | None) -> list[str]:
    parts: list[str] = []
    for spec in specs or []:
        parts.extend(["--arg", spec])
    return parts


def _chain_arg_specs(args: list[dict] | None) -> list[str]:
    specs: list[str] = []
    for arg in args or []:
        if not isinstance(arg, dict):
            continue
        flag = arg.get("flag") or arg.get("name")
        if not isinstance(flag, str) or not flag.startswith("--"):
            continue
        required = "optional" if arg.get("required") in {False, "optional"} else "required"
        typ = str(arg.get("type") or "string")
        description = str(arg.get("description") or flag.lstrip("-"))
        specs.append(f"{flag} | {required} | {typ} | {description}")
    return specs


def _save_tool_force_hint(
    name: str,
    summary: str,
    safety: str,
    from_cmd: str | None,
    file_path: str | None,
    args_spec: list[str] | None,
) -> str:
    parts = ["tk", "save", name, "--summary", summary, "--safety", safety]
    if file_path:
        parts.extend(["--file", file_path])
    elif from_cmd:
        parts.extend(["--from-cmd", from_cmd])
    parts.extend(_arg_cli_parts(args_spec))
    parts.append("--force")
    return _quoted_cli(parts)


def _save_chain_force_hint(
    name: str,
    summary: str,
    safety: str,
    steps: list[dict],
    args: list[dict] | None,
) -> str:
    parts = [
        "tk",
        "chain",
        "save",
        name,
        "--summary",
        summary,
        "--safety",
        safety,
        "--steps",
        json.dumps(steps, separators=(",", ":")),
    ]
    parts.extend(_arg_cli_parts(_chain_arg_specs(args)))
    parts.append("--force")
    return _quoted_cli(parts)


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


def _spec_env(spec: str) -> str:
    flag = spec.split("|", 1)[0].strip()
    return "TK_ARG_" + flag.lstrip("-").replace("-", "_").upper()


def _header_arg_specs(text: str) -> list[str]:
    raw: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# @tk-arg:"):
            raw.append(stripped.split(":", 1)[1].strip())
    normalized = _normalize_arg_specs(raw)
    return normalized or []


def _infer_arg_specs(script_text: str, declared: set[str]) -> list[str]:
    defaults: dict[str, str] = {}
    order: list[str] = []
    for line in script_text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for match in _OPTIONAL_ARG_RE.finditer(line):
            name, default = match.group(1), match.group(2)
            if name not in defaults or (default and not defaults[name]):
                defaults[name] = default
        for match in _BARE_ARG_RE.finditer(line):
            name = match.group(1)
            if name not in order:
                order.append(name)
    specs: list[str] = []
    for name in order:
        if f"TK_ARG_{name}" in declared:
            continue
        kebab = name.lower().replace("_", "-")
        default = defaults.get(name) or ""
        if default:
            specs.append(
                f"--{kebab} | optional | string | Parameter {kebab} (default: {default})"
            )
        else:
            specs.append(f"--{kebab} | required | string | Parameter {kebab}")
    return specs


def _specs_with_inferred(
    from_cmd: str | None,
    file_path: str | None,
    specs: list[str],
) -> list[str]:
    scan_text = ""
    header_specs: list[str] = []
    if isinstance(from_cmd, str) and from_cmd.strip():
        scan_text = from_cmd
    elif file_path:
        try:
            scan_text = Path(file_path).read_text(encoding="utf-8")
        except OSError:
            return specs
        header_specs = _header_arg_specs(scan_text)
    declared = {_spec_env(spec) for spec in specs}
    declared.update(_spec_env(spec) for spec in header_specs)
    inferred = _infer_arg_specs(scan_text, declared)
    user_envs = {_spec_env(spec) for spec in specs}
    preserved = [spec for spec in header_specs if _spec_env(spec) not in user_envs]
    return preserved + list(specs) + inferred


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
        text = "" if value is None else str(value)
        parts.append(shlex.quote(text) if any(ch.isspace() for ch in text) else text)
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
    already_exists_fix: str,
) -> tuple[int, str, str]:
    if dest.exists() and not force:
        return _failure("already_exists", f"{dest.name} already exists", already_exists_fix)
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
        quarantine = _state_dir(root) / "quarantine"
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
    try:
        from lib.catalog import check_item

        catalog_result = check_item(root, name_or_path)
    except Exception:
        catalog_result = None
    if isinstance(catalog_result, dict) and "ok" in catalog_result:
        errors = catalog_result.get("errors")
        if not isinstance(errors, list):
            catalog_result = dict(catalog_result)
            catalog_result["errors"] = [] if catalog_result.get("ok") else ["validation failed"]
        return catalog_result
    return {"name": str(name_or_path), "ok": False, "errors": ["validation failed"]}


def _discover(root: Path) -> dict[str, dict]:
    try:
        from lib.catalog import discover_catalog

        result = discover_catalog(root)
    except Exception:
        return {}
    return result if isinstance(result, dict) else {}


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


def _promote_chain(path: Path, today: str) -> bool:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(document, dict):
        return False
    document["verified"] = today
    try:
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


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
            if _chain_composes(catalog, left, right):
                continue
            union = tokens[left] | tokens[right]
            score = len(shared) / len(union) if union else 0
            same_namespace = left.split(".", 1)[0] == right.split(".", 1)[0]
            if score < (0.35 if same_namespace else 0.50):
                continue
            pairs.append(
                {
                    "tools": [left, right],
                    "shared": sorted(shared),
                    "score": round(score, 3),
                }
            )
    return pairs


def _chain_candidates(catalog: dict[str, dict], events: list[dict]) -> list[dict]:
    """Repeated consecutive tool pairs that no chain already starts with."""
    sequence: list[str | None] = []
    for record in events:
        if record.get("event") in _ERROR_EVENTS:
            sequence.append(None)
            continue
        if record.get("event") not in _USAGE_EVENTS:
            continue
        name = _event_name(record)
        if name:
            sequence.append(name)
    counts: dict[tuple[str, str], int] = {}
    for tool_a, tool_b in zip(sequence, sequence[1:]):
        if not tool_a or not tool_b or tool_a == tool_b:
            continue
        left = catalog.get(tool_a)
        right = catalog.get(tool_b)
        if not isinstance(left, dict) or not isinstance(right, dict):
            continue
        if left.get("kind") == "chain" or right.get("kind") == "chain":
            continue
        counts[(tool_a, tool_b)] = counts.get((tool_a, tool_b), 0) + 1
    covered = _chain_prefixes(catalog)
    candidates: list[dict] = []
    for (tool_a, tool_b), count in counts.items():
        if count < 2 or (tool_a, tool_b) in covered:
            continue
        candidates.append(
            {
                "steps": [tool_a, tool_b],
                "count": count,
                "suggested_chain": (
                    f"tk chain save <name> --summary '...' --steps '{tool_a} {tool_b}'"
                ),
            }
        )
    candidates.sort(key=lambda row: (-row["count"], row["steps"][0], row["steps"][1]))
    return candidates


def _chain_prefixes(catalog: dict[str, dict]) -> set[tuple[str, str]]:
    prefixes: set[tuple[str, str]] = set()
    for item in catalog.values():
        if item.get("kind") != "chain":
            continue
        tools: list[str] = []
        for step in (item.get("steps") or [])[:2]:
            tool = step.get("tool") if isinstance(step, dict) else step
            if isinstance(tool, str) and tool:
                tools.append(tool)
        if len(tools) == 2:
            prefixes.add((tools[0], tools[1]))
    return prefixes


def _chain_composes(catalog: dict[str, dict], left: str, right: str) -> bool:
    """A chain that lists the other item in steps is composition, not a duplicate."""
    for chain_name, other in ((left, right), (right, left)):
        item = catalog.get(chain_name) or {}
        if item.get("kind") != "chain":
            continue
        for step in item.get("steps") or []:
            tool = step.get("tool") if isinstance(step, dict) else step
            if tool == other:
                return True
    return False


def _tokens(name: str, summary: str) -> set[str]:
    raw = set(re.findall(r"[a-z0-9]+", f"{name} {summary}".lower()))
    return {token for token in raw if len(token) >= 3 and token not in _STOPWORDS}
