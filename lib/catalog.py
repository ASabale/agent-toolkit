"""Discovery, indexing, and validation for agent-toolkit tools and chains.

Zero third-party dependencies. Public functions catch unexpected failures and
return empty or error-shaped values instead of raising.
"""

from __future__ import annotations

import concurrent.futures
import difflib
import json
import os
import py_compile
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from lib.chainref import bare_arg_name, static_ref_error
from lib.guards import tool_subprocess_env
from lib.redact import secret_hits

_SAFETY = {"read-only", "mutating", "destructive"}
_TYPES = {"string", "int", "float", "bool"}
_DEFAULT_RE = re.compile(r"\(default:\s*([^)]*)\)", re.IGNORECASE)
_VERIFIED_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_NEED_ENV = re.compile(r"env:([A-Za-z_][A-Za-z0-9_]*)\Z")
_NEED_BIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,64}\Z")
_REQUIRE_ENV = re.compile(r"env:([A-Za-z_][A-Za-z0-9_]*)\Z")
_REQUIRE_BIN = re.compile(r"bin:([A-Za-z0-9][A-Za-z0-9._+-]{0,64})\Z")
_REQUIRE_FILE = re.compile(r"file:([A-Za-z0-9][A-Za-z0-9._+/-]{0,180})\Z")


def _empty_tool(path: Path) -> dict:
    try:
        resolved = str(path.resolve()) if path.exists() else str(path)
    except OSError:
        resolved = str(path)
    return {
        "kind": "tool",
        "name": "",
        "summary": "",
        "safety": "",
        "args": [],
        "output": "",
        "example": "",
        "verified": "",
        "needs": [],
        "schema": [],
        "requires": [],
        "deprecated": "",
        "keep": False,
        "path": resolved,
    }


def _empty_chain(path: Path) -> dict:
    item = _empty_tool(path)
    item["kind"] = "chain"
    item["steps"] = []
    return item


def _parse_arg(spec: str) -> dict:
    parts = [part.strip() for part in spec.split("|")]
    flag = parts[0] if parts else ""
    requirement = parts[1].lower() if len(parts) > 1 else ""
    typ = parts[2].lower() if len(parts) > 2 else ""
    description = " | ".join(parts[3:]).strip() if len(parts) > 3 else ""
    default = None
    match = _DEFAULT_RE.search(description)
    if match:
        default = match.group(1).strip()
    env_var = "TK_ARG_" + flag.lstrip("-").replace("-", "_").upper()
    return {
        "flag": flag,
        "env_var": env_var,
        "required": requirement == "required",
        "type": typ,
        "description": description,
        "default": default,
    }


def _normalize_arg(raw) -> dict:
    if isinstance(raw, str):
        return _parse_arg(raw)
    if isinstance(raw, dict):
        if "flag" in raw and isinstance(raw.get("flag"), str) and "type" in raw:
            flag = str(raw.get("flag") or "")
            description = str(raw.get("description") or "")
            default = raw.get("default", None)
            if default is None:
                match = _DEFAULT_RE.search(description)
                if match:
                    default = match.group(1).strip()
            elif default is not None:
                default = str(default)
            return {
                "flag": flag,
                "env_var": str(raw.get("env_var") or ("TK_ARG_" + flag.lstrip("-").replace("-", "_").upper())),
                "required": bool(raw.get("required")),
                "type": str(raw.get("type") or ""),
                "description": description,
                "default": default,
            }
        return _parse_arg(str(raw.get("spec") or raw.get("flag") or ""))
    return _parse_arg("")


