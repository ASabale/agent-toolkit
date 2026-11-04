"""Telemetry, tool/chain creation, and catalog evolution.

Public seam (CODING_STANDARDS.md §2.3):
- log_event: append-only telemetry; never raises
- save_tool / save_chain: write a draft, validate with check_item, roll back on failure
- evolve_report: promote verified-passing read-only tools and chains and summarize friction
- prune_tools: archive tools or chains, refusing to break a live chain
"""

from __future__ import annotations

import json
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
            dest = root / "state" / "archive" / f"{stamp}-{name}"
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
