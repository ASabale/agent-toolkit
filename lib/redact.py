"""Replace credential-shaped text with a fixed mask.

Callers learn two functions: ``redact`` returns the masked text, and
``secret_hits`` returns the rule names that matched, never the secret.
"""

from __future__ import annotations

import re

_TOKEN = r"[A-Za-z0-9+/_.:-]{20,}"
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("github_token", re.compile(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9_]{20,}(?![A-Za-z0-9_])")),
    ("aws_access_key", re.compile(r"(?<![A-Z0-9])AKIA[A-Z0-9]{16}(?![A-Z0-9])")),
    ("bearer", re.compile(r"(?<![A-Za-z0-9])Bearer " + _TOKEN)),
    (
        "private_key",
        re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    ),
    ("slack_token", re.compile(r"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9-]{10,}(?![A-Za-z0-9-])")),
    (
        "assignment",
        re.compile(
            r"(?<![A-Za-z0-9_])(?:token|key|password)(?![A-Za-z0-9_])\s*=\s*[\"']?" + _TOKEN
        ),
    ),
)
_MASK = "***"


def _matches(text: str) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, int, str]] = []
    for index, (name, pattern) in enumerate(_RULES):
        for match in pattern.finditer(text):
            found.append((index, match.start(), match.end(), name))
    found.sort()
    kept: list[tuple[int, int, str]] = []
    occupied: list[tuple[int, int]] = []
    for _index, start, end, name in found:
        if any(start < right and end > left for left, right in occupied):
            continue
        occupied.append((start, end))
        kept.append((start, end, name))
    kept.sort()
    return kept


def redact(text: str) -> str:
    """Replace each secret match with ``***``."""
    if not text:
        return text
    parts: list[str] = []
    cursor = 0
    for start, end, _name in _matches(text):
        parts.append(text[cursor:start])
        parts.append(_MASK)
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def secret_hits(text: str) -> list[str]:
    """Rule names that matched, in rule order, without the secret text."""
    seen: set[str] = set()
    for _start, _end, name in _matches(text):
        seen.add(name)
    return [name for name, _pattern in _RULES if name in seen]


def redact_data(value: object) -> object:
    """Redact string values. Mapping keys are kept."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_data(item) for key, item in value.items()}
    return value