def parse_tool_header(path: Path) -> dict:
    """Parse the leading ``# @tk-*`` comment block of a tool file."""
    path = Path(path)
    item = _empty_tool(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return item
    try:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#!"):
                continue
            if not stripped.startswith("#"):
                break
            body = stripped[1:].strip()
            if not body.startswith("@tk-"):
                continue
            key, _, value = body.partition(":")
            key = key.strip()
            value = value.strip()
            if key == "@tk-name":
                item["name"] = value
            elif key == "@tk-summary":
                item["summary"] = value
            elif key == "@tk-safety":
                item["safety"] = value
            elif key == "@tk-arg":
                item["args"].append(_parse_arg(value))
            elif key == "@tk-output":
                item["output"] = value
            elif key == "@tk-example":
                item["example"] = value
            elif key == "@tk-verified":
                item["verified"] = value
            elif key == "@tk-needs":
                item["needs"].extend(part for part in re.split(r"[\s,]+", value) if part)
            elif key == "@tk-schema":
                item["schema"].extend(_schema_keys(value))
            elif key == "@tk-requires":
                item["requires"].extend(part for part in re.split(r"[\s,]+", value) if part)
            elif key == "@tk-deprecated":
                item["deprecated"] = value
            elif key == "@tk-keep":
                item["keep"] = True
    except Exception:
        return item
    return item


def load_chain(path: Path) -> dict:
    """Load ``chains/<name>.json`` into the shared catalog item shape."""
    path = Path(path)
    item = _empty_chain(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return item
    except Exception:
        return item
    if not isinstance(data, dict):
        return item
    try:
        item["name"] = str(data.get("name") or "")
        item["summary"] = str(data.get("summary") or "")
        item["safety"] = str(data.get("safety") or "")
        item["output"] = str(data.get("output") or "")
        item["example"] = str(data.get("example") or "")
        item["verified"] = str(data.get("verified") or "")
        raw_args = data.get("args") or []
        item["args"] = [_normalize_arg(arg) for arg in raw_args] if isinstance(raw_args, list) else []
        steps = data.get("steps") or []
        item["steps"] = steps if isinstance(steps, list) else []
    except Exception:
        return _empty_chain(path)
    return item


def _hidden_part(part: str) -> bool:
    return part.startswith(".") or part.startswith("__")


def _catalog_relpath(root_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(root_dir).resolve()).as_posix()
    except (OSError, ValueError):
        try:
            return path.resolve().as_posix()
        except OSError:
            return str(path)


def _iter_catalog_files(root_dir: Path):
    """Yield ``(key, item, relpath)`` in deterministic first-wins scan order."""
    tools_dir = root_dir / "tools"
    if tools_dir.is_dir():
        for path in sorted(tools_dir.rglob("*")):
            try:
                relative = path.relative_to(tools_dir)
            except ValueError:
                continue
            if any(_hidden_part(part) for part in relative.parts):
                continue
            if not path.is_file():
                continue
            item = parse_tool_header(path)
            key = item["name"] or relative.as_posix()
            yield key, item, _catalog_relpath(root_dir, path)
    chains_dir = root_dir / "chains"
    if chains_dir.is_dir():
        for path in sorted(chains_dir.glob("*.json")):
            if _hidden_part(path.name) or not path.is_file():
                continue
            item = load_chain(path)
            key = item["name"] or path.name
            yield key, item, _catalog_relpath(root_dir, path)


def _name_claimants(root_dir: Path) -> dict[str, list[str]]:
    """Map each claimed name to every file path that uses it, first-seen order."""
    claimants: dict[str, list[str]] = {}
    for _key, item, relpath in _iter_catalog_files(root_dir):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        claimants.setdefault(name, []).append(relpath)
    return claimants


def _implied_catalog_name(root_dir: Path, path: Path, is_chain: bool) -> str | None:
    try:
        resolved = path.resolve()
    except OSError:
        return None
    if is_chain:
        try:
            resolved.relative_to((root_dir / "chains").resolve())
        except (OSError, ValueError):
            return None
        return path.stem
    try:
        relative = resolved.relative_to((root_dir / "tools").resolve())
    except (OSError, ValueError):
        return None
    return ".".join(relative.parts)


def _layout_errors(root_dir: Path, path: Path, item: dict, is_chain: bool) -> list[str]:
    implied = _implied_catalog_name(root_dir, path, is_chain)
    if implied is None:
        return []
    actual = str(item.get("name") or "")
    if actual == implied:
        return []
    return [f"name/path mismatch: @tk-name {actual} but path implies {implied}"]


def _duplicate_name_errors(root_dir: Path, name: str) -> list[str]:
    claimed = str(name or "").strip()
    if not claimed:
        return []
    paths = _name_claimants(root_dir).get(claimed) or []
    if len(paths) < 2:
        return []
    return [f"duplicate_name: {claimed} ({', '.join(paths)})"]


def resolve_named_item(root_dir: Path, name: str) -> tuple[str, dict | None, list[str]]:
    """Return one item, or every claimant path. Never pick a winner.

    Status is ``one`` (item and its single path), ``none``, or ``many``
    (no item; ``paths`` lists every repo-relative claimant in first-seen order).
    """
    root_dir = Path(root_dir)
    claimed = str(name or "").strip()
    if not claimed:
        return "none", None, []
    paths = list(_name_claimants(root_dir).get(claimed) or [])
    if not paths:
        return "none", None, []
    if len(paths) > 1:
        return "many", None, paths
    rel = paths[0]
    path = root_dir / rel
    if rel.startswith("chains/") and path.suffix == ".json":
        return "one", load_chain(path), paths
    return "one", parse_tool_header(path), paths


def discover_catalog(root_dir: Path) -> dict[str, dict]:
    """Scan ``tools/`` recursively and ``chains/*.json``. Keys are sorted.

    Duplicate names keep the first file in scan order (tools, then chains;
    each sorted). The return shape stays ``dict[name, item]``.
    """
    root_dir = Path(root_dir)
    items: dict[str, dict] = {}
    try:
        for key, item, _relpath in _iter_catalog_files(root_dir):
            if key not in items:
                items[key] = item
    except Exception:
        return dict(sorted(items.items()))
    return dict(sorted(items.items()))


def _arg_blob(item: dict) -> str:
    parts: list[str] = []
    for arg in item.get("args") or []:
        if not isinstance(arg, dict):
            parts.append(str(arg))
            continue
        parts.append(str(arg.get("flag") or ""))
        parts.append(str(arg.get("description") or ""))
    return " ".join(parts).lower()


def _name_segments(name: str) -> set[str]:
    return {part for part in re.split(r"[.\-_]+", name) if part}


_QUERY_STOPWORDS = {
    "a", "an", "all", "and", "by", "check", "file", "files", "find", "for",
    "from", "get", "in", "info", "into", "list", "of", "on", "path", "per",
    "repo", "run", "show", "status", "the", "to", "tool", "tools", "view", "with",
}


def _query_tokens(query: str) -> list[str]:
    return [tok for tok in query.lower().split() if tok]


def _score(item: dict, query: str) -> int:
    """Score query tokens: name exact 5 / substring 3, summary 2, args 1.

    Stopwords still match a name or name segment. They do not score against
    the summary or args.
    """
    tokens = _query_tokens(query)
    if not tokens:
        return 0
    name = str(item.get("name") or "").lower()
    summary = str(item.get("summary") or "").lower()
    args = _arg_blob(item)
    segments = _name_segments(name)
    score = 0
    for token in tokens:
        if token == name or token in segments:
            score += 5
        elif token in name:
            score += 3
        if token in _QUERY_STOPWORDS:
            continue
        if token in summary:
            score += 2
        if token in args:
            score += 1
    return score


def _token_coverage(item: dict, token: str) -> tuple[bool, bool]:
    """Return (any hit, name hit outside the namespace segment)."""
    name = str(item.get("name") or "").lower()
    summary = str(item.get("summary") or "").lower()
    args = _arg_blob(item)
    segments = _name_segments(name)
    namespace = name.split(".", 1)[0] if "." in name else ""
    name_hit = token == name or token in segments or token in name
    text_hit = token not in _QUERY_STOPWORDS and (token in summary or token in args)
    specific = name_hit and token != namespace
    return name_hit or text_hit, specific


def find_items(
    root_dir: Path,
    query: str = "",
    limit: int | None = None,
    namespace: str | None = None,
) -> list[dict]:
    """Return catalog items matching ``query``, best score then name.

    A positive ``limit`` keeps only the first matches. A non-empty
    ``namespace`` keeps names equal to that namespace or under it.
    """
    try:
        catalog = discover_catalog(root_dir)
        ambiguous = {
            claimed
            for claimed, paths in _name_claimants(root_dir).items()
            if len(paths) > 1
        }
        items = [
            item for item in catalog.values()
            if str(item.get("name") or "") not in ambiguous
        ]
        ns = str(namespace or "").strip().lower().rstrip(".")
        if ns:
            items = [item for item in items if _in_namespace(item, ns)]
        if not str(query or "").strip():
            ranked = sorted(items, key=lambda item: str(item.get("name") or ""))
        else:
            content = [tok for tok in _query_tokens(query) if tok not in _QUERY_STOPWORDS]
            namespaces = {
                str(item.get("name") or "").lower().split(".", 1)[0]
                for item in items
                if "." in str(item.get("name") or "")
            }
            hit_tokens: set[str] = set()
            specific_tokens: set[str] = set()
            text_tokens: set[str] = set()
            for item in items:
                summary = str(item.get("summary") or "").lower()
                args = _arg_blob(item)
                for token in content:
                    hit, specific = _token_coverage(item, token)
                    if hit:
                        hit_tokens.add(token)
                    if specific:
                        specific_tokens.add(token)
                    if token not in namespaces and (token in summary or token in args):
                        text_tokens.add(token)
            dead = [token for token in content if token not in hit_tokens]
            # Drop when a content token matches nothing and the other content
            # tokens are only namespace names (`git zzzz`, `list kubernetes
            # pods`). A summary hit (`ci`) or a non-namespace name hit
            # (`tree` in `fs.tree-digest`) keeps ordinary OR scoring.
            if dead and not specific_tokens and not text_tokens:
                ranked = []
            else:
                scored = []
                for item in items:
                    score = _score(item, query)
                    if score > 0:
                        scored.append((score, str(item.get("name") or ""), item))
                scored.sort(key=lambda row: (-row[0], row[1]))
                ranked = [row[2] for row in scored]
        if isinstance(limit, int) and limit > 0:
            return ranked[:limit]
        return ranked
    except Exception:
        return []


def _in_namespace(item: dict, namespace: str) -> bool:
    name = str(item.get("name") or "").lower()
    return name == namespace or name.startswith(f"{namespace}.")


_SHELL_ARG_RE = re.compile(
    r"(?:\$\{TK_ARG_([A-Z][A-Z0-9_]*)|\$TK_ARG_([A-Z][A-Z0-9_]*))\b"
)
_PY_ARG_RE = re.compile(
    r"""(?:environ\.get|getenv|environ)\s*[\(\[]\s*['"]TK_ARG_([A-Z][A-Z0-9_]*)['"]"""
)


def _strip_unquoted_comment(line: str) -> str:
    """Drop a trailing `# ...` comment that is outside quotes."""
    out: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(line):
        char = line[index]
        if quote:
            out.append(char)
            if char == "\\" and quote == '"' and index + 1 < len(line):
                out.append(line[index + 1])
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            out.append(char)
            index += 1
            continue
        if char == "#":
            break
        out.append(char)
        index += 1
    return "".join(out)


def _referenced_arg_names(line: str) -> set[str]:
    code = _strip_unquoted_comment(line)
    found: set[str] = set()
    for braced, bare in _SHELL_ARG_RE.findall(code):
        found.add(braced or bare)
    found.update(_PY_ARG_RE.findall(code))
    return found


def _undeclared_arg_env_errors(path: Path, item: dict) -> list[str]:
    declared = {
        str(arg.get("env_var"))
        for arg in (item.get("args") or [])
        if isinstance(arg, dict) and arg.get("env_var")
    }
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found: set[str] = set()
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        found.update(_referenced_arg_names(line))
    return [
        f"undeclared arg env var in script: TK_ARG_{name}"
        for name in sorted(found)
        if f"TK_ARG_{name}" not in declared
    ]


def suggest_closest_item(root_dir: Path, name: str) -> dict | None:
    """Return the closest catalog item for a mistyped name, or None."""
    try:
        catalog = discover_catalog(root_dir)
        ambiguous = {
            claimed
            for claimed, paths in _name_claimants(root_dir).items()
            if len(paths) > 1
        }
        keys = [key for key in catalog if key not in ambiguous]
        matches = difflib.get_close_matches(name, keys, n=1, cutoff=0.45)
        if matches:
            return catalog[matches[0]]
        tokens = [tok for tok in re.split(r"[.\-_]+", name) if tok]
        if not tokens:
            return None
        found = find_items(root_dir, " ".join(tokens))
        return found[0] if found else None
    except Exception:
        return None


def _instead(item: dict) -> str:
    """One replacement command. Empty when the tool is not deprecated."""
    raw = str(item.get("deprecated") or "").strip()
    if not raw:
        return ""
    if raw.startswith("tk "):
        return raw
    return f"tk run {raw}"


def format_find_output(items: list[dict]) -> str:
    """Two lines per item: name/safety/summary, then the run example.

    ``@tk-verified: none`` adds a short ``unverified`` tag on the first line.
    Lines stay within 140 characters so the find budget does not grow.
    """
    try:
        lines: list[str] = []
        for item in items:
            name = str(item.get("name") or "")
            safety = str(item.get("safety") or "")
            summary = str(item.get("summary") or "")
            example = str(item.get("example") or "")
            tag = " unverified" if str(item.get("verified") or "") == "none" else ""
            prefix = f"{name} [{safety}]{tag} — "
            room = 140 - len(prefix)
            if room < 0:
                head = prefix[:140]
            else:
                head = prefix + summary[:room]
            run = f"  run: {example}"
            if len(run) > 140:
                run = run[:140]
            lines.append(head)
            lines.append(run)
            instead = _instead(item)
            if instead:
                extra = f"  instead: {instead}"
                lines.append(extra[:140])
        if not lines:
            return ""
        return "\n".join(lines) + "\n"
    except Exception:
        return ""


def trust_label(verified: str, check_passed: bool = False) -> str:
    """Computed trust. A header cannot select ``signed``.

    ``check_passed`` is true only after ``tk check`` exited 0 on these bytes.
    A date or the word ``signed`` in ``@tk-verified`` does not raise trust.
    """
    if str(verified or "").strip().lower() == "signed":
        return "draft"
    if check_passed:
        return "check_passed"
    return "draft"


# Gateway fields an agent can rely on. Bump only when one of those
# stdout fields changes meaning, not when a header or a lint line is added.
CONTRACT_VERSION = 1


def format_info_output(item: dict) -> str:
    """Compact multi-line contract: name, kind, safety, summary, args, output, example, verified, trust."""
    try:
        lines = [
            f"contract: {CONTRACT_VERSION}",
            f"name: {item.get('name') or ''}",
            f"kind: {item.get('kind') or ''}",
            f"safety: {item.get('safety') or ''}",
            f"summary: {item.get('summary') or ''}",
            "args:",
        ]
        for arg in item.get("args") or []:
            if not isinstance(arg, dict):
                lines.append(f"  {arg}")
                continue
            requirement = "required" if arg.get("required") else "optional"
            lines.append(
                f"  {arg.get('flag') or ''} | {requirement} | {arg.get('type') or ''} | {arg.get('description') or ''}"
            )
        lines.append(f"output: {item.get('output') or ''}")
        lines.append(f"example: {item.get('example') or ''}")
        verified = str(item.get("verified") or "")
        lines.append(f"verified: {verified}")
        instead = _instead(item)
        if instead:
            lines.append(f"deprecated: {instead}")
        lines.append(
            "trust: "
            + trust_label(verified, bool(item.get("check_passed")))
        )
        return "\n".join(lines) + "\n"
    except Exception:
        return ""


def _interpreter(path: Path) -> str | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            first = handle.readline().strip().lower()
    except OSError:
        return None
    if not first.startswith("#!"):
        return None
    if "python" in first:
        return "python"
    # bash and sh, including `#!/usr/bin/env bash`.
    if re.search(r"(^|[/\s])(bash|sh)(\s|$)", first[2:]):
        return "shell"
    return "other"


def _flag_present(tokens: list[str], flag: str) -> bool:
    return any(token == flag or token.startswith(flag + "=") for token in tokens)


def _flag_has_value(tokens: list[str], flag: str) -> bool:
    for index, token in enumerate(tokens):
        if token == flag:
            if index + 1 >= len(tokens):
                return False
            nxt = tokens[index + 1]
            return bool(nxt) and not nxt.startswith("--")
        if token.startswith(flag + "="):
            return bool(token.split("=", 1)[1])
    return False


def _example_ok(name: str, example: str, args: list[dict]) -> list[str]:
    errors: list[str] = []
    text = (example or "").strip()
    prefix = f"tk run {name}"
    if not name or not (text == prefix or text.startswith(prefix + " ")):
        errors.append(f"example must start with 'tk run {name}'")
    try:
        tokens = shlex.split(text)
    except ValueError as exc:
        errors.append(f"example is not a valid command: {exc}")
        return errors
    for arg in args:
        if not arg.get("required"):
            continue
        flag = str(arg.get("flag") or "")
        if not flag:
            continue
        if not _flag_present(tokens, flag):
            errors.append(f"example missing required flag {flag}")
            continue
        if str(arg.get("type") or "string") == "bool":
            continue
        if not _flag_has_value(tokens, flag):
            errors.append(f"example missing value for required flag {flag}")
    return errors


def _syntax_error(path: Path) -> str | None:
    kind = _interpreter(path)
    if kind is None:
        return "syntax: missing shebang"
    if kind == "other":
        return "syntax: unsupported shebang"
    if kind == "shell":
        try:
            proc = subprocess.run(
                ["bash", "-n", str(path)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"syntax: {exc}"
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "bash -n failed").strip().splitlines()
            return "syntax: " + (detail[0] if detail else "bash -n failed")
        return None
    try:
        with tempfile.NamedTemporaryFile(prefix="tk-pyc-", delete=False) as handle:
            cfile = handle.name
        try:
            py_compile.compile(str(path), cfile=cfile, doraise=True)
        finally:
            try:
                os.unlink(cfile)
            except OSError:
                pass
    except py_compile.PyCompileError as exc:
        return f"syntax: {exc}"
    except Exception as exc:
        return f"syntax: {exc}"
    return None


def _script_mentions_tk_dry_run(path: Path) -> bool:
    """True when a non-comment line references ``TK_DRY_RUN``."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        if "TK_DRY_RUN" in _strip_unquoted_comment(line):
            return True
    return False


def _dry_run_guard_error(path: Path) -> str | None:
    """Fail mutating/destructive tools that never branch on ``TK_DRY_RUN``."""
    safety = str(parse_tool_header(path).get("safety") or "")
    if safety not in {"mutating", "destructive"}:
        return None
    if _script_mentions_tk_dry_run(path):
        return None
    return f"{safety} tool must branch on TK_DRY_RUN"


def _schema_keys(value: str) -> list[str]:
    """Top-level names from ``@tk-schema``. Braces reuse the output-key parser."""
    text = value.strip()
    if not text:
        return []
    if "{" in text:
        keys = output_keys(text)
        return list(keys or [])
    return [part for part in re.split(r"[\s,]+", text) if part]


def _schema_error(payload: dict, schema: list[str]) -> str | None:
    missing = [key for key in schema if key not in payload]
    if not missing:
        return None
    shown = ", ".join(missing)
    return f"dry-run missing schema key: {shown}; fix: include {shown} in the dry-run JSON object"


def _static_schema_error(path: Path, schema: list[str]) -> str | None:
    """Compare ``@tk-schema`` keys to a literal JSON object in the dry-run branch.

    This does not start the tool. A branch with no JSON object literal is not a
    schema failure; ``tk check --verify`` is the execution path.
    """
    if not schema:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"TK_DRY_RUN\b.*?^\s*fi\b", text, re.S | re.M)
    region = match.group(0) if match else text
    literals = re.findall(r"""['"](\{.*?\})['"]""", region, re.S)
    payload = None
    for literal in literals:
        try:
            parsed = json.loads(literal)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            payload = parsed
            break
    if payload is None:
        return None
    return _schema_error(payload, schema)


def _default_matches(typ: str, default: str) -> bool:
    if typ == "int":
        return re.fullmatch(r"[+-]?\d+", default) is not None
    if typ == "float":
        return re.fullmatch(r"[+-]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[eE][+-]?\d+)?", default) is not None
    if typ == "bool":
        return default.strip().lower() in {"true", "false", "1", "0", "yes", "no"}
    return True


def _header_errors(item: dict) -> list[str]:
    errors: list[str] = []
    for field in ("name", "summary", "safety", "output", "example", "verified"):
        if not str(item.get(field) or "").strip():
            errors.append(f"missing header: {field}")
    safety = str(item.get("safety") or "")
    if safety and safety not in _SAFETY:
        errors.append(f"invalid safety: {safety}")
    verified = str(item.get("verified") or "").strip()
    if verified.lower() == "signed":
        errors.append(
            "invalid verified: signed is not a date; fix: set @tk-verified to none or YYYY-MM-DD"
        )
    elif verified and verified != "none" and _VERIFIED_DATE.fullmatch(verified) is None:
        errors.append(
            f"invalid verified: {verified} is not a date; fix: set @tk-verified to none or YYYY-MM-DD"
        )
    seen_flags: set[str] = set()
    for arg in item.get("args") or []:
        if not isinstance(arg, dict):
            errors.append("invalid arg")
            continue
        flag = str(arg.get("flag") or "")
        if not flag.startswith("--"):
            errors.append(f"invalid arg flag: {flag or '(empty)'}")
        elif flag == "--yes":
            errors.append("reserved flag: --yes; fix: drop @tk-arg --yes")
        elif flag == "--confirm":
            errors.append("reserved flag: --confirm; fix: drop @tk-arg --confirm")
        elif flag in {"--raw", "--dry-run"}:
            errors.append(f"reserved flag: {flag}")
        elif flag in seen_flags:
            errors.append(f"duplicate arg flag: {flag}")
        else:
            seen_flags.add(flag)
        typ = str(arg.get("type") or "")
        if typ not in _TYPES:
            errors.append(f"invalid arg type for {flag or '(empty)'}: {typ or '(empty)'}")
        default = arg.get("default")
        if default is not None and typ in {"int", "float", "bool"} and not _default_matches(typ, str(default)):
            label = flag if flag.startswith("--") else f"--{flag.lstrip('-') or 'empty'}"
            errors.append(f"invalid default for {label}: {default} is not {typ}")
    return errors


def _which_on_path(name: str, env: dict[str, str]) -> str | None:
    """Resolve a command with the PATH the child process will inherit."""
    return shutil.which(name, path=env.get("PATH"))


def _needs_errors(item: dict, env: dict[str, str] | None = None) -> list[str]:
    """Name a missing executable or env var. Does not install or confine.

    ``env`` is the mapping the child will see. ``env:`` reads that mapping.
    A bare command is resolved with that mapping's PATH.
    """
    mapping = os.environ if env is None else env
    errors: list[str] = []
    for raw in item.get("needs") or []:
        token = str(raw).strip()
        env_match = _NEED_ENV.fullmatch(token)
        if env_match:
            name = env_match.group(1)
            if not mapping.get(name):
                errors.append(f"missing env: {name}; fix: export {name}=<value>")
            continue
        if not _NEED_BIN.fullmatch(token):
            errors.append(
                f"invalid @tk-needs: {token}; fix: use a command name or env:NAME"
            )
            continue
        if _which_on_path(token, mapping) is None:
            errors.append(f"missing executable: {token}; fix: install {token}")
    return errors


def _requires_report(
    item: dict, root_dir: Path, env: dict[str, str] | None = None
) -> tuple[list[str], list[str]]:
    """Evaluate @tk-requires without a write and without a shell.

    env:, bin:, and file: (a relative path inside the repo) are reads.
    ``env`` is the child mapping. Anything else is skipped and the reason is returned.
    """
    mapping = os.environ if env is None else env
    errors: list[str] = []
    skipped: list[str] = []
    root = Path(root_dir).resolve()
    for raw in item.get("requires") or []:
        token = str(raw).strip()
        env_match = _REQUIRE_ENV.fullmatch(token)
        if env_match:
            name = env_match.group(1)
            if not mapping.get(name):
                errors.append(f"missing env: {name}; fix: export {name}=<value>")
            continue
        bin_match = _REQUIRE_BIN.fullmatch(token)
        if bin_match:
            name = bin_match.group(1)
            if _which_on_path(name, mapping) is None:
                errors.append(f"missing executable: {name}; fix: install {name}")
            continue
        file_match = _REQUIRE_FILE.fullmatch(token)
        if file_match:
            rel = file_match.group(1)
            candidate = (root / rel).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                skipped.append(
                    f"skipped @tk-requires: {token}; why: path leaves the repo; not evaluated"
                )
                continue
            if not candidate.is_file():
                errors.append(f"missing file: {rel}; fix: create {rel}")
            continue
        skipped.append(
            f"skipped @tk-requires: {token}; why: only env:, bin:, and file: are evaluated without a write or a shell"
        )
    return errors, skipped


def _resolve(root_dir: Path, name_or_path: str | Path) -> tuple[Path | None, dict | None, str | None]:
    """Return path, preloaded item (chains), and a not-found message."""
    if isinstance(name_or_path, Path):
        path = name_or_path
        if path.is_file():
            return path, None, None
        return None, None, f"file not found: {path}"
    text = str(name_or_path)
    direct = Path(text)
    if direct.is_file():
        return direct, None, None
    under_root = root_dir / text
    if under_root.is_file():
        return under_root, None, None
    catalog = discover_catalog(root_dir)
    item = catalog.get(text)
    if item is None:
        return None, None, f"not in catalog: {text}"
    path = Path(item["path"])
    if not path.is_file():
        return None, None, f"file not found: {path}"
    return path, item, None


def output_keys(output: object) -> list[str] | None:
    """Return the top-level field names of an @tk-output like ``json | {a, b:[...], c}``.

    ``None`` means the text has no ``{...}`` shape, so callers skip the key check.
    A list is the keys in source order; an empty list means the braces held no keys.
    Nested ``{}``, ``[]`` and ``()`` stay inside the key that opened them.
    """
    text = str(output or "").strip()
    if "|" in text:
        text = text.split("|", 1)[1].strip()
    if not text.startswith("{"):
        return None
    depth = 0
    end = -1
    for idx, char in enumerate(text):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = idx
                break
    if end < 0:
        return None
    inner = text[1:end]
    keys: list[str] = []
    depth = 0
    start = 0
    for idx, char in enumerate(inner):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            key = inner[start:idx].split(":")[0].split("[")[0].strip()
            if key and key not in keys:
                keys.append(key)
            start = idx + 1
    key = inner[start:].split(":")[0].split("[")[0].strip()
    if key and key not in keys:
        keys.append(key)
    return keys


def _pick_query_key_errors(
    index: int,
    tool_name: str,
    step_args: dict,
    upstream_output: str,
    upstream_name: str,
) -> list[str]:
    """Validate json.pick/json.query keys against upstream @tk-output."""
    errors: list[str] = []
    upstream_keys = output_keys(upstream_output)
    if upstream_keys is None:
        return errors

    if tool_name == "json.pick":
        raw_keys = str(step_args.get("keys") or step_args.get("--keys") or "")
        requested = {key.strip() for key in raw_keys.split(",") if key.strip()}
        for key in sorted(requested):
            if key not in upstream_keys:
                errors.append(
                    f"step {index} (json.pick) key '{key}' not in upstream {upstream_name} output"
                )

    elif tool_name == "json.query":
        raw_expr = str(step_args.get("expr") or step_args.get("--expr") or "")
        expr = raw_expr.strip()
        if expr.startswith("{") and "}" in expr:
            end = expr.index("}")
            inner = expr[1:end]
            requested = {key.strip() for key in inner.split(",") if key.strip()}
            for key in sorted(requested):
                if key not in upstream_keys:
                    errors.append(
                        f"step {index} (json.query) key '{key}' not in upstream {upstream_name} output"
                    )
        elif expr and not expr.startswith("["):
            first_key = expr.split(".")[0].split("[")[0].strip()
            if first_key and first_key not in upstream_keys:
                errors.append(
                    f"step {index} (json.query) key '{first_key}' not in upstream {upstream_name} output"
                )

    return errors


def _flag_name(key: object) -> str:
    text = str(key)
    return text if text.startswith("--") else f"--{text}"


def _chain_wiring_errors(item: dict, catalog: dict) -> list[str]:
    """Static flag and reference checks for each chain step."""
    errors: list[str] = []
    declared_inputs = {
        bare_arg_name(str(arg.get("flag") or ""))
        for arg in (item.get("args") or [])
        if isinstance(arg, dict)
    }
    steps = item.get("steps") or []
    if not isinstance(steps, list):
        return errors
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        tool_name = step.get("tool")
        tool = catalog.get(tool_name) if tool_name else None
        if not tool_name or tool is None:
            continue
        if tool.get("kind") == "chain":
            errors.append(f"step {index} ({tool_name}) cannot target a chain")
            continue
        declared: dict[str, dict] = {}
        for arg in tool.get("args") or []:
            if isinstance(arg, dict) and arg.get("flag"):
                declared[str(arg["flag"])] = arg
        raw = step.get("args") or {}
        if not isinstance(raw, dict):
            errors.append(f"step {index} ({tool_name}) args must be an object")
            continue
        present: set[str] = set()
        for key, val in raw.items():
            flag = _flag_name(key)
            present.add(flag)
            if flag not in declared:
                errors.append(f"step {index} ({tool_name}) unknown flag: {flag}")
            if not isinstance(val, str):
                continue
            ref_error = static_ref_error(val, index, declared_inputs)
            if ref_error:
                errors.append(ref_error)
        for flag, arg in declared.items():
            if arg.get("required") and arg.get("default") is None and flag not in present:
                errors.append(f"step {index} ({tool_name}) missing required flag: {flag}")
        if tool_name in {"json.pick", "json.query"} and index > 0:
            prev_step = steps[index - 1]
            prev_tool_name = prev_step.get("tool") if isinstance(prev_step, dict) else None
            prev_tool = catalog.get(prev_tool_name) if prev_tool_name else None
            if prev_tool:
                upstream_output = str(prev_tool.get("output") or "")
                errors.extend(
                    _pick_query_key_errors(index, tool_name, raw, upstream_output, prev_tool_name)
                )
    return errors


def _file_secret_rules(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return secret_hits(text)


def _is_chain_path(root_dir: Path, path: Path) -> bool:
    if path.suffix.lower() != ".json":
        return False
    try:
        path.resolve().relative_to((root_dir / "chains").resolve())
        return True
    except (OSError, ValueError):
        return False


def check_item(root_dir: Path, name_or_path: str | Path) -> dict:
    """Validate one tool or chain. Always returns ``name``, ``ok``, ``errors``."""
    root_dir = Path(root_dir)
    label = str(name_or_path)
    try:
        path, preloaded, missing = _resolve(root_dir, name_or_path)
        if path is None or missing:
            return {"name": label, "ok": False, "errors": [missing or "file not found"]}
        is_chain = (preloaded or {}).get("kind") == "chain" or _is_chain_path(root_dir, path)
        item = preloaded if preloaded is not None else (load_chain(path) if is_chain else parse_tool_header(path))
        name = str(item.get("name") or path.stem)
        errors: list[str] = []
        skipped: list[str] = []
        secret_rules = _file_secret_rules(path)
        if not is_chain and not os.access(path, os.X_OK):
            errors.append(f"not executable: {path}")
        errors.extend(_header_errors(item))
        if not is_chain:
            errors.extend(_needs_errors(item, os.environ))
            require_errors, skipped = _requires_report(item, root_dir, os.environ)
            errors.extend(require_errors)
        errors.extend(_example_ok(str(item.get("name") or ""), str(item.get("example") or ""), item.get("args") or []))
        if not is_chain:
            errors.extend(_undeclared_arg_env_errors(path, item))
            syntax = _syntax_error(path)
            if syntax:
                errors.append(syntax)
            elif os.access(path, os.X_OK) and not secret_rules:
                guard = _dry_run_guard_error(path)
                if guard:
                    errors.append(guard)
                else:
                    schema_error = _static_schema_error(path, list(item.get("schema") or []))
                    if schema_error:
                        errors.append(schema_error)
        else:
            catalog = discover_catalog(root_dir)
            steps = item.get("steps") or []
            if not isinstance(steps, list):
                errors.append("chain steps must be a list")
            else:
                for index, step in enumerate(steps):
                    tool_name = step.get("tool") if isinstance(step, dict) else None
                    if not tool_name:
                        errors.append(f"step {index} missing tool")
                    elif tool_name not in catalog:
                        errors.append(f"step {index} tool not in catalog: {tool_name}")
                errors.extend(_chain_wiring_errors(item, catalog))
        if secret_rules:
            shown = ", ".join(secret_rules)
            errors.append(
                f"secret in file ({shown}); remove the credential from the file; fix: tk check {name}"
            )
        errors.extend(_layout_errors(root_dir, path, item, is_chain))
        errors.extend(_duplicate_name_errors(root_dir, str(item.get("name") or "")))
        if errors and not any("fix: tk " in str(err) for err in errors):
            errors.append(f"fix: tk check {name} --json")
        payload = {"name": name, "ok": not errors, "errors": errors}
        if skipped:
            payload["skipped"] = skipped
        return payload
    except Exception as exc:
        return {"name": label, "ok": False, "errors": [f"internal_error: {exc}"]}


def check_all(root_dir: Path) -> dict:
    """Run ``check_item`` on every catalog entry."""
    root_dir = Path(root_dir)
    try:
        catalog = discover_catalog(root_dir)
        names = list(catalog)
        workers = min(8, max(1, len(catalog)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda name: check_item(root_dir, name), names))
        errors = [f"{result['name']}: {err}" for result in results for err in result["errors"]]
        return {
            "ok": all(result["ok"] for result in results) if results else True,
            "checked": len(results),
            "results": results,
            "errors": errors,
        }
    except Exception as exc:
        return {
            "ok": False,
            "checked": 0,
            "results": [],
            "errors": [f"internal_error: {exc}"],
        }
