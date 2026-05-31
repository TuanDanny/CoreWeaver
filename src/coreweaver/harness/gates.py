from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .models import DebugIssue, IssueSeverity, TraceEvent


class Gate(Protocol):
    name: str

    def run(self, events: list[TraceEvent], issues: list[DebugIssue]) -> "GateResult":
        ...


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    findings: tuple[DebugIssue, ...] = field(default_factory=tuple)


class NoBlockerIssuesGate:
    name = "no_blocker_issues"

    def run(self, events: list[TraceEvent], issues: list[DebugIssue]) -> GateResult:
        blockers = tuple(issue for issue in issues if issue.severity == IssueSeverity.BLOCKER)
        return GateResult(name=self.name, passed=not blockers, findings=blockers)


class RequiredEventGate:
    def __init__(self, required_event_types: tuple[str, ...]) -> None:
        self.name = "required_events"
        self.required_event_types = required_event_types

    def run(self, events: list[TraceEvent], issues: list[DebugIssue]) -> GateResult:
        seen = {event.event_type for event in events}
        missing = [event_type for event_type in self.required_event_types if event_type not in seen]
        findings = tuple(
            DebugIssue(
                severity=IssueSeverity.ERROR,
                source="harness.gates",
                code="missing_event",
                message=f"missing required event: {event_type}",
                timestamp=events[-1].timestamp if events else "1970-01-01T00:00:00Z",
                details={"event_type": event_type},
            )
            for event_type in missing
        )
        return GateResult(name=self.name, passed=not findings, findings=findings)


class GateRunner:
    def __init__(self, gates: tuple[Gate, ...] | None = None) -> None:
        self.gates = gates or (NoBlockerIssuesGate(),)

    def run(self, events: list[TraceEvent], issues: list[DebugIssue]) -> tuple[GateResult, ...]:
        return tuple(gate.run(events, issues) for gate in self.gates)
