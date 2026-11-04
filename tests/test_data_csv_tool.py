"""Seam for data.csv-digest: schema, null counts, and sample truncation."""

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_DIGEST = ROOT / "tools/data/csv-digest"
_OUTPUT_CAP = 65536
_CELL_CAP = 200
_WIDE_COLUMNS = 20
_WIDE_LIMIT = 20
_WIDE_CELL_CHARS = 4096


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


def _tk_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("TK_ARG_") or key in {"TK_DRY_RUN", "TK_MAX_OUTPUT_BYTES"}:
            env.pop(key, None)
    env["TK_NO_TELEMETRY"] = "1"
    env["PATH"] = str(ROOT) + os.pathsep + env.get("PATH", "")
    return env


def _run_tk(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=_tk_env(),
    )


def _write_wide_csv(path: Path, *, rows: int, columns: int, cell_chars: int) -> None:
    names = [f"c{index:02d}" for index in range(columns)]
    cell = "x" * cell_chars
    body = [",".join(names)]
    body.extend(",".join([cell] * columns) for _ in range(rows))
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


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
        self.assertEqual(payload["truncated"], 1)
        self.assertEqual(payload["cells_truncated"], 0)
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
        self.assertEqual(payload["truncated"], 0)
        self.assertEqual(payload["cells_truncated"], 0)
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
        self.assertEqual(payload["cells_truncated"], 0)
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

    def test_output_header_documents_cells_truncated(self) -> None:
        output = next(
            line
            for line in CSV_DIGEST.read_text(encoding="utf-8").splitlines()
            if line.startswith("# @tk-output:")
        )
        self.assertIn("cells_truncated", output)
        self.assertIn("200", output)

    def test_sample_cells_over_200_chars_are_cut_and_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.csv"
            path.write_text(
                "keep,long\n"
                f"{'a' * _CELL_CAP},{'b' * (_CELL_CAP + 1)}\n"
                f"{'c' * 50},{'d' * _CELL_CAP}\n",
                encoding="utf-8",
            )
            proc = _run({"TK_ARG_PATH": str(path), "TK_ARG_LIMIT": "10"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["truncated"], 0)
        self.assertEqual(payload["cells_truncated"], 1)
        self.assertEqual(payload["sample"][0]["keep"], "a" * _CELL_CAP)
        self.assertEqual(payload["sample"][0]["long"], "b" * _CELL_CAP)
        self.assertEqual(payload["sample"][1]["keep"], "c" * 50)
        self.assertEqual(payload["sample"][1]["long"], "d" * _CELL_CAP)

    def test_default_limit_fits_20kb_cells(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wide.csv"
            cell = "x" * (20 * 1024)
            path.write_text("note\n" + "\n".join([cell] * 20) + "\n", encoding="utf-8")
            proc = _run_tk(["tk", "run", "data.csv-digest", "--path", str(path)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        raw = proc.stdout.encode("utf-8")
        self.assertLess(len(raw), _OUTPUT_CAP)
        payload = json.loads(proc.stdout)
        self.assertNotIn("error", payload)
        self.assertEqual(payload["rows"], 20)
        self.assertEqual(len(payload["sample"]), 10)
        self.assertEqual(payload["cells_truncated"], 10)
        self.assertTrue(all(len(row["note"]) == _CELL_CAP for row in payload["sample"]))
        self.assertEqual(payload["truncated"], 10)

    def test_printed_fix_for_output_too_large_fits_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wide.csv"
            _write_wide_csv(
                path,
                rows=_WIDE_LIMIT,
                columns=_WIDE_COLUMNS,
                cell_chars=_WIDE_CELL_CHARS,
            )
            failed = _run_tk(
                [
                    "tk",
                    "run",
                    "data.csv-digest",
                    "--path",
                    str(path),
                    "--limit",
                    str(_WIDE_LIMIT),
                ]
            )
            self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
            self.assertEqual(failed.stdout, "")
            err = json.loads(failed.stderr)
            self.assertEqual(err["error"], "output_too_large")
            argv = shlex.split(err["fix"])
            self.assertEqual(argv[:3], ["tk", "run", "data.csv-digest"])
            self.assertEqual(argv[argv.index("--path") + 1], str(path))
            self.assertEqual(argv[argv.index("--limit") + 1], str(_WIDE_LIMIT // 2))
            healed = _run_tk(argv)
        self.assertEqual(healed.returncode, 0, healed.stderr + healed.stdout)
        raw = healed.stdout.encode("utf-8")
        self.assertLess(len(raw), _OUTPUT_CAP)
        payload = json.loads(healed.stdout)
        self.assertNotIn("error", payload)
        self.assertEqual(payload["rows"], _WIDE_LIMIT)
        self.assertEqual(len(payload["sample"]), _WIDE_LIMIT // 2)
        self.assertEqual(payload["cells_truncated"], _WIDE_COLUMNS * (_WIDE_LIMIT // 2))
        self.assertTrue(
            all(len(value) == _CELL_CAP for row in payload["sample"] for value in row.values())
        )
        self.assertEqual(payload["truncated"], _WIDE_LIMIT // 2)

    def test_limit_one_sets_integer_truncated_and_next(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.csv"
            path.write_text("name\none\ntwo\n", encoding="utf-8")
            proc = _run_tk(["tk", "run", "data.csv-digest", "--path", str(path), "--limit", "1"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIsInstance(payload["truncated"], int)
        self.assertNotIsInstance(payload["truncated"], bool)
        self.assertGreaterEqual(payload["truncated"], 1)
        self.assertEqual(payload["next"], f"tk run data.csv-digest --path {path} --limit 2")


if __name__ == "__main__":
    unittest.main()
