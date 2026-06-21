from __future__ import annotations

import asyncio
import json
import os
import random
import time
import urllib.error
import urllib.request

from coreweaver.framework_types import stable_hash
from pydantic import BaseModel

from .client import ModelResponse


class OpenAICompatibleModelClient:
    """Minimal OpenAI-compatible chat/completions adapter for local_llm profile."""

    def __init__(self, *, endpoint: str | None = None, model: str | None = None, api_key: str | None = None, timeout_s: float | None = None) -> None:
        self.endpoint = (endpoint or os.environ.get("COREWEAVER_MODEL_ENDPOINT") or "http://localhost:20128/v1").rstrip("/")
        self.model = model or os.environ.get("COREWEAVER_MODEL") or "cx/gpt-5.5"
        self.api_key = api_key or os.environ.get("COREWEAVER_API_KEY") or os.environ.get("AGENT1_CODEX_API_KEY") or os.environ.get("SWARM_CODEX_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""
        self.timeout_s = float(timeout_s or os.environ.get("COREWEAVER_MODEL_TIMEOUT_S") or 60)
        concurrency = int(os.environ.get("COREWEAVER_MODEL_CONCURRENCY") or 1)
        self.semaphore = asyncio.Semaphore(concurrency)

    async def complete(self, *, prompt: str, idempotency_key: str, response_format: type[BaseModel] | None = None) -> ModelResponse:
        async with self.semaphore:
            # Enforce a 4.0s delay to stay safely under Gemini's 15 RPM rate limit
            await asyncio.sleep(4.0)
            return await asyncio.to_thread(self._complete_sync, prompt, idempotency_key, response_format)

    def _complete_sync(self, prompt: str, idempotency_key: str, response_format: type[BaseModel] | None = None) -> ModelResponse:
        system_content = "You are a semiconductor architecture expert. Return concise, technical findings only."
        if response_format:
            schema_json = json.dumps(response_format.model_json_schema(), indent=2)
            system_content += f"\n\nCRITICAL INSTRUCTION: You MUST return a pure JSON object. It must strictly validate against this JSON Schema:\n{schema_json}"
            
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        if response_format:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json", "Idempotency-Key": idempotency_key}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.endpoint}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        max_retries = 6
        base_delay = 1.0
        data = {}
        for attempt in range(max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_s) as response:  # noqa: S310 - endpoint is local/user-configured.
                    data = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                is_transient = exc.code in (429, 500, 502, 503, 504)
                if is_transient and attempt < max_retries:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                    time.sleep(delay)
                    continue
                raise ConnectionError(f"model endpoint returned HTTP {exc.code}: {exc.reason}") from exc
            except urllib.error.URLError as exc:
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                    time.sleep(delay)
                    continue
                raise ConnectionError(f"model endpoint unavailable: {exc.__class__.__name__}") from exc
        text = str(data.get("choices", [{}])[0].get("message", {}).get("content") or "")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return ModelResponse(
            text=text,
            output_hash=stable_hash(text),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            cost_usd=0.0,
            metadata={"model": self.model, "endpoint_hash": stable_hash(self.endpoint)[:12]},
        )
