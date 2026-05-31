from __future__ import annotations

from typing import Any

from pydantic import Field

from coreweaver.framework_types import StrictCoreModel, utc_now


class DebugIssueRecord(StrictCoreModel):
    severity: str
    source: str
    code: str
    message: str
    timestamp: str = Field(default_factory=utc_now)
    run_id: str | None = None
    revision_id: str | None = None
    span_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


def issue_from_hook(*, hook_name: str, severity: str, code: str, message: str) -> DebugIssueRecord:
    return DebugIssueRecord(severity=severity, source=f"hook.{hook_name}", code=code, message=message)
