"""OpenAI-compatible Codex client for Agent 2 hybrid RTL review."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from semiconductor_swarm.agents.agent1_planning.llm_config import build_openai_compatible_headers, resolve_swarm_llm_config
from semiconductor_swarm.agents.agent2_rtl.agent2_config import AGENT2_LLM_CONFIG
from semiconductor_swarm.runtime_events import emit_runtime_event


class Agent2CodexUnavailable(RuntimeError):
    """Raised when mandatory Agent 2 Codex evidence cannot be produced."""


@dataclass(frozen=True)
class Agent2CodexResult:
    content: str
    evidence: dict[str, Any]


def call_agent2_codex(prompt: str, *, purpose: str = "rtl_review", config: dict[str, Any] | None = None) -> Agent2CodexResult:
    cfg = resolve_swarm_llm_config({**AGENT2_LLM_CONFIG, **(config or {})})
    base_url = str(cfg["base_url"]).rstrip("/")
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": cfg["temperature"],
    }
    data = json.dumps(payload).encode("utf-8")
    headers = build_openai_compatible_headers(cfg)
    req = urllib.request.Request(f"{base_url}/chat/completions", data=data, headers=headers, method="POST")
    started = time.time()
    last_error = ""
    emit_runtime_event(
        {
            "type": "agent_action",
            "agent": "agent2",
            "label": "Agent 2 RTL Designer",
            "phase": "rtl",
            "action": "Codex request started",
            "status": "running",
            "summary": f"Calling {cfg['model']} for {purpose} at {base_url}",
        }
    )
    for retry in range(int(cfg.get("max_retries", 0)) + 1):
        try:
            with urllib.request.urlopen(req, timeout=float(cfg["timeout_s"])) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            content = _extract_content(body)
            evidence = _evidence(cfg, prompt, content, body, retry, started, purpose)
            emit_runtime_event(
                {
                    "type": "agent_action",
                    "agent": "agent2",
                    "label": "Agent 2 RTL Designer",
                    "phase": "rtl",
                    "action": "Codex response received",
                    "status": "pass",
                    "summary": f"Model {cfg['model']} returned {purpose} evidence in {evidence['latency_s']}s",
                    "metric": {"latency_s": evidence["latency_s"], "total_tokens": evidence.get("total_tokens")},
                }
            )
            _emit_usage_metrics(evidence)
            return Agent2CodexResult(content=content, evidence=evidence)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError) as exc:
            last_error = str(exc)
    emit_runtime_event(
        {
            "type": "agent_action",
            "agent": "agent2",
            "label": "Agent 2 RTL Designer",
            "phase": "rtl",
            "action": "Codex unavailable",
            "status": "fail",
            "summary": f"Agent 2 Codex API unavailable at {base_url}: {last_error}",
        }
    )
    raise Agent2CodexUnavailable(f"Agent 2 Codex API unavailable at {base_url}: {last_error}")


def _extract_content(body: dict[str, Any]) -> str:
    return str(body.get("choices", [{}])[0].get("message", {}).get("content", ""))


def _usage_fields(body: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return {
            "usage_status": "not_reported_by_endpoint",
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "cached_tokens": None,
            "estimated_cost_usd": None,
        }
    prompt_tokens = _int_or_none(usage.get("prompt_tokens"))
    completion_tokens = _int_or_none(usage.get("completion_tokens"))
    total_tokens = _int_or_none(usage.get("total_tokens"))
    cached_tokens = _int_or_none((usage.get("prompt_tokens_details") or {}).get("cached_tokens") if isinstance(usage.get("prompt_tokens_details"), dict) else usage.get("cached_tokens"))
    input_rate = float(cfg.get("input_usd_per_1m_tokens", 0.0) or 0.0)
    output_rate = float(cfg.get("output_usd_per_1m_tokens", 0.0) or 0.0)
    estimated = None
    if prompt_tokens is not None and completion_tokens is not None:
        estimated = round((prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000, 8)
    return {
        "usage_status": "reported",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens,
        "estimated_cost_usd": estimated,
    }


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _evidence(cfg: dict[str, Any], prompt: str, response: str, body: dict[str, Any], retry: int, started: float, purpose: str) -> dict[str, Any]:
    return {
        "schema_version": "agent2.codex_evidence.v1",
        "agent": "agent2",
        "purpose": purpose,
        "provider": cfg["provider"],
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "api_key_env": cfg.get("api_key_env"),
        "fallback_api_key_env": cfg.get("fallback_api_key_env"),
        "auth_header_present": bool(cfg.get("api_key")),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "retry_count": retry,
        "latency_s": round(time.time() - started, 3),
        **_usage_fields(body, cfg),
    }

def _emit_usage_metrics(evidence: dict[str, Any]) -> None:
    for name in ("prompt_tokens", "completion_tokens", "total_tokens", "estimated_cost_usd"):
        value = evidence.get(name)
        if value is not None:
            emit_runtime_event({"type": "metric", "name": f"codex_{name}", "value": value, "status": "info", "agent": "agent2"})
