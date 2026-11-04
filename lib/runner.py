"""Validate flags, run a tool, and run a chain.

stdout is compact JSON. Failures are single-line JSON on stderr
(``error``, ``why``, ``fix``) and never an unhandled traceback.
"""

from __future__ import annotations

import json
import math
import os
import re
import shlex
import subprocess
from pathlib import Path

from lib.evolver import log_event

_INPUT_REF = re.compile(r"^\$input\.([A-Za-z0-9_-]+)$")
_PREV_REF = re.compile(r"^\$prev\.(.+)$")
_STEP_REF = re.compile(r"^\$step\[(\d+)\]\.(.+)$")
_PATH_PART = re.compile(r"[^.\[\]]+|\[\d+\]")
_TRUE = {"true", "1", "yes"}
_FALSE = {"false", "0", "no"}


def _compact(payload: object) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _env_var(flag: str) -> str:
    name = flag[2:] if flag.startswith("--") else flag
    return "TK_ARG_" + name.replace("-", "_").upper()


def _bool_value(raw: str) -> str | None:
    token = raw.strip().lower()
    if token in _TRUE:
        return "true"
    if token in _FALSE:
        return "false"
    return None


def _valid_int(raw: str) -> bool:
    if any(ch in raw for ch in ".eE"):
        return False
    try:
        int(raw)
    except ValueError:
        return False
    return True


def _valid_float(raw: str) -> bool:
    try:
        number = float(raw)
    except ValueError:
        return False
    return math.isfinite(number)


def _fix_command(item: dict, supplied: dict[str, str]) -> str:
    name = item.get("name") or ""
    parts = [f"tk run {name}".rstrip()]
    for arg in item.get("args") or []:
        flag = arg["flag"]
        if flag not in supplied:
            continue
        parts.append(flag)
        parts.append(shlex.quote(supplied[flag]))
    for arg in item.get("args") or []:
        flag = arg["flag"]
        if arg.get("required") and flag not in supplied:
            parts.append(flag)
            parts.append("<value>")
    return " ".join(parts)


def _example(item: dict) -> str:
    return item.get("example") or "tk check"


def parse_cli_flags(argv: list[str]) -> tuple[dict[str, str], bool, list[str]]:
    """Extract ``--dry-run``, ``--flag`` values, and stray positional tokens."""
    flags: dict[str, str] = {}
    positional: list[str] = []
    dry_run = False
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--dry-run":
            dry_run = True
            index += 1
            continue
        if token.startswith("--dry-run="):
            value = token.split("=", 1)[1].strip().lower()
            dry_run = value not in {"0", "false", "no", "off"}
            index += 1
            continue
        if token.startswith("--"):
            if "=" in token:
                name, value = token.split("=", 1)
                flags[name] = value
                index += 1
                continue
            if index + 1 < len(argv) and not argv[index + 1].startswith("--"):
                flags[token] = argv[index + 1]
                index += 2
                continue
            flags[token] = "true"
            index += 1
            continue
        positional.append(token)
        index += 1
    return flags, dry_run, positional


def validate_and_build_env(
    item: dict,
    flags: dict[str, str],
    positional: list[str],
    dry_run: bool,
) -> tuple[bool, dict[str, str], dict | None]:
    """Reject bad argv and build ``TK_DRY_RUN`` / ``TK_ARG_*`` on success."""
    if positional:
        rendered = " ".join(positional)
        return False, {}, {
            "error": "positional_arguments_forbidden",
            "why": f"positional arguments are forbidden: {rendered}",
            "fix": _example(item),
        }

    declared = {arg["flag"]: arg for arg in (item.get("args") or [])}
    unknown = sorted(flag for flag in flags if flag not in declared)
    if unknown:
        return False, {}, {
            "error": "unknown_flag",
            "why": "unknown flags: " + ", ".join(unknown),
            "fix": _example(item),
        }

    normalized: dict[str, str] = {}
    type_errors: list[dict] = []
    for arg in item.get("args") or []:
        flag = arg["flag"]
        if flag not in flags:
            continue
        raw = flags[flag]
        kind = arg.get("type") or "string"
        if kind == "bool":
            value = _bool_value(raw)
            if value is None:
                type_errors.append({
                    "error": "invalid_type",
                    "why": f"{flag} expects bool, got {raw!r}",
                    "fix": _example(item),
                })
                continue
            normalized[flag] = value
        elif kind == "int":
            if not _valid_int(raw):
                type_errors.append({
                    "error": "invalid_type",
                    "why": f"{flag} expects int, got {raw!r}",
                    "fix": _example(item),
                })
                continue
            normalized[flag] = raw
        elif kind == "float":
            if not _valid_float(raw):
                type_errors.append({
                    "error": "invalid_type",
                    "why": f"{flag} expects float, got {raw!r}",
                    "fix": _example(item),
                })
                continue
            normalized[flag] = raw
        else:
            normalized[flag] = raw

    missing = [
        arg["flag"]
        for arg in (item.get("args") or [])
        if arg.get("required") and arg["flag"] not in flags
    ]
    if missing:
        return False, {}, {
            "error": "missing_required",
            "why": "missing required flags: " + ", ".join(missing),
            "fix": _fix_command(item, normalized),
        }
    if type_errors:
        return False, {}, type_errors[0]

    env: dict[str, str] = {"TK_DRY_RUN": "1" if dry_run else "0"}
    for arg in item.get("args") or []:
        flag = arg["flag"]
        key = arg.get("env_var") or _env_var(flag)
        if flag in normalized:
            env[key] = normalized[flag]
        elif not arg.get("required") and arg.get("default") is not None:
            env[key] = str(arg["default"])
    return True, env, None


