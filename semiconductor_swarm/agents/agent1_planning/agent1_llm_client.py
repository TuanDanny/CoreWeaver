"""OpenAI-compatible Codex client for Agent 1."""
from __future__ import annotations

import hashlib
import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from semiconductor_swarm.agents.agent1_planning.agent1_config import AGENT1_LLM_CONFIG
from semiconductor_swarm.agents.agent1_planning.llm_config import build_openai_compatible_headers, resolve_swarm_llm_config
from semiconductor_swarm.runtime_events import emit_runtime_event


@dataclass(frozen=True)
class Agent1CodexResult:
    content: str
    evidence: dict[str, Any]


def call_agent1_codex(prompt: str, *, config: dict[str, Any] | None = None) -> Agent1CodexResult:
    cfg = resolve_swarm_llm_config({**AGENT1_LLM_CONFIG, **(config or {})})
    base_url = str(cfg["base_url"]).rstrip("/")
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": cfg["temperature"],
    }
    if cfg.get("max_tokens") is not None:
        payload["max_tokens"] = int(cfg["max_tokens"])
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=data,
        headers=build_openai_compatible_headers(cfg),
        method="POST",
    )
    started = time.time()
    last_error = ""
    emit_runtime_event(
        {
            "type": "agent_action",
            "agent": "agent1",
            "label": "Agent 1 Architect",
            "phase": "planning",
            "action": "Codex request started",
            "status": "running",
            "summary": f"Calling {cfg['model']} at {base_url}",
        }
    )
    for retry in range(int(cfg.get("max_retries", 0)) + 1):
        try:
            with urllib.request.urlopen(req, timeout=float(cfg["timeout_s"])) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            evidence = _evidence(cfg, prompt, content, retry, started, body.get("usage"))
            emit_runtime_event(
                {
                    "type": "agent_action",
                    "agent": "agent1",
                    "label": "Agent 1 Architect",
                    "phase": "planning",
                    "action": "Codex response received",
                    "status": "pass",
                    "summary": f"Model {cfg['model']} returned architecture evidence in {evidence['latency_s']}s",
                    "metric": {"latency_s": evidence["latency_s"], "total_tokens": evidence.get("total_tokens")},
                }
            )
            _emit_usage_metrics(evidence)
            return Agent1CodexResult(content=content, evidence=evidence)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
            last_error = str(exc)
            if retry < int(cfg.get("max_retries", 0)):
                delay_s = min(2.0, 0.2 * (2**retry)) + random.uniform(0.0, 0.05)
                emit_runtime_event(
                    {
                        "type": "agent_action",
                        "agent": "agent1",
                        "label": "Agent 1 Architect",
                        "phase": "planning",
                        "action": "Codex retry backoff",
                        "status": "warning",
                        "summary": f"Retrying {cfg['model']} after {round(delay_s, 2)}s because {exc.__class__.__name__}: {last_error}",
                        "metric": {"retry": retry + 1, "delay_s": round(delay_s, 3)},
                    }
                )
                time.sleep(delay_s)
    emit_runtime_event(
        {
            "type": "agent_action",
            "agent": "agent1",
            "label": "Agent 1 Architect",
            "phase": "planning",
            "action": "Codex unavailable",
            "status": "fail",
            "summary": f"Agent 1 Codex API unavailable at {base_url}: {last_error}",
        }
    )
    raise RuntimeError(f"Agent 1 Codex API unavailable at {base_url}: {last_error}")


def _evidence(cfg: dict[str, Any], prompt: str, response: str, retry: int, started: float, usage: Any = None) -> dict[str, Any]:
    return {
        "provider": cfg["provider"],
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "api_key_env": cfg.get("api_key_env"),
        "auth_header_present": bool(cfg.get("api_key")),
        "timeout_s": float(cfg["timeout_s"]),
        "max_retries": int(cfg.get("max_retries", 0)),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "retry_count": retry,
        "latency_s": round(time.time() - started, 3),
        **_usage_fields(usage, cfg),
    }


def _usage_fields(usage: Any, cfg: dict[str, Any]) -> dict[str, Any]:
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


def _emit_usage_metrics(evidence: dict[str, Any]) -> None:
    emit_runtime_event({"type": "metric", "name": "codex_call_count", "value": 1, "status": "info", "agent": "agent1"})
    emit_runtime_event({"type": "metric", "name": "codex_latency_s", "value": evidence.get("latency_s"), "status": "info", "agent": "agent1"})
    for name in ("prompt_tokens", "completion_tokens", "total_tokens", "estimated_cost_usd"):
        value = evidence.get(name)
        if value is not None:
            emit_runtime_event({"type": "metric", "name": f"codex_{name}", "value": value, "status": "info", "agent": "agent1"})
