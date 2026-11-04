"""Seams for sql.schema, sql.query, web.read-text, and log.tail-errors."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
        conn.executemany(
            "INSERT INTO widgets (name) VALUES (?)",
            [("alpha",), ("beta",), ("gamma",)],
        )
        conn.execute("INSERT INTO notes (body) VALUES (?)", ("hello",))
        conn.commit()
    finally:
        conn.close()


class SqlSchemaTests(unittest.TestCase):
    def test_lists_user_tables_columns_and_row_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "app.db"
            _make_db(db)
            proc = _run(
                ROOT / "tools/sql/schema",
                {"TK_ARG_DB": str(db), "TK_ARG_TABLE": "all"},
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["db"], str(db))
        self.assertEqual(payload["table_count"], 2)
        by_name = {table["name"]: table for table in payload["tables"]}
        self.assertEqual(set(by_name), {"notes", "widgets"})
        widgets = by_name["widgets"]
        self.assertEqual(widgets["rows"], 3)
        self.assertEqual(
            widgets["columns"],
            [
                {"name": "id", "type": "INTEGER", "pk": 1, "notnull": 0},
                {"name": "name", "type": "TEXT", "pk": 0, "notnull": 1},
            ],
        )
        self.assertEqual(by_name["notes"]["rows"], 1)

    def test_table_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "app.db"
            _make_db(db)
            proc = _run(
                ROOT / "tools/sql/schema",
                {"TK_ARG_DB": str(db), "TK_ARG_TABLE": "notes"},
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["table_count"], 1)
        self.assertEqual(payload["tables"][0]["name"], "notes")

    def test_dry_run_does_not_require_a_database(self) -> None:
        proc = _run(
            ROOT / "tools/sql/schema",
            {"TK_ARG_DB": "example", "TK_ARG_TABLE": "all", "TK_DRY_RUN": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["db"], "example")


class SqlQueryTests(unittest.TestCase):
    def test_returns_row_dicts_and_marks_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "app.db"
            _make_db(db)
            proc = _run(
                ROOT / "tools/sql/query",
                {
                    "TK_ARG_DB": str(db),
                    "TK_ARG_SQL": "SELECT id, name FROM widgets ORDER BY id",
                    "TK_ARG_LIMIT": "2",
                },
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["db"], str(db))
        self.assertEqual(payload["columns"], ["id", "name"])
        self.assertEqual(payload["count"], 2)
        self.assertTrue(payload["truncated"])
        self.assertEqual(
            payload["rows"],
            [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}],
        )

    def test_rejects_mutating_sql_without_changing_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "app.db"
            _make_db(db)
            for sql in (
                "DELETE FROM widgets",
                "DROP TABLE widgets",
                "UPDATE widgets SET name = 'x'",
                "INSERT INTO widgets (name) VALUES ('nope')",
                "PRAGMA journal_mode = DELETE",
                "SELECT 1; DELETE FROM widgets",
            ):
                proc = _run(
                    ROOT / "tools/sql/query",
                    {
                        "TK_ARG_DB": str(db),
                        "TK_ARG_SQL": sql,
                        "TK_ARG_LIMIT": "25",
                    },
                )
                self.assertNotEqual(proc.returncode, 0, sql)
                err = json.loads(proc.stderr)
                self.assertIn("error", err)
                self.assertEqual(proc.stdout.strip(), "")
            conn = sqlite3.connect(db)
            try:
                count = conn.execute("SELECT COUNT(*) FROM widgets").fetchone()[0]
            finally:
                conn.close()
        self.assertEqual(count, 3)

    def test_dry_run(self) -> None:
        proc = _run(
            ROOT / "tools/sql/query",
            {
                "TK_ARG_DB": "example",
                "TK_ARG_SQL": "SELECT 1",
                "TK_ARG_LIMIT": "25",
                "TK_DRY_RUN": "1",
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["dry_run"])

    def test_allows_double_quoted_delete_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "items.db"
            conn = sqlite3.connect(db)
            try:
                conn.execute("CREATE TABLE items (delete_flag TEXT)")
                conn.execute("INSERT INTO items (delete_flag) VALUES ('keep')")
                conn.commit()
            finally:
                conn.close()
            proc = _run(
                ROOT / "tools/sql/query",
                {
                    "TK_ARG_DB": str(db),
                    "TK_ARG_SQL": 'SELECT "delete_flag" FROM items',
                    "TK_ARG_LIMIT": "25",
                },
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["rows"], [{"delete_flag": "keep"}])

    def test_rejects_vacuum_as_mutating_sql(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "empty.db"
            sqlite3.connect(db).close()
            proc = _run(
                ROOT / "tools/sql/query",
                {
                    "TK_ARG_DB": str(db),
                    "TK_ARG_SQL": "VACUUM",
                    "TK_ARG_LIMIT": "25",
                },
            )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stderr)["error"], "mutating_sql")
        self.assertEqual(proc.stdout.strip(), "")


class WebReadTextTests(unittest.TestCase):
    def test_distills_local_html(self) -> None:
        html = """<!doctype html>
        <html><head><title>Widget Notes</title>
        <style>.x{color:red}</style>
        <script>var SECRET_TOKEN = 1;</script>
        </head><body>
        <nav><h1>Skip Nav</h1><a href="/nav">Nav</a></nav>
        <h1>Widgets</h1>
        <h2>Usage</h2>
        <p>Hello   world from the body.</p>
        <a href="https://example.com/docs">Docs</a>
        <footer>footer noise</footer>
        </body></html>
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.html"
            path.write_text(html, encoding="utf-8")
            proc = _run(
                ROOT / "tools/web/read-text",
                {"TK_ARG_SOURCE": str(path), "TK_ARG_MAX_CHARS": "4000"},
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["title"], "Widget Notes")
        self.assertEqual(
            payload["headings"],
            [{"level": "h1", "text": "Widgets"}, {"level": "h2", "text": "Usage"}],
        )
        self.assertEqual(
            payload["links"],
            [{"text": "Docs", "href": "https://example.com/docs"}],
        )
        self.assertIn("Hello world from the body.", payload["text"])
        self.assertNotIn("SECRET_TOKEN", payload["text"])
        self.assertNotIn("Skip Nav", payload["text"])
        self.assertNotIn("footer noise", payload["text"])
        self.assertFalse(payload["truncated"])

    def test_truncates_text(self) -> None:
        html = "<html><body><p>" + ("abcdef" * 50) + "</p></body></html>"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "long.html"
            path.write_text(html, encoding="utf-8")
            proc = _run(
                ROOT / "tools/web/read-text",
                {"TK_ARG_SOURCE": str(path), "TK_ARG_MAX_CHARS": "20"},
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["truncated"])
        self.assertEqual(len(payload["text"]), 20)
        self.assertTrue(payload["text"].startswith("abcdef"))


