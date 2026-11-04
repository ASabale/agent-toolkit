"""Seams for catalog items that had no behavioral tests.

Covers git.branch-digest (the tool behind the retired git.repo-health chain)
plus docs.python-symbol, gh.issue-view, gh.search-code, py.test-digest, and
sys.port-owner. Issues #81, #97, and #88 own the other former misses.

Fake binaries sit on PATH. No network.
"""

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

_FAKE_GH_BODY = """
import json
import sys

args = sys.argv[1:]
if args[:2] == ["search", "code"]:
    sys.stdout.write(
        json.dumps(
            [
                {
                    "path": "lib/tk.py",
                    "repository": {"nameWithOwner": "cli/cli"},
                    "textMatches": [{"fragment": "def main():\\\\n    return 0"}],
                },
                {
                    "path": "tools/demo.py",
                    "repository": {"nameWithOwner": "cli/cli"},
                    "textMatches": [{"fragment": "print('hi')"}],
                },
            ]
        )
    )
elif args[:2] == ["issue", "view"]:
    sys.stdout.write(
        json.dumps(
            {
                "number": 7,
                "title": "Fix parser",
                "state": "OPEN",
                "author": {"login": "ada"},
                "url": "https://example.test/issues/7",
                "body": "hello world",
                "comments": [
                    {
                        "author": {"login": "bob"},
                        "body": "first note",
                        "createdAt": "2026-01-01T00:00:00Z",
                    },
                    {
                        "author": {"login": "cara"},
                        "body": "trailing comment",
                        "createdAt": "2026-01-02T00:00:00Z",
                    },
                ],
            }
        )
    )
else:
    sys.stderr.write("unexpected gh args\\n")
    raise SystemExit(2)
"""

_FAKE_LSOF = """#!/bin/sh
printf '%s\\n' 'p4242' 'cnginx' 'uwww' 'p4343' 'cpython' 'uada'
"""


def _run(script: Path, env: dict, stdin: str = "") -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    for key in list(merged):
        if key.startswith("TK_ARG_") or key == "TK_DRY_RUN":
            merged.pop(key, None)
    merged.update(env)
    merged.setdefault("TK_DRY_RUN", "0")
    return subprocess.run(
        [sys.executable, str(script)],
        input=stdin,
        capture_output=True,
        text=True,
        env=merged,
    )


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _write_fake_gh(path: Path, body: str = _FAKE_GH_BODY) -> None:
    _write_exec(path, f"#!{sys.executable}\n{body}")


def _with_bin_path(bin_dir: Path, env: dict) -> dict:
    merged = dict(env)
    merged["PATH"] = str(bin_dir)
    return merged


def _git(repo: Path, *args: str) -> None:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Ada"
    env["GIT_AUTHOR_EMAIL"] = "ada@example.com"
    env["GIT_COMMITTER_NAME"] = "Ada"
    env["GIT_COMMITTER_EMAIL"] = "ada@example.com"
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)


