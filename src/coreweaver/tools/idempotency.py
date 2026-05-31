from __future__ import annotations

from coreweaver.framework_types import StrictCoreModel


class ToolIdempotencyRecord(StrictCoreModel):
    idempotency_key: str
    tool_call_id: str
    status: str
    output_hash: str | None = None
