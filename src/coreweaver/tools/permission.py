from __future__ import annotations

from enum import Enum

from coreweaver.framework_types import StrictCoreModel


class PermissionStatus(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"
    BLOCK = "block"


class PermissionDecision(StrictCoreModel):
    status: PermissionStatus
    reason: str
