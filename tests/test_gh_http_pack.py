"""Seams for gh.pr-diff-digest, gh.pr-overview, and http.health-probe."""

import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.catalog import load_chain
from lib.runner import run_chain

_VIEW = {
    "number": 7,
    "title": "Fix parser",
    "state": "OPEN",
    "additions": 12,
    "deletions": 3,
    "changedFiles": 2,
    "files": [
        {"path": "src/a.py", "additions": 10, "deletions": 1},
        {"path": "src/b.py", "additions": 2, "deletions": 2},
    ],
}

_DIFF = """diff --git a/src/a.py b/src/a.py
index 111..222 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1,3 +1,5 @@ def alpha():
 context
+x
@@ -20,2 +22,2 @@ def beta():
@@ -30,1 +32,1 @@ def gamma():
@@ -40,1 +42,1 @@ def delta():
@@ -50,1 +52,1 @@ def epsilon():
@@ -60,1 +62,1 @@ def zeta():
diff --git a/src/b.py b/src/b.py
@@ -8,4 +8,5 @@ class Bee:
+y
"""

_FAKE_GH = """#!/usr/bin/env python3
import json
import sys

view = %s
diff = %s
args = sys.argv[1:]
if "diff" in args:
    sys.stdout.write(diff)
elif "view" in args:
    sys.stdout.write(json.dumps(view))
else:
    sys.stderr.write("unexpected gh args\\n")
    raise SystemExit(2)
""" % (
    json.dumps(_VIEW),
    json.dumps(_DIFF),
)


def _run(script: Path, env: dict) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    for key in list(merged):
        if key.startswith("TK_ARG_") or key in {"TK_DRY_RUN", "TK_GH_BIN"}:
            merged.pop(key, None)
    merged.update(env)
    merged.setdefault("TK_DRY_RUN", "0")
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=merged,
    )


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/ok":
            body = b"ok"
            status = 200
        else:
            body = b"no"
            status = 500
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return


class PrDiffDigestTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.fake = root / "gh"
        self.fake.write_text(_FAKE_GH, encoding="utf-8")
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IEXEC)

    def test_hunks_capped_and_files_truncated(self) -> None:
        proc = _run(
            ROOT / "tools/gh/pr-diff-digest",
            {"TK_GH_BIN": str(self.fake), "TK_ARG_REPO": "cli/cli", "TK_ARG_PR": "7", "TK_ARG_LIMIT": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["repo"], "cli/cli")
        self.assertEqual(payload["pr"], 7)
        self.assertEqual(payload["title"], "Fix parser")
        self.assertEqual(payload["state"], "OPEN")
        self.assertEqual(payload["files_changed"], 2)
        self.assertEqual(payload["additions"], 12)
        self.assertEqual(payload["deletions"], 3)
        self.assertTrue(payload["truncated"])
        self.assertEqual(len(payload["files"]), 1)
        file0 = payload["files"][0]
        self.assertEqual(file0["path"], "src/a.py")
        self.assertEqual(file0["additions"], 10)
        self.assertEqual(file0["deletions"], 1)
        self.assertEqual(
            file0["hunks"],
            [
                "@@ -1,3 +1,5 @@ def alpha():",
                "@@ -20,2 +22,2 @@ def beta():",
                "@@ -30,1 +32,1 @@ def gamma():",
                "@@ -40,1 +42,1 @@ def delta():",
                "@@ -50,1 +52,1 @@ def epsilon():",
            ],
        )

    def test_all_files_when_under_limit(self) -> None:
        proc = _run(
            ROOT / "tools/gh/pr-diff-digest",
            {"TK_GH_BIN": str(self.fake), "TK_ARG_REPO": "cli/cli", "TK_ARG_PR": "7", "TK_ARG_LIMIT": "30"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["truncated"])
        self.assertEqual([row["path"] for row in payload["files"]], ["src/a.py", "src/b.py"])
        self.assertEqual(payload["files"][1]["hunks"], ["@@ -8,4 +8,5 @@ class Bee:"])

    def test_dry_run(self) -> None:
        proc = _run(
            ROOT / "tools/gh/pr-diff-digest",
            {"TK_ARG_REPO": "cli/cli", "TK_ARG_PR": "1", "TK_ARG_LIMIT": "20", "TK_DRY_RUN": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            {"dry_run": True, "repo": "cli/cli", "pr": 1, "limit": 20},
        )


class PrOverviewChainTests(unittest.TestCase):
    def test_chain_picks_overview_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "gh"
            fake.write_text(_FAKE_GH, encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            previous = os.environ.get("TK_GH_BIN")
            os.environ["TK_GH_BIN"] = str(fake)
            try:
                item = load_chain(ROOT / "chains/gh.pr-overview.json")
                code, stdout, stderr = run_chain(ROOT, item, {"--repo": "cli/cli", "--pr": "7"})
            finally:
                if previous is None:
                    os.environ.pop("TK_GH_BIN", None)
                else:
                    os.environ["TK_GH_BIN"] = previous
        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(
            set(payload),
            {"repo", "pr", "title", "state", "files_changed", "additions", "deletions", "files"},
        )
        self.assertEqual(payload["title"], "Fix parser")
        self.assertEqual(len(payload["files"]), 2)
        self.assertNotIn("truncated", payload)


class HealthProbeTests(unittest.TestCase):
    def test_local_ok_and_server_error(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        port = server.server_address[1]
        urls = f"http://127.0.0.1:{port}/ok,http://127.0.0.1:{port}/fail"
        proc = _run(
            ROOT / "tools/http/health-probe",
            {"TK_ARG_URLS": urls, "TK_ARG_TIMEOUT": "5"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["all_ok"])
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["healthy"], 1)
        self.assertEqual(payload["unhealthy"], 1)
        ok, bad = payload["results"]
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["status"], 200)
        self.assertIsNone(ok["error"])
        self.assertEqual(ok["content_type"], "text/plain")
        self.assertIsInstance(ok["latency_ms"], int)
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["status"], 500)
        self.assertIsNone(bad["error"])
        self.assertEqual(bad["content_type"], "text/plain")

    def test_dry_run_splits_urls(self) -> None:
        proc = _run(
            ROOT / "tools/http/health-probe",
            {"TK_ARG_URLS": "https://example.com, https://example.org", "TK_ARG_TIMEOUT": "5", "TK_DRY_RUN": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            {"dry_run": True, "urls": ["https://example.com", "https://example.org"], "timeout": 5},
        )


if __name__ == "__main__":
    unittest.main()
