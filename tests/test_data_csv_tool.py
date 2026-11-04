"""Seam for data.csv-digest: schema, null counts, and sample truncation."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_DIGEST = ROOT / "tools/data/csv-digest"


def _run(env: dict) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    for key in list(merged):
        if key.startswith("TK_ARG_") or key == "TK_DRY_RUN":
            merged.pop(key, None)
    merged.update(env)
    merged.setdefault("TK_DRY_RUN", "0")
    return subprocess.run(
        [sys.executable, str(CSV_DIGEST)],
        capture_output=True,
        text=True,
        env=merged,
    )


class CsvDigestTests(unittest.TestCase):
    def test_csv_null_counts_and_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.csv"
            path.write_text(
                "name,qty,note\n"
                "bolt,2,\n"
                "nut,,ok\n"
                ",1, \n",
                encoding="utf-8",
            )
            proc = _run(
                {"TK_ARG_PATH": str(path), "TK_ARG_LIMIT": "2"},
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["path"], str(path))
        self.assertEqual(payload["delimiter"], ",")
        self.assertEqual(payload["columns"], ["name", "qty", "note"])
        self.assertEqual(payload["rows"], 3)
        self.assertTrue(payload["truncated"])
        self.assertEqual(
            payload["null_counts"],
            {"name": 1, "qty": 1, "note": 2},
        )
        self.assertEqual(
            payload["sample"],
            [
                {"name": "bolt", "qty": "2", "note": ""},
                {"name": "nut", "qty": "", "note": "ok"},
            ],
        )

    def test_tsv_delimiter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.tsv"
            path.write_text("a\tb\n1\t2\n3\t\n", encoding="utf-8")
            proc = _run({"TK_ARG_PATH": str(path), "TK_ARG_LIMIT": "10"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["delimiter"], "\t")
        self.assertEqual(payload["columns"], ["a", "b"])
        self.assertEqual(payload["rows"], 2)
        self.assertFalse(payload["truncated"])
        self.assertEqual(payload["null_counts"], {"a": 0, "b": 1})
        self.assertEqual(payload["sample"], [{"a": "1", "b": "2"}, {"a": "3", "b": ""}])

    def test_semicolon_delimiter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.csv"
            path.write_text("a;b\n1;2\n", encoding="utf-8")
            proc = _run({"TK_ARG_PATH": str(path)})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["delimiter"], ";")
        self.assertEqual(payload["rows"], 1)
        self.assertEqual(payload["sample"], [{"a": "1", "b": "2"}])

    def test_dry_run(self) -> None:
        proc = _run(
            {"TK_ARG_PATH": "data.csv", "TK_ARG_LIMIT": "4", "TK_DRY_RUN": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            {"dry_run": True, "path": "data.csv", "limit": 4},
        )


if __name__ == "__main__":
    unittest.main()
