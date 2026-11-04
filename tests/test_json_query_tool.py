"""Seams for json.query and the git.repo-audit chain."""

import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUERY = ROOT / "tools/json/query"
CHAIN = ROOT / "chains/git.repo-audit.json"

DOC = {
    "items": [
        {"id": 1, "name": "alpha", "ok": True, "count": 1},
        {"id": 2, "name": "beta", "ok": False, "count": 3},
        {"id": 3, "name": "gamma", "ok": True, "count": 2},
    ],
    "meta": {"owner": {"login": "ada"}},
}


def _run(env: dict, stdin: str = "") -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    for key in list(merged):
        if key.startswith("TK_ARG_") or key == "TK_DRY_RUN":
            merged.pop(key, None)
    merged.update(env)
    merged.setdefault("TK_DRY_RUN", "0")
    return subprocess.run(
        [str(QUERY)],
        capture_output=True,
        text=True,
        input=stdin,
        env=merged,
        cwd=ROOT,
    )


class JsonQueryTests(unittest.TestCase):
    def test_nested_path(self) -> None:
        proc = _run({"TK_ARG_EXPR": "meta.owner.login"}, json.dumps(DOC))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), "ada")

    def test_wildcard_projection(self) -> None:
        proc = _run({"TK_ARG_EXPR": "items[*].name"}, json.dumps(DOC))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["results"], ["alpha", "beta", "gamma"])
        self.assertEqual(payload["count"], 3)
        self.assertEqual(payload["truncated"], 0)

    def test_equality_and_numeric_filters(self) -> None:
        eq = _run({"TK_ARG_EXPR": "items[?ok==true].name"}, json.dumps(DOC))
        self.assertEqual(eq.returncode, 0, eq.stderr)
        self.assertEqual(json.loads(eq.stdout)["results"], ["alpha", "gamma"])

        gt = _run({"TK_ARG_EXPR": "items[?count>1].name"}, json.dumps(DOC))
        self.assertEqual(gt.returncode, 0, gt.stderr)
        self.assertEqual(json.loads(gt.stdout)["results"], ["beta", "gamma"])

    def test_malformed_filter_predicate(self) -> None:
        proc = _run({"TK_ARG_EXPR": "items[?ok]"}, json.dumps(DOC))
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stderr)["error"], "invalid_expr")

        empty_key = _run({"TK_ARG_EXPR": "items[?==1]"}, json.dumps(DOC))
        self.assertEqual(empty_key.returncode, 2)
        self.assertEqual(json.loads(empty_key.stderr)["error"], "invalid_expr")

    def test_inclusive_comparisons_and_quoted_bracket(self) -> None:
        ge = _run({"TK_ARG_EXPR": "items[?count>=2].name"}, json.dumps(DOC))
        self.assertEqual(ge.returncode, 0, ge.stderr)
        self.assertEqual(json.loads(ge.stdout)["results"], ["beta", "gamma"])

        le = _run({"TK_ARG_EXPR": "items[?count<=1].name"}, json.dumps(DOC))
        self.assertEqual(le.returncode, 0, le.stderr)
        self.assertEqual(json.loads(le.stdout)["results"], ["alpha"])

        quoted = {
            "items": [
                {"id": 9, "note": "a]b"},
                {"id": 1, "note": "plain"},
            ]
        }
        proc = _run({"TK_ARG_EXPR": "items[?note=='a]b'].id"}, json.dumps(quoted))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["results"], [9])

    def test_object_projection(self) -> None:
        proc = _run({"TK_ARG_EXPR": "items[*].{id,name}"}, json.dumps(DOC))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout)["results"],
            [
                {"id": 1, "name": "alpha"},
                {"id": 2, "name": "beta"},
                {"id": 3, "name": "gamma"},
            ],
        )

    def test_limit_truncates_lists(self) -> None:
        proc = _run(
            {"TK_ARG_EXPR": "items[*].name", "TK_ARG_LIMIT": "2"},
            json.dumps(DOC),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["results"], ["alpha", "beta"])
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["truncated"], 1)

    def test_dry_run_skips_stdin(self) -> None:
        proc = _run({"TK_ARG_EXPR": "items[*].name", "TK_ARG_LIMIT": "20", "TK_DRY_RUN": "1"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            {"dry_run": True, "expr": "items[*].name", "limit": 20},
        )


class RepoAuditChainTests(unittest.TestCase):
    def test_chain_contract_and_run(self) -> None:
        raw = json.loads(CHAIN.read_text(encoding="utf-8"))
        self.assertEqual(raw["name"], "git.repo-audit")
        self.assertEqual(raw["safety"], "read-only")
        self.assertEqual(raw["summary"], "Recent commits distilled to sha and subject for a git repository")
        self.assertEqual(raw["verified"], "2026-11-04")
        self.assertEqual(raw["output"], "json | {count, truncated, results:[{sha, subject}]}")
        self.assertEqual(raw["example"], "tk run git.repo-audit --repo . --limit 5")
        self.assertEqual(raw["steps"][0]["tool"], "git.log-recent")
        self.assertEqual(raw["steps"][0]["args"]["repo"], "$input.repo")
        self.assertEqual(raw["steps"][1]["tool"], "json.query")
        self.assertEqual(raw["steps"][1]["args"]["expr"], "commits[*].{sha,subject}")

        env = os.environ.copy()
        env["TK_NO_TELEMETRY"] = "1"
        proc = subprocess.run(
            [str(ROOT / "tk"), "run", "git.repo-audit", "--repo", str(ROOT), "--limit", "3"],
            capture_output=True,
            text=True,
            env=env,
            cwd=ROOT,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        payload = json.loads(proc.stdout)
        rows = payload["results"] if isinstance(payload, dict) else payload
        self.assertGreaterEqual(len(rows), 1)
        self.assertLessEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(set(row), {"sha", "subject"})
            self.assertRegex(row["sha"], r"^[0-9a-f]{7,40}$")
            self.assertIsInstance(row["subject"], str)
            self.assertTrue(row["subject"])


if __name__ == "__main__":
    unittest.main()
