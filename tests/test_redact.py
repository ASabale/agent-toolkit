"""Secret scanning and redaction at the public check, run, and telemetry seams."""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from lib.catalog import check_item
from lib.redact import redact, secret_hits
from lib.runner import run_tool


def _github():
    return "gh" + "p_" + ("a" * 20)


def _aws():
    return "AKIA" + ("B" * 16)


def _bearer():
    return "Bearer " + ("c" * 20)


def _private_key():
    return "-----BEGIN " + "RSA PRIVATE KEY-----"


def _slack():
    return "xox" + "b-" + ("1" * 10)


def _assignment():
    return "password=" + ("d" * 20)


def _item(path: Path) -> dict:
    return {
        "kind": "tool",
        "name": "demo.echo",
        "summary": "echo",
        "safety": "read-only",
        "args": [
            {
                "flag": "--name",
                "env_var": "TK_ARG_NAME",
                "required": True,
                "type": "string",
                "description": "Name",
                "default": None,
            }
        ],
        "output": "json",
        "example": "tk run demo.echo --name example",
        "verified": "none",
        "path": str(path),
    }


def _write_script(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


class RedactTests(unittest.TestCase):
    def test_rules_replace_matches_and_return_names_only(self):
        secrets = {
            "github_token": _github(),
            "aws_access_key": _aws(),
            "bearer": _bearer(),
            "private_key": _private_key(),
            "slack_token": _slack(),
            "assignment": _assignment(),
        }
        text = " ".join(secrets.values())
        cleaned = redact(text)
        self.assertEqual(secret_hits(text), list(secrets))
        for secret in secrets.values():
            self.assertNotIn(secret, cleaned)
            self.assertNotIn(secret, " ".join(secret_hits(text)))
        self.assertIn("***", cleaned)

    def test_keeps_short_assignments_and_ordinary_words(self):
        text = 'password=short {"password": "nope", "token": "keyboard"} tokenize'
        self.assertEqual(redact(text), text)
        self.assertEqual(secret_hits(text), [])

    def test_check_item_reports_secret_without_leaking_it(self):
        secret = _github()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = _write_script(
                root,
                "leak",
                "#!/usr/bin/env python3\n"
                "import sys\n"
                f"sys.stderr.write({secret!r})\n"
                "raise SystemExit(1)\n",
            )
            report = check_item(root, path)
        self.assertFalse(report["ok"])
        joined = "\n".join(report["errors"])
        self.assertIn("fix: tk check", joined)
        self.assertIn("secret in file (github_token)", joined)
        self.assertNotIn(secret, joined)

    def test_run_tool_redacts_secret_in_stderr_and_events(self):
        secret = _slack()
        previous_telemetry = os.environ.get("TK_NO_TELEMETRY")
        previous_state = os.environ.get("TK_STATE_DIR")
        try:
            os.environ["TK_NO_TELEMETRY"] = ""
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["TK_STATE_DIR"] = tmp
                root = Path(tmp)
                script = _write_script(
                    root,
                    "json-err",
                    "#!/usr/bin/env python3\n"
                    "import json, sys\n"
                    f"json.dump({{'error': 'nope', 'why': 'token ' + {secret!r}, 'fix': 'tk check'}}, sys.stderr)\n"
                    "raise SystemExit(2)\n",
                )
                code, out, err = run_tool(root, _item(script), {"--name": "ada"})
                events = (Path(tmp) / "events.jsonl").read_text(encoding="utf-8")
        finally:
            if previous_telemetry is None:
                os.environ.pop("TK_NO_TELEMETRY", None)
            else:
                os.environ["TK_NO_TELEMETRY"] = previous_telemetry
            if previous_state is None:
                os.environ.pop("TK_STATE_DIR", None)
            else:
                os.environ["TK_STATE_DIR"] = previous_state
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertNotIn(secret, err)
        self.assertIn("***", err)
        self.assertNotIn(secret, events)
        self.assertIn("***", events)

    def test_run_tool_leaves_ordinary_why_unchanged(self):
        previous_telemetry = os.environ.get("TK_NO_TELEMETRY")
        previous_state = os.environ.get("TK_STATE_DIR")
        try:
            os.environ["TK_NO_TELEMETRY"] = ""
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["TK_STATE_DIR"] = tmp
                root = Path(tmp)
                script = _write_script(
                    root,
                    "json-err",
                    "#!/usr/bin/env python3\n"
                    "import json, sys\n"
                    "json.dump({'error': 'nope', 'why': 'missing --repo', 'fix': 'tk check'}, sys.stderr)\n"
                    "raise SystemExit(2)\n",
                )
                code, _out, err = run_tool(root, _item(script), {"--name": "ada"})
                event = json.loads((Path(tmp) / "events.jsonl").read_text(encoding="utf-8"))
        finally:
            if previous_telemetry is None:
                os.environ.pop("TK_NO_TELEMETRY", None)
            else:
                os.environ["TK_NO_TELEMETRY"] = previous_telemetry
            if previous_state is None:
                os.environ.pop("TK_STATE_DIR", None)
            else:
                os.environ["TK_STATE_DIR"] = previous_state
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)["why"], "missing --repo")
        self.assertEqual(event["why"], "missing --repo")


if __name__ == "__main__":
    unittest.main()
