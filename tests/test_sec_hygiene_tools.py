"""Seams for sec.secret-scan, code.todos, and sec.repo-hygiene."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET_SCAN = ROOT / "tools/sec/secret-scan"
TODOS = ROOT / "tools/code/todos"
CHAIN = ROOT / "chains/sec.repo-hygiene.json"

GITHUB = "ghp_" + ("A" * 30)
AWS = "AKIA" + ("B" * 16)


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


class SecretScanTests(unittest.TestCase):
    def test_detects_tokens_and_never_prints_raw_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text(
                f'gh = "{GITHUB}"\naws = "{AWS}"\n',
                encoding="utf-8",
            )
            skipped = root / "node_modules"
            skipped.mkdir()
            (skipped / "pkg.js").write_text(f'const t = "{GITHUB}"\n', encoding="utf-8")
            (root / "blob.bin").write_bytes(b"\x00" + AWS.encode() + b"\n")
            proc = _run(SECRET_SCAN, {"TK_ARG_PATH": tmp, "TK_ARG_LIMIT": "25"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn(GITHUB, proc.stdout)
        self.assertNotIn(GITHUB, proc.stderr)
        self.assertNotIn(AWS, proc.stdout)
        self.assertNotIn(AWS, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["clean"])
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["truncated"], False)
        rules = {row["rule"] for row in payload["findings"]}
        self.assertEqual(rules, {"github_token", "aws_access_key"})
        for row in payload["findings"]:
            self.assertIn("****", row["preview"])
            self.assertNotIn(GITHUB, row["preview"])
            self.assertNotIn(AWS, row["preview"])
        gh = next(row for row in payload["findings"] if row["rule"] == "github_token")
        self.assertEqual(gh["preview"], "ghp_****AA")
        aws = next(row for row in payload["findings"] if row["rule"] == "aws_access_key")
        self.assertEqual(aws["preview"], "AKIA****BB")
        self.assertEqual(gh["file"], "app.py")
        self.assertEqual(gh["line"], 1)

    def test_dry_run(self) -> None:
        proc = _run(
            SECRET_SCAN,
            {"TK_ARG_PATH": ".", "TK_ARG_LIMIT": "20", "TK_DRY_RUN": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            {"dry_run": True, "path": ".", "limit": 20},
        )


class TodosTests(unittest.TestCase):
    def test_comment_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.py"
            path.write_text(
                "# TODO: fix edge case\n// FIXME(auth): token expiry\nnot a todo\n",
                encoding="utf-8",
            )
            proc = _run(TODOS, {"TK_ARG_PATH": str(path), "TK_ARG_LIMIT": "30"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["truncated"], False)
        self.assertEqual(
            [(row["tag"], row["text"], row["line"]) for row in payload["items"]],
            [("TODO", "fix edge case", 1), ("FIXME", "token expiry", 2)],
        )

    def test_dry_run(self) -> None:
        proc = _run(
            TODOS,
            {
                "TK_ARG_PATH": ".",
                "TK_ARG_TAGS": "TODO,FIXME",
                "TK_ARG_LIMIT": "20",
                "TK_DRY_RUN": "1",
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            {"dry_run": True, "path": ".", "tags": "TODO,FIXME", "limit": 20},
        )


class RepoHygieneTests(unittest.TestCase):
    def test_chain_contract_and_run(self) -> None:
        raw = json.loads(CHAIN.read_text(encoding="utf-8"))
        self.assertEqual(raw["name"], "sec.repo-hygiene")
        self.assertEqual(raw["verified"], "2026-11-04")
        self.assertEqual(raw["args"][0]["flag"], "--path")
        self.assertTrue(raw["args"][0]["required"])
        self.assertEqual(raw["args"][0]["type"], "string")
        self.assertEqual(raw["steps"][0]["tool"], "sec.secret-scan")
        self.assertEqual(raw["steps"][0]["args"], {"path": "$input.path"})
        self.assertEqual(raw["steps"][1]["tool"], "json.pick")
        self.assertEqual(
            raw["steps"][1]["args"]["keys"],
            "path,clean,count,truncated,findings",
        )
        self.assertEqual(raw["example"], "tk run sec.repo-hygiene --path .")

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "leak.txt").write_text(GITHUB + "\n", encoding="utf-8")
            env = os.environ.copy()
            env["TK_NO_TELEMETRY"] = "1"
            proc = subprocess.run(
                [str(ROOT / "tk"), "run", "sec.repo-hygiene", "--path", tmp],
                capture_output=True,
                text=True,
                env=env,
                cwd=ROOT,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn(GITHUB, proc.stdout)
        self.assertNotIn(GITHUB, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(set(payload), {"path", "clean", "count", "truncated", "findings"})
        self.assertFalse(payload["clean"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["findings"][0]["rule"], "github_token")
        self.assertIn("****", payload["findings"][0]["preview"])


if __name__ == "__main__":
    unittest.main()
