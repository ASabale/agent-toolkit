"""Chain step references shared by check and run.

Syntax: ``$input.<flag>``, ``$prev``, ``$prev.<path>``, ``$step[i]``,
``$step[i].<path>``. ``static_ref_error`` is the check-time verdict.
``resolve_expr`` is the run-time value. Callers do not re-parse the syntax.
"""

from __future__ import annotations

import json
import re

_INPUT_REF = re.compile(r"^\$input\.([A-Za-z0-9_-]+)$")
_PREV_REF = re.compile(r"^\$prev\.(.+)$")
_STEP_WHOLE = re.compile(r"^\$step\[(-?\d+)\]$")
_STEP_REF = re.compile(r"^\$step\[(-?\d+)\]\.(.+)$")
_STEP_ANY = re.compile(r"^\$step\[(-?\d+)\](?:\..*)?$")
_PATH_PART = re.compile(r"[^.\[\]]+|\[\d+\]")


def bare_arg_name(flag: str) -> str:
    """Flag or ``$input`` name with the leading dashes removed and hyphens folded."""
    bare = flag[2:] if flag.startswith("--") else flag.lstrip("-")
    return bare.replace("-", "_")


def static_ref_error(text: str, step_index: int, declared_inputs: set[str]) -> str | None:
    """Return the check error for one step argument, or ``None`` when it is legal.

    ``declared_inputs`` holds :func:`bare_arg_name` forms of the chain's own flags.
    A non-reference string is legal. Path existence is a run-time question.
    """
    text = text.strip()
    input_match = _INPUT_REF.fullmatch(text)
    if input_match and bare_arg_name(input_match.group(1)) not in declared_inputs:
        return f"step {step_index} unresolved input reference: {text}"
    if (text == "$prev" or text.startswith("$prev.")) and step_index == 0:
        return f"step 0 cannot reference $prev: {text}"
    step_match = _STEP_ANY.fullmatch(text)
    if step_match:
        ref = int(step_match.group(1))
        if ref < 0 or ref >= step_index:
            return f"step {step_index} invalid step reference: {text}"
    return None


def _compact(payload: object) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def stringify(value: object) -> str:
    """Value passed through a step flag: strings stay, everything else is compact JSON."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return _compact(value)


def _walk(data: object, path: str) -> object:
    current = data
    for part in _PATH_PART.findall(path):
        if part.startswith("["):
            if not isinstance(current, list):
                raise KeyError(path)
            current = current[int(part[1:-1])]
        else:
            if not isinstance(current, dict) or part not in current:
                raise KeyError(path)
            current = current[part]
    return current


def _bare_forms(flag: str) -> set[str]:
    bare = flag[2:] if flag.startswith("--") else flag
    return {bare, bare.replace("-", "_"), bare.replace("_", "-")}


def _env_var(flag: str) -> str:
    name = flag[2:] if flag.startswith("--") else flag
    return "TK_ARG_" + name.replace("-", "_").upper()


def _dry_dummy(expect_type: str) -> str:
    if expect_type in {"int", "float"}:
        return "1"
    if expect_type == "bool":
        return "true"
    return "example"


def _missing_on_synthetic(dry_run: bool, payload: object, expect_type: str) -> tuple[str | None, str | None] | None:
    """Dummy stand-in when a dry-run payload omitted the referenced key."""
    if dry_run and isinstance(payload, dict) and payload.get("dry_run") is True:
        return _dry_dummy(expect_type), None
    return None


def resolve_expr(
    expr: str,
    chain_item: dict,
    env: dict[str, str],
    prev: object,
    steps: list[object],
    dry_run: bool = False,
    expect_type: str = "string",
) -> tuple[str | None, str | None]:
    """Resolve one step argument.

    Returns ``(value, None)`` or ``(None, original)`` when the reference cannot
    be read. A string that is not a reference is returned unchanged.
    """
    text = expr.strip()
    input_match = _INPUT_REF.fullmatch(text)
    if input_match:
        wanted = input_match.group(1)
        for arg in chain_item.get("args") or []:
            if wanted not in _bare_forms(arg["flag"]):
                continue
            key = arg.get("env_var") or _env_var(arg["flag"])
            if key in env:
                return env[key], None
        return None, text

    if text == "$prev":
        if prev is None:
            return None, text
        return stringify(prev), None

    prev_match = _PREV_REF.fullmatch(text)
    if prev_match:
        if prev is None:
            return None, text
        try:
            return stringify(_walk(prev, prev_match.group(1))), None
        except (KeyError, IndexError, TypeError):
            fallback = _missing_on_synthetic(dry_run, prev, expect_type)
            return fallback if fallback is not None else (None, text)

    whole_step = _STEP_WHOLE.fullmatch(text)
    if whole_step:
        index = int(whole_step.group(1))
        if index < 0 or index >= len(steps):
            return None, text
        return stringify(steps[index]), None

    step_match = _STEP_REF.fullmatch(text)
    if step_match:
        index = int(step_match.group(1))
        if index < 0 or index >= len(steps):
            return None, text
        try:
            return stringify(_walk(steps[index], step_match.group(2))), None
        except (KeyError, IndexError, TypeError):
            fallback = _missing_on_synthetic(dry_run, steps[index], expect_type)
            return fallback if fallback is not None else (None, text)

    return text, None
