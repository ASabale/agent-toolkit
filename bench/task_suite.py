#!/usr/bin/env python3
"""Scripted task suite. Not a model run and not a catalog tool.

No network. From the repo root:

    python3 bench/task_suite.py --json

Scripted scores stay under ``scripted``. ``model`` stays null unless a real
harness run is passed in. This command does not invoke a model.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK_IDS = (
    "find_run",
    "miss_name",
    "declared_dependency_missing",
    "save_chain",
    "check_new_tool",
    "chain_dependency_changed",
    "partial_chain",
    "destructive_without_policy",
    "migrate_dry_run",
)
_METRICS = (
    "first_attempt_success",
    "turns",
    "tool_calls",
    "context_tokens",
    "recovery_success",
    "execution_failure",
    "elapsed_ms",
    "authorization_violation",
)


def _blank(task_id: str, scored: bool) -> dict:
    row = {"id": task_id, "scored": scored}
    for key in _METRICS:
        row[key] = None
    return row


def _model_row(task_id: str) -> dict:
    return _blank(task_id, False)


def _commit(root: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _isolate(root: Path) -> Path:
    dest = Path(tempfile.mkdtemp(prefix="tk-tasks-"))
    for name in ("lib", "tools", "chains"):
        shutil.copytree(root / name, dest / name, symlinks=True)
    shutil.copy2(root / "tk", dest / "tk")
    os.chmod(dest / "tk", 0o755)
    return dest


def _tool(name: str, safety: str, body: str, needs: str = "") -> str:
    needs_line = f"# @tk-needs: {needs}\n" if needs else ""
    return (
        "#!/usr/bin/env bash\n"
        f"# @tk-name: {name}\n"
        f"# @tk-summary: Bench fixture {name}\n"
        f"# @tk-safety: {safety}\n"
        f"{needs_line}"
        "# @tk-output: json | Distilled object\n"
        f"# @tk-example: tk run {name}\n"
        "# @tk-verified: none\n"
        "\n"
        "if [[ \"${TK_DRY_RUN:-0}\" == \"1\" ]]; then\n"
        "  printf '%s\\n' '{\"dry_run\":true}'\n"
        "  exit 0\n"
        "fi\n"
        f"{body}"
    )


def _write_tool(dest: Path, name: str, text: str) -> Path:
    namespace, leaf = name.split(".", 1)
    path = dest / "tools" / namespace / leaf
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o755)
    return path


def _tk(dest: Path, state: Path, args: list[str], extra: dict | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["TK_NO_TELEMETRY"] = "1"
    env["TK_STATE_DIR"] = str(state)
    env.pop("TK_DRY_RUN", None)
    if extra:
        env.update(extra)
    return subprocess.run(
        [str(dest / "tk"), *args],
        cwd=dest,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _tokens(proc: subprocess.CompletedProcess[str]) -> int:
    return (len(proc.stdout.encode("utf-8")) + len(proc.stderr.encode("utf-8"))) // 4


def _calls(args: list[str]) -> int:
    return 1 if args and args[0] in {"run", "chain", "check", "save"} else 0


class _Task:
    def __init__(self, task_id: str) -> None:
        self.row = _blank(task_id, True)
        self.turns = 0
        self.calls = 0
        self.tokens = 0
        self.elapsed_ms = 0
        self.recovery: bool | None = None
        self.violation = False

    def run(self, dest: Path, state: Path, args: list[str], extra: dict | None = None) -> subprocess.CompletedProcess[str]:
        started = time.perf_counter()
        proc = _tk(dest, state, args, extra)
        self.elapsed_ms += int((time.perf_counter() - started) * 1000)
        self.turns += 1
        self.calls += _calls(args)
        self.tokens += _tokens(proc)
        return proc

    def finish(self, success: bool, execution_failure: bool) -> dict:
        self.row["first_attempt_success"] = success
        self.row["turns"] = self.turns
        self.row["tool_calls"] = self.calls
        self.row["context_tokens"] = self.tokens
        self.row["recovery_success"] = self.recovery
        self.row["execution_failure"] = execution_failure
        self.row["elapsed_ms"] = self.elapsed_ms
        self.row["authorization_violation"] = self.violation
        return self.row


def _find_run(dest: Path, state: Path) -> dict:
    task = _Task("find_run")
    found = task.run(dest, state, ["find", "proc-info"])
    command = ""
    for line in found.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("run:"):
            command = stripped.split(":", 1)[1].strip()
            break
    ran = None
    if command:
        parts = shlex.split(command)
        if parts and parts[0] == "tk":
            ran = task.run(dest, state, parts[1:])
    success = found.returncode == 0 and ran is not None and ran.returncode == 0
    return task.finish(success, not success)


def _miss_name(dest: Path, state: Path) -> dict:
    task = _Task("miss_name")
    missed = task.run(dest, state, ["run", "bench.not-a-tool"])
    recovered = None
    try:
        payload = json.loads(missed.stderr)
        parts = shlex.split(str(payload.get("fix") or ""))
    except (json.JSONDecodeError, ValueError):
        parts = []
    if parts and parts[0] == "tk":
        recovered = task.run(dest, state, parts[1:])
    task.recovery = recovered is not None and recovered.returncode == 0
    success = missed.returncode != 0 and task.recovery is True
    return task.finish(success, recovered is None)


def _missing_dependency(dest: Path, state: Path, sentinel: Path) -> dict:
    task = _Task("declared_dependency_missing")
    _write_tool(
        dest,
        "bench.needs",
        _tool(
            "bench.needs",
            "read-only",
            f"printf '%s\\n' ran > {shlex.quote(str(sentinel))}\nprintf '%s\\n' '{{\"ok\":true}}'\n",
            needs="tk-bench-missing-bin",
        ),
    )
    proc = task.run(dest, state, ["run", "bench.needs"])
    try:
        payload = json.loads(proc.stderr)
    except json.JSONDecodeError:
        payload = {}
    success = (
        proc.returncode != 0
        and payload.get("error") == "declared_dependency_missing"
        and not sentinel.exists()
    )
    return task.finish(success, payload.get("error") != "declared_dependency_missing")


def _save_chain(dest: Path, state: Path) -> dict:
    task = _Task("save_chain")
    steps = json.dumps(
        [
            {"tool": "sys.proc-info", "args": {"query": "python3"}},
            {"tool": "json.pick", "args": {"keys": "query"}},
        ]
    )
    proc = task.run(
        dest,
        state,
        ["chain", "save", "bench.two", "--summary", "two existing tools", "--steps", steps],
    )
    saved = dest / "chains" / "bench.two.json"
    success = proc.returncode == 0 and saved.is_file()
    return task.finish(success, not success)


def _check_new(dest: Path, state: Path) -> dict:
    task = _Task("check_new_tool")
    path = _write_tool(
        dest,
        "bench.plain",
        _tool("bench.plain", "read-only", "printf '%s\\n' '{\"ok\":true}'\n"),
    )
    before = {item.name for item in path.parent.iterdir()}
    proc = task.run(dest, state, ["check", "bench.plain"])
    after = {item.name for item in path.parent.iterdir()}
    success = proc.returncode == 0 and before == after and not (path.parent / ".checked").exists()
    return task.finish(success, not success)


def _pin_change(dest: Path, state: Path) -> dict:
    task = _Task("chain_dependency_changed")
    _write_tool(dest, "bench.stable", _tool("bench.stable", "read-only", "printf '%s\\n' '{\"ok\":true}'\n"))
    steps = json.dumps([{"tool": "bench.stable"}])
    saved = task.run(dest, state, ["chain", "save", "bench.pinned", "--summary", "pinned", "--steps", steps])
    tool = dest / "tools" / "bench" / "stable"
    tool.write_bytes(tool.read_bytes() + b"\n# changed\n")
    os.chmod(tool, 0o755)
    ran = task.run(dest, state, ["chain", "bench.pinned"])
    try:
        payload = json.loads(ran.stderr)
    except json.JSONDecodeError:
        payload = {}
    success = saved.returncode == 0 and payload.get("error") == "chain_dependency_changed"
    return task.finish(success, payload.get("error") != "chain_dependency_changed")


def _partial(dest: Path, state: Path, mark: Path) -> dict:
    task = _Task("partial_chain")
    _write_tool(
        dest,
        "bench.mark",
        _tool(
            "bench.mark",
            "read-only",
            f"printf '%s\\n' ok > {shlex.quote(str(mark))}\nprintf '%s\\n' '{{\"ok\":true}}'\n",
        ),
    )
    _write_tool(
        dest,
        "bench.fail",
        _tool("bench.fail", "read-only", "printf '%s\\n' '{\"error\":\"boom\"}' >&2\nexit 1\n"),
    )
    steps = json.dumps([{"tool": "bench.mark"}, {"tool": "bench.fail"}])
    saved = task.run(dest, state, ["chain", "save", "bench.partial", "--summary", "partial", "--steps", steps])
    ran = task.run(dest, state, ["chain", "bench.partial"])
    outcomes = []
    trace = state / "trace.jsonl"
    if trace.is_file():
        for line in trace.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("name") == "bench.partial" and record.get("phase") == "finish":
                outcomes.append(record.get("outcome"))
    success = saved.returncode == 0 and ran.returncode != 0 and mark.is_file() and "partial" in outcomes
    return task.finish(success, "partial" not in outcomes)


def _destructive(dest: Path, state: Path, sentinel: Path) -> dict:
    task = _Task("destructive_without_policy")
    _write_tool(
        dest,
        "bench.deny",
        _tool(
            "bench.deny",
            "destructive",
            f"printf '%s\\n' ran > {shlex.quote(str(sentinel))}\nprintf '%s\\n' '{{\"ok\":true}}'\n",
        ),
    )
    proc = task.run(dest, state, ["run", "bench.deny"])
    task.violation = sentinel.exists()
    success = proc.returncode != 0 and not sentinel.exists()
    return task.finish(success, sentinel.exists())


def run_suite(root: Path) -> dict:
    """Run the nine scripted tasks. Model fields stay null."""
    dest = _isolate(root)
    state = Path(tempfile.mkdtemp(prefix="tk-task-state-"))
    mark = state / "mark"
    sentinel = state / "sentinel"
    try:
        rows = [
            _find_run(dest, state),
            _miss_name(dest, state),
            _missing_dependency(dest, state, sentinel),
            _save_chain(dest, state),
            _check_new(dest, state),
            _pin_change(dest, state),
            _partial(dest, state, mark),
            _destructive(dest, state, state / "deny-sentinel"),
        ]
        skipped = _blank("migrate_dry_run", False)
        rows.append(skipped)
    finally:
        shutil.rmtree(dest, ignore_errors=True)
        shutil.rmtree(state, ignore_errors=True)
    return {
        "toolkit_commit": _commit(root),
        "scripted": {"tasks": rows},
        "model": {
            "model_id": None,
            "harness_id": None,
            "toolkit_commit": None,
            "tasks": [_model_row(task_id) for task_id in TASK_IDS],
        },
    }


def main() -> int:
    if sys.argv[1:] != ["--json"]:
        sys.stderr.write(
            json.dumps(
                {
                    "error": "unknown_args",
                    "why": "the scripted suite takes only --json",
                    "fix": "python3 bench/task_suite.py --json",
                }
            )
            + "\n"
        )
        return 2
    sys.stdout.write(json.dumps(run_suite(ROOT), separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
