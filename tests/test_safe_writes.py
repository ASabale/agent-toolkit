"""Mutating tools and chains return a plan unless the caller passes --yes."""

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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.catalog import _header_errors  # noqa: E402
from lib.runner import parse_cli_flags, run_chain  # noqa: E402


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )


def _ok(repo: Path, *args: str) -> None:
    proc = _git(repo, *args)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)


def _refs(repo: Path) -> str:
    proc = _git(repo, "show-ref")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc.stdout


def _head(repo: Path) -> str:
    proc = _git(repo, "rev-parse", "HEAD")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc.stdout.strip()


def _tk(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["TK_NO_TELEMETRY"] = "1"
    env["TK_STATE_DIR"] = env.get("TK_STATE_DIR") or "/tmp/tk-safe-writes-unused"
    return subprocess.run(
        [sys.executable, str(ROOT / "tk"), *args],
        capture_output=True,
        text=True,
        env=env,
    )


class ReservedYesTests(unittest.TestCase):
    def test_header_errors_rejects_yes_with_fix(self) -> None:
        errors = _header_errors(
            {
                "name": "demo.yes",
                "summary": "Declares the reserved flag",
                "safety": "read-only",
                "output": "json",
                "example": "tk run demo.yes",
                "verified": "none",
                "args": [{"flag": "--yes", "type": "bool"}],
            }
        )
        self.assertTrue(errors)
        self.assertIn("fix", errors[0])
        self.assertIn("reserved flag: --yes", errors[0])

    def test_parse_does_not_treat_yes_as_a_tool_flag(self) -> None:
        item = {"args": [{"flag": "--repo", "type": "string"}]}
        flags, dry_run, positional = parse_cli_flags(
            ["--yes", "--repo", "scratch", "--yes=1"], item
        )
        self.assertEqual(flags, {"--repo": "scratch"})
        self.assertFalse(dry_run)
        self.assertEqual(positional, [])
        swallowed, _, _ = parse_cli_flags(["--repo", "--yes"], item)
        self.assertNotEqual(swallowed.get("--repo"), "--yes")


class GitSyncSafeWriteTests(unittest.TestCase):
    def _feature_repo(self, tmp: Path) -> tuple[Path, Path]:
        origin = tmp / "origin.git"
        subprocess.run(
            ["git", "init", "--bare", "-b", "main", str(origin)],
            check=True,
            capture_output=True,
            text=True,
        )
        clone = tmp / "clone"
        _ok(tmp, "init", "-b", "main", str(clone))
        _ok(clone, "config", "user.name", "Ada")
        _ok(clone, "config", "user.email", "ada@example.com")
        (clone / "shared.txt").write_text("base\n", encoding="utf-8")
        _ok(clone, "add", "shared.txt")
        _ok(clone, "commit", "-m", "base")
        _ok(clone, "remote", "add", "origin", str(origin))
        _ok(clone, "push", "-u", "origin", "main")
        _ok(clone, "checkout", "-b", "feature")
        (clone / "shared.txt").write_text("feature\n", encoding="utf-8")
        _ok(clone, "commit", "-am", "feature")
        return origin, clone

    def test_git_sync_without_yes_prints_plan_and_apply_and_does_not_move_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin, clone = self._feature_repo(Path(tmp))
            before_head = _head(clone)
            before_refs = (_refs(clone), _refs(origin))
            proc = _tk("run", "git.sync", "--repo", str(clone))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertIs(payload["dry_run"], True)
            self.assertIsInstance(payload["plan"], list)
            self.assertTrue(payload["plan"])
            self.assertEqual(_head(clone), before_head)
            self.assertEqual((_refs(clone), _refs(origin)), before_refs)
            apply = payload["apply"]
            self.assertIn("--yes", apply)
            self.assertIn(str(clone), apply)
            env = os.environ.copy()
            env["PATH"] = str(ROOT) + os.pathsep + env.get("PATH", "")
            env["TK_NO_TELEMETRY"] = "1"
            ran = subprocess.run(apply, shell=True, capture_output=True, text=True, env=env)
            self.assertEqual(ran.returncode, 0, ran.stderr or ran.stdout)
            pushed = json.loads(ran.stdout)
            self.assertIs(pushed["pushed"], True)
            self.assertNotEqual(_refs(origin), before_refs[1])

    def test_yes_on_read_only_matches_the_unadorned_command(self) -> None:
        plain = _tk("run", "env.check", "--bins", "git", "--vars", "none")
        marked = _tk("run", "env.check", "--yes", "--bins", "git", "--vars", "none")
        self.assertEqual(plain.returncode, 0, plain.stderr)
        self.assertEqual(marked.returncode, 0, marked.stderr)
        self.assertEqual(json.loads(plain.stdout), json.loads(marked.stdout))
        self.assertNotIn("apply", json.loads(marked.stdout))


class ChainSafeWriteTests(unittest.TestCase):
    def test_chain_with_mutating_step_dry_runs_until_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tool = root / "tools" / "lab" / "touch"
            tool.parent.mkdir(parents=True)
            tool.write_text(
                "#!/usr/bin/env bash\n"
                "# @tk-name: lab.touch\n"
                "# @tk-summary: Touch a path\n"
                "# @tk-safety: mutating\n"
                "# @tk-arg: --path | required | string | Path to touch\n"
                "# @tk-output: json | object\n"
                "# @tk-example: tk run lab.touch --path example\n"
                "# @tk-verified: none\n"
                "if [ \"${TK_DRY_RUN:-0}\" = 1 ]; then\n"
                "  printf '%s\\n' '{\"dry_run\":true,\"plan\":[\"touch\"]}'\n"
                "  exit 0\n"
                "fi\n"
                "touch \"$TK_ARG_PATH\"\n"
                "printf '%s\\n' '{}'\n",
                encoding="utf-8",
            )
            tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
            target = root / "touched"
            chain = {
                "kind": "chain",
                "name": "lab.touch-chain",
                "summary": "Touch via one step",
                "safety": "read-only",
                "args": [
                    {
                        "flag": "--path",
                        "required": True,
                        "type": "string",
                        "description": "Path",
                    }
                ],
                "steps": [{"tool": "lab.touch", "args": {"path": "$input.path"}}],
                "output": "json",
                "example": "tk run lab.touch-chain --path example",
                "verified": "none",
            }
            code, out, err = run_chain(
                root, chain, {"--path": str(target)}, confirmed=False
            )
            self.assertEqual(code, 0, err)
            payload = json.loads(out)
            self.assertIs(payload["dry_run"], True)
            self.assertEqual(payload["plan"], ["touch"])
            self.assertTrue(payload["apply"].endswith("--yes"))
            self.assertIn("--path", payload["apply"])
            self.assertFalse(target.exists())
            live, live_out, live_err = run_chain(
                root, chain, {"--path": str(target)}, confirmed=True
            )
            self.assertEqual(live, 0, live_err)
            self.assertEqual(json.loads(live_out), {})
            self.assertTrue(target.is_file())
