from __future__ import annotations

from coreweaver.framework_types import stable_hash

from .client import ModelResponse


class MockModelClient:
    async def complete(self, *, prompt: str, idempotency_key: str) -> ModelResponse:
        text = f"mock:{stable_hash({'prompt': prompt, 'key': idempotency_key})[:12]}"
        return ModelResponse(text=text, output_hash=stable_hash(text), prompt_tokens=len(prompt.split()), completion_tokens=len(text.split()))
