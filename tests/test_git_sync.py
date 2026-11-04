"""git.sync rebases the current feature branch onto origin/main and pushes it."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "tools/git/sync"


def _identity() -> dict[str, str]:
    return {
        "GIT_AUTHOR_NAME": "Ada",
        "GIT_AUTHOR_EMAIL": "ada@example.com",
        "GIT_COMMITTER_NAME": "Ada",
        "GIT_COMMITTER_EMAIL": "ada@example.com",
    }


def _run(env: dict) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    for key in list(merged):
        if key.startswith("TK_ARG_") or key == "TK_DRY_RUN":
            merged.pop(key, None)
    merged.update(_identity())
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
    env.update(_identity())
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


def _pair(tmp: Path) -> tuple[Path, Path]:
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
    return origin, clone


def _sha(repo: Path, ref: str) -> str:
    proc = _git(repo, "rev-parse", ref)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc.stdout.strip()


class GitSyncRefuseMainTests(unittest.TestCase):
    def test_refuses_when_current_branch_is_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin, clone = _pair(Path(tmp))
            before = _sha(origin, "refs/heads/main")
            proc = _run({"TK_ARG_REPO": str(clone)})
            self.assertNotEqual(proc.returncode, 0, proc.stdout)
            self.assertEqual(proc.stdout.strip(), "")
            payload = json.loads(proc.stderr)
            self.assertEqual(payload["error"], "on_main")
            self.assertIn("main", payload["why"])
            self.assertIn("tk run git.sync", payload["fix"])
            self.assertIn("git checkout -b fix/sync", payload["fix"])
            self.assertEqual(_git(clone, "symbolic-ref", "--short", "HEAD").stdout.strip(), "main")
            self.assertEqual(_sha(origin, "refs/heads/main"), before)
            self.assertEqual(_git(origin, "show-ref", "--heads").stdout.count("\n"), 1)

    def test_refuses_when_current_branch_equals_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin, clone = _pair(Path(tmp))
            _ok(clone, "checkout", "-b", "develop")
            before = _sha(origin, "refs/heads/main")
            proc = _run({"TK_ARG_REPO": str(clone), "TK_ARG_BRANCH": "develop"})
            self.assertNotEqual(proc.returncode, 0, proc.stdout)
            self.assertEqual(proc.stdout.strip(), "")
            payload = json.loads(proc.stderr)
            self.assertEqual(payload["error"], "on_base")
            self.assertIn("develop", payload["why"])
            self.assertIn("git checkout -b fix/sync", payload["fix"])
            self.assertEqual(_git(clone, "symbolic-ref", "--short", "HEAD").stdout.strip(), "develop")
            self.assertEqual(_sha(origin, "refs/heads/main"), before)

    def test_refuses_detached_head_and_fix_is_runnable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin, clone = _pair(Path(tmp))
            before = _sha(origin, "refs/heads/main")
            _ok(clone, "checkout", "--detach")
            proc = _run({"TK_ARG_REPO": str(clone)})
            self.assertNotEqual(proc.returncode, 0, proc.stdout)
            self.assertEqual(proc.stdout.strip(), "")
            payload = json.loads(proc.stderr)
            self.assertEqual(payload["error"], "detached_head")
            fix = payload["fix"]
            self.assertNotIn("<", fix)
            self.assertNotIn(">", fix)
            checkout, separator, retry = fix.partition(" && ")
            self.assertTrue(separator)
            self.assertIn("tk run git.sync", retry)
            ran = subprocess.run(
                checkout,
                shell=True,
                cwd=str(clone),
                capture_output=True,
                text=True,
                env={**os.environ, **_identity()},
            )
            self.assertEqual(ran.returncode, 0, ran.stderr)
            self.assertEqual(_git(clone, "symbolic-ref", "--short", "HEAD").stdout.strip(), "fix/sync")
            synced = _run({"TK_ARG_REPO": str(clone)})
            self.assertEqual(synced.returncode, 0, synced.stderr)
            self.assertIs(json.loads(synced.stdout)["pushed"], True)
            self.assertEqual(_sha(origin, "refs/heads/main"), before)
            self.assertEqual(_sha(origin, "refs/heads/fix/sync"), _sha(clone, "HEAD"))


class GitSyncDryRunTests(unittest.TestCase):
    def test_dry_run_describes_feature_branch_sync_and_does_not_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "not-a-repo"
            sentinel = Path(tmp) / "untouched.txt"
            sentinel.write_text("keep\n", encoding="utf-8")
            proc = _run(
                {
                    "TK_ARG_REPO": str(missing),
                    "TK_ARG_REMOTE": "origin",
                    "TK_DRY_RUN": "1",
                }
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["repo"], str(missing))
            self.assertEqual(payload["remote"], "origin")
            self.assertEqual(payload.get("base"), "main")
            plan = payload.get("plan")
            self.assertIsInstance(plan, list)
            self.assertEqual(len(plan), 3)
            joined = " ".join(str(item) for item in plan).lower()
            self.assertIn("fetch", joined)
            self.assertIn("pull --rebase --autostash", joined)
            self.assertIn("push", joined)
            self.assertIn("main", joined)
            self.assertFalse(missing.exists())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep\n")
            self.assertEqual(list(Path(tmp).iterdir()), [sentinel])

    def test_header_and_example_describe_feature_branch_sync(self) -> None:
        text = SYNC.read_text(encoding="utf-8")
        self.assertIn("current feature branch", text)
        self.assertIn("# @tk-example: tk run git.sync --repo .", text)
        self.assertNotIn("--branch main", text)
        self.assertIn("Base branch to rebase onto", text)


class GitSyncFeatureBranchTests(unittest.TestCase):
    def test_rebases_onto_origin_main_and_pushes_current_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin, clone = _pair(Path(tmp))
            other = Path(tmp) / "other"
            subprocess.run(
                ["git", "clone", str(origin), str(other)],
                check=True,
                capture_output=True,
                text=True,
            )
            (other / "shared.txt").write_text("from-main\n", encoding="utf-8")
            _ok(other, "add", "shared.txt")
            _ok(other, "commit", "-m", "main moves")
            _ok(other, "push", "origin", "main")
            _ok(clone, "checkout", "-b", "fix/sync")
            (clone / "feature.txt").write_text("feature\n", encoding="utf-8")
            _ok(clone, "add", "feature.txt")
            _ok(clone, "commit", "-m", "feature work")
            proc = _run({"TK_ARG_REPO": str(clone)})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["branch"], "fix/sync")
            self.assertEqual(payload["base"], "main")
            self.assertEqual(payload["status"], "rebased")
            self.assertIs(payload["rebased"], True)
            self.assertIs(payload["pushed"], True)
            self.assertEqual(payload["behind"], 0)
            self.assertEqual((clone / "shared.txt").read_text(encoding="utf-8"), "from-main\n")
            self.assertEqual((clone / "feature.txt").read_text(encoding="utf-8"), "feature\n")
            self.assertEqual(_git(clone, "symbolic-ref", "--short", "HEAD").stdout.strip(), "fix/sync")
            self.assertEqual(_sha(origin, "refs/heads/fix/sync"), _sha(clone, "HEAD"))
            remote_log = _git(origin, "log", "--oneline", "fix/sync").stdout
            self.assertIn("feature work", remote_log)
            self.assertIn("main moves", remote_log)
            self.assertEqual(_sha(origin, "refs/heads/main"), _sha(other, "HEAD"))

    def test_up_to_date_feature_branch_is_still_pushed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin, clone = _pair(Path(tmp))
            main_before = _sha(origin, "refs/heads/main")
            _ok(clone, "checkout", "-b", "fix/sync")
            (clone / "feature.txt").write_text("feature\n", encoding="utf-8")
            _ok(clone, "add", "feature.txt")
            _ok(clone, "commit", "-m", "feature work")
            proc = _run({"TK_ARG_REPO": str(clone)})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["branch"], "fix/sync")
            self.assertEqual(payload["status"], "up_to_date")
            self.assertIs(payload["rebased"], False)
            self.assertIs(payload["pushed"], True)
            self.assertEqual(payload["behind"], 0)
            self.assertEqual(_sha(origin, "refs/heads/main"), main_before)
            self.assertEqual(_sha(origin, "refs/heads/fix/sync"), _sha(clone, "HEAD"))
            self.assertIn("feature work", _git(origin, "log", "--oneline", "fix/sync").stdout)


if __name__ == "__main__":
    unittest.main()
