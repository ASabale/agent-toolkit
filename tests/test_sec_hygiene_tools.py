"""Seams for sec.secret-scan and code.todos."""

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

    def test_specific_rule_suppresses_overlapping_generic_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cfg.py").write_text(
                f'api_key = "{GITHUB}"\n',
                encoding="utf-8",
            )
            hidden = root / ".secrets"
            hidden.mkdir()
            (hidden / "extra.txt").write_text(f"{GITHUB}\n", encoding="utf-8")
            proc = _run(SECRET_SCAN, {"TK_ARG_PATH": tmp, "TK_ARG_LIMIT": "25"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn(GITHUB, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(
            [(row["rule"], row["file"], row["line"]) for row in payload["findings"]],
            [("github_token", "cfg.py", 1)],
        )
        self.assertIn("****", payload["findings"][0]["preview"])

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

    def test_ignores_tk_headers_prose_and_string_literals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sample.py").write_text(
                "\n".join(
                    [
                        "# @tk-summary: List TODO, FIXME, and similar tags",
                        "# See TODO, FIXME, and BUG tags",
                        "# TODO: real work",
                        "text = '''",
                        "# TODO: inside a string",
                        "'''",
                        "# FIXME: also real",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            script = root / "tool"
            script.write_text(
                "#!/usr/bin/env python3\n"
                'doc = """\n'
                "# TODO: shebang string\n"
                '"""\n'
                "# BUG: shebang comment\n",
                encoding="utf-8",
            )
            prose = root / "notes.txt"
            prose.write_text(
                "# See TODO, FIXME, and BUG tags\n# TODO: keep this\n",
                encoding="utf-8",
            )
            proc = _run(TODOS, {"TK_ARG_PATH": tmp, "TK_ARG_LIMIT": "30"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(
            [(row["file"], row["tag"], row["text"]) for row in payload["items"]],
            [
                ("notes.txt", "TODO", "keep this"),
                ("sample.py", "TODO", "real work"),
                ("sample.py", "FIXME", "also real"),
                ("tool", "BUG", "shebang comment"),
            ],
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


class SecretScanCliTests(unittest.TestCase):
    def test_run_keeps_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "leak.txt").write_text(GITHUB + "\n", encoding="utf-8")
            env = os.environ.copy()
            env["TK_NO_TELEMETRY"] = "1"
            env.pop("TK_STATE_DIR", None)
            proc = subprocess.run(
                [str(ROOT / "tk"), "run", "sec.secret-scan", "--path", tmp, "--limit", "25"],
                capture_output=True,
                text=True,
                env=env,
                cwd=ROOT,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn(GITHUB, proc.stdout)
        self.assertNotIn(GITHUB, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIn("truncated", payload)
        self.assertFalse(payload["truncated"])
        self.assertFalse(payload["clean"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["findings"][0]["rule"], "github_token")
        self.assertIn("****", payload["findings"][0]["preview"])
        missing = subprocess.run(
            [str(ROOT / "tk"), "find", "sec.repo-hygiene"],
            capture_output=True,
            text=True,
            env=env,
            cwd=ROOT,
        )
        self.assertEqual(missing.returncode, 0, missing.stderr)
        self.assertNotIn("sec.repo-hygiene", missing.stdout)


if __name__ == "__main__":
    unittest.main()
