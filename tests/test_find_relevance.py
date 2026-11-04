"""Relevance threshold for tk find: every non-stopword token must match."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.catalog import find_items  # noqa: E402

TK = ROOT / "tk"


def _run_find(*args: str, telemetry: bool = False) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if telemetry:
        env.pop("TK_NO_TELEMETRY", None)
    else:
        env["TK_NO_TELEMETRY"] = "1"
    return subprocess.run(
        [sys.executable, str(TK), "find", *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
        check=False,
    )


class FindRelevanceTests(unittest.TestCase):
    def test_irrelevant_query_matches_nothing(self):
        self.assertEqual(find_items(ROOT, "list kubernetes pods"), [])

    def test_namespace_term_plus_unknown_token_matches_nothing(self):
        self.assertEqual(find_items(ROOT, "git zzzz"), [])

    def test_representative_queries_still_match(self):
        cases = {
            "git diff": "git.diff-digest",
            "log errors": "log.tail-errors",
            "env check": "env.check",
        }
        for query, expected in cases.items():
            names = [item["name"] for item in find_items(ROOT, query)]
            self.assertIn(expected, names, query)

    def test_cli_no_match_and_real_queries(self):
        pods = _run_find("list kubernetes pods")
        self.assertEqual(pods.returncode, 0)
        payload = json.loads(pods.stderr)
        self.assertEqual(payload["error"], "no_match")
        self.assertTrue(payload["fix"].startswith("tk "))

        git_miss = _run_find("git", "zzzz")
        self.assertEqual(json.loads(git_miss.stderr)["fix"], "tk find --namespace git")

        for query in ("git diff", "log errors", "env check"):
            found = _run_find(query)
            self.assertEqual(found.stderr, "", query)
            self.assertIn(query.split()[0], found.stdout)


if __name__ == "__main__":
    unittest.main()
