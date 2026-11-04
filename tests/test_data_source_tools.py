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


def _install_fake_psql(directory: Path, stdout: str, code: int = 0) -> Path:
    """A psql stand-in that records argv, PGOPTIONS, and stdin, then prints stdout."""
    log = directory / "psql-capture.txt"
    script = directory / "psql"
    script.write_text(
        "\n".join(
            [
                f"#!{sys.executable}",
                "import os, sys",
                "from pathlib import Path",
                "log = Path(os.environ['PSQL_CAPTURE'])",
                "stdin = sys.stdin.read()",
                "log.write_text(",
                "    'argv:' + '\\0'.join(sys.argv) + '\\n'",
                "    + 'PGOPTIONS:' + os.environ.get('PGOPTIONS', '') + '\\n'",
                "    + 'stdin:' + stdin",
                ")",
                f"sys.stdout.write({stdout!r})",
                f"raise SystemExit({code})",
                "",
            ]
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return log


def _postgres_env(bin_dir: Path, log: Path, **extra: str) -> dict:
    env = {
        "PATH": str(bin_dir),
        "PSQL_CAPTURE": str(log),
        "TK_ARG_DB": "postgresql://app:supersecret@localhost:5432/appdb",
    }
    env.update(extra)
    return env


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

    def test_postgres_url_uses_psql_and_redacts_password(self) -> None:
        tables = [
            {
                "name": "widgets",
                "rows": 3,
                "columns": [
                    {"name": "id", "type": "integer", "pk": 1, "notnull": 0},
                    {"name": "name", "type": "text", "pk": 0, "notnull": 1},
                ],
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            log = _install_fake_psql(bin_dir, json.dumps(tables))
            proc = _run(
                ROOT / "tools/sql/schema",
                _postgres_env(bin_dir, log, TK_ARG_TABLE="all"),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("supersecret", proc.stdout)
            self.assertNotIn("supersecret", proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["db"], "postgresql://app:***@localhost:5432/appdb")
            self.assertEqual(payload["table_count"], 1)
            self.assertEqual(payload["tables"], tables)
            captured = log.read_text(encoding="utf-8")
        self.assertIn("information_schema.columns", captured)
        self.assertIn("-c default_transaction_read_only=on", captured)
        self.assertIn("-c statement_timeout=15000", captured)
        self.assertIn("-X", captured)
        self.assertIn("-A", captured)
        self.assertIn("-t", captured)

    def test_postgres_schema_missing_psql(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run(
                ROOT / "tools/sql/schema",
                {
                    "PATH": tmp,
                    "TK_ARG_DB": "postgres://app:supersecret@localhost/appdb",
                    "TK_ARG_TABLE": "all",
                },
            )
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("supersecret", proc.stdout)
        self.assertNotIn("supersecret", proc.stderr)
        err = json.loads(proc.stderr)
        self.assertEqual(err["error"], "psql_unavailable")
        self.assertEqual(err["fix"], "install postgresql-client")
        self.assertTrue(err["why"])

    def test_header_mentions_postgres_urls(self) -> None:
        header = (ROOT / "tools/sql/schema").read_text(encoding="utf-8").splitlines()[:12]
        text = "\n".join(header)
        self.assertIn("Postgres", text)
        self.assertIn("postgres://", text)


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
        self.assertEqual(payload["truncated"], 1)
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

    def test_limit_one_sets_integer_truncated_and_next(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "app.db"
            _make_db(db)
            env = os.environ.copy()
            env["TK_NO_TELEMETRY"] = "1"
            proc = subprocess.run(
                [
                    str(ROOT / "tk"),
                    "run",
                    "sql.query",
                    "--db",
                    str(db),
                    "--sql",
                    "SELECT id, name FROM widgets ORDER BY id",
                    "--limit",
                    "1",
                ],
                capture_output=True,
                text=True,
                env=env,
                cwd=ROOT,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIsInstance(payload["truncated"], int)
        self.assertNotIsInstance(payload["truncated"], bool)
        self.assertGreaterEqual(payload["truncated"], 1)
        self.assertEqual(
            payload["next"],
            f"tk run sql.query --db {db} --sql 'SELECT id, name FROM widgets ORDER BY id' --limit 2",
        )

    def test_postgres_url_shapes_rows_and_hides_password(self) -> None:
        body = {
            "columns": ["id", "name"],
            "total": 3,
            "rows": [
                {"id": 1, "name": "alpha"},
                {"id": 2, "name": "beta"},
                {"id": 3, "name": "gamma"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            log = _install_fake_psql(bin_dir, json.dumps(body))
            proc = _run(
                ROOT / "tools/sql/query",
                _postgres_env(
                    bin_dir,
                    log,
                    TK_ARG_SQL="SELECT id, name FROM widgets ORDER BY id",
                    TK_ARG_LIMIT="2",
                ),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("supersecret", proc.stdout)
            self.assertNotIn("supersecret", proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["db"], "postgresql://app:***@localhost:5432/appdb")
            self.assertEqual(payload["columns"], ["id", "name"])
            self.assertEqual(payload["count"], 2)
            self.assertIsInstance(payload["truncated"], int)
            self.assertNotIsInstance(payload["truncated"], bool)
            self.assertEqual(payload["truncated"], 1)
            self.assertEqual(
                payload["rows"],
                [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}],
            )
            captured = log.read_text(encoding="utf-8")
        self.assertIn("json_agg", captured)
        self.assertIn("row_to_json", captured)
        self.assertIn("LIMIT 2", captured)
        self.assertIn("-c default_transaction_read_only=on", captured)
        self.assertIn("-c statement_timeout=15000", captured)
        argv = captured.splitlines()[0]
        self.assertIn("\0-X\0", argv)
        self.assertIn("\0-A\0", argv)
        self.assertTrue(argv.endswith("\0-t"))

    def test_postgres_write_is_rejected_before_psql(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            log = _install_fake_psql(bin_dir, "should-not-run")
            proc = _run(
                ROOT / "tools/sql/query",
                _postgres_env(
                    bin_dir,
                    log,
                    TK_ARG_SQL="DELETE FROM widgets",
                    TK_ARG_LIMIT="25",
                ),
            )
            self.assertFalse(log.exists())
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stderr)["error"], "mutating_sql")
        self.assertNotIn("supersecret", proc.stdout)
        self.assertNotIn("supersecret", proc.stderr)

    def test_postgres_missing_psql(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run(
                ROOT / "tools/sql/query",
                {
                    "PATH": tmp,
                    "TK_ARG_DB": "postgres://app:supersecret@localhost/appdb",
                    "TK_ARG_SQL": "SELECT 1",
                    "TK_ARG_LIMIT": "25",
                },
            )
        self.assertEqual(proc.returncode, 1)
        err = json.loads(proc.stderr)
        self.assertEqual(err["error"], "psql_unavailable")
        self.assertEqual(err["fix"], "install postgresql-client")
        self.assertNotIn("supersecret", proc.stdout + proc.stderr)

    def test_query_header_mentions_postgres_urls(self) -> None:
        header = (ROOT / "tools/sql/query").read_text(encoding="utf-8").splitlines()[:12]
        text = "\n".join(header)
        self.assertIn("Postgres", text)
        self.assertIn("postgres://", text)


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
        self.assertEqual(payload["truncated"], 0)

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
        self.assertEqual(payload["truncated"], 2)
        self.assertEqual([item["message"] for item in payload["errors"]], ["ERROR one", "ERROR two"])

    def test_limit_one_sets_integer_truncated_and_next(self) -> None:
        body = "ERROR one\nERROR two\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.log"
            path.write_text(body, encoding="utf-8")
            env = os.environ.copy()
            env["TK_NO_TELEMETRY"] = "1"
            proc = subprocess.run(
                [
                    str(ROOT / "tk"),
                    "run",
                    "log.tail-errors",
                    "--path",
                    str(path),
                    "--tail",
                    "50",
                    "--limit",
                    "1",
                ],
                capture_output=True,
                text=True,
                env=env,
                cwd=ROOT,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIsInstance(payload["truncated"], int)
        self.assertNotIsInstance(payload["truncated"], bool)
        self.assertGreaterEqual(payload["truncated"], 1)
        self.assertEqual(
            payload["next"],
            f"tk run log.tail-errors --path {path} --tail 50 --limit 2",
        )


if __name__ == "__main__":
    unittest.main()
