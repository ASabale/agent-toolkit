"""Seams for lib/catalog.py: header parsing, search, find text, and check_item."""

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.catalog import (  # noqa: E402
    check_all,
    check_item,
    discover_catalog,
    find_items,
    format_find_output,
    format_info_output,
    load_chain,
    output_keys,
    parse_tool_header,
    suggest_closest_item,
)
from lib.runner import run_tool  # noqa: E402


def _write(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
    if executable:
        mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    path.chmod(mode)


def _bash_tool(name: str, summary: str, safety: str = "read-only", args=None, body=None, example=None) -> str:
    args = args or [("--target", "required", "string", "Target resource identifier")]
    arg_lines = "\n".join(
        f"# @tk-arg: {flag} | {req} | {typ} | {desc}" for flag, req, typ, desc in args
    )
    required_flags = " ".join(f"{flag} example" for flag, req, _typ, _desc in args if req == "required")
    example = example or f"tk run {name} {required_flags}".strip()
    if body is None:
        body = """if [[ "${TK_DRY_RUN:-0}" == "1" ]]; then
  printf '%s\\n' '{"dry_run":true}'
  exit 0
fi
printf '%s\\n' '{"ok":true}'
"""
    return (
        "#!/usr/bin/env bash\n"
        f"# @tk-name: {name}\n"
        f"# @tk-summary: {summary}\n"
        f"# @tk-safety: {safety}\n"
        f"{arg_lines}\n"
        f"# @tk-output: json | Distilled object\n"
        f"# @tk-example: {example}\n"
        "# @tk-verified: none\n"
        "\n"
        f"{body}"
    )


class ParseHeaderTests(unittest.TestCase):
    def test_parse_tool_header_fields_env_and_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.echo"
            _write(path, _bash_tool(
                "demo.echo",
                "Echo a target id",
                args=[
                    ("--target", "required", "string", "Target resource identifier"),
                    ("--limit", "optional", "int", "Maximum items to return (default: 20)"),
                ],
                example="tk run demo.echo --target example --limit 10",
            ))
            item = parse_tool_header(path)

        self.assertEqual(item["kind"], "tool")
        self.assertEqual(item["name"], "demo.echo")
        self.assertEqual(item["summary"], "Echo a target id")
        self.assertEqual(item["safety"], "read-only")
        self.assertEqual(item["output"], "json | Distilled object")
        self.assertEqual(item["example"], "tk run demo.echo --target example --limit 10")
        self.assertEqual(item["verified"], "none")
        self.assertEqual(item["path"], str(path.resolve()))
        self.assertEqual(item["args"][0]["flag"], "--target")
        self.assertEqual(item["args"][0]["env_var"], "TK_ARG_TARGET")
        self.assertTrue(item["args"][0]["required"])
        self.assertEqual(item["args"][0]["type"], "string")
        self.assertIsNone(item["args"][0]["default"])
        self.assertEqual(item["args"][1]["flag"], "--limit")
        self.assertEqual(item["args"][1]["env_var"], "TK_ARG_LIMIT")
        self.assertFalse(item["args"][1]["required"])
        self.assertEqual(item["args"][1]["type"], "int")
        self.assertEqual(item["args"][1]["default"], "20")

    def test_parse_missing_file_does_not_raise(self):
        missing = Path(tempfile.gettempdir()) / "tk-catalog-does-not-exist"
        item = parse_tool_header(missing)
        self.assertEqual(item["kind"], "tool")
        self.assertEqual(item["name"], "")
        self.assertEqual(item["args"], [])

    def test_load_chain_normalizes_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.pipeline.json"
            path.write_text(json.dumps({
                "name": "demo.pipeline",
                "summary": "Echo then stop",
                "safety": "read-only",
                "args": ["--target | required | string | Target resource identifier"],
                "steps": [{"tool": "demo.echo"}],
                "output": "json | object",
                "example": "tk run demo.pipeline --target example",
                "verified": "none",
            }), encoding="utf-8")
            item = load_chain(path)
        self.assertEqual(item["kind"], "chain")
        self.assertEqual(item["name"], "demo.pipeline")
        self.assertEqual(item["steps"], [{"tool": "demo.echo"}])
        self.assertEqual(item["args"][0]["env_var"], "TK_ARG_TARGET")
        self.assertTrue(item["args"][0]["required"])
        self.assertEqual(item["path"], str(path.resolve()))

    def test_load_chain_bad_json_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text("{", encoding="utf-8")
            item = load_chain(path)
        self.assertEqual(item["kind"], "chain")
        self.assertEqual(item["name"], "")
        self.assertEqual(item["steps"], [])


class DiscoverAndFindTests(unittest.TestCase):
    def _catalog(self, root: Path) -> None:
        _write(
            root / "tools" / "gh" / "pr-checks",
            _bash_tool(
                "gh.pr-checks",
                "Fetch failing pull request checks",
                args=[("--repo", "required", "string", "Repository name")],
                example="tk run gh.pr-checks --repo example",
            ),
            executable=True,
        )
        _write(
            root / "tools" / "notes" / "list",
            _bash_tool(
                "notes.list",
                "List notes",
                args=[("--limit", "optional", "int", "Maximum items to return (default: 20)")],
                example="tk run notes.list",
            ),
            executable=True,
        )
        _write(
            root / "tools" / "pr" / "view",
            _bash_tool(
                "pr.view",
                "Show one record",
                args=[("--repo", "required", "string", "Repository name")],
                example="tk run pr.view --repo example",
            ),
            executable=True,
        )
        _write(root / "tools" / ".hidden" / "secret", _bash_tool("secret.tool", "nope"), executable=True)
        _write(root / "tools" / "__pycache__" / "x", _bash_tool("cache.tool", "nope"), executable=True)

    def test_discover_skips_hidden_and_sorts_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._catalog(root)
            catalog = discover_catalog(root)
        self.assertEqual(list(catalog), ["gh.pr-checks", "notes.list", "pr.view"])

    def test_empty_query_lists_all_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._catalog(root)
            names = [item["name"] for item in find_items(root, "")]
        self.assertEqual(names, ["gh.pr-checks", "notes.list", "pr.view"])

    def test_search_ranks_exact_name_tokens_above_summary_and_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._catalog(root)
            # "pr" is an exact name segment of gh.pr-checks (5) and pr.view (5).
            # "view" is an exact segment of pr.view (5) and also in its summary (2).
            # gh.pr-checks does not contain "view". notes.list matches neither.
            ranked = [item["name"] for item in find_items(root, "pr view")]
        self.assertEqual(ranked, ["pr.view", "gh.pr-checks"])

    def test_find_items_positive_limit_slices_sorted_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._catalog(root)
            limited = [item["name"] for item in find_items(root, "", limit=2)]
            unbounded = [item["name"] for item in find_items(root, "", limit=None)]
            ignored = [item["name"] for item in find_items(root, "", limit=0)]
            namespaced = [item["name"] for item in find_items(root, "", namespace="  GH. ")]
            dotted = [item["name"] for item in find_items(root, "view", namespace="pr.")]
            unmatched = [item["name"] for item in find_items(root, "", namespace="missing")]
        self.assertEqual(limited, ["gh.pr-checks", "notes.list"])
        self.assertEqual(unbounded, ["gh.pr-checks", "notes.list", "pr.view"])
        self.assertEqual(ignored, unbounded)
        self.assertEqual(namespaced, ["gh.pr-checks"])
        self.assertEqual(dotted, ["pr.view"])
        self.assertEqual(unmatched, [])

    def test_summary_hit_beats_args_only_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._catalog(root)
            # "notes" exact segment + summary on notes.list.
            # "pull" is only in gh.pr-checks summary (weight 2), not the name.
            summary_first = [item["name"] for item in find_items(root, "pull")]
            self.assertEqual(summary_first, ["gh.pr-checks"])
            # "repository" appears only in --repo descriptions (weight 1).
            arg_hits = [item["name"] for item in find_items(root, "repository")]
        self.assertEqual(arg_hits, ["gh.pr-checks", "pr.view"])

    def test_format_find_output_is_two_lines_per_item(self):
        items = [
            {
                "name": "gh.pr-checks",
                "safety": "read-only",
                "summary": "Fetch failing pull request checks",
                "example": "tk run gh.pr-checks --repo example",
            },
            {
                "name": "notes.list",
                "safety": "mutating",
                "summary": "List notes",
                "example": "tk run notes.list",
            },
        ]
        text = format_find_output(items)
        self.assertEqual(
            text,
            "gh.pr-checks [read-only] — Fetch failing pull request checks\n"
            "  run: tk run gh.pr-checks --repo example\n"
            "notes.list [mutating] — List notes\n"
            "  run: tk run notes.list\n",
        )

    def test_format_info_output_lists_contract_fields(self):
        item = {
            "name": "demo.echo",
            "kind": "tool",
            "safety": "read-only",
            "summary": "Echo a target id",
            "args": [{
                "flag": "--target",
                "env_var": "TK_ARG_TARGET",
                "required": True,
                "type": "string",
                "description": "Target resource identifier",
                "default": None,
            }],
            "output": "json | Distilled object",
            "example": "tk run demo.echo --target example",
            "verified": "none",
        }
        text = format_info_output(item)
        self.assertIn("name: demo.echo", text)
        self.assertIn("kind: tool", text)
        self.assertIn("safety: read-only", text)
        self.assertIn("summary: Echo a target id", text)
        self.assertIn("--target | required | string | Target resource identifier", text)
        self.assertIn("output: json | Distilled object", text)
        self.assertIn("example: tk run demo.echo --target example", text)
        self.assertIn("verified: none", text)


class CheckItemTests(unittest.TestCase):
    def test_check_item_accepts_valid_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "tools" / "demo" / "echo"
            _write(path, _bash_tool("demo.echo", "Echo a target id"), executable=True)
            result = check_item(root, "demo.echo")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["name"], "demo.echo")

    def test_check_item_needs_missing_executable_names_a_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "tools" / "demo" / "echo"
            text = _bash_tool("demo.echo", "Echo a target id")
            text = text.replace(
                "# @tk-verified: none\n",
                "# @tk-verified: none\n# @tk-needs: definitely-missing-bin\n",
                1,
            )
            _write(path, text, executable=True)
            result = check_item(root, "demo.echo")
        self.assertFalse(result["ok"])
        blob = " ".join(result["errors"])
        self.assertIn("definitely-missing-bin", blob)
        self.assertIn("fix:", blob)
        self.assertNotIn("sandbox", blob.lower())

    def test_check_item_needs_missing_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "tools" / "demo" / "echo"
            text = _bash_tool("demo.echo", "Echo a target id")
            text = text.replace(
                "# @tk-verified: none\n",
                "# @tk-verified: none\n# @tk-needs: env:TK_NEEDS_ABSENT_FOR_TEST\n",
                1,
            )
            _write(path, text, executable=True)
            os.environ.pop("TK_NEEDS_ABSENT_FOR_TEST", None)
            result = check_item(root, "demo.echo")
        blob = " ".join(result["errors"])
        self.assertIn("missing env: TK_NEEDS_ABSENT_FOR_TEST", blob)
        self.assertIn("fix:", blob)

    def test_check_item_needs_present_bin_and_env_stay_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "tools" / "demo" / "echo"
            text = _bash_tool("demo.echo", "Echo a target id")
            text = text.replace(
                "# @tk-verified: none\n",
                "# @tk-verified: none\n# @tk-needs: sh env:TK_NEEDS_PRESENT\n",
                1,
            )
            _write(path, text, executable=True)
            old = os.environ.get("TK_NEEDS_PRESENT")
            os.environ["TK_NEEDS_PRESENT"] = "1"
            try:
                result = check_item(root, "demo.echo")
            finally:
                if old is None:
                    os.environ.pop("TK_NEEDS_PRESENT", None)
                else:
                    os.environ["TK_NEEDS_PRESENT"] = old
        self.assertTrue(result["ok"], result)

    def test_check_item_needs_still_runs_the_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "tools" / "demo" / "echo"
            body = "printf '%s\\n' 'not-json'\n"
            text = _bash_tool("demo.echo", "Echo a target id", body=body)
            text = text.replace(
                "# @tk-verified: none\n",
                "# @tk-verified: none\n# @tk-needs: definitely-missing-bin\n",
                1,
            )
            _write(path, text, executable=True)
            result = check_item(root, "demo.echo")
        blob = " ".join(result["errors"])
        self.assertIn("definitely-missing-bin", blob)
        self.assertTrue(any("json" in err.lower() for err in result["errors"]))

    def test_check_item_missing_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "tools" / "bare"
            _write(path, "#!/usr/bin/env bash\necho hi\n", executable=True)
            result = check_item(root, path)
        self.assertFalse(result["ok"])
        blob = " ".join(result["errors"]).lower()
        for field in ("summary", "safety", "output", "example", "verified"):
            self.assertIn(field, blob)

    def test_check_item_non_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "tools" / "demo" / "echo"
            _write(path, _bash_tool("demo.echo", "Echo a target id"), executable=False)
            result = check_item(root, path)
        self.assertFalse(result["ok"])
        self.assertTrue(any("executable" in err.lower() for err in result["errors"]))

    def test_check_item_python_syntax_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "tools" / "bad" / "syntax"
            text = """#!/usr/bin/env python3
# @tk-name: bad.syntax
# @tk-summary: Broken python tool
# @tk-safety: read-only
# @tk-arg: --target | required | string | Target resource identifier
# @tk-output: json | object
# @tk-example: tk run bad.syntax --target example
# @tk-verified: none

def broken(
"""
            _write(path, text, executable=True)
            result = check_item(root, path)
        self.assertFalse(result["ok"])
        self.assertTrue(any("syntax" in err.lower() for err in result["errors"]))

    def test_check_item_reports_undeclared_script_arg_env_vars(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "tools" / "demo" / "echo"
            body = """if [[ "${TK_DRY_RUN:-0}" == "1" ]]; then
  printf '%s\\n' '{"dry_run":true}'
  exit 0
fi
# TK_ARG_SKIP stays a comment and is not an undeclared arg.
printf '%s\\n' \"$TK_ARG_OTHER\"
printf '%s\\n' \"${TK_ARG_EXTRA}\"
"""
            _write(
                path,
                _bash_tool("demo.echo", "Echo a target id", body=body),
                executable=True,
            )
            result = check_item(root, "demo.echo")
        self.assertFalse(result["ok"])
        self.assertEqual(
            [err for err in result["errors"] if err.startswith("undeclared arg env var")],
            [
                "undeclared arg env var in script: TK_ARG_EXTRA",
                "undeclared arg env var in script: TK_ARG_OTHER",
            ],
        )

    def test_check_item_ignores_tk_arg_in_inline_comment_and_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "tools" / "demo" / "echo"
            body = """if [[ "${TK_DRY_RUN:-0}" == "1" ]]; then
  printf '%s\\n' '{"dry_run":true}'
  exit 0
fi
printf '%s\\n' '{"ok":true}' # TK_ARG_FOO is only a comment
printf '%s\\n' 'error: TK_ARG_FOO was not set'
printf '%s\\n' \"$TK_ARG_TARGET\"
"""
            _write(path, _bash_tool("demo.echo", "Echo a target id", body=body), executable=True)
            result = check_item(root, "demo.echo")
        self.assertNotIn(
            "undeclared arg env var in script: TK_ARG_FOO",
            result["errors"],
        )
        self.assertTrue(result["ok"], result["errors"])

    def test_check_item_rejects_required_flag_without_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "tools" / "demo" / "echo"
            _write(
                path,
                _bash_tool(
                    "demo.echo",
                    "Echo a target id",
                    example="tk run demo.echo --target",
                    args=[
                        ("--target", "required", "string", "Target resource identifier"),
                        ("--verbose", "required", "bool", "Print extra detail"),
                    ],
                ),
                executable=True,
            )
            result = check_item(root, "demo.echo")
        self.assertFalse(result["ok"])
        self.assertTrue(any("missing value" in err and "--target" in err for err in result["errors"]))
        self.assertFalse(any("--verbose" in err and "missing value" in err for err in result["errors"]))

    def test_check_item_broken_dry_run_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "tools" / "bad" / "dry"
            body = """if [[ "${TK_DRY_RUN:-0}" == "1" ]]; then
  printf '%s\\n' 'not-json'
  exit 0
fi
printf '%s\\n' '{"ok":true}'
"""
            _write(
                path,
                _bash_tool("bad.dry", "Prints plain text on dry run", body=body),
                executable=True,
            )
            result = check_item(root, "bad.dry")
        self.assertFalse(result["ok"])
        self.assertTrue(any("dry-run" in err.lower() or "json" in err.lower() for err in result["errors"]))

    def test_check_item_chain_missing_step_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = root / "chains" / "demo.pipeline.json"
            chain.parent.mkdir(parents=True)
            chain.write_text(json.dumps({
                "name": "demo.pipeline",
                "summary": "Calls a tool that is not in the catalog",
                "safety": "read-only",
                "args": [],
                "steps": [{"tool": "missing.tool"}],
                "output": "json | object",
                "example": "tk run demo.pipeline",
                "verified": "none",
            }), encoding="utf-8")
            result = check_item(root, "demo.pipeline")
        self.assertFalse(result["ok"])
        self.assertTrue(any("missing.tool" in err for err in result["errors"]))
        self.assertFalse(any("dry-run" in err for err in result["errors"]))

    def _chain_with_tool(self, root: Path, steps, chain_args=None, tool_args=None, body=None):
        _write(
            root / "tools" / "demo" / "echo",
            _bash_tool(
                "demo.echo",
                "Echo a target id",
                args=tool_args
                or [
                    ("--target", "required", "string", "Target resource identifier"),
                    ("--limit", "optional", "int", "Maximum items (default: 3)"),
                ],
                body=body,
            ),
            executable=True,
        )
        chain = root / "chains" / "demo.pipeline.json"
        chain.parent.mkdir(parents=True)
        chain.write_text(json.dumps({
            "name": "demo.pipeline",
            "summary": "Wires demo.echo",
            "safety": "read-only",
            "args": chain_args if chain_args is not None else [
                {"flag": "--repo", "required": True, "type": "string", "description": "Repository path"},
            ],
            "steps": steps,
            "output": "json | object",
            "example": "tk run demo.pipeline --repo .",
            "verified": "none",
        }), encoding="utf-8")

    def test_check_item_chain_unknown_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._chain_with_tool(root, [{"tool": "demo.echo", "args": {"nope": "x", "target": "a"}}])
            result = check_item(root, "demo.pipeline")
        self.assertFalse(result["ok"])
        self.assertIn("step 0 (demo.echo) unknown flag: --nope", result["errors"])

    def test_check_item_chain_missing_required_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._chain_with_tool(
                root,
                [{"tool": "demo.echo", "args": {}}],
                tool_args=[
                    ("--target", "required", "string", "Target resource identifier"),
                    ("--limit", "required", "int", "Maximum items (default: 3)"),
                ],
            )
            result = check_item(root, "demo.pipeline")
        self.assertFalse(result["ok"])
        self.assertIn("step 0 (demo.echo) missing required flag: --target", result["errors"])
        self.assertFalse(any("--limit" in err and "missing required" in err for err in result["errors"]))

    def test_check_item_chain_unresolved_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._chain_with_tool(
                root,
                [{"tool": "demo.echo", "args": {"target": "$input.repo_path"}}],
                chain_args=[
                    {"flag": "--repo-path", "required": True, "type": "string", "description": "Repository path"},
                ],
            )
            chain = root / "chains" / "demo.pipeline.json"
            data = json.loads(chain.read_text(encoding="utf-8"))
            data["example"] = "tk run demo.pipeline --repo-path ."
            data["steps"] = [{"tool": "demo.echo", "args": {"target": "$input.missing"}}]
            chain.write_text(json.dumps(data), encoding="utf-8")
            bad = check_item(root, "demo.pipeline")
            data["steps"] = [{"tool": "demo.echo", "args": {"target": "$input.repo_path"}}]
            chain.write_text(json.dumps(data), encoding="utf-8")
            good = check_item(root, "demo.pipeline")
        self.assertIn("step 0 unresolved input reference: $input.missing", bad["errors"])
        self.assertNotIn("unresolved input reference", " ".join(good["errors"]))
        self.assertTrue(good["ok"], good["errors"])

    def test_check_item_chain_step0_prev_and_bad_step_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._chain_with_tool(
                root,
                [
                    {"tool": "demo.echo", "args": {"target": "$prev.id"}},
                    {"tool": "demo.echo", "args": {"target": "$step[1].id"}},
                    {"tool": "demo.echo", "args": {"target": "$prev"}},
                ],
            )
            result = check_item(root, "demo.pipeline")
        self.assertIn("step 0 cannot reference $prev: $prev.id", result["errors"])
        self.assertIn("step 1 invalid step reference: $step[1].id", result["errors"])
        self.assertFalse(any("step 2 cannot reference $prev" in err for err in result["errors"]))

    def test_check_item_chain_step_cannot_target_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inner = root / "chains" / "demo.inner.json"
            inner.parent.mkdir(parents=True)
            inner.write_text(json.dumps({
                "name": "demo.inner",
                "summary": "Nested chain that must not be a step target",
                "safety": "read-only",
                "args": [],
                "steps": [],
                "output": "json | object",
                "example": "tk run demo.inner",
                "verified": "none",
            }), encoding="utf-8")
            outer = root / "chains" / "demo.outer.json"
            outer.write_text(json.dumps({
                "name": "demo.outer",
                "summary": "Chain that illegally targets another chain",
                "safety": "read-only",
                "args": [],
                "steps": [{"tool": "demo.inner", "args": {}}],
                "output": "json | object",
                "example": "tk run demo.outer",
                "verified": "none",
            }), encoding="utf-8")
            result = check_item(root, "demo.outer")
        self.assertFalse(result["ok"])
        self.assertIn("step 0 (demo.inner) cannot target a chain", result["errors"])

    def test_check_item_chain_dry_run_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = """printf '%s\\n' '{"error":"nope"}' >&2
exit 2
"""
            self._chain_with_tool(
                root,
                [{"tool": "demo.echo", "args": {"target": "$input.repo"}}],
                body=body,
            )
            result = check_item(root, "demo.pipeline")
        self.assertFalse(result["ok"])
        self.assertTrue(any(err.startswith("chain dry-run failed:") for err in result["errors"]))

    def test_check_all_aggregates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "tools" / "demo" / "echo",
                _bash_tool("demo.echo", "Echo a target id"),
                executable=True,
            )
            _write(
                root / "tools" / "bare",
                "#!/usr/bin/env bash\necho hi\n",
                executable=True,
            )
            report = check_all(root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["checked"], 2)
        self.assertGreaterEqual(len(report["errors"]), 1)
        self.assertEqual(len(report["results"]), 2)

    def test_check_item_rejects_duplicate_flags_and_mistyped_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "tools" / "demo" / "echo"
            _write(
                path,
                _bash_tool(
                    "demo.echo",
                    "Echo a target id",
                    args=[
                        ("--limit", "optional", "int", "Maximum items (default: nope)"),
                        ("--limit", "optional", "int", "Maximum items (default: 5)"),
                        ("--verbose", "optional", "bool", "Verbose (default: maybe)"),
                        ("--ratio", "optional", "float", "Ratio (default: 1.5)"),
                    ],
                    example="tk run demo.echo",
                ),
                executable=True,
            )
            result = check_item(root, "demo.echo")
        self.assertFalse(result["ok"])
        self.assertIn("duplicate arg flag: --limit", result["errors"])
        self.assertIn("invalid default for --limit: nope is not int", result["errors"])
        self.assertIn("invalid default for --verbose: maybe is not bool", result["errors"])
        self.assertFalse(any("ratio" in err and "invalid default" in err for err in result["errors"]))

    def _chain_with_json_pick(self, root: Path, pick_keys: str, tool_output: str):
        """Create a tool with explicit output and a chain that pipes to json.pick."""
        tool_text = (
            "#!/usr/bin/env bash\n"
            "# @tk-name: producer.tool\n"
            "# @tk-summary: Produces structured output\n"
            "# @tk-safety: read-only\n"
            "# @tk-arg: --target | required | string | Target\n"
            f"# @tk-output: {tool_output}\n"
            "# @tk-example: tk run producer.tool --target example\n"
            "# @tk-verified: none\n"
            "\n"
            "if [[ \"${TK_DRY_RUN:-0}\" == \"1\" ]]; then\n"
            "  printf '%s\\n' '{\"dry_run\":true}'\n"
            "  exit 0\n"
            "fi\n"
            "printf '%s\\n' '{\"a\":1}'\n"
        )
        _write(root / "tools" / "producer" / "tool", tool_text, executable=True)
        _write(
            root / "tools" / "json" / "pick",
            _bash_tool(
                "json.pick",
                "Keep only named keys",
                args=[("--keys", "required", "string", "Comma-separated keys")],
                example="tk run json.pick --keys a,b",
            ),
            executable=True,
        )
        chain = root / "chains" / "test.pipeline.json"
        chain.parent.mkdir(parents=True, exist_ok=True)
        chain.write_text(json.dumps({
            "name": "test.pipeline",
            "summary": "Producer then pick",
            "safety": "read-only",
            "args": [{"flag": "--target", "required": True, "type": "string", "description": "Target"}],
            "steps": [
                {"tool": "producer.tool", "args": {"target": "$input.target"}},
                {"tool": "json.pick", "args": {"keys": pick_keys}},
            ],
            "output": "json | object",
            "example": "tk run test.pipeline --target example",
            "verified": "none",
        }), encoding="utf-8")

    def test_check_item_chain_json_pick_missing_key_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._chain_with_json_pick(root, "a,b,missing", "json | {a, b, c}")
            result = check_item(root, "test.pipeline")
        self.assertFalse(result["ok"])
        self.assertIn("step 1 (json.pick) key 'missing' not in upstream producer.tool output", result["errors"])

    def test_check_item_chain_json_pick_all_keys_present_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._chain_with_json_pick(root, "a,b", "json | {a, b, c}")
            result = check_item(root, "test.pipeline")
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["errors"], [])

    def test_check_item_chain_upstream_output_not_braces_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._chain_with_json_pick(root, "missing,keys", "json | distilled object")
            result = check_item(root, "test.pipeline")
        self.assertTrue(result["ok"], result["errors"])

    def test_check_item_chain_json_pick_nested_output_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._chain_with_json_pick(root, "repo,pr,fail,pass", "json | {repo, pr, fail:[{name, url}], pending, pass}")
            result = check_item(root, "test.pipeline")
        self.assertTrue(result["ok"], result["errors"])

    def test_check_item_chain_json_pick_nested_missing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._chain_with_json_pick(root, "repo,checks", "json | {repo, pr, fail:[{name, url}], pending, pass}")
            result = check_item(root, "test.pipeline")
        self.assertFalse(result["ok"])
        self.assertIn("step 1 (json.pick) key 'checks' not in upstream producer.tool output", result["errors"])


