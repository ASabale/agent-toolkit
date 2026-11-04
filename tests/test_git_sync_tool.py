"""Seam for git.sync: rebase onto a remote branch, or abort on conflict."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "tools/git/sync"


def _run(env: dict) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    for key in list(merged):
        if key.startswith("TK_ARG_") or key == "TK_DRY_RUN":
            merged.pop(key, None)
    merged.update(env)
    merged.setdefault("TK_DRY_RUN", "0")
    return subprocess.run(
        [sys.executable, str(SYNC)],
        capture_output=True,
        text=True,
        env=merged,
    )


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Ada"
    env["GIT_AUTHOR_EMAIL"] = "ada@example.com"
    env["GIT_COMMITTER_NAME"] = "Ada"
    env["GIT_COMMITTER_EMAIL"] = "ada@example.com"
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _ok(repo: Path, *args: str) -> None:
    proc = _git(repo, *args)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)


def _pair(tmp: Path) -> tuple[Path, Path, Path]:
    origin = tmp / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(origin)],
        check=True,
        capture_output=True,
        text=True,
    )
    clone_a = tmp / "clone_a"
    _ok(tmp, "init", "-b", "main", str(clone_a))
    (clone_a / "shared.txt").write_text("base\n", encoding="utf-8")
    (clone_a / "local.txt").write_text("keep\n", encoding="utf-8")
    _ok(clone_a, "add", "shared.txt", "local.txt")
    _ok(clone_a, "commit", "-m", "base")
    _ok(clone_a, "remote", "add", "origin", str(origin))
    _ok(clone_a, "push", "-u", "origin", "main")
    clone_b = tmp / "clone_b"
    subprocess.run(
        ["git", "clone", str(origin), str(clone_b)],
        check=True,
        capture_output=True,
        text=True,
    )
    return origin, clone_a, clone_b


class GitSyncTests(unittest.TestCase):
    def test_rebases_and_keeps_unstaged_dirty_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _origin, clone_a, clone_b = _pair(Path(tmp))
            (clone_a / "shared.txt").write_text("from-a\n", encoding="utf-8")
            _ok(clone_a, "add", "shared.txt")
            _ok(clone_a, "commit", "-m", "ahead on a")
            _ok(clone_a, "push", "origin", "main")
            dirty = clone_b / "local.txt"
            dirty.write_text("keep\ndirty\n", encoding="utf-8")
            proc = _run(
                {
                    "TK_ARG_REPO": str(clone_b),
                    "TK_ARG_REMOTE": "origin",
                    "TK_ARG_BRANCH": "main",
                }
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "rebased")
            self.assertIs(payload["rebased"], True)
            self.assertEqual(payload["behind"], 0)
            self.assertEqual(dirty.read_text(encoding="utf-8"), "keep\ndirty\n")
            self.assertEqual((clone_b / "shared.txt").read_text(encoding="utf-8"), "from-a\n")
            porcelain = _git(clone_b, "status", "--porcelain")
            self.assertIn("local.txt", porcelain.stdout)

    def test_conflict_aborts_rebase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _origin, clone_a, clone_b = _pair(Path(tmp))
            (clone_a / "shared.txt").write_text("from-a\n", encoding="utf-8")
            _ok(clone_a, "add", "shared.txt")
            _ok(clone_a, "commit", "-m", "a edit")
            _ok(clone_a, "push", "origin", "main")
            (clone_b / "shared.txt").write_text("from-b\n", encoding="utf-8")
            _ok(clone_b, "add", "shared.txt")
            _ok(clone_b, "commit", "-m", "b edit")
            proc = _run({"TK_ARG_REPO": str(clone_b)})
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("rebase_conflict", proc.stderr)
            self.assertEqual(proc.stdout.strip(), "")
            head = _git(clone_b, "symbolic-ref", "--short", "HEAD")
            self.assertEqual(head.stdout.strip(), "main")
            rebase = _git(clone_b, "rev-parse", "--git-path", "rebase-merge")
            path = Path(rebase.stdout.strip())
            if not path.is_absolute():
                path = clone_b / path
            self.assertFalse(path.exists())
            self.assertEqual((clone_b / "shared.txt").read_text(encoding="utf-8"), "from-b\n")


if __name__ == "__main__":
    unittest.main()
