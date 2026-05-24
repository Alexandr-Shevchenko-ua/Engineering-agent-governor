"""Lightweight secret redaction for logs and reports."""

from __future__ import annotations

import re

REDACTION_WARNING = (
    "Governor applies lightweight redaction only. Logs and artifacts may still "
    "contain sensitive data. Do not paste secrets into recorded outputs."
)

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.MULTILINE), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"\b(sk-[a-zA-Z0-9]{20,})\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"\b(ghp_[a-zA-Z0-9]{36,})\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\b(glpat-[a-zA-Z0-9\-_]{20,})\b"), "[REDACTED_GITLAB_TOKEN]"),
    (re.compile(r"(?i)(bearer\s+)[a-zA-Z0-9\-._~+/]+=*"), r"\1[REDACTED_BEARER]"),
    (re.compile(r"(?i)(authorization\s*:\s*)([^\s\n]+)"), r"\1[REDACTED_AUTH]"),
    (re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)['\"]?[^\s'\",]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(password\s*[=:]\s*)['\"]?[^\s'\",]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(secret\s*[=:]\s*)['\"]?[^\s'\",]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(token\s*[=:]\s*)['\"]?[^\s'\",]+"), r"\1[REDACTED]"),
]


def redact(text: str) -> str:
    if not text:
        return text
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out
