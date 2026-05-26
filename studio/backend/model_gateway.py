"""Model provider boundary for Studio backend."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

PROBE_TIMEOUT_S = 15.0


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    enabled: bool
    kind: str


def provider_registry() -> dict[str, ProviderSpec]:
    return {
        "openai_compatible": ProviderSpec("openai_compatible", "OpenAI-compatible", True, "chat_completions"),
        "openai": ProviderSpec("openai", "OpenAI", False, "future"),
        "gemini": ProviderSpec("gemini", "Gemini", False, "future"),
        "grok": ProviderSpec("grok", "Grok", False, "future"),
    }


def public_provider_registry() -> list[dict[str, Any]]:
    return [spec.__dict__ for spec in provider_registry().values()]


async def probe_openai_compatible_endpoint(endpoint: str, model: str, api_key: str) -> dict[str, bool | str]:
    base = endpoint.rstrip("/")
    if not base.startswith(("http://", "https://")):
        return {"ok": False, "message": "Invalid endpoint URL"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Respond with OK only."}],
        "max_tokens": 1,
        "temperature": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
            response = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
    except httpx.TimeoutException:
        return {"ok": False, "message": f"Network timeout: endpoint did not respond within {int(PROBE_TIMEOUT_S)}s."}
    except httpx.ConnectError:
        return {"ok": False, "message": "Network error: cannot connect to endpoint. Check whether 9Router is running."}
    except httpx.RequestError as exc:
        return {"ok": False, "message": f"Network error: cannot connect to endpoint. Check whether 9Router is running. ({exc.__class__.__name__})"}
    if response.status_code == 200:
        try:
            body = response.json()
        except ValueError:
            return {"ok": False, "message": "Invalid chat/completions response"}
        if isinstance(body, dict) and isinstance(body.get("choices"), list) and body["choices"]:
            return {"ok": True, "message": "Connection OK"}
        return {"ok": False, "message": "Invalid chat/completions response"}
    if response.status_code in {401, 403}:
        return {"ok": False, "message": "Access denied: API key is invalid, expired, or unauthorized."}
    if response.status_code == 429:
        return {"ok": False, "message": "Rate limited: wait before retrying."}
    return {"ok": False, "message": f"Endpoint responded with HTTP {response.status_code}"}
