"""Shared OpenAI-compatible Codex API config for all swarm agents."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


SWARM_LLM_CONFIG: dict[str, Any] = {
    "provider": "openai_compatible",
    "base_url": "http://localhost:20128/v1",
    "model": "cx/gpt-5.5",
    "local_config_path": "codex_api.local.json",
    "api_key_env": "SWARM_CODEX_API_KEY",
    "fallback_api_key_env": "AGENT1_CODEX_API_KEY",
    "timeout_s": 120,
    "temperature": 0.2,
    "max_retries": 2,
}


def resolve_swarm_llm_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return shared LLM config with optional overrides, local file, and env-driven API key."""
    cfg = {**SWARM_LLM_CONFIG, **(overrides or {})}
    local_cfg = _read_local_config(str(cfg["local_config_path"]))
    cfg.update({key: value for key, value in local_cfg.items() if value not in (None, "")})
    api_key = os.environ.get(str(cfg["api_key_env"])) or os.environ.get(str(cfg["fallback_api_key_env"])) or cfg.get("api_key")
    if api_key:
        cfg["api_key"] = api_key
    return cfg


def _read_local_config(path: str) -> dict[str, Any]:
    local_path = Path(path)
    if not local_path.is_file():
        return {}
    return json.loads(local_path.read_text(encoding="utf-8"))


def build_openai_compatible_headers(cfg: dict[str, Any]) -> dict[str, str]:
    """Build headers for OpenAI-compatible chat/completions requests."""
    headers = {"Content-Type": "application/json"}
    api_key = cfg.get("api_key")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers