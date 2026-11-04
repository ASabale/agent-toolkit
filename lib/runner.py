"""Validate flags, run a tool, and run a chain.

stdout is compact JSON. Failures are single-line JSON on stderr
(``error``, ``why``, ``fix``) and never an unhandled traceback.
"""

from __future__ import annotations

import difflib
import json
import math
import os
import re
import shlex
import signal
import subprocess
from pathlib import Path

from lib.evolver import log_event

_INPUT_REF = re.compile(r"^\$input\.([A-Za-z0-9_-]+)$")
_PREV_REF = re.compile(r"^\$prev\.(.+)$")
_STEP_WHOLE = re.compile(r"^\$step\[(-?\d+)\]$")
_STEP_REF = re.compile(r"^\$step\[(-?\d+)\]\.(.+)$")
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


def _example_flag_value(item: dict, flag: str, kind: str) -> str:
    """Valid stand-in for one flag, taken from the catalog example when present."""
    example = str(item.get("example") or "")
    try:
        tokens = shlex.split(example)
    except ValueError:
        tokens = example.split()
    for index, token in enumerate(tokens):
        if token == flag and index + 1 < len(tokens) and not tokens[index + 1].startswith("-"):
            return tokens[index + 1]
        if token.startswith(flag + "="):
            return token.split("=", 1)[1]
    for arg in item.get("args") or []:
        if arg.get("flag") == flag and arg.get("default") not in (None, ""):
            return str(arg["default"])
    if kind == "bool":
        return "true"
    if kind == "int":
        return "1"
    if kind == "float":
        return "1.0"
    return "value"


def _invalid_type_fix(
    item: dict,
    flags: dict[str, str],
    flag: str,
    kind: str,
    dry_run: bool,
) -> str:
    """Caller command with only the bad flag replaced by a valid example value."""
    supplied = dict(flags)
    supplied[flag] = _example_flag_value(item, flag, kind)
    command = _fix_command(item, supplied)
    if dry_run:
        command += " --dry-run"
    return command


_BOOL_FLAG_VALUES = {"true", "false", "1", "0", "yes", "no"}


def _flag_types(item: dict | None) -> dict[str, str] | None:
    if item is None:
        return None
    types: dict[str, str] = {}
    for arg in item.get("args") or []:
        if not isinstance(arg, dict):
            continue
        flag = arg.get("flag")
        if isinstance(flag, str) and flag:
            types[flag] = str(arg.get("type") or "string")
    return types


def _is_dry_run_token(token: str) -> bool:
    return token == "--dry-run" or token.startswith("--dry-run=")


def _is_raw_token(token: str) -> bool:
    return token == "--raw" or token.startswith("--raw=")


