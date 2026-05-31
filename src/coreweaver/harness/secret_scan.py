from __future__ import annotations

import re
from dataclasses import dataclass


_SECRET_PATTERNS = (
    ("openai_key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("bearer", re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE)),
    ("api_key_assignment", re.compile(r"(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}", re.IGNORECASE)),
)


@dataclass(frozen=True)
class SecretFinding:
    code: str
    line: int
    column: int
    preview: str


def scan_text_for_secrets(text: str) -> tuple[SecretFinding, ...]:
    findings: list[SecretFinding] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for code, pattern in _SECRET_PATTERNS:
            for match in pattern.finditer(line):
                findings.append(
                    SecretFinding(
                        code=code,
                        line=line_no,
                        column=match.start() + 1,
                        preview=_redact(match.group(0)),
                    )
                )
    return tuple(findings)


def _redact(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return value[:4] + "***" + value[-2:]
