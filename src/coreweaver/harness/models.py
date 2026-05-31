from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class HarnessValidationError(ValueError):
    """Raised when a harness contract is malformed."""


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKER = "blocker"


def validate_id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise HarnessValidationError(f"{field_name} must match {_ID_RE.pattern}")
    return value


def validate_iso8601(value: str, field_name: str = "timestamp") -> str:
    if not isinstance(value, str) or "T" not in value:
        raise HarnessValidationError(f"{field_name} must be ISO8601 datetime")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise HarnessValidationError(f"{field_name} must be ISO8601 datetime") from exc
    return value


def validate_sha256(value: str, field_name: str = "sha256") -> str:
    if not isinstance(value, str) or not _SHA256_RE.match(value):
        raise HarnessValidationError(f"{field_name} must be 64 hex chars")
    return value.lower()


def ensure_jsonable(value: Any, field_name: str) -> Any:
    try:
        json.dumps(value, sort_keys=True)
    except TypeError as exc:
        raise HarnessValidationError(f"{field_name} must be JSON serializable") from exc
    return value


@dataclass(frozen=True)
class ArtifactRef:
    path: str
    sha256: str
    kind: str

    def __post_init__(self) -> None:
        if not self.path or not isinstance(self.path, str):
            raise HarnessValidationError("artifact path is required")
        validate_sha256(self.sha256)
        validate_id(self.kind, "artifact kind")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TraceEvent:
    event_type: str
    run_id: str
    revision_id: str
    span_id: str
    parent_span_id: str | None
    timestamp: str
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_id(self.event_type, "event_type")
        validate_id(self.run_id, "run_id")
        validate_id(self.revision_id, "revision_id")
        validate_id(self.span_id, "span_id")
        if self.parent_span_id is not None:
            validate_id(self.parent_span_id, "parent_span_id")
        validate_iso8601(self.timestamp)
        ensure_jsonable(self.payload, "payload")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DebugIssue:
    severity: IssueSeverity
    source: str
    code: str
    message: str
    timestamp: str
    run_id: str | None = None
    revision_id: str | None = None
    span_id: str | None = None
    artifact_ref: ArtifactRef | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.severity, str):
            object.__setattr__(self, "severity", IssueSeverity(self.severity))
        validate_id(self.source, "source")
        validate_id(self.code, "code")
        if not self.message:
            raise HarnessValidationError("message is required")
        validate_iso8601(self.timestamp)
        for name in ("run_id", "revision_id", "span_id"):
            value = getattr(self, name)
            if value is not None:
                validate_id(value, name)
        ensure_jsonable(self.details, "details")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["severity"] = self.severity.value
        return data


@dataclass(frozen=True)
class ScopeContract:
    task_id: str
    goal: str
    allowed_files: tuple[str, ...]
    forbidden_files: tuple[str, ...]
    acceptance_commands: tuple[str, ...]
    rollback_plan: str
    approvals_required: tuple[str, ...] = ()
    time_budget_minutes: int | None = None
    network_egress: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        validate_id(self.task_id, "task_id")
        if not self.goal.strip():
            raise HarnessValidationError("goal is required")
        if not self.allowed_files:
            raise HarnessValidationError("allowed_files is required")
        if not self.forbidden_files:
            raise HarnessValidationError("forbidden_files is required")
        if not self.acceptance_commands:
            raise HarnessValidationError("acceptance_commands is required")
        if not self.rollback_plan.strip():
            raise HarnessValidationError("rollback_plan is required")
        if self.time_budget_minutes is not None and self.time_budget_minutes <= 0:
            raise HarnessValidationError("time_budget_minutes must be positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
