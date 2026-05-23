"""Normalized semantic finding model for Agent 2 V3."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SemanticFinding:
    severity: str
    source: str
    owner: str
    file: str | None
    module: str | None
    rule: str
    message: str
    suggested_fix: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)