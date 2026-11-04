"""Shared helpers that strip repeated boilerplate from Python tools (stdlib only)."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path


def emit(payload, code=0) -> int:
    stream = sys.stdout if code == 0 else sys.stderr
    stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return code


def fail(error, why, fix, code=1) -> int:
    return emit({"error": error, "why": why, "fix": fix}, code)


def is_dry_run() -> bool:
    return os.environ.get("TK_DRY_RUN", "0") == "1"


def dry_run_ok(**fields) -> int:
    return emit({"dry_run": True, **fields})


def dry_run_plan(plan, **fields) -> int:
    return emit({"dry_run": True, "plan": plan, **fields})


def _env_name(name: str) -> str:
    return name if name.startswith("TK_ARG_") else "TK_ARG_" + name.lstrip("-").replace("-", "_").upper()


def arg_str(name, default="") -> str:
    return os.environ.get(_env_name(name)) or default


def arg_int(name, default, *, min_val=1, fix) -> int:
    raw = os.environ.get(_env_name(name)) or str(default)
    label = name.lstrip("-").removeprefix("TK_ARG_").replace("_", "-").lower()
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(fail("invalid_flag", f"{label} is not an int: {raw}", fix, 2))
    if value < min_val:
        raise SystemExit(fail("invalid_flag", f"{label} must be >= {min_val}", fix, 2))
    return value


def paginate(items, limit, key="items", **extra) -> dict:
    seq = list(items)
    kept = seq[: max(0, int(limit))]
    return {**extra, key: kept, "count": len(kept), "truncated": max(0, len(seq) - int(limit))}


def _kill_pg(proc: subprocess.Popen) -> None:
    if proc.pid is None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _gh_auth_fix(cmd, why: str) -> str | None:
    tokens = ("auth login", "not logged", "not authenticated", "http 401", "bad credentials")
    if cmd and Path(str(cmd[0])).name == "gh" and any(token in why.lower() for token in tokens):
        return "gh auth login"
    return None


def run_cmd(cmd, *, timeout=30, fix, error_code="cmd_failed", cwd=None):
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=cwd, start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise SystemExit(fail("not_found", f"{exc.filename or cmd[0]} not found", fix))
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_pg(proc)
        raise SystemExit(fail("timeout", f"command timed out after {timeout:g}s", fix))
    if proc.returncode != 0:
        why = (stderr or stdout or f"exited {proc.returncode}").strip()
        raise SystemExit(fail(error_code, why, _gh_auth_fix(cmd, why) or fix))
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def run_main(fn, *, default_fix):
    try:
        raise SystemExit(fn())
    except FileNotFoundError as exc:
        raise SystemExit(fail("not_found", f"{exc.filename or 'command'} not found", default_fix))
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(fail("timeout", f"command timed out after {exc.timeout:g}s", default_fix))
    except Exception as exc:
        raise SystemExit(fail("internal_error", str(exc), default_fix))
