"""Validate flags, run a tool, and run a chain.

stdout is compact JSON. Failures are single-line JSON on stderr
(``error``, ``why``, ``fix``) and never an unhandled traceback.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import os
import shlex
import signal
import subprocess
from pathlib import Path

from lib.catalog import output_keys
from lib.chainref import resolve_expr, stringify
from lib.evolver import append_audit, log_event, record_feedback
from lib.guards import tool_subprocess_env
from lib.redact import redact_data

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
            parts.append(
                shlex.quote(_example_flag_value(item, flag, arg.get("type") or "string"))
            )
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


def _is_yes_token(token: str) -> bool:
    return token == "--yes" or token.startswith("--yes=")


def _is_confirm_token(token: str) -> bool:
    return token == "--confirm" or token.startswith("--confirm=")


def _is_global_modifier(token: str) -> bool:
    return (
        _is_dry_run_token(token)
        or _is_raw_token(token)
        or _is_yes_token(token)
        or _is_confirm_token(token)
    )


def parse_cli_flags(argv: list[str], item: dict | None = None) -> tuple[dict[str, str], bool, list[str]]:
    """Extract ``--dry-run``, ignore ``--raw``, ``--yes``, and ``--confirm``.

    When ``item`` is set, boolean args only swallow a following token that is
    an explicit bool literal. Other declared (and unknown) flags take the next
    token even when it starts with ``-``, except ``--dry-run``, ``--raw``,
    ``--yes``, and ``--confirm``. A bare ``--confirm`` consumes its plan id.
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
        if _is_raw_token(token) or _is_yes_token(token):
            index += 1
            continue
        if token == "--confirm":
            if index + 1 < len(argv) and not _is_global_modifier(argv[index + 1]):
                index += 2
            else:
                index += 1
            continue
        if token.startswith("--confirm="):
            index += 1
            continue
        if token.startswith("--"):
            if "=" in token:
                name, value = token.split("=", 1)
                flags[name] = value
                index += 1
                continue
            if index + 1 < len(argv) and not _is_global_modifier(argv[index + 1]):
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


def confirm_id_from_argv(argv: list[str]) -> str | None:
    """Return the ``--confirm`` value.

    ``None`` when the flag is absent. ``""`` when it is present without a value.
    """
    found = False
    value = ""
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--confirm":
            found = True
            if index + 1 < len(argv) and not _is_global_modifier(argv[index + 1]):
                value = argv[index + 1]
                index += 2
                continue
            value = ""
            index += 1
            continue
        if token.startswith("--confirm="):
            found = True
            value = token.split("=", 1)[1]
            index += 1
            continue
        index += 1
    if not found:
        return None
    return value


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
    return code, "", _compact(redact_data(payload))


def _why_from_stderr(stderr: str) -> str:
    text = (stderr or "").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("why"), str):
        return payload["why"]
    return text


def _needs_audit(item: dict) -> bool:
    if _writes(item):
        return True
    return bool(os.environ.get("TK_ISOLATION", "").strip())


def _audit_via(confirmed: bool, audit_via: str | None) -> str:
    if audit_via in {"policy", "confirm", "yes", "unconfirmed"}:
        return audit_via
    return "yes" if confirmed else "unconfirmed"


def _audit_or_deny(
    root_dir: Path,
    item: dict,
    dry_run: bool,
    confirmed: bool,
    plan_id: str,
    exit_code: int | None,
    audit_via: str | None,
) -> tuple[int, str, str] | None:
    """Record a gateway decision. A writer with no record does not run."""
    if not _needs_audit(item):
        return None
    wrote = append_audit(
        root_dir,
        {
            "plan_id": plan_id,
            "name": str(item.get("name") or ""),
            "decision": "dry_run" if dry_run else "allow",
            "via": _audit_via(confirmed, audit_via),
            "enforced": ["env_allowlist", "timeout", "output_cap"],
            "isolation": "none",
            "exit": exit_code,
        },
    )
    if wrote or not _writes(item):
        return None
    return _failure(
        1,
        {
            "error": "audit_failed",
            "why": "the audit record was not written",
            "fix": "make the state directory writable on this filesystem",
        },
    )


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
    record_feedback(root_dir, str(item.get("name") or ""), code, stderr)


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


def _pick_fix_keys(item: dict, parsed: dict, max_bytes: int) -> list[str]:
    def value_bytes(key: str) -> int:
        return len(_compact(parsed.get(key)).encode("utf-8"))

    def fits(keys: list[str]) -> bool:
        subset = {key: parsed[key] for key in keys if key in parsed}
        return len(_compact(subset).encode("utf-8")) <= max_bytes

    declared = [key for key in (output_keys(item.get("output")) or []) if key in parsed]
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
        return f"{command} --raw | head"
    keys = _pick_fix_keys(item, parsed, max_bytes)
    if not keys:
        return f"{command} --raw | head"
    return f"{raised} | tk run json.pick --keys {','.join(keys)}"


