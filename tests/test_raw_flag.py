"""`--raw` is a no-op global modifier (issue #17)."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.catalog import _header_errors, check_item  # noqa: E402
from lib.runner import parse_cli_flags, validate_and_build_env  # noqa: E402

TK = ROOT / "tk"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["TK_NO_TELEMETRY"] = "1"
    env.pop("TK_RAW", None)
    return env


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(TK), *args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=_env(),
    )


def _path_item() -> dict:
    return {
        "kind": "tool",
        "name": "demo.path",
        "summary": "path",
        "safety": "read-only",
        "args": [
            {
                "flag": "--path",
                "env_var": "TK_ARG_PATH",
                "required": True,
                "type": "string",
                "description": "Path",
                "default": None,
            }
        ],
        "output": "json",
        "example": "tk run demo.path --path lib",
        "verified": "none",
        "path": "/tmp/demo-path",
    }


def _complete_item(flag: str) -> dict:
    return {
        "kind": "tool",
        "name": "demo.reserved",
        "summary": "Reserved flag demo",
        "safety": "read-only",
        "args": [
            {
                "flag": flag,
                "env_var": "TK_ARG_X",
                "required": False,
                "type": "bool",
                "description": "x",
                "default": None,
            }
        ],
        "output": "json",
        "example": "tk run demo.reserved",
        "verified": "none",
        "path": "/tmp/demo-reserved",
    }


def _write_tool(path: Path, name: str, flag: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/usr/bin/env bash\n"
        f"# @tk-name: {name}\n"
        "# @tk-summary: Reserved flag demo\n"
        "# @tk-safety: read-only\n"
        f"# @tk-arg: {flag} | optional | bool | x\n"
        "# @tk-output: json | object\n"
        f"# @tk-example: tk run {name}\n"
        "# @tk-verified: none\n"
        "\n"
        'if [[ "${TK_DRY_RUN:-0}" == "1" ]]; then\n'
        "  printf '%s\\n' '{\"dry_run\":true}'\n"
        "  exit 0\n"
        "fi\n"
        "printf '%s\\n' '{\"ok\":true}'\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class ParseRawFlagTests(unittest.TestCase):
    def test_raw_is_consumed_and_does_not_appear_in_flags(self) -> None:
        item = _path_item()
        cases = (
            ["--raw", "--path", "lib"],
            ["--path", "lib", "--raw"],
            ["--raw=1", "--path", "lib"],
        )
        for argv in cases:
            with self.subTest(argv=argv):
                flags, dry_run, positional = parse_cli_flags(argv, item)
                self.assertEqual(flags, {"--path": "lib"})
                self.assertFalse(dry_run)
                self.assertEqual(positional, [])
                self.assertNotIn("--raw", flags)

    def test_string_flag_does_not_swallow_raw(self) -> None:
        item = _path_item()
        flags, dry_run, positional = parse_cli_flags(["--path", "--raw"], item)
        self.assertNotEqual(flags.get("--path"), "--raw")
        self.assertEqual(flags, {"--path": "true"})
        self.assertFalse(dry_run)
        self.assertEqual(positional, [])

        dry_flags, is_dry, dry_pos = parse_cli_flags(["--path", "--dry-run"], item)
        self.assertEqual(dry_flags, flags)
        self.assertTrue(is_dry)
        self.assertEqual(dry_pos, positional)

    def test_built_env_has_no_tk_raw(self) -> None:
        item = _path_item()
        flags, dry_run, positional = parse_cli_flags(
            ["--path", "lib", "--raw=1"], item
        )
        ok, env, err = validate_and_build_env(item, flags, positional, dry_run)
        self.assertTrue(ok, err)
        self.assertNotIn("TK_RAW", env)
        self.assertEqual(env.get("TK_ARG_PATH"), "lib")


class HeaderReservedFlagTests(unittest.TestCase):
    def test_header_errors_rejects_raw_and_dry_run(self) -> None:
        self.assertIn("reserved flag: --raw", _header_errors(_complete_item("--raw")))
        self.assertIn(
            "reserved flag: --dry-run", _header_errors(_complete_item("--dry-run"))
        )
        self.assertFalse(
            any(err.startswith("reserved flag:") for err in _header_errors(_path_item()))
        )

    def test_check_item_rejects_declared_raw_and_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_path = root / "tools" / "demo" / "reserved"
            _write_tool(raw_path, "demo.reserved", "--raw")
            raw_result = check_item(root, "demo.reserved")
            dry_path = root / "tools" / "demo" / "dry"
            _write_tool(dry_path, "demo.dry", "--dry-run")
            dry_result = check_item(root, "demo.dry")
        self.assertFalse(raw_result["ok"])
        self.assertIn("reserved flag: --raw", raw_result["errors"])
        self.assertFalse(dry_result["ok"])
        self.assertIn("reserved flag: --dry-run", dry_result["errors"])


class RawFlagCliTests(unittest.TestCase):
    def test_env_check_stdout_is_identical_with_raw_placements(self) -> None:
        baseline = _run("run", "env.check", "--bins", "git", "--vars", "none")
        self.assertEqual(baseline.returncode, 0, baseline.stderr)
        variants = (
            ["run", "env.check", "--raw", "--bins", "git", "--vars", "none"],
            ["run", "env.check", "--bins", "git", "--raw", "--vars", "none"],
            ["run", "env.check", "--bins", "git", "--vars", "none", "--raw"],
            ["run", "env.check", "--bins", "git", "--vars", "none", "--raw=1"],
        )
        for argv in variants:
            with self.subTest(argv=argv):
                proc = _run(*argv)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stdout, baseline.stdout)

    def test_chain_stdout_is_identical_with_raw(self) -> None:
        baseline = _run("run", "git.repo-audit", "--repo", ".", "--limit", "2")
        self.assertEqual(baseline.returncode, 0, baseline.stderr)
        raw = _run("run", "git.repo-audit", "--repo", ".", "--limit", "2", "--raw")
        self.assertEqual(raw.returncode, 0, raw.stderr)
        self.assertEqual(raw.stdout, baseline.stdout)

    def test_cli_tool_env_has_no_tk_raw(self) -> None:
        proc = _run("run", "env.check", "--bins", "git", "--vars", "TK_RAW", "--raw")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["variables"], [{"name": "TK_RAW", "set": False, "length": 0}])
        self.assertEqual(payload["missing_vars"], ["TK_RAW"])

    def test_tk_check_rejects_declared_raw_and_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw_path = Path(tmp) / "raw-tool"
            _write_tool(raw_path, "demo.reserved", "--raw")
            raw = _run("check", str(raw_path))
            dry_path = Path(tmp) / "dry-tool"
            _write_tool(dry_path, "demo.dry", "--dry-run")
            dry = _run("check", str(dry_path))
        self.assertNotEqual(raw.returncode, 0, raw.stdout)
        self.assertIn("reserved flag: --raw", raw.stdout)
        self.assertNotEqual(dry.returncode, 0, dry.stdout)
        self.assertIn("reserved flag: --dry-run", dry.stdout)


if __name__ == "__main__":
    unittest.main()
