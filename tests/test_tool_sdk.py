"""Seams for lib/tool_sdk.py and the Python example in tools/.template."""

from __future__ import annotations

import ast
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.catalog import check_item  # noqa: E402
from lib.tool_sdk import (  # noqa: E402
    arg_int,
    arg_str,
    dry_run_ok,
    dry_run_plan,
    emit,
    fail,
    is_dry_run,
    paginate,
    run_cmd,
    run_main,
)

SDK = ROOT / "lib" / "tool_sdk.py"
TEMPLATE = ROOT / "tools" / ".template"
_ALLOWED_IMPORT_ROOTS = {"json", "os", "signal", "subprocess", "sys", "pathlib", "__future__"}


def _capture(fn):
    out = StringIO()
    err = StringIO()
    with patch("sys.stdout", out), patch("sys.stderr", err):
        try:
            code = fn()
        except SystemExit as exc:
            return exc.code, out.getvalue(), err.getvalue()
    return code, out.getvalue(), err.getvalue()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _python_example() -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    marker = ": <<'TK_PYTHON_EXAMPLE'\n"
    start = text.index(marker) + len(marker)
    end = text.index("\nTK_PYTHON_EXAMPLE", start)
    return text[start:end]


class ToolSdkContractTests(unittest.TestCase):
    def test_module_is_stdlib_only_and_within_line_budget(self) -> None:
        source = SDK.read_text(encoding="utf-8")
        self.assertLessEqual(len(source.splitlines()), 110)
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0] or "__future__")
        self.assertTrue(imported)
        self.assertTrue(imported <= _ALLOWED_IMPORT_ROOTS)

    def test_emit_writes_compact_json_and_fail_uses_stderr(self) -> None:
        code, out, err = _capture(lambda: emit({"ok": True, "n": 1}))
        self.assertEqual(code, 0)
        self.assertEqual(out, '{"ok":true,"n":1}\n')
        self.assertEqual(err, "")
        code, out, err = _capture(lambda: fail("missing_flag", "need --target", "tk run demo.echo --target x", 2))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(
            json.loads(err),
            {"error": "missing_flag", "why": "need --target", "fix": "tk run demo.echo --target x"},
        )

    def test_dry_run_helpers_and_env_toggle(self) -> None:
        with patch.dict(os.environ, {"TK_DRY_RUN": "0"}, clear=False):
            self.assertFalse(is_dry_run())
        with patch.dict(os.environ, {"TK_DRY_RUN": "1"}, clear=False):
            self.assertTrue(is_dry_run())
            code, out, err = _capture(lambda: dry_run_ok(target="demo", limit=3))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(json.loads(out), {"dry_run": True, "target": "demo", "limit": 3})
        code, out, _err = _capture(lambda: dry_run_plan(["git fetch origin"], repo="."))
        self.assertEqual(json.loads(out), {"dry_run": True, "plan": ["git fetch origin"], "repo": "."})

    def test_arg_str_and_arg_int_read_tk_arg_env(self) -> None:
        env = {"TK_ARG_TARGET": "alpha", "TK_ARG_LIMIT": "4"}
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(arg_str("TARGET"), "alpha")
            self.assertEqual(arg_str("--target"), "alpha")
            self.assertEqual(arg_str("MISSING", "fallback"), "fallback")
            self.assertEqual(arg_int("LIMIT", 20, fix="tk run demo --limit 20"), 4)
            self.assertEqual(arg_int("--limit", 20, fix="tk run demo --limit 20"), 4)

    def test_arg_int_rejects_non_int_and_below_min(self) -> None:
        with patch.dict(os.environ, {"TK_ARG_LIMIT": "nope"}, clear=False):
            code, out, err = _capture(lambda: arg_int("LIMIT", 20, fix="tk run demo --limit 20"))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        payload = json.loads(err)
        self.assertEqual(payload["error"], "invalid_flag")
        self.assertIn("limit is not an int", payload["why"])
        self.assertEqual(payload["fix"], "tk run demo --limit 20")
        with patch.dict(os.environ, {"TK_ARG_LIMIT": "0"}, clear=False):
            code, _out, err = _capture(lambda: arg_int("LIMIT", 20, min_val=1, fix="tk run demo --limit 1"))
        self.assertEqual(code, 2)
        self.assertIn("must be >= 1", json.loads(err)["why"])

    def test_paginate_sets_count_and_integer_truncated(self) -> None:
        rows = [{"id": n} for n in range(5)]
        payload = paginate(rows, 2, key="matches", extra=True)
        self.assertEqual(payload["matches"], [{"id": 0}, {"id": 1}])
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["truncated"], 3)
        self.assertIsInstance(payload["truncated"], int)
        self.assertTrue(payload["extra"])
        empty = paginate(rows, 10, key="items")
        self.assertEqual(empty["count"], 5)
        self.assertEqual(empty["truncated"], 0)
        self.assertEqual(empty["items"], rows)
        self.assertIsNot(empty["items"], rows)

    def test_run_cmd_success_uses_new_session(self) -> None:
        with patch("lib.tool_sdk.subprocess.Popen", wraps=subprocess.Popen) as mocked:
            completed = run_cmd([sys.executable, "-c", "print('ok')"], fix="retry")
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout.strip(), "ok")
        self.assertTrue(mocked.call_args.kwargs.get("start_new_session"))

    def test_run_cmd_missing_binary_and_gh_auth_fix(self) -> None:
        code, out, err = _capture(lambda: run_cmd(["tk-sdk-missing-bin"], timeout=1, fix="install it"))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        payload = json.loads(err)
        self.assertEqual(payload["error"], "not_found")
        self.assertIn("tk-sdk-missing-bin", payload["why"])
        self.assertEqual(payload["fix"], "install it")

        class FakeProc:
            pid = 9
            returncode = 1

            def communicate(self, timeout=None):
                return "", "gh: To get started with GitHub CLI, please run:  gh auth login\n"

        with patch("lib.tool_sdk.subprocess.Popen", return_value=FakeProc()):
            code, _out, err = _capture(
                lambda: run_cmd(["gh", "issue", "view", "1"], fix="tk run gh.issue-view --repo x --number 1")
            )
        self.assertEqual(code, 1)
        payload = json.loads(err)
        self.assertEqual(payload["error"], "cmd_failed")
        self.assertEqual(payload["fix"], "gh auth login")

    def test_run_cmd_timeout_kills_process_group(self) -> None:
        tracked: list[int] = []

        def _reap() -> None:
            for pid in tracked:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

        self.addCleanup(_reap)
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "child.pid"
            script = Path(tmp) / "slow.py"
            script.write_text(
                "import subprocess, time\n"
                "child = subprocess.Popen(['sleep', '30'])\n"
                f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            code, out, err = _capture(
                lambda: run_cmd([sys.executable, str(script)], timeout=2, fix="retry")
            )
            self.assertTrue(pid_file.is_file(), err)
            child_pid = int(pid_file.read_text(encoding="utf-8").strip())
        tracked.append(child_pid)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        payload = json.loads(err)
        self.assertEqual(payload["error"], "timeout")
        self.assertIn("timed out", payload["why"])
        self.assertFalse(_pid_alive(child_pid), f"descendant {child_pid} survived timeout")

    def test_run_main_maps_known_and_unexpected_errors(self) -> None:
        code, out, err = _capture(lambda: run_main(lambda: 0, default_fix="tk check"))
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertEqual(err, "")

        def boom() -> int:
            raise RuntimeError("nope")

        code, out, err = _capture(lambda: run_main(boom, default_fix="tk check demo"))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(json.loads(err), {"error": "internal_error", "why": "nope", "fix": "tk check demo"})

        def missing() -> int:
            raise FileNotFoundError(2, "No such file", "gh")

        code, _out, err = _capture(lambda: run_main(missing, default_fix="install gh"))
        self.assertEqual(json.loads(err)["error"], "not_found")
        self.assertIn("gh", json.loads(err)["why"])

        def timed() -> int:
            raise subprocess.TimeoutExpired(["sleep"], 9)

        code, _out, err = _capture(lambda: run_main(timed, default_fix="retry"))
        self.assertEqual(json.loads(err)["error"], "timeout")
        self.assertIn("9", json.loads(err)["why"])

        def already_failed() -> int:
            raise SystemExit(fail("invalid_flag", "bad", "fix", 2))

        code, out, err = _capture(lambda: run_main(already_failed, default_fix="tk check"))
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)["error"], "invalid_flag")


