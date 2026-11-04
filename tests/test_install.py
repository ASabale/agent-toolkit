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

_INSTALL_CMDS = (
    "sh",
    "od",
    "mkdir",
    "ln",
    "mktemp",
    "rm",
    "grep",
    "git",
    "uname",
    "readlink",
    "printf",
    "dirname",
)


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
        skill = repo / "skills" / "agent-toolkit"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("name: agent-toolkit\n", encoding="utf-8")
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

    def _isolated_path(self, include: tuple[str, ...] = ()) -> str:
        bin_dir = Path(tempfile.mkdtemp(dir=self.tmp))
        for name in (*_INSTALL_CMDS, *include):
            src = shutil.which(name)
            self.assertIsNotNone(src, name)
            dest = bin_dir / name
            if not dest.exists():
                dest.symlink_to(src)
        return str(bin_dir)

    def _install(
        self,
        extra: dict[str, str] | None = None,
        args: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", str(self.repo / "install.sh"), *args],
            capture_output=True,
            text=True,
            cwd=self.repo,
            env=self._env(extra),
            check=False,
        )

    def _snapshot(self, root: Path) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for path in sorted(root.rglob("*")):
            rel = str(path.relative_to(root))
            if path.is_symlink():
                rows.append((rel, f"link:{os.readlink(path)}"))
            elif path.is_dir():
                rows.append((rel, "dir"))
            else:
                rows.append((rel, path.read_text(encoding="utf-8")))
        return rows

    def _payload(self, extra: dict[str, str] | None = None) -> dict:
        proc = self._install(extra)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIsInstance(payload, dict)
        return payload

    def _assert_skill_link(self, dest: Path) -> None:
        self.assertTrue(dest.is_symlink(), dest)
        self.assertEqual(dest.resolve(), (self.repo / "skills" / "agent-toolkit").resolve())

    def _stderr_objects(self, proc: subprocess.CompletedProcess[str]) -> list[dict]:
        objects: list[dict] = []
        for line in proc.stderr.splitlines():
            text = line.strip()
            if not text.startswith("{"):
                continue
            payload = json.loads(text)
            self.assertIsInstance(payload, dict)
            objects.append(payload)
        return objects

    def _stderr_diag(
        self,
        proc: subprocess.CompletedProcess[str],
        code: str | None = None,
        key: str = "error",
    ) -> dict:
        found: list[dict] = []
        for payload in self._stderr_objects(proc):
            if code is None or payload.get(key) == code:
                return payload
            found.append(payload)
        self.fail(f"no JSON {key} {code or ''} on stderr: {proc.stderr!r} ({found})")

    def test_no_claude_dir_links_only_agents_skill(self) -> None:
        payload = self._payload()
        agents = self.home / ".agents" / "skills" / "agent-toolkit"
        self._assert_skill_link(agents)
        self.assertFalse((self.home / ".claude").exists())
        self.assertEqual(payload["skill"], str(agents))
        self.assertEqual(payload["skill_links"], [str(agents)])
        self.assertEqual(payload["skill_links_skipped"], [])

    def test_claude_dir_creates_both_links_and_is_idempotent(self) -> None:
        (self.home / ".claude").mkdir()
        first = self._payload()
        agents = self.home / ".agents" / "skills" / "agent-toolkit"
        claude = self.home / ".claude" / "skills" / "agent-toolkit"
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
        dest = self.home / ".claude" / "skills" / "agent-toolkit"
        dest.mkdir(parents=True)
        marker = dest / "keep-me"
        marker.write_text("owned\n", encoding="utf-8")

        payload = self._payload()
        agents = self.home / ".agents" / "skills" / "agent-toolkit"
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
        agents = self.home / ".agents" / "skills" / "agent-toolkit"
        self._assert_skill_link(agents)
        self._assert_skill_link(extra_a / "agent-toolkit")
        self._assert_skill_link(extra_b / "agent-toolkit")
        self.assertEqual(
            payload["skill_links"],
            [str(agents), str(extra_a / "agent-toolkit"), str(extra_b / "agent-toolkit")],
        )
        self.assertEqual(payload["skill_links_skipped"], [])
        self.assertFalse((self.home / ".claude").exists())

    def test_control_characters_in_paths_emit_valid_json(self) -> None:
        home = self.tmp / "ho\tme\nX"
        extra = self.tmp / "sk\till\x01"
        payload = self._payload({"HOME": str(home), "TK_SKILL_DIRS": str(extra)})
        agents = home / ".agents" / "skills" / "agent-toolkit"
        self._assert_skill_link(agents)
        self._assert_skill_link(extra / "agent-toolkit")
        self.assertEqual(payload["skill_links"], [str(agents), str(extra / "agent-toolkit")])
        self.assertIn("\t", payload["bin"])
        self.assertIn("\n", payload["skill"])
        self.assertIn("\t", payload["skill"])
        self.assertFalse((self.repo / "X").exists())

    def test_newline_in_home_stays_one_absolute_link(self) -> None:
        home = self.tmp / "a\nb"
        payload = self._payload({"HOME": str(home)})
        agents = home / ".agents" / "skills" / "agent-toolkit"
        self._assert_skill_link(agents)
        self.assertEqual(payload["skill"], str(agents))
        self.assertEqual(payload["skill_links"], [str(agents)])
        self.assertTrue(payload["skill_links"][0].startswith("/"))
        self.assertFalse((self.repo / "b").exists())

    def test_migrates_old_toolkit_symlink_and_is_idempotent(self) -> None:
        parent = self.home / ".agents" / "skills"
        parent.mkdir(parents=True)
        old = parent / "toolkit"
        old.symlink_to(self.repo / "skills" / "toolkit")
        first = self._payload()
        new = parent / "agent-toolkit"
        self.assertFalse(old.exists())
        self.assertFalse(old.is_symlink())
        self._assert_skill_link(new)
        self.assertEqual(first["skill"], str(new))
        self.assertEqual(first["skill_links"], [str(new)])
        self.assertEqual(first["skill_links_skipped"], [])

        second = self._payload()
        self.assertFalse(old.exists())
        self.assertFalse(old.is_symlink())
        self._assert_skill_link(new)
        self.assertEqual(second["skill_links"], first["skill_links"])
        self.assertEqual(second["skill_links_skipped"], [])

    def test_foreign_toolkit_symlink_is_left_in_place(self) -> None:
        parent = self.home / ".agents" / "skills"
        parent.mkdir(parents=True)
        other = self.tmp / "other"
        other.mkdir()
        (other / "SKILL.md").write_text("foreign\n", encoding="utf-8")
        old = parent / "toolkit"
        old.symlink_to(other)
        payload = self._payload()
        new = parent / "agent-toolkit"
        self.assertTrue(old.is_symlink())
        self.assertEqual(old.resolve(), other.resolve())
        self.assertEqual((old / "SKILL.md").read_text(encoding="utf-8"), "foreign\n")
        self._assert_skill_link(new)
        self.assertEqual(payload["skill_links"], [str(new)])
        self.assertEqual(payload["skill_links_skipped"], [])

        second = self._payload()
        self.assertTrue(old.is_symlink())
        self.assertEqual(old.resolve(), other.resolve())
        self._assert_skill_link(new)
        self.assertEqual(second["skill_links"], payload["skill_links"])
        self.assertEqual(second["skill_links_skipped"], [])

    def test_existing_real_old_toolkit_dir_is_left_in_place(self) -> None:
        old = self.home / ".agents" / "skills" / "toolkit"
        old.mkdir(parents=True)
        marker = old / "keep-me"
        marker.write_text("owned\n", encoding="utf-8")
        payload = self._payload()
        new = self.home / ".agents" / "skills" / "agent-toolkit"
        self.assertTrue(old.is_dir())
        self.assertFalse(old.is_symlink())
        self.assertEqual(marker.read_text(encoding="utf-8"), "owned\n")
        self._assert_skill_link(new)
        self.assertEqual(payload["skill_links"], [str(new)])
        self.assertEqual(payload["skill_links_skipped"], [])

    def test_missing_python3_exits_nonzero_with_install_hint(self) -> None:
        proc = self._install({"PATH": self._isolated_path()})
        self.assertNotEqual(proc.returncode, 0)
        err = self._stderr_diag(proc, "python3_missing")
        self.assertEqual(err["error"], "python3_missing")
        self.assertIn("python3", err["why"])
        self.assertIn("python3", err["fix"])
        self.assertFalse((self.home / ".local" / "bin" / "tk").exists())

    def test_missing_gh_warns_and_continues(self) -> None:
        proc = self._install({"PATH": self._isolated_path(include=("python3",))})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["installed"])
        err = self._stderr_diag(proc, "gh_missing")
        self.assertEqual(err["error"], "gh_missing")
        self.assertIn("gh", err["why"])
        self.assertIn("gh", err["fix"])
        self._assert_skill_link(self.home / ".agents" / "skills" / "agent-toolkit")

    def test_default_install_does_not_change_hooks_path(self) -> None:
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "core.hooksPath", "keep-me"],
            check=True,
            capture_output=True,
        )
        proc = self._install()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(_hooks_path(self.repo), "keep-me")
        self.assertNotIn("hooksPath", payload)
        hint = self._stderr_diag(proc, "hooksPath_unchanged", key="note")
        self.assertNotIn("error", hint)
        self.assertIn("core.hooksPath", hint["why"] + hint["fix"])
        self.assertIn(".githooks", hint["fix"])

    def test_successful_install_stderr_has_note_without_error(self) -> None:
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        path = self._isolated_path(include=("python3",))
        gh = Path(path) / "gh"
        gh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        proc = self._install({"PATH": path})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["installed"])
        objects = self._stderr_objects(proc)
        for payload in objects:
            self.assertNotIn("error", payload, payload)
        notes = [item for item in objects if item.get("note") == "hooksPath_unchanged"]
        self.assertEqual(len(notes), 1, proc.stderr)
        self.assertIn("core.hooksPath", notes[0]["why"] + notes[0]["fix"])
        self.assertIn("config core.hooksPath .githooks", notes[0]["fix"])

    def test_dry_run_creates_nothing_in_temp_home(self) -> None:
        before = self._snapshot(self.home)
        marker = self.repo / "tk-ran"
        tk = self.repo / "tk"
        tk.write_text(
            "#!/bin/sh\n"
            "touch \"$(dirname \"$0\")/tk-ran\"\n"
            "printf '%s\\n' '{\"ok\":true}'\n",
            encoding="utf-8",
        )
        tk.chmod(tk.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        proc = self._install(args=("--dry-run",))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._snapshot(self.home), before)
        self.assertFalse(marker.exists())
        self.assertFalse((self.home / ".local").exists())
        self.assertFalse((self.home / ".agents").exists())

    def test_dry_run_output_lists_expected_targets(self) -> None:
        proc = self._install(args=("--dry-run",))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        home = str(self.home)
        repo = str(self.repo)
        self.assertEqual(
            proc.stdout.splitlines(),
            [
                f"mkdir {home}/.local",
                f"mkdir {home}/.local/bin",
                f"{repo}/tk -> {home}/.local/bin/tk",
                f"mkdir {home}/.agents",
                f"mkdir {home}/.agents/skills",
                f"{repo}/skills/agent-toolkit -> {home}/.agents/skills/agent-toolkit",
            ],
        )

    def test_dry_run_lists_claude_and_extra_skill_dirs(self) -> None:
        (self.home / ".claude").mkdir()
        extra = self.tmp / "extra skills"
        proc = self._install(args=("--dry-run",), extra={"TK_SKILL_DIRS": str(extra)})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        home = str(self.home)
        repo = str(self.repo)
        self.assertEqual(
            proc.stdout.splitlines(),
            [
                f"mkdir {home}/.local",
                f"mkdir {home}/.local/bin",
                f"{repo}/tk -> {home}/.local/bin/tk",
                f"mkdir {home}/.agents",
                f"mkdir {home}/.agents/skills",
                f"{repo}/skills/agent-toolkit -> {home}/.agents/skills/agent-toolkit",
                f"mkdir {home}/.claude/skills",
                f"{repo}/skills/agent-toolkit -> {home}/.claude/skills/agent-toolkit",
                f"mkdir {extra}",
                f"{repo}/skills/agent-toolkit -> {extra}/agent-toolkit",
            ],
        )
        self.assertFalse((self.home / ".local").exists())
        self.assertFalse(extra.exists())
        self.assertEqual(self._snapshot(self.home), [(".claude", "dir")])

    def test_real_run_still_creates_bin_and_skill_paths(self) -> None:
        proc = self._install()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        tk_link = self.home / ".local" / "bin" / "tk"
        skill = self.home / ".agents" / "skills" / "agent-toolkit"
        self.assertTrue(tk_link.is_symlink(), tk_link)
        self.assertEqual(tk_link.resolve(), (self.repo / "tk").resolve())
        self._assert_skill_link(skill)
        self.assertEqual(payload["installed"], True)
        self.assertEqual(payload["bin"], str(tk_link))
        self.assertEqual(payload["skill"], str(skill))
        self.assertEqual(payload["skill_links"], [str(skill)])
        self.assertEqual(payload["skill_links_skipped"], [])

    def test_dry_run_then_real_run_creates_the_planned_paths(self) -> None:
        preview = self._install(args=("--dry-run",))
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(self._snapshot(self.home), [])
        proc = self._install()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((self.home / ".local" / "bin" / "tk").is_symlink())
        self._assert_skill_link(self.home / ".agents" / "skills" / "agent-toolkit")
        for line in preview.stdout.splitlines():
            if line.startswith("mkdir "):
                self.assertTrue(Path(line.removeprefix("mkdir ")).is_dir(), line)
            elif " -> " in line:
                _src, dest = line.split(" -> ", 1)
                self.assertTrue(Path(dest).is_symlink(), line)

    def test_dry_run_leaves_existing_tree_unchanged(self) -> None:
        first = self._install()
        self.assertEqual(first.returncode, 0, first.stderr)
        before = self._snapshot(self.home)
        proc = self._install(args=("--dry-run",))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._snapshot(self.home), before)
        home = str(self.home)
        repo = str(self.repo)
        self.assertEqual(
            proc.stdout.splitlines(),
            [
                f"{repo}/tk -> {home}/.local/bin/tk",
                f"{repo}/skills/agent-toolkit -> {home}/.agents/skills/agent-toolkit",
            ],
        )

    def test_dry_run_does_not_remove_old_toolkit_symlink(self) -> None:
        parent = self.home / ".agents" / "skills"
        parent.mkdir(parents=True)
        old = parent / "toolkit"
        old.symlink_to(self.repo / "skills" / "toolkit")
        before = self._snapshot(self.home)
        proc = self._install(args=("--dry-run",))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._snapshot(self.home), before)
        self.assertTrue(old.is_symlink())
        self.assertIn(f"rm {old}", proc.stdout.splitlines())
        self.assertIn(
            f"{self.repo}/skills/agent-toolkit -> {parent / 'agent-toolkit'}",
            proc.stdout.splitlines(),
        )

    def test_dry_run_does_not_replace_real_skill_dir(self) -> None:
        dest = self.home / ".agents" / "skills" / "agent-toolkit"
        dest.mkdir(parents=True)
        marker = dest / "keep-me"
        marker.write_text("owned\n", encoding="utf-8")
        before = self._snapshot(self.home)
        proc = self._install(args=("--dry-run",))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._snapshot(self.home), before)
        self.assertEqual(marker.read_text(encoding="utf-8"), "owned\n")
        self.assertNotIn(
            f"{self.repo}/skills/agent-toolkit -> {dest}",
            proc.stdout.splitlines(),
        )
        self.assertIn(
            f"{self.repo}/tk -> {self.home}/.local/bin/tk",
            proc.stdout.splitlines(),
        )

    def test_unknown_flag_exits_nonzero_with_corrected_usage(self) -> None:
        script = str(self.repo / "install.sh")
        before = self._snapshot(self.home)
        proc = self._install(args=("--not-a-flag",))
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(proc.stderr.splitlines(), [f"usage: {script}"])
        self.assertEqual(self._snapshot(self.home), before)
        self.assertFalse((self.home / ".local").exists())

    def test_unknown_flag_quotes_corrected_command_when_path_has_spaces(self) -> None:
        spaced = self.tmp / "dir with space"
        spaced.mkdir()
        script = spaced / "install.sh"
        shutil.copy2(self.repo / "install.sh", script)
        before = self._snapshot(self.home)
        proc = subprocess.run(
            ["sh", str(script), "--nope"],
            capture_output=True,
            text=True,
            cwd=spaced,
            env=self._env(),
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(proc.stderr.splitlines(), [f"usage: '{script}'"])
        self.assertEqual(self._snapshot(self.home), before)

    def test_unknown_flag_keeps_dry_run_in_corrected_usage(self) -> None:
        script = str(self.repo / "install.sh")
        before = self._snapshot(self.home)
        proc = self._install(args=("--bogus", "--dry-run"))
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(proc.stderr.splitlines(), [f"usage: {script} --dry-run"])
        self.assertEqual(self._snapshot(self.home), before)

    def test_default_install_leaves_unset_hooks_path(self) -> None:
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        self.assertIsNone(_hooks_path(self.repo))
        payload = self._payload()
        self.assertIsNone(_hooks_path(self.repo))
        self.assertNotIn("hooksPath", payload)
