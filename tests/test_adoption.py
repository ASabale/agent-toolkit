"""Sandbox install, then find and run one read-only tool.

Uses a temporary HOME. Does not call npx. Does not write tools/ or chains/.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _hooks_path(repo: Path) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(repo), "config", "--get", "core.hooksPath"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


class AdoptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._repo_hooks = _hooks_path(ROOT)
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()

    def tearDown(self) -> None:
        current = _hooks_path(ROOT)
        if current != self._repo_hooks:
            if self._repo_hooks is None:
                subprocess.run(
                    ["git", "-C", str(ROOT), "config", "--unset-all", "core.hooksPath"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            else:
                subprocess.run(
                    ["git", "-C", str(ROOT), "config", "core.hooksPath", self._repo_hooks],
                    capture_output=True,
                    text=True,
                    check=False,
                )
        self._tmp.cleanup()
        self.assertEqual(current if current == self._repo_hooks else _hooks_path(ROOT), self._repo_hooks)

    def test_install_find_and_run_env_check(self) -> None:
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["TK_NO_TELEMETRY"] = "1"
        env.pop("TK_SKILL_DIRS", None)
        env.pop("TK_STATE_DIR", None)

        installed = subprocess.run(
            ["sh", str(ROOT / "install.sh")],
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=env,
            check=False,
        )
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertIn("hooksPath_unchanged", installed.stderr)
        link = self.home / ".local" / "bin" / "tk"
        self.assertTrue(link.is_symlink(), link)
        self.assertEqual(link.resolve(), (ROOT / "tk").resolve())

        env["PATH"] = str(self.home / ".local" / "bin") + os.pathsep + env.get("PATH", "")
        found = subprocess.run(
            ["tk", "find", "PATH binaries"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=env,
            check=False,
        )
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertIn("tk run env.check", found.stdout)

        ran = subprocess.run(
            ["tk", "run", "env.check", "--bins", "git,python3", "--vars", "none"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=env,
            check=False,
        )
        self.assertEqual(ran.returncode, 0, ran.stderr)
        payload = json.loads(ran.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["missing_bins"], [])

        dirty = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain", "--", "tools", "chains"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(dirty.stdout, "")
