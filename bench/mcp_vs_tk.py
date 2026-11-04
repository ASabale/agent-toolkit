#!/usr/bin/env python3
"""Offline MCP-vs-tk byte/turn counter over recorded fixtures.

VISION.md §2.2: measure idle, discovery, and output bytes so the MCP-bloat
claim is checkable. This is not a catalog tool.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = Path(__file__).resolve().parent / "fixtures"
REQUIRED = ("source", "server_version", "captured_on")
ESTIMATE_NOTE = "bytes/4 estimate"
# sql.* and web.read-text echo the path they are given. An absolute checkout
# or $TMPDIR path would make output_bytes depend on where the tree lives.
_WORK_DIR = Path("bench") / "work"
_DB_FILENAME = "fixture.sqlite"
_GH_STUB = """#!/usr/bin/env python3
import json
import sys

ROLLUP = {rollup}
args = sys.argv[1:]
if args[:2] == ["pr", "view"] and "statusCheckRollup" in args:
    sys.stdout.write(json.dumps(ROLLUP))
    raise SystemExit(0)
sys.stderr.write("unexpected gh args\\n")
raise SystemExit(2)
"""


def _err(error: str, why: str, fix: str) -> int:
    sys.stderr.write(
        json.dumps({"error": error, "why": why, "fix": fix}, separators=(",", ":"))
        + "\n"
    )
    return 2


def _compact_bytes(value: object) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _est_tokens(idle: int, discovery: int, output: int) -> int:
    return (idle + discovery + output) // 4


def _side(idle: int, discovery: int, output: int, tool_call_count: int) -> dict:
    return {
        "idle_bytes": idle,
        "discovery_bytes": discovery,
        "output_bytes": output,
        "tool_call_count": tool_call_count,
        "est_tokens": _est_tokens(idle, discovery, output),
        "est_tokens_note": ESTIMATE_NOTE,
    }


def skill_path(root: Path) -> Path:
    preferred = root / "skills" / "agent-toolkit" / "SKILL.md"
    fallback = root / "skills" / "toolkit" / "SKILL.md"
    if preferred.is_file():
        return preferred
    if fallback.is_file():
        return fallback
    raise FileNotFoundError("SKILL.md not found under skills/agent-toolkit or skills/toolkit")


def load_fixture(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    missing = [key for key in REQUIRED if not payload.get(key)]
    if missing:
        raise ValueError(
            f"{path.name} missing {', '.join(missing)}"
        )
    return payload


def list_fixtures(directory: Path) -> list[Path]:
    return sorted(path for path in directory.glob("*.json") if path.is_file())


def _run_tk(root: Path, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.update(env)
    merged["TK_NO_TELEMETRY"] = "1"
    return subprocess.run(
        [sys.executable, str(root / "tk"), *args],
        capture_output=True,
        text=True,
        cwd=root,
        env=merged,
        check=False,
    )


def _replace_tokens(flags: list[str], tokens: dict[str, str]) -> list[str]:
    return [tokens.get(flag, flag) for flag in flags]


def _write_gh_stub(directory: Path, rollup: dict) -> Path:
    path = directory / "gh"
    path.write_text(_GH_STUB.format(rollup=json.dumps(rollup)), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _relative_to_root(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _prepare_work(root: Path) -> Path:
    directory = root / _WORK_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _cleanup_work(root: Path, created: list[Path]) -> None:
    for path in created:
        path.unlink(missing_ok=True)
    directory = root / _WORK_DIR
    if directory.is_dir() and not any(directory.iterdir()):
        directory.rmdir()


def _sqlite_token(root: Path, spec: dict) -> tuple[str, Path]:
    path = _write_sqlite(_prepare_work(root), spec)
    return _relative_to_root(root, path), path


def _html_token(root: Path, fixtures_dir: Path, html_name: str) -> tuple[str, Path | None]:
    source = (fixtures_dir / html_name).resolve()
    try:
        return _relative_to_root(root, source), None
    except ValueError:
        dest = _prepare_work(root) / Path(html_name).name
        dest.write_bytes(source.read_bytes())
        return _relative_to_root(root, dest), dest


def _write_sqlite(directory: Path, spec: dict) -> Path:
    path = directory / _DB_FILENAME
    path.unlink(missing_ok=True)
    table = spec["table"]
    columns = spec["columns"]
    quoted = []
    for column in columns:
        piece = f'"{column["name"]}" {column["type"]}'
        if column.get("pk"):
            piece += " PRIMARY KEY"
        if column.get("notnull"):
            piece += " NOT NULL"
        quoted.append(piece)
    conn = sqlite3.connect(path)
    try:
        conn.execute(f'CREATE TABLE "{table}" ({", ".join(quoted)})')
        rows = spec.get("rows") or []
        if rows:
            names = [column["name"] for column in columns]
            marks = ", ".join("?" for _ in names)
            conn.executemany(
                f'INSERT INTO "{table}" ({", ".join(names)}) VALUES ({marks})',
                [tuple(row[name] for name in names) for row in rows],
            )
        conn.commit()
    finally:
        conn.close()
    return path


def measure_mcp(fixture: dict) -> dict:
    idle = _compact_bytes(fixture["mcp_tools_list"])
    results = fixture.get("mcp_results") or []
    output = sum(_compact_bytes(item.get("result")) for item in results)
    return _side(idle, 0, output, len(results))


def measure_tk(root: Path, fixture: dict, work: Path, fixtures_dir: Path) -> dict:
    idle = skill_path(root).stat().st_size
    tk = fixture.get("tk") or {}
    tokens: dict[str, str] = {}
    env: dict[str, str] = {}
    created: list[Path] = []
    try:
        if "gh_status_check_rollup" in tk:
            stub = _write_gh_stub(work, tk["gh_status_check_rollup"])
            env["PATH"] = str(stub.parent) + os.pathsep + os.environ.get("PATH", "")
        if "sqlite" in tk:
            token, db_path = _sqlite_token(root, tk["sqlite"])
            tokens["$DB"] = token
            created.append(db_path)
        html_name = tk.get("html_file")
        if html_name:
            token, copied = _html_token(root, fixtures_dir, str(html_name))
            tokens["$HTML"] = token
            if copied is not None:
                created.append(copied)
        query = tk.get("find") or ""
        found = _run_tk(root, ["find", query], env)
        if found.returncode != 0:
            raise RuntimeError(found.stderr.strip() or f"tk find exited {found.returncode}")
        discovery = len(found.stdout.encode("utf-8"))
        output = 0
        runs = tk.get("runs") or []
        for run in runs:
            flags = _replace_tokens(list(run.get("flags") or []), tokens)
            proc = _run_tk(root, ["run", run["name"], *flags], env)
            if proc.returncode != 0:
                raise RuntimeError(
                    proc.stderr.strip() or f"tk run {run['name']} exited {proc.returncode}"
                )
            output += len(proc.stdout.encode("utf-8"))
        return _side(idle, discovery, output, len(runs))
    finally:
        _cleanup_work(root, created)


def run_bench(root: Path, fixtures_dir: Path) -> list[dict]:
    paths = list_fixtures(fixtures_dir)
    if not paths:
        raise ValueError(f"no fixture JSON files in {fixtures_dir}")
    reports: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="tk-bench-") as tmp:
        work = Path(tmp)
        for index, path in enumerate(paths):
            fixture = load_fixture(path)
            task_dir = work / str(index)
            task_dir.mkdir()
            reports.append(
                {
                    "task": fixture.get("task") or path.stem,
                    "source": fixture["source"],
                    "server_version": fixture["server_version"],
                    "captured_on": fixture["captured_on"],
                    "mcp": measure_mcp(fixture),
                    "tk": measure_tk(root, fixture, task_dir, fixtures_dir),
                }
            )
    return reports


def _parse_args(argv: list[str]) -> tuple[Path, bool] | int:
    fixtures = DEFAULT_FIXTURES
    json_mode = False
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--json":
            json_mode = True
            i += 1
            continue
        if token == "--fixtures":
            if i + 1 >= len(argv):
                return _err("missing_flag", "--fixtures requires a directory", "python3 bench/mcp_vs_tk.py --json")
            fixtures = Path(argv[i + 1])
            i += 2
            continue
        return _err(
            "unknown_flag",
            f"unknown flag {token}",
            "python3 bench/mcp_vs_tk.py --json",
        )
    if not json_mode:
        return _err(
            "missing_flag",
            "--json is required",
            "python3 bench/mcp_vs_tk.py --json",
        )
    return fixtures, True


def main() -> int:
    parsed = _parse_args(sys.argv[1:])
    if isinstance(parsed, int):
        return parsed
    fixtures_dir, _ = parsed
    if not fixtures_dir.is_dir():
        return _err(
            "missing_fixtures",
            f"{fixtures_dir} is not a directory",
            "python3 bench/mcp_vs_tk.py --json --fixtures bench/fixtures",
        )
    try:
        reports = run_bench(ROOT, fixtures_dir)
    except ValueError as exc:
        why = str(exc)
        if "missing" in why:
            return _err(
                "missing_provenance",
                why,
                "add source, server_version, and captured_on to every fixture",
            )
        return _err("invalid_fixture", why, "fix the fixture JSON in bench/fixtures")
    except (FileNotFoundError, RuntimeError, KeyError, TypeError) as exc:
        return _err("bench_failed", str(exc), "python3 bench/mcp_vs_tk.py --json")
    sys.stdout.write(json.dumps(reports, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        raise SystemExit(_err("internal_error", str(exc), "python3 bench/mcp_vs_tk.py --json"))