class LogTailErrorsTests(unittest.TestCase):
    def test_dedupes_errors_inside_the_tail(self) -> None:
        lines = ["INFO startup ok"]
        lines.append("ERROR disk full on /data")
        lines.extend(["INFO tick"] * 20)
        lines.extend(
            [
                "ERROR disk full on /data",
                "error   disk full on /data",
                "FATAL cannot allocate",
                "INFO finished",
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.log"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            proc = _run(
                ROOT / "tools/log/tail-errors",
                {
                    "TK_ARG_PATH": str(path),
                    "TK_ARG_TAIL": "6",
                    "TK_ARG_LIMIT": "20",
                },
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["path"], str(path))
        self.assertEqual(len(payload["errors"]), 2)
        disk, fatal = payload["errors"]
        self.assertEqual(disk["count"], 2)
        self.assertEqual(disk["message"], "ERROR disk full on /data")
        self.assertEqual(disk["first_line"], 23)
        self.assertEqual(disk["last_line"], 24)
        self.assertEqual(fatal["count"], 1)
        self.assertEqual(fatal["first_line"], 25)
        self.assertEqual(fatal["last_line"], 25)
        self.assertFalse(payload["truncated"])

    def test_preserves_case_in_message_while_deduping(self) -> None:
        body = "ValueError: missing field\nvalueerror: missing field\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.log"
            path.write_text(body, encoding="utf-8")
            proc = _run(
                ROOT / "tools/log/tail-errors",
                {
                    "TK_ARG_PATH": str(path),
                    "TK_ARG_TAIL": "50",
                    "TK_ARG_LIMIT": "20",
                },
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(len(payload["errors"]), 1)
        error = payload["errors"][0]
        self.assertEqual(error["message"], "ValueError: missing field")
        self.assertEqual(error["count"], 2)
        self.assertIn("ValueError", error["message"])

    def test_limit_caps_groups(self) -> None:
        body = "\n".join(
            [
                "ERROR one",
                "ERROR two",
                "panic: three",
                "Traceback (most recent call last):",
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.log"
            path.write_text(body + "\n", encoding="utf-8")
            proc = _run(
                ROOT / "tools/log/tail-errors",
                {
                    "TK_ARG_PATH": str(path),
                    "TK_ARG_TAIL": "500",
                    "TK_ARG_LIMIT": "2",
                },
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(len(payload["errors"]), 2)
        self.assertTrue(payload["truncated"])
        self.assertEqual([item["message"] for item in payload["errors"]], ["ERROR one", "ERROR two"])


class InspectChainTests(unittest.TestCase):
    def test_chain_picks_schema_fields(self) -> None:
        raw = json.loads((ROOT / "chains/sql.inspect-db.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["name"], "sql.inspect-db")
        self.assertEqual(raw["safety"], "read-only")
        self.assertEqual(raw["steps"][0]["tool"], "sql.schema")
        self.assertEqual(raw["steps"][0]["args"]["db"], "$input.db")
        self.assertEqual(raw["steps"][1]["tool"], "json.pick")
        self.assertEqual(raw["steps"][1]["args"]["keys"], "db,table_count,tables")


if __name__ == "__main__":
    unittest.main()