def _sample_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "ada@example.com")
    _git(repo, "config", "user.name", "Ada")
    (repo / "readme.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "readme.txt")
    _git(repo, "commit", "-m", "init")
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    return repo


def _stderr_error(proc: subprocess.CompletedProcess[str]) -> dict:
    self_check = proc.stdout.strip()
    if self_check:
        raise AssertionError(f"expected empty stdout, got {proc.stdout!r}")
    return json.loads(proc.stderr)


class RepoHealthChainTests(unittest.TestCase):
    def test_success_reports_branch_health_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _sample_repo(Path(tmp))
            env = os.environ.copy()
            env["TK_NO_TELEMETRY"] = "1"
            proc = subprocess.run(
                [str(ROOT / "tk"), "run", "git.branch-digest", "--repo", str(repo)],
                capture_output=True,
                text=True,
                env=env,
                cwd=ROOT,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(
            set(payload),
            {"branch", "ahead", "behind", "dirty", "detached", "upstream"},
        )
        self.assertTrue(payload["branch"])
        self.assertFalse(payload["detached"])
        self.assertGreaterEqual(payload["dirty"], 1)

    def test_error_when_path_is_not_a_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["TK_NO_TELEMETRY"] = "1"
            proc = subprocess.run(
                [str(ROOT / "tk"), "run", "git.branch-digest", "--repo", tmp],
                capture_output=True,
                text=True,
                env=env,
                cwd=ROOT,
            )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        err = json.loads(proc.stderr)
        self.assertEqual(err["error"], "not_a_repo")
        self.assertIn("fix", err)


class DocsPythonSymbolTests(unittest.TestCase):
    def test_success_distills_stdlib_function(self) -> None:
        proc = _run(
            ROOT / "tools/docs/python-symbol",
            {"TK_ARG_TARGET": "json.dumps", "TK_ARG_MAX_LINES": "8"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["target"], "json.dumps")
        self.assertEqual(payload["kind"], "function")
        self.assertIn("obj", payload["signature"])
        self.assertTrue(payload["summary"])
        self.assertTrue(payload["doc"])
        self.assertLessEqual(len(payload["doc"].splitlines()), 8)

    def test_error_unknown_symbol(self) -> None:
        proc = _run(
            ROOT / "tools/docs/python-symbol",
            {"TK_ARG_TARGET": "no_such_tk_module.Nope"},
        )
        self.assertEqual(proc.returncode, 1)
        err = _stderr_error(proc)
        self.assertEqual(err["error"], "symbol_not_found")
        self.assertIn("tk run docs.python-symbol --target", err["fix"])


class GhIssueViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.bin_dir = Path(self._td.name)
        _write_fake_gh(self.bin_dir / "gh")

    def test_success_keeps_trailing_comments(self) -> None:
        proc = _run(
            ROOT / "tools/gh/issue-view",
            _with_bin_path(
                self.bin_dir,
                {
                    "TK_ARG_REPO": "cli/cli",
                    "TK_ARG_NUMBER": "7",
                    "TK_ARG_COMMENTS": "1",
                },
            ),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["repo"], "cli/cli")
        self.assertEqual(payload["number"], 7)
        self.assertEqual(payload["title"], "Fix parser")
        self.assertEqual(payload["state"], "OPEN")
        self.assertEqual(payload["author"], "ada")
        self.assertEqual(payload["url"], "https://example.test/issues/7")
        self.assertEqual(payload["body"], "hello world")
        self.assertEqual(
            payload["comments"],
            [
                {
                    "author": "cara",
                    "body": "trailing comment",
                    "created_at": "2026-01-02T00:00:00Z",
                }
            ],
        )

    def test_error_negative_comments(self) -> None:
        proc = _run(
            ROOT / "tools/gh/issue-view",
            _with_bin_path(
                self.bin_dir,
                {
                    "TK_ARG_REPO": "cli/cli",
                    "TK_ARG_NUMBER": "7",
                    "TK_ARG_COMMENTS": "-1",
                },
            ),
        )
        self.assertEqual(proc.returncode, 2)
        err = _stderr_error(proc)
        self.assertEqual(err["error"], "invalid_flag")
        self.assertIn("--comments 5", err["fix"])


class GhSearchCodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.bin_dir = Path(self._td.name)
        _write_fake_gh(self.bin_dir / "gh")

    def test_success_clips_snippets(self) -> None:
        proc = _run(
            ROOT / "tools/gh/search-code",
            _with_bin_path(
                self.bin_dir,
                {
                    "TK_ARG_QUERY": "def main",
                    "TK_ARG_REPO": "cli/cli",
                    "TK_ARG_LIMIT": "5",
                },
            ),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["query"], "def main")
        self.assertEqual(payload["repo"], "cli/cli")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["matches"][0]["repo"], "cli/cli")
        self.assertEqual(payload["matches"][0]["path"], "lib/tk.py")
        self.assertIn("def main():", payload["matches"][0]["snippet"])
        self.assertNotIn("\n", payload["matches"][0]["snippet"])

    def test_error_gh_failed(self) -> None:
        _write_exec(
            self.bin_dir / "gh",
            "#!/bin/sh\necho 'API rate limit' >&2\nexit 1\n",
        )
        proc = _run(
            ROOT / "tools/gh/search-code",
            _with_bin_path(
                self.bin_dir,
                {"TK_ARG_QUERY": "def main", "TK_ARG_REPO": "all", "TK_ARG_LIMIT": "5"},
            ),
        )
        self.assertEqual(proc.returncode, 1)
        err = _stderr_error(proc)
        self.assertEqual(err["error"], "gh_failed")
        self.assertIn("API rate limit", err["why"])


class PyTestDigestTests(unittest.TestCase):
    def test_success_counts_passing_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            suite = Path(tmp) / "suite"
            suite.mkdir()
            (suite / "test_ok.py").write_text(
                "import unittest\n"
                "class OkTests(unittest.TestCase):\n"
                "    def test_pass(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            proc = _run(
                ROOT / "tools/py/test-digest",
                {"TK_ARG_PATH": str(suite), "TK_ARG_PATTERN": "test*.py"},
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["ran"], 1)
        self.assertEqual(payload["failed"], 0)
        self.assertEqual(payload["errors"], 0)
        self.assertEqual(payload["failures"], [])

    def test_error_path_is_not_a_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "not-a-dir.py"
            file_path.write_text("x = 1\n", encoding="utf-8")
            proc = _run(
                ROOT / "tools/py/test-digest",
                {"TK_ARG_PATH": str(file_path)},
            )
        self.assertEqual(proc.returncode, 1)
        err = _stderr_error(proc)
        self.assertEqual(err["error"], "not_a_directory")
        self.assertIn(str(file_path), err["why"])


class SysPortOwnerTests(unittest.TestCase):
    def test_success_parses_lsof_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            _write_exec(bin_dir / "lsof", _FAKE_LSOF)
            proc = _run(
                ROOT / "tools/sys/port-owner",
                _with_bin_path(bin_dir, {"TK_ARG_PORT": "80"}),
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            {
                "port": 80,
                "listen": [
                    {"pid": 4242, "cmd": "nginx", "user": "www"},
                    {"pid": 4343, "cmd": "python", "user": "ada"},
                ],
            },
        )

    def test_error_port_out_of_range(self) -> None:
        proc = _run(ROOT / "tools/sys/port-owner", {"TK_ARG_PORT": "0"})
        self.assertEqual(proc.returncode, 2)
        err = _stderr_error(proc)
        self.assertEqual(err["error"], "invalid_flag")
        self.assertEqual(err["why"], "port must be 1-65535")
        self.assertEqual(err["fix"], "tk run sys.port-owner --port 80")


if __name__ == "__main__":
    unittest.main()
