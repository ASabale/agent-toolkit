"""wiki.lint rejects ASabale/agent-toolkit citations that are not on HEAD."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TK = ROOT / "tk"


def _run_lint(path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["TK_NO_TELEMETRY"] = "1"
    return subprocess.run(
        [sys.executable, str(TK), "run", "wiki.lint", "--path", str(path)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
        check=False,
    )


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Wiki Lint"
    env["GIT_AUTHOR_EMAIL"] = "wiki-lint@example.com"
    env["GIT_COMMITTER_NAME"] = "Wiki Lint"
    env["GIT_COMMITTER_EMAIL"] = "wiki-lint@example.com"
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


class WikiLintAncestorTests(unittest.TestCase):
    def test_non_ancestor_sha_is_an_error_with_squash_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.assertEqual(_git(repo, "init", "-b", "main").returncode, 0)
            self.assertEqual(_git(repo, "commit", "--allow-empty", "-m", "base").returncode, 0)
            self.assertEqual(_git(repo, "checkout", "-b", "side").returncode, 0)
            self.assertEqual(_git(repo, "commit", "--allow-empty", "-m", "side").returncode, 0)
            side = _git(repo, "rev-parse", "HEAD").stdout.strip()
            self.assertEqual(_git(repo, "checkout", "main").returncode, 0)
            head = _git(repo, "rev-parse", "HEAD").stdout.strip()
            wiki = repo / "wiki"
            wiki.mkdir()
            (wiki / "index.md").write_text(
                "# Index\n\n"
                "On 2026-11-04, `ASabale/agent-toolkit@" + head + "` is on HEAD.\n"
                "On 2026-11-04, `ASabale/agent-toolkit@" + side + "` is a branch commit.\n"
                "On 2026-11-04, `ASabale/agent-toolkit@aaaaaaaa` is not in this history.\n",
                encoding="utf-8",
            )
            proc = _run_lint(wiki)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            payload["bad_citations"],
            [
                {
                    "source": "index.md",
                    "sha": side,
                    "error": "not_ancestor",
                    "fix": "cite the squash commit on main",
                }
            ],
        )

    def test_missing_git_history_does_not_fail_the_citation(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = Path(tmp)
            (wiki / "index.md").write_text(
                "# Index\n\nOn 2026-11-04 see `ASabale/agent-toolkit@deadbee`.\n",
                encoding="utf-8",
            )
            proc = _run_lint(wiki)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["bad_citations"], [])


if __name__ == "__main__":
    unittest.main()
