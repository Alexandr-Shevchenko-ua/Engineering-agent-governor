"""Validator verdict extraction from free-form markdown."""

from __future__ import annotations

import re

VERDICT_LABELS: tuple[str, ...] = (
    "HUMAN_DECISION_REQUIRED",
    "REPAIR_REQUIRED",
    "PASS_WITH_RISK",
    "PASS",
)

_LABEL_ALT = "|".join(re.escape(v) for v in VERDICT_LABELS)

# Verdict: PASS, **Verdict:** PASS, - Verdict: PASS_WITH_RISK
_VERDICT_LINE = re.compile(
    rf"^\s*(?:[-*]\s+)?\*{{0,2}}Verdict\s*:?\s*\*{{0,2}}\s*({_LABEL_ALT})\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Standalone label on its own line only (avoids "Could be PASS after repair.")
_STANDALONE_LINE = re.compile(
    rf"^\s*({_LABEL_ALT})\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_FENCE = re.compile(r"```(?:\w+)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def parse_validator_verdict(text: str | None) -> str | None:
    """Return normalized verdict label or None if not found."""
    if not text:
        return None

    for block in _FENCE.findall(text):
        for line in block.splitlines():
            m = _STANDALONE_LINE.match(line)
            if m:
                return m.group(1).upper()

    for pattern in (_VERDICT_LINE, _STANDALONE_LINE):
        m = pattern.search(text)
        if m:
            return m.group(1).upper()

    return None