def _failure(code: int, payload: dict) -> tuple[int, str, str]:
    return code, "", _compact(payload)


def _why_from_stderr(stderr: str) -> str:
    text = (stderr or "").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("why"), str):
        return payload["why"]
    return text


def _record_run(root_dir: Path, item: dict, code: int, stderr: str, dry_run: bool) -> None:
    """Log real executions only. Dry-run must not count as use."""
    if dry_run:
        return
    payload = {
        "name": item.get("name", ""),
        "kind": item.get("kind", "tool"),
    }
    if code == 0:
        log_event(root_dir, "run_ok", payload)
        return
    payload["why"] = _why_from_stderr(stderr)
    log_event(root_dir, "run_error", payload)


def run_tool(
    root_dir: Path,
    item: dict,
    flags: dict[str, str],
    positional: list[str] | None = None,
    dry_run: bool = False,
    stdin_data: str | None = None,
) -> tuple[int, str, str]:
    """Validate ``flags``, execute ``item['path']``, and compact JSON stdout."""
    try:
        ok, built, err = validate_and_build_env(
            item, flags, list(positional or []), dry_run
        )
        if not ok:
            return _record_and_return(
                root_dir, item, dry_run,
                _failure(1, err or {"error": "internal_error", "why": "validation failed", "fix": "tk check"}),
            )

        env = os.environ.copy()
        env.update(built)
        timeout = float(os.environ.get("TK_TIMEOUT", "60"))
        try:
            completed = subprocess.run(
                [str(item["path"])],
                input=stdin_data,
                capture_output=True,
                text=True,
                env=env,
                cwd=str(root_dir),
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return _record_and_return(
                root_dir, item, dry_run,
                _failure(
                    1,
                    {
                        "error": "tool_timeout",
                        "why": f"tool exceeded {timeout:g}s",
                        "fix": _example(item),
                    },
                ),
            )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if completed.returncode != 0:
            return _record_and_return(
                root_dir, item, dry_run,
                _failure(completed.returncode, _tool_failure(item, completed.returncode, stderr)),
            )
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            return _record_and_return(
                root_dir, item, dry_run,
                _failure(
                    1,
                    {"error": "invalid_output", "why": "stdout is not valid JSON", "fix": "tk check"},
                ),
            )
        return _record_and_return(root_dir, item, dry_run, (0, _compact(parsed), ""))
    except Exception as exc:  # noqa: BLE001 — trust invariant: no raw traceback
        return _record_and_return(
            root_dir, item, dry_run,
            _failure(1, {"error": "internal_error", "why": str(exc), "fix": "tk check"}),
        )


def _record_and_return(
    root_dir: Path,
    item: dict,
    dry_run: bool,
    result: tuple[int, str, str],
) -> tuple[int, str, str]:
    code, _stdout, stderr = result
    _record_run(root_dir, item, code, stderr, dry_run)
    return result


def _tool_failure(item: dict, code: int, stderr: str) -> dict:
    text = stderr.strip()
    if text:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and {"error", "why", "fix"} <= payload.keys():
            return payload
    return {
        "error": "tool_failed",
        "why": text or f"exit {code}",
        "fix": _example(item),
    }


def _stringify(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return _compact(value)


def _walk(data: object, path: str) -> object:
    current = data
    for part in _PATH_PART.findall(path):
        if part.startswith("["):
            if not isinstance(current, list):
                raise KeyError(path)
            current = current[int(part[1:-1])]
        else:
            if not isinstance(current, dict) or part not in current:
                raise KeyError(path)
            current = current[part]
    return current


def _bare_forms(flag: str) -> set[str]:
    bare = flag[2:] if flag.startswith("--") else flag
    return {bare, bare.replace("-", "_"), bare.replace("_", "-")}


def _resolve_expr(
    expr: str,
    chain_item: dict,
    env: dict[str, str],
    prev: object,
    steps: list[object],
) -> tuple[str | None, str | None]:
    text = expr.strip()
    input_match = _INPUT_REF.fullmatch(text)
    if input_match:
        wanted = input_match.group(1)
        for arg in chain_item.get("args") or []:
            if wanted not in _bare_forms(arg["flag"]):
                continue
            key = arg.get("env_var") or _env_var(arg["flag"])
            if key in env:
                return env[key], None
        return None, text

    prev_match = _PREV_REF.fullmatch(text)
    if prev_match:
        if prev is None:
            return None, text
        try:
            return _stringify(_walk(prev, prev_match.group(1))), None
        except (KeyError, IndexError, TypeError):
            return None, text

    step_match = _STEP_REF.fullmatch(text)
    if step_match:
        index = int(step_match.group(1))
        if index >= len(steps):
            return None, text
        try:
            return _stringify(_walk(steps[index], step_match.group(2))), None
        except (KeyError, IndexError, TypeError):
            return None, text

    return text, None


def run_chain(
    root_dir: Path,
    chain_item: dict,
    flags: dict[str, str],
    positional: list[str] | None = None,
    dry_run: bool = False,
) -> tuple[int, str, str]:
    """Validate chain flags, resolve step references, and stop on the first error."""
    try:
        ok, env, err = validate_and_build_env(
            chain_item, flags, list(positional or []), dry_run
        )
        if not ok:
            return _record_and_return(
                root_dir, chain_item, dry_run,
                _failure(1, err or {"error": "internal_error", "why": "validation failed", "fix": "tk check"}),
            )

        steps = chain_item.get("steps") or []
        if not steps:
            return _record_and_return(
                root_dir, chain_item, dry_run,
                _failure(
                    1,
                    {"error": "invalid_chain", "why": "chain has no steps", "fix": _example(chain_item)},
                ),
            )

        from lib.catalog import discover_catalog

        catalog = discover_catalog(root_dir)
        prev: object = None
        outputs: list[object] = []
        last_stdout = ""
        for step in steps:
            tool_name = step.get("tool") if isinstance(step, dict) else None
            tool = catalog.get(tool_name) if tool_name else None
            if tool is None:
                return _record_and_return(
                    root_dir, chain_item, dry_run,
                    _failure(
                        1,
                        {
                            "error": "unknown_tool",
                            "why": f"unknown tool: {tool_name}",
                            "fix": _example(chain_item),
                        },
                    ),
                )
            step_flags: dict[str, str] = {}
            raw_args = step.get("args") or {}
            for key, value in raw_args.items():
                flag = key if str(key).startswith("--") else f"--{key}"
                if not isinstance(value, str):
                    step_flags[flag] = _stringify(value)
                    continue
                resolved, bad = _resolve_expr(value, chain_item, env, prev, outputs)
                if bad is not None or resolved is None:
                    return _record_and_return(
                        root_dir, chain_item, dry_run,
                        _failure(
                            1,
                            {
                                "error": "unresolved_reference",
                                "why": f"could not resolve {bad or value}",
                                "fix": _example(chain_item),
                            },
                        ),
                    )
                step_flags[flag] = resolved

            code, stdout, stderr = run_tool(
                root_dir,
                tool,
                step_flags,
                dry_run=dry_run,
                stdin_data=None if prev is None else last_stdout,
            )
            if code != 0:
                return _record_and_return(root_dir, chain_item, dry_run, (code, stdout, stderr))
            prev = json.loads(stdout)
            outputs.append(prev)
            last_stdout = stdout
        return _record_and_return(root_dir, chain_item, dry_run, (0, last_stdout, ""))
    except Exception as exc:  # noqa: BLE001 — trust invariant: no raw traceback
        return _record_and_return(
            root_dir, chain_item, dry_run,
            _failure(1, {"error": "internal_error", "why": str(exc), "fix": "tk check"}),
        )
