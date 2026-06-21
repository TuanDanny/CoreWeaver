from __future__ import annotations

import time
from pydantic import BaseModel

from coreweaver.framework_types import stable_hash
from coreweaver.runtime.checkpoints import InMemoryCheckpointStore

from .client import ModelClient, ModelResponse
from .mock import MockModelClient
from .records import ModelCallRecord, ModelRouteDecision


class ModelRouter:
    def __init__(self, client: ModelClient | None = None, checkpoint_store: InMemoryCheckpointStore | None = None) -> None:
        self.client = client or MockModelClient()
        self.checkpoints = checkpoint_store or InMemoryCheckpointStore()

    async def complete(self, *, prompt: str, idempotency_key: str, model_name: str = "mock", response_format: type[BaseModel] | None = None) -> tuple[ModelResponse, ModelCallRecord]:
        if self.checkpoints.has_completed(idempotency_key):
            return self.checkpoints.get_completed(idempotency_key)
        start = time.perf_counter()
        response = await self.client.complete(prompt=prompt, idempotency_key=idempotency_key, response_format=response_format)
        latency_ms = int((time.perf_counter() - start) * 1000)
        record = ModelCallRecord(
            model_call_id=f"model:{stable_hash(idempotency_key)[:16]}",
            route=ModelRouteDecision(route_id="default", model_name=model_name, reason="framework mock route"),
            idempotency_key=idempotency_key,
            input_hash=stable_hash(prompt),
            output_hash=response.output_hash,
            latency_ms=latency_ms,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            cost_usd=response.cost_usd,
            status="completed",
        )
        result = (response, record)
        self.checkpoints.record_completed(idempotency_key, result)
        return result