def _writes(item: dict) -> bool:
    return str(item.get("safety") or "") in {"mutating", "destructive"}


def _apply_command(item: dict, flags: dict[str, str]) -> str:
    return _fix_command(item, flags) + " --yes"


def _plan_id(name: str, flags: dict[str, str], plan: list) -> str:
    """8 hex chars over name, sorted flags, and the dry-run plan. Not permission."""
    body = {
        "name": name,
        "flags": [[flag, flags[flag]] for flag in sorted(flags)],
        "plan": plan,
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]


def _confirm_command(item: dict, flags: dict[str, str], plan_id: str) -> str:
    return _fix_command(item, flags) + " --confirm " + plan_id


def _plan_list(payload: object) -> list:
    plan = payload.get("plan") if isinstance(payload, dict) else None
    if not isinstance(plan, list):
        return []
    return plan


def _safe_write_result(item: dict, flags: dict[str, str], payload: object) -> dict:
    plan = _plan_list(payload)
    plan_id = _plan_id(str(item.get("name") or ""), flags, plan)
    return {
        "dry_run": True,
        "plan": plan,
        "plan_id": plan_id,
        "apply": _apply_command(item, flags),
        "confirm": _confirm_command(item, flags, plan_id),
    }


def _plan_mismatch(item: dict, flags: dict[str, str], why: str) -> tuple[int, str, str]:
    return _failure(
        2,
        {"error": "plan_mismatch", "why": why, "fix": _fix_command(item, flags)},
    )


def _chain_writes(root_dir: Path, chain_item: dict) -> bool:
    if _writes(chain_item):
        return True
    from lib.catalog import discover_catalog

    catalog = discover_catalog(root_dir)
    for step in chain_item.get("steps") or []:
        if not isinstance(step, dict):
            continue
        tool = catalog.get(step.get("tool"))
        if tool is not None and _writes(tool):
            return True
    return False


def run_tool(
    root_dir: Path,
    item: dict,
    flags: dict[str, str],
    positional: list[str] | None = None,
    dry_run: bool = False,
    stdin_data: str | None = None,
    confirmed: bool = True,
    raw: bool = False,
    confirm_id: str | None = None,
    audit_via: str | None = None,
) -> tuple[int, str, str]:
    """Validate ``flags``, execute ``item['path']``, and compact JSON stdout.

    ``confirmed`` defaults to true so in-process callers keep today's behavior.
    ``tk run`` passes false unless argv contains ``--yes``. A mutating or
    destructive tool then runs as a dry-run and returns ``plan`` plus ``apply``.
    ``confirm_id`` reruns that dry-run and executes only when the id matches.
    ``--yes`` (``confirmed`` true) ignores ``confirm_id``.
    """
    try:
        user_dry_run = dry_run
        writer = _writes(item)
        if writer and not confirmed and confirm_id is not None and not user_dry_run:
            if confirm_id == "":
                return _record_and_return(
                    root_dir,
                    item,
                    False,
                    _plan_mismatch(item, flags, "--confirm needs a plan_id"),
                )
            code, out, err = run_tool(
                root_dir,
                item,
                flags,
                positional,
                False,
                stdin_data,
                confirmed=False,
                raw=raw,
                confirm_id=None,
            )
            if code != 0:
                return code, out, err
            try:
                probed = json.loads(out)
            except json.JSONDecodeError:
                probed = None
            expected = probed.get("plan_id") if isinstance(probed, dict) else None
            if not isinstance(expected, str) or expected != confirm_id:
                shown = expected if isinstance(expected, str) else ""
                return _record_and_return(
                    root_dir,
                    item,
                    False,
                    _plan_mismatch(item, flags, f"plan_id is {shown}, got {confirm_id}"),
                )
            return run_tool(
                root_dir,
                item,
                flags,
                positional,
                False,
                stdin_data,
                confirmed=True,
                raw=raw,
                confirm_id=None,
                audit_via="confirm",
            )
        gated = (not confirmed) and writer
        if gated:
            dry_run = True
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

        denied = _audit_or_deny(
            root_dir,
            item,
            dry_run,
            confirmed,
            str(confirm_id or ""),
            None,
            audit_via,
        )
        if denied is not None:
            return _record_and_return(root_dir, item, dry_run, denied)

        env = tool_subprocess_env(built)
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
        if size > max_bytes and not raw:
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
        if gated:
            hinted = _safe_write_result(item, flags, hinted)
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


def _annotate_step_stop(stderr: str, chain_name: str, index: int, total: int, tool_name: str) -> str:
    text = (stderr or "").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return stderr
    if not isinstance(payload, dict) or not {"error", "why", "fix"} <= payload.keys():
        return stderr
    why = str(payload.get("why") or "")
    marker = f"chain {chain_name} stopped at step {index}/{total} ({tool_name}): "
    if why.startswith(marker):
        return stderr
    payload["why"] = marker + why
    return _compact(payload)


