"""Edge cases for git digests, subprocess failures, and gh.triage-pr key picking."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.catalog import load_chain
from lib.runner import run_chain


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _run_tool(script: Path, env: dict, stdin: str = "") -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.update(env)
    merged["TK_DRY_RUN"] = "0"
    return subprocess.run(
        [sys.executable, str(script)],
        input=stdin,
        capture_output=True,
        text=True,
        env=merged,
    )


class BranchDigestUnbornTests(unittest.TestCase):
    def test_unborn_branch_with_untracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _git(repo, "init")
            (repo / "notes.txt").write_text("dirty\n", encoding="utf-8")
            proc = _run_tool(
                ROOT / "tools/git/branch-digest",
                {"TK_ARG_REPO": str(repo)},
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["branch"])
        self.assertNotEqual(payload["branch"], "HEAD")
        self.assertEqual(payload["ahead"], 0)
        self.assertEqual(payload["behind"], 0)
        self.assertIsNone(payload["upstream"])
        self.assertFalse(payload["detached"])
        self.assertGreaterEqual(payload["dirty"], 1)


class DiffDigestRenameTests(unittest.TestCase):
    def _repo_with_rename_and_edit(self) -> tempfile.TemporaryDirectory:
        tmp = tempfile.TemporaryDirectory()
        repo = Path(tmp.name)
        _git(repo, "init")
        _git(repo, "config", "user.email", "edge@example.com")
        _git(repo, "config", "user.name", "Edge")
        (repo / "old.txt").write_text("alpha\n", encoding="utf-8")
        (repo / "keep.txt").write_text("keep\n", encoding="utf-8")
        _git(repo, "add", "old.txt", "keep.txt")
        _git(repo, "commit", "-m", "base")
        _git(repo, "mv", "old.txt", "new.txt")
        (repo / "keep.txt").write_text("keep\nchanged\n", encoding="utf-8")
        return tmp

    def test_rename_is_one_file(self) -> None:
        tmp = self._repo_with_rename_and_edit()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name)
        # Isolate the rename: restore the second file so only the mv remains.
        _git(repo, "checkout", "--", "keep.txt")
        proc = _run_tool(
            ROOT / "tools/git/diff-digest",
            {"TK_ARG_REPO": str(repo), "TK_ARG_REF": "HEAD"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["files_changed"], 1)
        self.assertEqual(len(payload["files"]), 1)
        self.assertEqual(payload["files"][0]["path"], "new.txt")
        self.assertEqual(payload["files"][0]["status"], "renamed")
        self.assertEqual(payload["truncated"], 0)

    def test_limit_reports_truncated_count(self) -> None:
        tmp = self._repo_with_rename_and_edit()
        self.addCleanup(tmp.cleanup)
        proc = _run_tool(
            ROOT / "tools/git/diff-digest",
            {"TK_ARG_REPO": str(tmp.name), "TK_ARG_REF": "HEAD", "TK_ARG_LIMIT": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["files_changed"], 2)
        self.assertEqual(len(payload["files"]), 1)
        self.assertEqual(payload["truncated"], 1)


class TriageChainTests(unittest.TestCase):
    def test_dry_run_and_json_pick_preserves_keys(self) -> None:
        chain_path = ROOT / "chains/gh.triage-pr.json"
        raw = json.loads(chain_path.read_text(encoding="utf-8"))
        keys = raw["steps"][1]["args"]["keys"]
        self.assertEqual(keys, "repo,pr,fail,pending,pass")

        item = load_chain(chain_path)
        code, stdout, stderr = run_chain(
            ROOT,
            item,
            {"--repo": "owner/name", "--pr": "7"},
            dry_run=True,
        )
        self.assertEqual(code, 0, stderr)
        dry = json.loads(stdout)
        self.assertEqual(dry.get("keys"), ["repo", "pr", "fail", "pending", "pass"])

        mock = {
            "repo": "owner/name",
            "pr": 7,
            "fail": [{"name": "ci", "url": "https://example.test/ci"}],
            "pending": 2,
            "pass": 9,
            "noise": True,
        }
        proc = _run_tool(
            ROOT / "tools/json/pick",
            {"TK_ARG_KEYS": keys},
            stdin=json.dumps(mock),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        picked = json.loads(proc.stdout)
        self.assertEqual(
            picked,
            {
                "repo": "owner/name",
                "pr": 7,
                "fail": [{"name": "ci", "url": "https://example.test/ci"}],
                "pending": 2,
                "pass": 9,
            },
        )


if __name__ == "__main__":
    unittest.main()
