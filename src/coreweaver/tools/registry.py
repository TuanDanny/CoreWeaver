from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from coreweaver.framework_types import stable_hash
from coreweaver.runtime.checkpoints import InMemoryCheckpointStore

from .permission import PermissionDecision, PermissionStatus
from .schema import ToolSchema

ToolFn = Callable[[dict[str, Any]], Any | Awaitable[Any]]


class ToolRegistry:
    def __init__(self, checkpoint_store: InMemoryCheckpointStore | None = None) -> None:
        self._tools: dict[str, tuple[ToolSchema, ToolFn, PermissionDecision]] = {}
        self._checkpoints = checkpoint_store or InMemoryCheckpointStore()

    def register(self, schema: ToolSchema, fn: ToolFn, permission: PermissionDecision | None = None) -> None:
        self._tools[schema.name] = (schema, fn, permission or PermissionDecision(status=PermissionStatus.ALLOW, reason="registered safe tool"))

    async def call(self, name: str, payload: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        if self._checkpoints.has_completed(idempotency_key):
            return self._checkpoints.get_completed(idempotency_key)
        schema, fn, permission = self._tools[name]
        if permission.status != PermissionStatus.ALLOW:
            raise PermissionError(permission.reason)
        schema.validate_input(payload)
        result = fn(payload)
        if inspect.isawaitable(result):
            result = await result
        record = {
            "tool_call_id": f"tool:{stable_hash([name, idempotency_key])[:16]}",
            "tool_name": name,
            "result": result,
            "output_hash": stable_hash(result),
        }
        self._checkpoints.record_completed(idempotency_key, record)
        return record
