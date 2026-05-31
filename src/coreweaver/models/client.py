from __future__ import annotations

from typing import Protocol

from pydantic import Field

from coreweaver.framework_types import StrictCoreModel


class ModelResponse(StrictCoreModel):
    text: str
    output_hash: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    metadata: dict[str, object] = Field(default_factory=dict)


class ModelClient(Protocol):
    async def complete(self, *, prompt: str, idempotency_key: str) -> ModelResponse:
        ...
