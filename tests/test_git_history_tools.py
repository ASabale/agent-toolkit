"""Seams for git.blame-slice, git.hotspots, git.branch-digest, and git.log-recent."""

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLAME = ROOT / "tools/git/blame-slice"
HOTSPOTS = ROOT / "tools/git/hotspots"
DIGEST = ROOT / "tools/git/branch-digest"
LOG = ROOT / "tools/git/log-recent"


def _run(script: Path, env: dict) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    for key in list(merged):
        if key.startswith("TK_ARG_") or key == "TK_DRY_RUN":
            merged.pop(key, None)
    merged.update(env)
    merged.setdefault("TK_DRY_RUN", "0")
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=merged,
    )


def _git(repo: Path, *args: str, author: str) -> None:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = author
    env["GIT_AUTHOR_EMAIL"] = f"{author.lower()}@example.com"
    env["GIT_COMMITTER_NAME"] = author
    env["GIT_COMMITTER_EMAIL"] = f"{author.lower()}@example.com"
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
    _git(repo, "init", author="Alice")
    notes = repo / "notes.txt"
    notes.write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")
    (repo / "alpha.txt").write_text("alpha\n", encoding="utf-8")
    (repo / "beta.txt").write_text("beta\n", encoding="utf-8")
    _git(repo, "add", "notes.txt", "alpha.txt", "beta.txt", author="Alice")
    _git(repo, "commit", "-m", "first note", author="Alice")
    notes.write_text("one\ntwo\nCHANGED\nAGAIN\nfive\n", encoding="utf-8")
    (repo / "alpha.txt").write_text("alpha2\n", encoding="utf-8")
    _git(repo, "add", "notes.txt", "alpha.txt", author="Bob")
    _git(repo, "commit", "-m", "second note", author="Bob")
    return repo


