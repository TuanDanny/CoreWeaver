"""Typed contracts for Agent 2 swarm-of-experts subagents."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from semiconductor_swarm.contracts.common import APB_SLAVE_INTERFACE
from semiconductor_swarm.contracts.validators import agent1_to_agent2_spec


def validate_agent2_architecture_spec(spec: dict[str, Any]) -> None:
    """Validate Agent 2 input contract without importing Agent 1 implementation."""
    spec = agent1_to_agent2_spec(spec)
    required = {"project_name", "ip_blocks", "interfaces", "constraints"}
    missing = required.difference(spec)
    if missing:
        raise ValueError(f"Missing spec keys: {sorted(missing)}")
    if "clocking" not in spec and "clock_domains" not in spec:
        raise ValueError("Missing spec keys: ['clocking' or 'clock_domains']")
    if spec["interfaces"].get("apb_slave") != APB_SLAVE_INTERFACE:
        raise ValueError("Agent 2 requires exact locked APB slave pinout")
    if spec["constraints"].get("agent2_port_renaming_allowed") is not False:
        raise ValueError("Agent 2 requires port renaming to be disabled")


@dataclass(frozen=True)
class Agent2SubAgentResult:
    """Deterministic result returned by each Agent 2 specialist."""

    agent_id: str
    name: str
    version: str = "2.1_MB"
    pass_: bool = True
    artifacts: dict[str, Any] = field(default_factory=dict)
    findings: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    needs_repair: bool = False
    confidence: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["pass"] = data.pop("pass_")
        return data


def pass_result(agent_id: str, name: str, *, artifacts: dict[str, Any] | None = None, decisions: list[dict[str, Any]] | None = None) -> Agent2SubAgentResult:
    return Agent2SubAgentResult(
        agent_id=agent_id,
        name=name,
        artifacts=artifacts or {},
        decisions=decisions or [],
    )


def fail_result(agent_id: str, name: str, *, findings: list[dict[str, Any]], artifacts: dict[str, Any] | None = None) -> Agent2SubAgentResult:
    return Agent2SubAgentResult(
        agent_id=agent_id,
        name=name,
        pass_=False,
        artifacts=artifacts or {},
        findings=findings,
        needs_repair=True,
        confidence=1.0,
    )