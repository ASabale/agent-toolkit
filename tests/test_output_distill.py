"""Local-fixture seams for distilled http.json-get and bounded code.search."""

import json
import os
import shlex
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
OVERSIZE_REPO_FIXTURE = {
    "name": "Hello-World",
    "full_name": "octocat/Hello-World",
    "owner": {"login": "octocat", "id": 1},
    "description": "GitHub repo fixture used to measure default json-get size.",
    "stargazers_count": 1842,
    "blob": "x" * 3000,
}
OVERSIZE_ARRAY_FIXTURE = [
    {"id": index, "name": f"item-{index:02d}", "desc": "y" * 80}
    for index in range(50)
]
BULK_ARRAY_FIXTURE = [
    {"id": index, "name": f"n{index}", "desc": "y" * 8}
    for index in range(2000)
]


class _RepoHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/repos":
            body = json.dumps(REPO_FIXTURE).encode("utf-8")
        elif path == "/repo":
            body = json.dumps(OVERSIZE_REPO_FIXTURE).encode("utf-8")
        elif path == "/list":
            body = json.dumps(OVERSIZE_ARRAY_FIXTURE).encode("utf-8")
        elif path == "/bulk":
            body = json.dumps(BULK_ARRAY_FIXTURE).encode("utf-8")
        elif path == "/tiny":
            body = json.dumps({"ok": True, "n": 1}).encode("utf-8")
        elif path == "/items":
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

    def _oversize_query_url(self) -> str:
        return f"{self.base}/repo?a=1&b=2"

    def _oversize_array_url(self) -> str:
        return f"{self.base}/list?a=1&b=2"

    def _bulk_array_url(self) -> str:
        return f"{self.base}/bulk?a=1&b=2"

    def _stated_cap(self, fix: str) -> int:
        argv = shlex.split(fix)
        if "--max-bytes" in argv:
            value = int(argv[argv.index("--max-bytes") + 1])
            self.assertGreater(value, 0, fix)
            return value
        for token in argv:
            if token.startswith("TK_MAX_OUTPUT_BYTES="):
                return int(token.split("=", 1)[1])
        return _MAX_DEFAULT_BYTES

    def _run_fix_through_shell(self, fix: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        for key in list(env):
            if key.startswith("TK_ARG_") or key == "TK_DRY_RUN":
                env.pop(key, None)
        env["TK_NO_TELEMETRY"] = "1"
        env["PATH"] = str(ROOT) + os.pathsep + env.get("PATH", "")
        return subprocess.run(
            fix,
            shell=True,
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=env,
        )

    def test_fix_quotes_url_with_query_ampersand(self) -> None:
        url = self._oversize_query_url()
        proc = _run(JSON_GET, {"TK_ARG_URL": url})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["truncated"])
        argv = shlex.split(payload["fix"])
        self.assertEqual(argv[0], "tk")
        self.assertIn("--url", argv)
        self.assertEqual(argv[argv.index("--url") + 1], url)
        self.assertIn("--keys", argv)
        keys = argv[argv.index("--keys") + 1]
        self.assertTrue(keys)
        self.assertNotEqual(keys, "all")
        self.assertIn(shlex.quote(url), payload["fix"])
        self.assertIn(shlex.quote(keys), payload["fix"])

    def _assert_verbatim_fix_narrows(self, url: str) -> dict:
        proc = _run(JSON_GET, {"TK_ARG_URL": url})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["truncated"])
        argv = shlex.split(payload["fix"])
        self.assertEqual(argv[argv.index("--url") + 1], url)
        self.assertIn("--keys", argv)
        keys = argv[argv.index("--keys") + 1]
        self.assertNotEqual(keys, "all")
        healed = self._run_fix_through_shell(payload["fix"])
        self.assertEqual(healed.returncode, 0, healed.stderr + healed.stdout)
        raw = healed.stdout.encode("utf-8")
        narrowed = json.loads(healed.stdout)
        cap = self._stated_cap(payload["fix"])
        self.assertLessEqual(
            len(raw.rstrip(b"\n")),
            cap,
            f"fix {payload['fix']!r} returned {len(raw)} B above stated cap {cap}",
        )
        return {"payload": payload, "keys": keys, "narrowed": narrowed, "raw": raw}

    def test_fix_command_run_verbatim_stays_under_cap(self) -> None:
        object_case = self._assert_verbatim_fix_narrows(self._oversize_query_url())
        self.assertNotIn("blob", object_case["payload"])
        self.assertNotIn("blob", object_case["keys"].split(","))
        self.assertLessEqual(len(object_case["raw"].rstrip(b"\n")), _MAX_DEFAULT_BYTES)
        self.assertNotIn("blob", object_case["narrowed"])
        self.assertNotIn("truncated", object_case["narrowed"])

        array_case = self._assert_verbatim_fix_narrows(self._oversize_array_url())
        self.assertNotEqual(array_case["keys"], "all")
        if isinstance(array_case["narrowed"], dict):
            self.assertNotIn("truncated", array_case["narrowed"])

    def test_two_thousand_item_fix_succeeds_within_stated_cap(self) -> None:
        id_only = [{"id": item["id"]} for item in BULK_ARRAY_FIXTURE]
        id_size = len(json.dumps(id_only, separators=(",", ":")).encode("utf-8"))
        self.assertEqual(len(BULK_ARRAY_FIXTURE), 2000)
        self.assertGreater(id_size, _MAX_DEFAULT_BYTES)
        url = self._bulk_array_url()
        proc = _run(JSON_GET, {"TK_ARG_URL": url})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertLessEqual(len(proc.stdout.encode("utf-8").rstrip(b"\n")), _MAX_DEFAULT_BYTES)
        self.assertTrue(payload["truncated"])
        self.assertIn(shlex.quote(url), payload["fix"])
        cap = self._stated_cap(payload["fix"])
        self.assertGreater(cap, _MAX_DEFAULT_BYTES, payload["fix"])
        argv = shlex.split(payload["fix"])
        self.assertTrue(
            "--max-bytes" in argv or any(token.startswith("TK_MAX_OUTPUT_BYTES=") for token in argv),
            payload["fix"],
        )
        healed = self._run_fix_through_shell(payload["fix"])
        self.assertEqual(healed.returncode, 0, healed.stderr + healed.stdout)
        raw = healed.stdout.encode("utf-8").rstrip(b"\n")
        self.assertLessEqual(len(raw), cap, payload["fix"])
        narrowed = json.loads(healed.stdout)
        self.assertIsInstance(narrowed, list)
        self.assertEqual(len(narrowed), 2000)
        self.assertTrue(all(set(item) == {"id"} for item in narrowed))
        self.assertEqual(narrowed[0]["id"], 0)
        self.assertEqual(narrowed[-1]["id"], 1999)

    def test_max_bytes_zero_returns_the_full_document(self) -> None:
        header = "\n".join(
            line
            for line in JSON_GET.read_text(encoding="utf-8").splitlines()
            if line.startswith("#")
        )
        self.assertIn("# @tk-arg: --max-bytes", header)
        self.assertIn("0 returns the full document", header)
        example = next(
            line for line in header.splitlines() if line.startswith("# @tk-example:")
        )
        self.assertIn("--max-bytes 0", example)

        direct = _run(
            JSON_GET,
            {"TK_ARG_URL": f"{self.base}/repo", "TK_ARG_MAX_BYTES": "0"},
        )
        self.assertEqual(direct.returncode, 0, direct.stderr)
        self.assertEqual(json.loads(direct.stdout), OVERSIZE_REPO_FIXTURE)

        bulk = _run(
            JSON_GET,
            {"TK_ARG_URL": f"{self.base}/bulk", "TK_ARG_MAX_BYTES": "0"},
        )
        self.assertEqual(bulk.returncode, 0, bulk.stderr)
        self.assertEqual(json.loads(bulk.stdout), BULK_ARRAY_FIXTURE)

        capped = _run(JSON_GET, {"TK_ARG_URL": self._oversize_query_url()})
        self.assertEqual(capped.returncode, 0, capped.stderr)
        payload = json.loads(capped.stdout)
        self.assertTrue(payload["truncated"])
        self.assertIn("--max-bytes 0", payload["hint"])
        hint_argv = shlex.split(payload["hint"])
        self.assertEqual(hint_argv[hint_argv.index("--url") + 1], self._oversize_query_url())
        self.assertEqual(hint_argv[hint_argv.index("--max-bytes") + 1], "0")
        self.assertIn(shlex.quote(self._oversize_query_url()), payload["hint"])
        healed = self._run_fix_through_shell(payload["hint"])
        self.assertEqual(healed.returncode, 0, healed.stderr + healed.stdout)
        self.assertEqual(json.loads(healed.stdout), OVERSIZE_REPO_FIXTURE)


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

    def test_explicit_limit_above_30_is_honored(self) -> None:
        tmp = self._fixture()
        self.addCleanup(tmp.cleanup)
        proc = _run(
            SEARCH,
            {
                "TK_ARG_PATH": tmp.name,
                "TK_ARG_PATTERN": "needle",
                "TK_ARG_LIMIT": "40",
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["count"], 40)
        self.assertEqual(len(payload["matches"]), 40)
        self.assertEqual(payload["truncated"], 0)
        self.assertNotIn("limit_clamped_to", payload)


if __name__ == "__main__":
    unittest.main()
