"""Shared state for Agent 2 V2 deterministic orchestrator."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Agent2State:
    spec: dict[str, Any]
    debug: bool = False
    files: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)

    @property
    def project(self) -> str:
        return str(self.spec["project_name"])

    @property
    def blocks(self) -> list[str]:
        return [str(block["name"]) for block in self.spec.get("ip_blocks", [])]

    def record(self, result: Any) -> None:
        self.trace.append(result.as_dict())
        self.artifacts[result.agent_id] = result.artifacts