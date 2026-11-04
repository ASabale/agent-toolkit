"""Guards for git option injection, SQLite URI quoting, and non-public URLs."""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT_ENV = "TK_NO_TELEMETRY"


class GuardTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ[ROOT_ENV] = "1"
        os.environ.pop("TK_ALLOW_PRIVATE_URLS", None)
        self._state = tempfile.TemporaryDirectory()
        os.environ["TK_STATE_DIR"] = self._state.name
        self.addCleanup(self._state.cleanup)

    def test_git_token_rejects_options_and_whitespace(self) -> None:
        from lib.guards import safe_git_token

        self.assertFalse(safe_git_token("--upload-pack=evil"))
        self.assertFalse(safe_git_token("origin main"))
        self.assertTrue(safe_git_token("origin"))
        self.assertTrue(safe_git_token("main"))

    def test_sqlite_uri_encodes_query_characters(self) -> None:
        from lib.guards import sqlite_ro_uri

        uri = sqlite_ro_uri("/tmp/a?mode=rw#b.db")
        self.assertIn("%3F", uri)
        self.assertIn("%23", uri)
        self.assertTrue(uri.startswith("file:"))
        self.assertTrue(uri.endswith("?mode=ro"))

    def test_public_url_blocks_loopback_and_metadata(self) -> None:
        from lib.guards import public_url_error

        self.assertIsNotNone(public_url_error("http://127.0.0.1/"))
        self.assertIsNotNone(public_url_error("http://169.254.169.254/latest"))
        self.assertIsNotNone(public_url_error("http://10.0.0.5/"))
        self.assertIsNotNone(public_url_error("http://192.168.1.1/"))
        self.assertIsNotNone(public_url_error("file:///etc/passwd"))

    def test_private_url_hatch(self) -> None:
        from lib.guards import public_url_error

        os.environ["TK_ALLOW_PRIVATE_URLS"] = "1"
        self.assertIsNone(public_url_error("http://127.0.0.1/health"))
        self.assertIsNotNone(public_url_error("file:///etc/passwd"))

    def test_child_env_drops_unrelated_secrets(self) -> None:
        from lib.guards import tool_subprocess_env

        os.environ["AWS_SECRET_ACCESS_KEY"] = "nope"
        env = tool_subprocess_env({"TK_DRY_RUN": "1", "TK_ARG_REPO": "."})
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
        self.assertEqual(env["TK_DRY_RUN"], "1")
        self.assertEqual(env.get("TK_ARG_REPO"), ".")
        os.environ["https_proxy"] = "http://proxy.example:8080"
        os.environ["NO_PROXY"] = "localhost"
        os.environ["PYTHONPATH"] = "/tmp/caller-src"
        os.environ["GIT_AUTHOR_NAME"] = "Ada"
        os.environ["GH_LOG"] = "/tmp/gh.log"
        env = tool_subprocess_env({"TK_DRY_RUN": "1"})
        self.assertEqual(env.get("https_proxy"), "http://proxy.example:8080")
        self.assertEqual(env.get("NO_PROXY"), "localhost")
        self.assertEqual(env.get("GIT_AUTHOR_NAME"), "Ada")
        self.assertEqual(env.get("PYTHONPATH"), "/tmp/caller-src")
        self.assertEqual(env.get("GH_LOG"), "/tmp/gh.log")
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)

    def test_checked_open_rejects_redirect_to_loopback(self) -> None:
        import lib.guards as guards

        class _Redirect(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1/landed")
                self.end_headers()

            def log_message(self, _format: str, *_args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), _Redirect)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        port = server.server_address[1]
        real = guards.public_url_error
        state = {"first": True}

        def allow_first(url: str) -> str | None:
            if state["first"]:
                state["first"] = False
                return None
            return real(url)

        guards.public_url_error = allow_first
        try:
            request = urllib.request.Request(f"http://127.0.0.1:{port}/start")
            with self.assertRaises(guards.UnsafeURL) as caught:
                guards.checked_open(request, 2)
        finally:
            guards.public_url_error = real
        self.assertIn("127.0.0.1", str(caught.exception))
