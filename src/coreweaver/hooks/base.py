from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, Protocol

from pydantic import Field

from coreweaver.framework_types import StrictCoreModel

from .results import HookResult


class HookPoint(str, Enum):
    ON_INTAKE = "on_intake"
    ON_MESSAGE_PUBLISH = "on_message_publish"
    ON_MODEL_CALL = "on_model_call"
    ON_TOOL_CALL = "on_tool_call"
    ON_GROUP_SESSION = "on_group_session"
    ON_PRINCIPAL_REVIEW = "on_principal_review"
    ON_SIGNOFF_GATE = "on_signoff_gate"
    ON_HANDOFF = "on_handoff"


class HookContext(StrictCoreModel):
    run_id: str
    revision_id: str
    span_id: str
    hook_point: HookPoint
    payload: Any
    metadata: dict[str, Any] = Field(default_factory=dict)


class Hook(Protocol):
    name: str

    def __call__(self, context: HookContext) -> Awaitable[HookResult]:
        ...


HookCallable = Callable[[HookContext], Awaitable[HookResult]]
