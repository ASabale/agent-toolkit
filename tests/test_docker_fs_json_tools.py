"""Seams for docker.ps-digest, json.diff, and fs.read-slice."""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(script: Path, env: dict) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    for key in list(merged):
        if key.startswith("TK_ARG_") or key in {"TK_DRY_RUN", "TK_DOCKER_BIN"}:
            merged.pop(key, None)
    merged.update(env)
    merged.setdefault("TK_DRY_RUN", "0")
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=merged,
    )


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class DockerPsDigestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fake = self.root / "docker"
        _write_exec(
            self.fake,
            "#!/bin/sh\n"
            "printf '%s\\n' \\\n"
            '\'{"ID":"abc","Names":"web","Image":"nginx:1","State":"running","Status":"Up 2 hours","Ports":"0.0.0.0:80->80/tcp"}\' \\\n'
            '\'{"ID":"def","Names":"api","Image":"api:2","State":"running","Status":"Up 1 hour","Ports":"8080/tcp"}\' \\\n'
            '\'{"ID":"ghi","Names":"job","Image":"busybox","State":"exited","Status":"Exited (0)","Ports":""}\'\n',
        )

    def test_filters_state_and_caps_limit(self) -> None:
        proc = _run(
            ROOT / "tools/docker/ps-digest",
            {"TK_DOCKER_BIN": str(self.fake), "TK_ARG_STATE": "running", "TK_ARG_LIMIT": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["running"], 2)
        self.assertEqual(payload["exited"], 1)
        self.assertTrue(payload["truncated"])
        self.assertEqual(
            payload["containers"],
            [
                {
                    "id": "abc",
                    "name": "web",
                    "image": "nginx:1",
                    "state": "running",
                    "status": "Up 2 hours",
                    "ports": "0.0.0.0:80->80/tcp",
                }
            ],
        )

    def test_all_returns_every_container(self) -> None:
        proc = _run(
            ROOT / "tools/docker/ps-digest",
            {"TK_DOCKER_BIN": str(self.fake), "TK_ARG_STATE": "all", "TK_ARG_LIMIT": "25"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["count"], 3)
        self.assertFalse(payload["truncated"])
        self.assertEqual([row["name"] for row in payload["containers"]], ["web", "api", "job"])

    def test_missing_binary_is_docker_unavailable(self) -> None:
        proc = _run(
            ROOT / "tools/docker/ps-digest",
            {"TK_DOCKER_BIN": str(self.root / "missing-docker"), "TK_ARG_STATE": "all", "TK_ARG_LIMIT": "5"},
        )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        err = json.loads(proc.stderr)
        self.assertEqual(err["error"], "docker_unavailable")

    def test_nonzero_docker_is_docker_failed(self) -> None:
        broken = self.root / "broken-docker"
        _write_exec(broken, "#!/bin/sh\necho 'Cannot connect to the Docker daemon' >&2\nexit 1\n")
        proc = _run(
            ROOT / "tools/docker/ps-digest",
            {"TK_DOCKER_BIN": str(broken), "TK_ARG_STATE": "all", "TK_ARG_LIMIT": "5"},
        )
        self.assertEqual(proc.returncode, 1)
        err = json.loads(proc.stderr)
        self.assertEqual(err["error"], "docker_failed")
        self.assertIn("Docker daemon", err["why"])

    def test_dry_run(self) -> None:
        proc = _run(
            ROOT / "tools/docker/ps-digest",
            {"TK_ARG_STATE": "exited", "TK_ARG_LIMIT": "4", "TK_DRY_RUN": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {"dry_run": True, "state": "exited", "limit": 4})


class JsonDiffTests(unittest.TestCase):
    def test_nested_added_removed_and_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left.json"
            right = root / "right.json"
            left.write_text(
                json.dumps(
                    {
                        "a": {"b": 1, "c": 2},
                        "items": [{"name": "x"}, {"name": "y"}],
                        "gone": True,
                    }
                ),
                encoding="utf-8",
            )
            right.write_text(
                json.dumps(
                    {
                        "a": {"b": 1, "d": 3},
                        "items": [{"name": "z"}],
                        "extra": 1,
                    }
                ),
                encoding="utf-8",
            )
            proc = _run(
                ROOT / "tools/json/diff",
                {"TK_ARG_LEFT": str(left), "TK_ARG_RIGHT": str(right), "TK_ARG_LIMIT": "30"},
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["equal"])
        self.assertFalse(payload["truncated"])
        self.assertEqual(payload["added"], [{"path": "a.d", "value": 3}, {"path": "extra", "value": 1}])
        self.assertEqual(
            payload["removed"],
            [
                {"path": "a.c", "value": 2},
                {"path": "gone", "value": True},
                {"path": "items[1]", "value": {"name": "y"}},
            ],
        )
        self.assertEqual(payload["changed"], [{"path": "items[0].name", "left": "x", "right": "z"}])
        self.assertEqual(payload["count"], 6)

    def test_bool_is_not_an_int(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left.json"
            right = root / "right.json"
            left.write_text('{"flag": true}', encoding="utf-8")
            right.write_text('{"flag": 1}', encoding="utf-8")
            proc = _run(
                ROOT / "tools/json/diff",
                {"TK_ARG_LEFT": str(left), "TK_ARG_RIGHT": str(right)},
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["equal"])
        self.assertEqual(payload["changed"], [{"path": "flag", "left": True, "right": 1}])
        self.assertEqual(payload["added"], [])
        self.assertEqual(payload["removed"], [])

    def test_equal_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "same.json"
            path.write_text('{"n":[1,{"ok":true}]}', encoding="utf-8")
            proc = _run(
                ROOT / "tools/json/diff",
                {"TK_ARG_LEFT": str(path), "TK_ARG_RIGHT": str(path), "TK_ARG_LIMIT": "5"},
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(
            payload,
            {"equal": True, "count": 0, "truncated": False, "added": [], "removed": [], "changed": []},
        )

    def test_limit_caps_each_category(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left.json"
            right = root / "right.json"
            left.write_text("{}", encoding="utf-8")
            right.write_text(json.dumps({f"k{i}": i for i in range(4)}), encoding="utf-8")
            proc = _run(
                ROOT / "tools/json/diff",
                {"TK_ARG_LEFT": str(left), "TK_ARG_RIGHT": str(right), "TK_ARG_LIMIT": "2"},
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["count"], 4)
        self.assertEqual([row["path"] for row in payload["added"]], ["k0", "k1"])

    def test_dry_run(self) -> None:
        proc = _run(
            ROOT / "tools/json/diff",
            {"TK_ARG_LEFT": "a.json", "TK_ARG_RIGHT": "b.json", "TK_ARG_LIMIT": "20", "TK_DRY_RUN": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            {"dry_run": True, "left": "a.json", "right": "b.json", "limit": 20},
        )


class ReadSliceTests(unittest.TestCase):
    def test_inclusive_range_and_line_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.txt"
            long_line = "L" * 350
            path.write_text("one\ntwo\n" + long_line + "\nfour\n", encoding="utf-8")
            proc = _run(
                ROOT / "tools/fs/read-slice",
                {"TK_ARG_PATH": str(path), "TK_ARG_START": "2", "TK_ARG_END": "80"},
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["total_lines"], 4)
        self.assertEqual(payload["start"], 2)
        self.assertEqual(payload["end"], 4)
        self.assertEqual(payload["lines"][0], {"line": 2, "text": "two"})
        self.assertEqual(payload["lines"][1]["line"], 3)
        self.assertEqual(len(payload["lines"][1]["text"]), 300)
        self.assertEqual(payload["lines"][2], {"line": 4, "text": "four"})

    def test_empty_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.txt"
            path.write_text("", encoding="utf-8")
            proc = _run(
                ROOT / "tools/fs/read-slice",
                {"TK_ARG_PATH": str(path), "TK_ARG_START": "1", "TK_ARG_END": "80"},
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["total_lines"], 0)
        self.assertEqual(payload["lines"], [])

    def test_start_past_end_is_invalid_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "short.txt"
            path.write_text("only\n", encoding="utf-8")
            proc = _run(
                ROOT / "tools/fs/read-slice",
                {"TK_ARG_PATH": str(path), "TK_ARG_START": "5", "TK_ARG_END": "9"},
            )
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(json.loads(proc.stderr)["error"], "invalid_range")

    def test_rejects_binary_file_with_nul(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blob.bin"
            path.write_bytes(b"hello\x00world\n")
            proc = _run(
                ROOT / "tools/fs/read-slice",
                {"TK_ARG_PATH": str(path), "TK_ARG_START": "1", "TK_ARG_END": "80"},
            )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        payload = json.loads(proc.stderr)
        self.assertEqual(payload["error"], "binary_file")
        self.assertIn(str(path), payload["why"])

    def test_dry_run(self) -> None:
        proc = _run(
            ROOT / "tools/fs/read-slice",
            {"TK_ARG_PATH": "README.md", "TK_ARG_START": "1", "TK_ARG_END": "30", "TK_DRY_RUN": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            {"dry_run": True, "path": "README.md", "start": 1, "end": 30},
        )


if __name__ == "__main__":
    unittest.main()
