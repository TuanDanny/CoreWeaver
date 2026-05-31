from __future__ import annotations

from pydantic import Field

from coreweaver.framework_types import StrictCoreModel, utc_now


class ModelRouteDecision(StrictCoreModel):
    route_id: str
    model_name: str
    reason: str


class ModelCallRecord(StrictCoreModel):
    model_call_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    route: ModelRouteDecision
    idempotency_key: str
    input_hash: str
    output_hash: str | None = None
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    retry_count: int = 0
    status: str = "pending"
    timestamp: str = Field(default_factory=utc_now)


class ModelIdempotencyRecord(StrictCoreModel):
    idempotency_key: str
    model_call_id: str
    status: str
    output_hash: str | None = None