class TemplateExampleTests(unittest.TestCase):
    def test_template_keeps_bash_and_python_sdk_example(self) -> None:
        text = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("#!/usr/bin/env bash", text)
        self.assertIn("TK_PYTHON_EXAMPLE", text)
        example = _python_example()
        self.assertIn("from lib.tool_sdk import", example)
        self.assertIn("run_main", example)
        self.assertIn("paginate", example)
        self.assertIn("is_dry_run", example)

    def test_extracted_python_example_passes_check_and_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tool = root / "tools" / "demo" / "echo"
            tool.parent.mkdir(parents=True)
            source = _python_example().replace("namespace.verb-noun", "demo.echo")
            tool.write_text(source, encoding="utf-8")
            tool.chmod(tool.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            lib_dir = root / "lib"
            lib_dir.mkdir()
            shutil.copy2(SDK, lib_dir / "tool_sdk.py")
            (lib_dir / "__init__.py").write_text("", encoding="utf-8")
            result = check_item(root, "demo.echo")
            self.assertTrue(result["ok"], result)
            env = os.environ.copy()
            env.update(
                {
                    "TK_NO_TELEMETRY": "1",
                    "TK_DRY_RUN": "0",
                    "TK_ARG_TARGET": "alpha",
                    "TK_ARG_LIMIT": "1",
                }
            )
            live = subprocess.run(
                [str(tool)],
                capture_output=True,
                text=True,
                cwd=str(root),
                env=env,
                check=False,
            )
            self.assertEqual(live.returncode, 0, live.stderr)
            payload = json.loads(live.stdout)
            self.assertEqual(payload["target"], "alpha")
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["truncated"], 0)
            self.assertEqual(payload["items"], [{"id": "alpha"}])


if __name__ == "__main__":
    unittest.main()