def _unquoted_command_sub(text: str) -> bool:
    """True when ``$(`` appears outside single or double quotes."""
    quote = ""
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\" and quote == '"':
                escaped = True
            elif char == quote:
                quote = ""
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if text.startswith("$(", index):
            return True
        index += 1
    return False


def _rejected_tool_fix(fix: str) -> bool:
    """A tool-supplied fix may not add a second command."""
    if "\n" in fix or "\r" in fix or ";" in fix:
        return True
    return _unquoted_command_sub(fix)


def _tool_failure(item: dict, code: int, stderr: str) -> dict:
    text = stderr.strip()
    if text:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and {"error", "why", "fix"} <= payload.keys():
            fix = payload.get("fix")
            if isinstance(fix, str) and _rejected_tool_fix(fix):
                payload = dict(payload)
                payload["fix"] = _example(item)
            return payload
    return {
        "error": "tool_failed",
        "why": text or f"exit {code}",
        "fix": _example(item),
    }


def run_chain(
    root_dir: Path,
    chain_item: dict,
    flags: dict[str, str],
    positional: list[str] | None = None,
    dry_run: bool = False,
    confirmed: bool = True,
    confirm_id: str | None = None,
    audit_via: str | None = None,
) -> tuple[int, str, str]:
    """Validate chain flags, resolve step references, and stop on the first error.

    A chain that writes, or that calls a mutating or destructive step, follows
    the same ``--yes`` rule as ``run_tool`` when ``confirmed`` is false.
    ``confirm_id`` executes that chain only when it matches the dry-run id.
    """
    try:
        user_dry_run = dry_run
        writer = _chain_writes(root_dir, chain_item)
        if writer and not confirmed and confirm_id is not None and not user_dry_run:
            if confirm_id == "":
                return _record_and_return(
                    root_dir,
                    chain_item,
                    False,
                    _plan_mismatch(chain_item, flags, "--confirm needs a plan_id"),
                )
            code, out, err = run_chain(
                root_dir,
                chain_item,
                flags,
                positional,
                False,
                confirmed=False,
                confirm_id=None,
            )
            if code != 0:
                return code, out, err
            try:
                probed = json.loads(out)
            except json.JSONDecodeError:
                probed = None
            expected = probed.get("plan_id") if isinstance(probed, dict) else None
            if not isinstance(expected, str) or expected != confirm_id:
                shown = expected if isinstance(expected, str) else ""
                return _record_and_return(
                    root_dir,
                    chain_item,
                    False,
                    _plan_mismatch(
                        chain_item, flags, f"plan_id is {shown}, got {confirm_id}"
                    ),
                )
            return run_chain(
                root_dir,
                chain_item,
                flags,
                positional,
                False,
                confirmed=True,
                confirm_id=None,
                audit_via="confirm",
            )
        gated = (not confirmed) and writer
        if gated:
            dry_run = True
        plans: list = []
        ok, env, err = validate_and_build_env(
            chain_item, flags, list(positional or []), dry_run
        )
        if not ok:
            return _record_and_return(
                root_dir, chain_item, dry_run,
                _failure(1, err or {"error": "internal_error", "why": "validation failed", "fix": "tk check"}),
            )

        denied = _audit_or_deny(
            root_dir,
            chain_item,
            dry_run,
            confirmed,
            str(confirm_id or ""),
            None,
            audit_via,
        )
        if denied is not None:
            return _record_and_return(root_dir, chain_item, dry_run, denied)

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
        for index, step in enumerate(steps, start=1):
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
                    step_flags[flag] = stringify(value)
                    continue
                resolved, bad = resolve_expr(
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
                stderr = _annotate_step_stop(
                    stderr,
                    str(chain_item.get("name") or ""),
                    index,
                    len(steps),
                    str(tool_name),
                )
                return _record_and_return(root_dir, chain_item, dry_run, (code, stdout, stderr))
            prev = json.loads(stdout)
            outputs.append(prev)
            if isinstance(prev, dict) and isinstance(prev.get("plan"), list):
                plans.extend(prev["plan"])
            last_stdout = stdout
        if gated:
            plan_id = _plan_id(str(chain_item.get("name") or ""), flags, plans)
            last_stdout = _compact(
                {
                    "dry_run": True,
                    "plan": plans,
                    "plan_id": plan_id,
                    "apply": _apply_command(chain_item, flags),
                    "confirm": _confirm_command(chain_item, flags, plan_id),
                }
            )
        return _record_and_return(root_dir, chain_item, dry_run, (0, last_stdout, ""))
    except Exception as exc:  # noqa: BLE001 — trust invariant: no raw traceback
        return _record_and_return(
            root_dir, chain_item, dry_run,
            _failure(1, {"error": "internal_error", "why": str(exc), "fix": "tk check"}),
        )
