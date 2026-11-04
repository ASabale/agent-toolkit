"""Local-fixture seams for distilled http.json-get and bounded code.search."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSON_GET = ROOT / "tools/http/json-get"
SEARCH = ROOT / "tools/code/search"
_MAX_DEFAULT_BYTES = 2048


def _repo_fixture() -> dict:
    pad = 0
    while True:
        doc = {
            "id": 1296269,
            "name": "Hello-World",
            "full_name": "octocat/Hello-World",
            "private": False,
            "owner": {
                "login": "octocat",
                "id": 1,
                "node_id": "MDQ6VXNlcjE=",
                "avatar_url": "https://avatars.githubusercontent.com/u/1?v=4",
                "url": "https://api.github.com/users/octocat",
                "html_url": "https://github.com/octocat",
                "type": "User",
                "site_admin": False,
            },
            "html_url": "https://github.com/octocat/Hello-World",
            "description": "GitHub repo fixture used to measure default json-get size. " + ("x" * pad),
            "fork": False,
            "stargazers_count": 1842,
            "watchers_count": 1842,
            "language": "Python",
            "forks_count": 17,
            "open_issues_count": 3,
            "default_branch": "master",
            "license": {
                "key": "mit",
                "name": "MIT License",
                "spdx_id": "MIT",
                "url": "https://api.github.com/licenses/mit",
            },
            "topics": ["demo", "hello-world", "fixture"],
            "visibility": "public",
            "archived": False,
            "disabled": False,
            "readme": "Lorem ipsum dolor sit amet. " * 40,
        }
        size = len(json.dumps(doc, separators=(",", ":")).encode("utf-8"))
        if size >= 5259:
            return doc
        pad += max(1, 5259 - size)


REPO_FIXTURE = _repo_fixture()


class _RepoHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/repos":
            body = json.dumps(REPO_FIXTURE).encode("utf-8")
        elif self.path == "/tiny":
            body = json.dumps({"ok": True, "n": 1}).encode("utf-8")
        elif self.path == "/items":
            body = json.dumps(
                [
                    {"owner": {"login": "ada"}, "stargazers_count": 3, "name": "a"},
                    {"owner": {"login": "grace"}, "stargazers_count": 9, "name": "b"},
                ]
            ).encode("utf-8")
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


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


class JsonGetDistillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _RepoHandler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join, 2)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def test_nested_keys_rebuild_owner_login(self) -> None:
        self.assertGreaterEqual(
            len(json.dumps(REPO_FIXTURE, separators=(",", ":")).encode("utf-8")),
            5259,
        )
        proc = _run(
            JSON_GET,
            {
                "TK_ARG_URL": f"{self.base}/repos",
                "TK_ARG_KEYS": "owner.login,stargazers_count",
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload, {"owner": {"login": "octocat"}, "stargazers_count": 1842})
        self.assertNotIn("truncated", payload)

    def test_default_repo_output_is_capped_with_fix(self) -> None:
        proc = _run(JSON_GET, {"TK_ARG_URL": f"{self.base}/repos"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        raw = proc.stdout.encode("utf-8")
        self.assertLess(len(raw), 5000)
        self.assertLessEqual(len(raw.rstrip(b"\n")), _MAX_DEFAULT_BYTES)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["truncated"])
        self.assertIn("fix", payload)
        self.assertTrue(payload["fix"].startswith("tk run http.json-get --url "))
        self.assertIn("--keys", payload["fix"])
        self.assertIn("owner.login", payload["fix"])
        self.assertIn("stargazers_count", payload)
        self.assertNotIn("description", payload)

    def test_small_default_payload_is_unchanged(self) -> None:
        proc = _run(JSON_GET, {"TK_ARG_URL": f"{self.base}/tiny"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {"ok": True, "n": 1})

    def test_nested_keys_on_array(self) -> None:
        proc = _run(
            JSON_GET,
            {
                "TK_ARG_URL": f"{self.base}/items",
                "TK_ARG_KEYS": "owner.login,stargazers_count",
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            [
                {"owner": {"login": "ada"}, "stargazers_count": 3},
                {"owner": {"login": "grace"}, "stargazers_count": 9},
            ],
        )


class CodeSearchBoundTests(unittest.TestCase):
    def _fixture(self) -> tempfile.TemporaryDirectory:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        for index in range(40):
            (root / f"hit{index:02d}.py").write_text(
                f"needle {'x' * 200}\nkeep {index}\n",
                encoding="utf-8",
            )
        (root / "skip.js").write_text("no match here\n", encoding="utf-8")
        return tmp

    def test_default_output_is_bounded_and_lines_trimmed(self) -> None:
        tmp = self._fixture()
        self.addCleanup(tmp.cleanup)
        proc = _run(SEARCH, {"TK_ARG_PATH": tmp.name, "TK_ARG_PATTERN": "needle"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        raw = proc.stdout.encode("utf-8")
        self.assertLess(len(raw), 5000)
        self.assertLessEqual(len(raw.rstrip(b"\n")), _MAX_DEFAULT_BYTES)
        payload = json.loads(proc.stdout)
        self.assertLessEqual(payload["count"], 30)
        self.assertEqual(payload["count"], len(payload["matches"]))
        self.assertGreaterEqual(payload["truncated"], 1)
        self.assertTrue(payload["matches"])
        self.assertTrue(all(len(item["text"]) <= 160 for item in payload["matches"]))
        self.assertTrue(all(item["text"].startswith("needle ") for item in payload["matches"]))

    def test_explicit_low_limit_keeps_omitted_count(self) -> None:
        tmp = self._fixture()
        self.addCleanup(tmp.cleanup)
        proc = _run(
            SEARCH,
            {
                "TK_ARG_PATH": tmp.name,
                "TK_ARG_PATTERN": "needle",
                "TK_ARG_LIMIT": "2",
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["truncated"], 38)


if __name__ == "__main__":
    unittest.main()
