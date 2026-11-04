"""Installer skill-link targets. Never touches the real HOME or this repo's git config."""

from __future__ import annotations

import json
import os
import shutil
import stat
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


class InstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self._repo_hooks = _hooks_path(ROOT)
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.repo = self._stub_repo(self.tmp / "repo")

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
        self.assertEqual(
            current,
            self._repo_hooks,
            "install.sh must not change this clone's core.hooksPath",
        )

    def _stub_repo(self, repo: Path) -> Path:
        skill = repo / "skills" / "toolkit"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("name: toolkit\n", encoding="utf-8")
        shutil.copy2(ROOT / "install.sh", repo / "install.sh")
        tk = repo / "tk"
        tk.write_text('#!/bin/sh\nprintf \'{"ok":true,"checked":0}\'\n', encoding="utf-8")
        tk.chmod(tk.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return repo

    def _env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["TK_NO_TELEMETRY"] = "1"
        env.pop("TK_SKILL_DIRS", None)
        if extra:
            env.update(extra)
        return env

    def _install(self, extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", str(self.repo / "install.sh")],
            capture_output=True,
            text=True,
            cwd=self.repo,
            env=self._env(extra),
            check=False,
        )

    def _payload(self, extra: dict[str, str] | None = None) -> dict:
        proc = self._install(extra)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIsInstance(payload, dict)
        return payload

    def _assert_skill_link(self, dest: Path) -> None:
        self.assertTrue(dest.is_symlink(), dest)
        self.assertEqual(dest.resolve(), (self.repo / "skills" / "toolkit").resolve())

    def test_no_claude_dir_links_only_agents_skill(self) -> None:
        payload = self._payload()
        agents = self.home / ".agents" / "skills" / "toolkit"
        self._assert_skill_link(agents)
        self.assertFalse((self.home / ".claude").exists())
        self.assertEqual(payload["skill"], str(agents))
        self.assertEqual(payload["skill_links"], [str(agents)])
        self.assertEqual(payload["skill_links_skipped"], [])

    def test_claude_dir_creates_both_links_and_is_idempotent(self) -> None:
        (self.home / ".claude").mkdir()
        first = self._payload()
        agents = self.home / ".agents" / "skills" / "toolkit"
        claude = self.home / ".claude" / "skills" / "toolkit"
        self._assert_skill_link(agents)
        self._assert_skill_link(claude)
        self.assertEqual(first["skill_links"], [str(agents), str(claude)])
        self.assertEqual(first["skill_links_skipped"], [])

        second = self._payload()
        self._assert_skill_link(agents)
        self._assert_skill_link(claude)
        self.assertEqual(second["skill_links"], first["skill_links"])
        self.assertEqual(second["skill_links_skipped"], [])

    def test_existing_real_claude_skill_dir_is_skipped(self) -> None:
        dest = self.home / ".claude" / "skills" / "toolkit"
        dest.mkdir(parents=True)
        marker = dest / "keep-me"
        marker.write_text("owned\n", encoding="utf-8")

        payload = self._payload()
        agents = self.home / ".agents" / "skills" / "toolkit"
        self._assert_skill_link(agents)
        self.assertTrue(dest.is_dir())
        self.assertFalse(dest.is_symlink())
        self.assertEqual(marker.read_text(encoding="utf-8"), "owned\n")
        self.assertEqual(payload["skill_links"], [str(agents)])
        skipped = payload["skill_links_skipped"]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["path"], str(dest))
        self.assertIn("non-symlink", skipped[0]["reason"])

    def test_tk_skill_dirs_links_each_colon_separated_path(self) -> None:
        extra_a = self.tmp / "a"
        extra_b = self.tmp / "b"
        payload = self._payload({"TK_SKILL_DIRS": f"{extra_a}:{extra_b}"})
        agents = self.home / ".agents" / "skills" / "toolkit"
        self._assert_skill_link(agents)
        self._assert_skill_link(extra_a / "toolkit")
        self._assert_skill_link(extra_b / "toolkit")
        self.assertEqual(
            payload["skill_links"],
            [str(agents), str(extra_a / "toolkit"), str(extra_b / "toolkit")],
        )
        self.assertEqual(payload["skill_links_skipped"], [])
        self.assertFalse((self.home / ".claude").exists())

    def test_control_characters_in_paths_emit_valid_json(self) -> None:
        home = self.tmp / "ho\tme\nX"
        extra = self.tmp / "sk\till\x01"
        payload = self._payload({"HOME": str(home), "TK_SKILL_DIRS": str(extra)})
        agents = home / ".agents" / "skills" / "toolkit"
        self._assert_skill_link(agents)
        self._assert_skill_link(extra / "toolkit")
        self.assertEqual(payload["skill_links"], [str(agents), str(extra / "toolkit")])
        self.assertIn("\t", payload["bin"])
        self.assertIn("\n", payload["skill"])
        self.assertIn("\t", payload["skill"])
        self.assertFalse((self.repo / "X").exists())

    def test_newline_in_home_stays_one_absolute_link(self) -> None:
        home = self.tmp / "a\nb"
        payload = self._payload({"HOME": str(home)})
        agents = home / ".agents" / "skills" / "toolkit"
        self._assert_skill_link(agents)
        self.assertEqual(payload["skill"], str(agents))
        self.assertEqual(payload["skill_links"], [str(agents)])
        self.assertTrue(payload["skill_links"][0].startswith("/"))
        self.assertFalse((self.repo / "b").exists())
