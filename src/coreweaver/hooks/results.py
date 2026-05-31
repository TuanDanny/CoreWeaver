from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from coreweaver.debug.issues import DebugIssueRecord
from coreweaver.framework_types import StrictCoreModel


class HookStatus(str, Enum):
    CONTINUE = "continue"
    WARN = "warn"
    BLOCK = "block"
    REQUIRE_HITL = "require_hitl"
    RETRY = "retry"
    REPLACE_PAYLOAD = "replace_payload"
    KILL = "kill"
    QUARANTINE = "quarantine"


class RetryPolicy(StrictCoreModel):
    max_attempts: int = 1
    backoff_ms: int = 0


class HookResult(StrictCoreModel):
    status: HookStatus
    hook_name: str
    source: str
    reason: str
    replacement_payload: Any | None = None
    retry_policy: RetryPolicy | None = None
    debug_issue: DebugIssueRecord | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return self.status in {
            HookStatus.BLOCK,
            HookStatus.REQUIRE_HITL,
            HookStatus.KILL,
            HookStatus.QUARANTINE,
        }

    @classmethod
    def continue_(cls, hook_name: str, reason: str = "ok") -> "HookResult":
        return cls(status=HookStatus.CONTINUE, hook_name=hook_name, source=hook_name, reason=reason)