def parse_cli_flags(argv: list[str], item: dict | None = None) -> tuple[dict[str, str], bool, list[str]]:
    """Extract ``--dry-run``, ignore ``--raw``, parse ``--flag`` values, and stray tokens.

    When ``item`` is set, boolean args only swallow a following token that is
    an explicit bool literal. Other declared (and unknown) flags take the next
    token even when it starts with ``-``, except ``--dry-run`` and ``--raw``.
    """
    flags: dict[str, str] = {}
    positional: list[str] = []
    dry_run = False
    schema = _flag_types(item)
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
        if _is_raw_token(token):
            index += 1
            continue
        if token.startswith("--"):
            if "=" in token:
                name, value = token.split("=", 1)
                flags[name] = value
                index += 1
                continue
            if (
                index + 1 < len(argv)
                and not _is_dry_run_token(argv[index + 1])
                and not _is_raw_token(argv[index + 1])
            ):
                nxt = argv[index + 1]
                if schema is None:
                    if not nxt.startswith("--"):
                        flags[token] = nxt
                        index += 2
                        continue
                else:
                    kind = schema.get(token)
                    if kind == "bool":
                        if nxt.lower() in _BOOL_FLAG_VALUES:
                            flags[token] = nxt
                            index += 2
                            continue
                    else:
                        flags[token] = nxt
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
        spec_by_name = {
            (flag[2:] if flag.startswith("--") else flag.lstrip("-")): flag
            for flag in declared
            if flag
        }
        candidates = [f"--{key}" for key in spec_by_name]
        suggestions: dict[str, str] = {}
        for flag in unknown:
            bad = flag[2:] if flag.startswith("--") else flag.lstrip("-")
            matches = difflib.get_close_matches("--" + bad, candidates, n=1, cutoff=0.55)
            if matches:
                suggestions[flag] = matches[0]
        missing_required = [
            arg["flag"]
            for arg in (item.get("args") or [])
            if arg.get("required") and arg["flag"] not in flags
        ]
        if len(unknown) == 1 and unknown[0] not in suggestions and len(missing_required) == 1:
            suggestions[unknown[0]] = missing_required[0]
        rendered = []
        for flag in unknown:
            hint = suggestions.get(flag)
            if hint:
                rendered.append(f"{flag} (did you mean {hint}?)")
            else:
                rendered.append(flag)
        if suggestions:
            rewritten = dict(flags)
            for bad_flag, good_flag in suggestions.items():
                if bad_flag not in rewritten:
                    continue
                if good_flag in rewritten:
                    rewritten.pop(bad_flag)
                else:
                    rewritten[good_flag] = rewritten.pop(bad_flag)
            fix = _fix_command(item, rewritten)
        else:
            fix = _example(item)
        return False, {}, {
            "error": "unknown_flag",
            "why": "unknown flags: " + ", ".join(rendered),
            "fix": fix,
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
                    "fix": _invalid_type_fix(item, flags, flag, kind, dry_run),
                })
                continue
            normalized[flag] = value
        elif kind == "int":
            if not _valid_int(raw):
                type_errors.append({
                    "error": "invalid_type",
                    "why": f"{flag} expects int, got {raw!r}",
                    "fix": _invalid_type_fix(item, flags, flag, kind, dry_run),
                })
                continue
            normalized[flag] = raw
        elif kind == "float":
            if not _valid_float(raw):
                type_errors.append({
                    "error": "invalid_type",
                    "why": f"{flag} expects float, got {raw!r}",
                    "fix": _invalid_type_fix(item, flags, flag, kind, dry_run),
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


def _positive_float(raw: str, default: float) -> float:
    try:
        value = float(raw)
    except ValueError:
        return default
    if value <= 0:
        return default
    return value


def _positive_int(raw: str, default: int) -> int:
    try:
        value = int(raw)
    except ValueError:
        return default
    if value <= 0:
        return default
    return value


def _declares_flag(item: dict, flag: str) -> bool:
    return any(
        isinstance(arg, dict) and arg.get("flag") == flag
        for arg in (item.get("args") or [])
    )


def _arg_default_int(item: dict, flag: str, fallback: int) -> int:
    for arg in item.get("args") or []:
        if not isinstance(arg, dict) or arg.get("flag") != flag:
            continue
        raw = arg.get("default")
        if raw is None:
            return fallback
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return fallback
        return value if value > 0 else fallback
    return fallback


def _effective_limit(item: dict, flags: dict[str, str]) -> int:
    raw = flags.get("--limit")
    if raw is None:
        return _arg_default_int(item, "--limit", 1)
    try:
        value = int(raw)
    except ValueError:
        return _arg_default_int(item, "--limit", 1)
    return value if value > 0 else 1


def _command_with_limit(item: dict, flags: dict[str, str], limit: int) -> str:
    return _fix_command(item, {**flags, "--limit": str(limit)})


_NEXT_LIMIT_CAP = 200


def _maybe_next_payload(item: dict, flags: dict[str, str], parsed: object) -> object:
    if not isinstance(parsed, dict) or not _declares_flag(item, "--limit"):
        return parsed
    truncated = parsed.get("truncated")
    if type(truncated) is not int or truncated <= 0:
        return parsed
    current = _effective_limit(item, flags)
    next_limit = min(max(current * 2, 1), current + truncated, _NEXT_LIMIT_CAP)
    return {**parsed, "next": _command_with_limit(item, flags, next_limit)}


def _declared_output_keys(output: object) -> list[str]:
    text = str(output or "").strip()
    if "|" in text:
        text = text.split("|", 1)[1].strip()
    if not text.startswith("{"):
        return []
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
        return []
    inner = text[1:end]
    keys: list[str] = []
    depth = 0
    start = 0
    for idx, char in enumerate(inner):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            key = inner[start:idx].strip().split(":")[0].split("[")[0].strip()
            if key and key not in keys:
                keys.append(key)
            start = idx + 1
    key = inner[start:].strip().split(":")[0].split("[")[0].strip()
    if key and key not in keys:
        keys.append(key)
    return keys


def _pick_fix_keys(item: dict, parsed: dict, max_bytes: int) -> list[str]:
    def value_bytes(key: str) -> int:
        return len(_compact(parsed.get(key)).encode("utf-8"))

    def fits(keys: list[str]) -> bool:
        subset = {key: parsed[key] for key in keys if key in parsed}
        return len(_compact(subset).encode("utf-8")) <= max_bytes

    declared = [key for key in _declared_output_keys(item.get("output")) if key in parsed]
    if declared:
        keys = declared[:3]
    else:
        names = [str(key) for key in parsed]
        keys = names if len(names) <= 1 else [key for key in names if key != max(names, key=value_bytes)]
    while len(keys) > 1 and not fits(keys):
        drop = max(keys, key=value_bytes)
        keys = [key for key in keys if key != drop]
    return keys


_TIMEOUT_KILL_GRACE_SECONDS = 0.2


def _timeout_fix(item: dict, flags: dict[str, str], timeout: float) -> str:
    return f"TK_TIMEOUT={timeout * 2:g} {_fix_command(item, flags)}"


def _terminate_process_group(proc: subprocess.Popen[str]) -> None:
    pid = proc.pid
    if pid is None:
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        proc.wait(timeout=_TIMEOUT_KILL_GRACE_SECONDS)
    except (subprocess.TimeoutExpired, OSError):
        pass
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass


def _output_too_large_fix(
    item: dict,
    flags: dict[str, str],
    parsed: object,
    size: int,
    max_bytes: int,
) -> str:
    if _declares_flag(item, "--limit"):
        halved = max(_effective_limit(item, flags) // 2, 1)
        return _command_with_limit(item, flags, halved)
    command = _fix_command(item, flags)
    raised = f"TK_MAX_OUTPUT_BYTES={size} {command}"
    if not isinstance(parsed, dict) or not parsed:
        return raised
    keys = _pick_fix_keys(item, parsed, max_bytes)
    if not keys:
        return raised
    return f"{raised} | tk run json.pick --keys {','.join(keys)}"


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

        if dry_run:
            # Lazy import: lib.catalog already imports run_chain from this module.
            from lib.catalog import _dry_run_guard_error

            guard = _dry_run_guard_error(Path(str(item.get("path") or "")))
            if guard:
                name = str(item.get("name") or "")
                return _record_and_return(
                    root_dir,
                    item,
                    dry_run,
                    _failure(
                        1,
                        {
                            "error": "dry_run_unsupported",
                            "why": guard,
                            "fix": f"tk check {name}".rstrip(),
                        },
                    ),
                )

        env = os.environ.copy()
        env.update(built)
        env["TK_ROOT_DIR"] = str(root_dir)
        timeout = _positive_float(os.environ.get("TK_TIMEOUT", ""), 60.0)
        proc = subprocess.Popen(
            [str(item["path"])],
            stdin=None if stdin_data is None else subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd=None,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(input=stdin_data, timeout=timeout)
        except subprocess.TimeoutExpired:
            _terminate_process_group(proc)
            try:
                proc.communicate(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
            return _record_and_return(
                root_dir, item, dry_run,
                _failure(
                    1,
                    {
                        "error": "tool_timeout",
                        "why": f"tool exceeded {timeout:g}s",
                        "fix": _timeout_fix(item, flags, timeout),
                    },
                ),
            )
        stdout = stdout or ""
        stderr = stderr or ""
        if proc.returncode != 0:
            return _record_and_return(
                root_dir, item, dry_run,
                _failure(proc.returncode, _tool_failure(item, proc.returncode, stderr)),
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
        compact_out = _compact(parsed)
        max_bytes = _positive_int(os.environ.get("TK_MAX_OUTPUT_BYTES", ""), 65536)
        size = len(compact_out.encode("utf-8"))
        if size > max_bytes:
            return _record_and_return(
                root_dir, item, dry_run,
                _failure(
                    1,
                    {
                        "error": "output_too_large",
                        "why": f"output {size} bytes exceeds TK_MAX_OUTPUT_BYTES ({max_bytes})",
                        "fix": _output_too_large_fix(item, flags, parsed, size, max_bytes),
                    },
                ),
            )
        hinted = _maybe_next_payload(item, flags, parsed)
        return _record_and_return(root_dir, item, dry_run, (0, _compact(hinted), ""))
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


def _synthetic_dry_payload(payload: object) -> bool:
    return isinstance(payload, dict) and payload.get("dry_run") is True


def _dry_dummy(expect_type: str) -> str:
    if expect_type in {"int", "float"}:
        return "1"
    if expect_type == "bool":
        return "true"
    return "example"


def _missing_on_synthetic(dry_run: bool, payload: object, expect_type: str) -> tuple[str | None, str | None] | None:
    """Dummy stand-in when a dry-run payload omitted the referenced key."""
    if dry_run and _synthetic_dry_payload(payload):
        return _dry_dummy(expect_type), None
    return None


def _resolve_expr(
    expr: str,
    chain_item: dict,
    env: dict[str, str],
    prev: object,
    steps: list[object],
    dry_run: bool = False,
    expect_type: str = "string",
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

    if text == "$prev":
        if prev is None:
            return None, text
        return _stringify(prev), None

    prev_match = _PREV_REF.fullmatch(text)
    if prev_match:
        if prev is None:
            return None, text
        try:
            return _stringify(_walk(prev, prev_match.group(1))), None
        except (KeyError, IndexError, TypeError):
            fallback = _missing_on_synthetic(dry_run, prev, expect_type)
            return fallback if fallback is not None else (None, text)

    whole_step = _STEP_WHOLE.fullmatch(text)
    if whole_step:
        index = int(whole_step.group(1))
        if index < 0 or index >= len(steps):
            return None, text
        return _stringify(steps[index]), None

    step_match = _STEP_REF.fullmatch(text)
    if step_match:
        index = int(step_match.group(1))
        if index < 0 or index >= len(steps):
            return None, text
        try:
            return _stringify(_walk(steps[index], step_match.group(2))), None
        except (KeyError, IndexError, TypeError):
            fallback = _missing_on_synthetic(dry_run, steps[index], expect_type)
            return fallback if fallback is not None else (None, text)

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
            flag_types = {
                str(arg.get("flag")): str(arg.get("type") or "string")
                for arg in (tool.get("args") or [])
                if isinstance(arg, dict) and arg.get("flag")
            }
            for key, value in raw_args.items():
                flag = key if str(key).startswith("--") else f"--{key}"
                if not isinstance(value, str):
                    step_flags[flag] = _stringify(value)
                    continue
                resolved, bad = _resolve_expr(
                    value,
                    chain_item,
                    env,
                    prev,
                    outputs,
                    dry_run,
                    flag_types.get(flag, "string"),
                )
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