class BlameSliceTests(unittest.TestCase):
    def test_groups_consecutive_lines_by_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _sample_repo(Path(tmp))
            proc = _run(
                BLAME,
                {
                    "TK_ARG_REPO": str(repo),
                    "TK_ARG_FILE": "notes.txt",
                    "TK_ARG_START": "1",
                    "TK_ARG_END": "5",
                },
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["file"], "notes.txt")
        self.assertEqual(payload["start"], 1)
        self.assertEqual(payload["end"], 5)
        hunks = payload["hunks"]
        self.assertEqual(len(hunks), 3)
        self.assertEqual(
            [(h["start_line"], h["end_line"]) for h in hunks],
            [(1, 2), (3, 4), (5, 5)],
        )
        self.assertEqual(hunks[0]["author"], "Alice")
        self.assertEqual(hunks[0]["summary"], "first note")
        self.assertEqual(len(hunks[0]["sha"]), 40)
        self.assertEqual(hunks[1]["author"], "Bob")
        self.assertEqual(hunks[1]["summary"], "second note")
        self.assertNotEqual(hunks[0]["sha"], hunks[1]["sha"])
        self.assertEqual(hunks[2]["sha"], hunks[0]["sha"])
        self.assertTrue(hunks[0]["date"])

    def test_default_end_on_short_file_clamps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _git(repo, "init", author="Alice")
            notes = repo / "short.txt"
            notes.write_text("one\ntwo\n", encoding="utf-8")
            _git(repo, "add", "short.txt", author="Alice")
            _git(repo, "commit", "-m", "short", author="Alice")
            proc = _run(
                BLAME,
                {
                    "TK_ARG_REPO": str(repo),
                    "TK_ARG_FILE": "short.txt",
                },
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["start"], 1)
        self.assertEqual(payload["end"], 40)
        self.assertEqual(
            [(h["start_line"], h["end_line"]) for h in payload["hunks"]],
            [(1, 2)],
        )
        self.assertEqual(payload["hunks"][0]["summary"], "short")

    def test_start_past_eof_is_invalid_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _git(repo, "init", author="Alice")
            (repo / "short.txt").write_text("one\ntwo\n", encoding="utf-8")
            _git(repo, "add", "short.txt", author="Alice")
            _git(repo, "commit", "-m", "short", author="Alice")
            proc = _run(
                BLAME,
                {
                    "TK_ARG_REPO": str(repo),
                    "TK_ARG_FILE": "short.txt",
                    "TK_ARG_START": "99",
                },
            )
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(proc.stdout, "")
        payload = json.loads(proc.stderr)
        self.assertEqual(payload["error"], "invalid_range")
        self.assertEqual(
            payload["why"],
            "--start 99 exceeds file length (2 lines)",
        )
        self.assertIn("--start 1 --end 2", payload["fix"])

    def test_missing_file_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _sample_repo(Path(tmp))
            proc = _run(
                BLAME,
                {
                    "TK_ARG_REPO": str(repo),
                    "TK_ARG_FILE": "missing.txt",
                    "TK_ARG_START": "1",
                    "TK_ARG_END": "5",
                },
            )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        payload = json.loads(proc.stderr)
        self.assertEqual(payload["error"], "missing_file")
        self.assertIn("missing.txt", payload["why"])

    def test_dry_run_skips_git(self) -> None:
        proc = _run(
            BLAME,
            {
                "TK_ARG_REPO": "example",
                "TK_ARG_FILE": "example",
                "TK_DRY_RUN": "1",
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            {
                "dry_run": True,
                "repo": "example",
                "file": "example",
                "start": 1,
                "end": 40,
            },
        )


class HotspotTests(unittest.TestCase):
    def test_ranks_files_and_truncates_at_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _sample_repo(Path(tmp))
            proc = _run(
                HOTSPOTS,
                {
                    "TK_ARG_REPO": str(repo),
                    "TK_ARG_MAX_COMMITS": "100",
                    "TK_ARG_LIMIT": "1",
                },
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["commits_scanned"], 2)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(len(payload["hotspots"]), 1)
        top = payload["hotspots"][0]
        self.assertEqual(top["file"], "alpha.txt")
        self.assertEqual(top["commits"], 2)
        self.assertEqual(top["authors"], 2)

    def test_empty_repo_reports_no_hotspots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _git(repo, "init", author="Alice")
            proc = _run(HOTSPOTS, {"TK_ARG_REPO": str(repo)})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            {
                "repo": str(repo),
                "commits_scanned": 0,
                "count": 0,
                "truncated": False,
                "hotspots": [],
            },
        )

    def test_dry_run_skips_git(self) -> None:
        proc = _run(
            HOTSPOTS,
            {
                "TK_ARG_REPO": "example",
                "TK_ARG_MAX_COMMITS": "50",
                "TK_ARG_LIMIT": "10",
                "TK_DRY_RUN": "1",
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            {
                "dry_run": True,
                "repo": "example",
                "max_commits": 50,
                "limit": 10,
            },
        )


class BranchDigestTests(unittest.TestCase):
    def test_dry_run_echoes_flags_and_reports_no_results(self) -> None:
        proc = _run(
            DIGEST,
            {
                "TK_ARG_REPO": "example",
                "TK_DRY_RUN": "1",
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(
            payload,
            {
                "dry_run": True,
                "repo": "example",
                "branch": None,
                "ahead": None,
                "behind": None,
                "dirty": None,
                "detached": None,
                "upstream": None,
            },
        )
        self.assertIs(payload["dry_run"], True)
        self.assertIsNone(payload["branch"])
        self.assertIsNone(payload["dirty"])


class LogRecentTests(unittest.TestCase):
    def test_dry_run_echoes_flags_and_reports_no_results(self) -> None:
        proc = _run(
            LOG,
            {
                "TK_ARG_REPO": "example",
                "TK_ARG_LIMIT": "3",
                "TK_DRY_RUN": "1",
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(
            payload,
            {
                "dry_run": True,
                "repo": "example",
                "limit": 3,
                "count": None,
                "commits": [],
            },
        )
        self.assertIs(payload["dry_run"], True)
        self.assertIsNone(payload["count"])

    def test_real_repo_returns_newest_subjects_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _sample_repo(Path(tmp))
            extra = repo / "gamma.txt"
            extra.write_text("gamma\n", encoding="utf-8")
            _git(repo, "add", "gamma.txt", author="Carol")
            _git(repo, "commit", "-m", "third note", author="Carol")
            proc = _run(
                LOG,
                {
                    "TK_ARG_REPO": str(repo),
                    "TK_ARG_LIMIT": "2",
                    "TK_DRY_RUN": "0",
                },
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertNotIn("dry_run", payload)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(len(payload["commits"]), 2)
        self.assertEqual(payload["commits"][0]["subject"], "third note")
        self.assertEqual(payload["commits"][1]["subject"], "second note")
        self.assertEqual(len(payload["commits"][0]["sha"]), 40)
        self.assertEqual(payload["commits"][0]["author"], "Carol")

    def test_bad_limit_errors_in_dry_run_and_real_modes(self) -> None:
        cases = (
            ("abc", "limit is not an int: abc"),
            ("0", "limit must be >= 1"),
            ("-3", "limit must be >= 1"),
        )
        for dry in ("1", "0"):
            for raw, why in cases:
                with self.subTest(dry_run=dry, limit=raw):
                    proc = _run(
                        LOG,
                        {
                            "TK_ARG_REPO": "example",
                            "TK_ARG_LIMIT": raw,
                            "TK_DRY_RUN": dry,
                        },
                    )
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertEqual(proc.stdout, "")
                    payload = json.loads(proc.stderr)
                    fix = "tk run git.log-recent --repo example --limit 5"
                    if dry == "1":
                        fix += " --dry-run"
                    self.assertEqual(
                        payload,
                        {
                            "error": "invalid_flag",
                            "why": why,
                            "fix": fix,
                        },
                    )
        missing_repo = _run(LOG, {"TK_ARG_LIMIT": "nope", "TK_DRY_RUN": "0"})
        self.assertEqual(
            json.loads(missing_repo.stderr)["fix"],
            "tk run git.log-recent --repo . --limit 5",
        )

    def test_invalid_limit_fix_runs_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spaced = Path(tmp) / "my repo"
            spaced.mkdir()
            repo = _sample_repo(spaced)
            repo_text = str(repo)
            self.assertIn(" ", repo_text)
            for dry in ("0", "1"):
                with self.subTest(dry_run=dry):
                    proc = _run(
                        LOG,
                        {
                            "TK_ARG_REPO": repo_text,
                            "TK_ARG_LIMIT": "0",
                            "TK_DRY_RUN": dry,
                        },
                    )
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertEqual(proc.stdout, "")
                    payload = json.loads(proc.stderr)
                    self.assertEqual(payload["error"], "invalid_flag")
                    expected = [
                        "tk",
                        "run",
                        "git.log-recent",
                        "--repo",
                        repo_text,
                        "--limit",
                        "5",
                    ]
                    if dry == "1":
                        expected.append("--dry-run")
                    argv = shlex.split(payload["fix"])
                    self.assertEqual(argv, expected)
                    self.assertIn(shlex.quote(repo_text), payload["fix"])
                    argv[0] = "./tk"
                    env = os.environ.copy()
                    for key in list(env):
                        if key.startswith("TK_ARG_") or key == "TK_DRY_RUN":
                            env.pop(key, None)
                    env["TK_NO_TELEMETRY"] = "1"
                    healed = subprocess.run(
                        argv,
                        capture_output=True,
                        text=True,
                        cwd=ROOT,
                        env=env,
                        check=False,
                    )
                    self.assertEqual(healed.returncode, 0, healed.stderr + healed.stdout)
                    healed_payload = json.loads(healed.stdout)
                    self.assertNotIn("error", healed_payload)
                    self.assertEqual(healed_payload["repo"], repo_text)
                    if dry == "1":
                        self.assertIs(healed_payload["dry_run"], True)
                        self.assertEqual(healed_payload["limit"], 5)
                        self.assertIsNone(healed_payload["count"])
                    else:
                        self.assertNotIn("dry_run", healed_payload)
                        self.assertEqual(healed_payload["count"], 2)
                        self.assertEqual(len(healed_payload["commits"]), 2)


if __name__ == "__main__":
    unittest.main()