class OutputKeysTests(unittest.TestCase):
    """One @tk-output parser serves chain validation and the too-large fix."""

    DECLARED = "json | {zeta, alpha, mid:{nested}, tail:[1, 2]}"

    def _producer(self, root: Path) -> Path:
        path = root / "tools" / "order" / "producer"
        _write(
            path,
            "#!/usr/bin/env python3\n"
            "# @tk-name: order.producer\n"
            "# @tk-summary: Produce keys in a fixed order\n"
            "# @tk-safety: read-only\n"
            f"# @tk-output: {self.DECLARED}\n"
            "# @tk-example: tk run order.producer\n"
            "# @tk-verified: none\n"
            "\n"
            "import json, os, sys\n"
            "if os.environ.get('TK_DRY_RUN') == '1':\n"
            "    json.dump({'dry_run': True}, sys.stdout)\n"
            "    sys.exit(0)\n"
            "json.dump(\n"
            "    {'tail': 'x' * 60, 'alpha': 2, 'zeta': 1, 'mid': {'nested': 3}},\n"
            "    sys.stdout,\n"
            ")\n",
            executable=True,
        )
        return path

    def _chain(self, root: Path, pick_keys: str, name: str = "order.pipeline") -> None:
        _write(
            root / "tools" / "json" / "pick",
            _bash_tool(
                "json.pick",
                "Keep only named keys",
                args=[("--keys", "required", "string", "Comma-separated keys")],
                example="tk run json.pick --keys a,b",
            ),
            executable=True,
        )
        chain = root / "chains" / f"{name}.json"
        chain.parent.mkdir(parents=True, exist_ok=True)
        chain.write_text(
            json.dumps(
                {
                    "name": name,
                    "summary": "Producer then pick",
                    "safety": "read-only",
                    "args": [],
                    "steps": [
                        {"tool": "order.producer", "args": {}},
                        {"tool": "json.pick", "args": {"keys": pick_keys}},
                    ],
                    "output": "json | object",
                    "example": f"tk run {name}",
                    "verified": "none",
                }
            ),
            encoding="utf-8",
        )

    def test_output_keys_keeps_source_order_and_skips_non_braces(self):
        self.assertEqual(
            output_keys(self.DECLARED),
            ["zeta", "alpha", "mid", "tail"],
        )
        self.assertEqual(output_keys("json | {count:(1, 2), list:[1, 2], nested:{deep}}"), ["count", "list", "nested"])
        self.assertIsNone(output_keys("json | Distilled object"))
        self.assertEqual(output_keys("json | {}"), [])

    def test_check_item_and_too_large_fix_agree_on_one_key_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            producer = self._producer(root)
            self._chain(root, "zeta,alpha,mid")
            checked = check_item(root, "order.pipeline")
            self.assertTrue(checked["ok"], checked["errors"])

            item = parse_tool_header(producer)
            item["path"] = str(producer)
            previous = os.environ.get("TK_MAX_OUTPUT_BYTES")
            os.environ["TK_MAX_OUTPUT_BYTES"] = "40"
            os.environ["TK_NO_TELEMETRY"] = "1"
            try:
                code, out, err = run_tool(root, item, {})
            finally:
                if previous is None:
                    os.environ.pop("TK_MAX_OUTPUT_BYTES", None)
                else:
                    os.environ["TK_MAX_OUTPUT_BYTES"] = previous
        self.assertEqual(code, 1, out + err)
        payload = json.loads(err)
        self.assertEqual(payload["error"], "output_too_large")
        fix = payload["fix"]
        self.assertTrue(fix.endswith(" | tk run json.pick --keys zeta,alpha,mid"), fix)
        # The order the chain check accepted is the order the fix suggests.
        self.assertEqual(fix.split("--keys ", 1)[1].split(","), output_keys(self.DECLARED)[:3])

    def test_check_item_rejects_a_key_nested_inside_a_declared_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._producer(root)
            self._chain(root, "zeta,nested", name="order.bad")
            result = check_item(root, "order.bad")
        self.assertFalse(result["ok"])
        self.assertIn(
            "step 1 (json.pick) key 'nested' not in upstream order.producer output",
            result["errors"],
        )


class SuggestClosestItemTests(unittest.TestCase):
    def test_close_name_then_token_fallback_then_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "tools" / "alpha" / "widget",
                _bash_tool("alpha.widget", "Widget summary", args=[], example="tk run alpha.widget"),
                executable=True,
            )
            _write(
                root / "tools" / "fs" / "tree-digest",
                _bash_tool("fs.tree-digest", "Tree digest", args=[], example="tk run fs.tree-digest"),
                executable=True,
            )
            close = suggest_closest_item(root, "alph.widget")
            tokens = suggest_closest_item(root, "qqqq-tree")
            missing = suggest_closest_item(root, "qqqq-zzzz")
        self.assertEqual(close["name"], "alpha.widget")
        self.assertEqual(tokens["name"], "fs.tree-digest")
        self.assertIsNone(missing)


if __name__ == "__main__":
    unittest.main()
