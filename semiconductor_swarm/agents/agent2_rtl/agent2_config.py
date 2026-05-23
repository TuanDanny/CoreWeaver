"""Agent 2 Codex API defaults."""
from __future__ import annotations

from semiconductor_swarm.agents.agent1_planning.llm_config import SWARM_LLM_CONFIG

AGENT2_LLM_CONFIG = {
    **SWARM_LLM_CONFIG,
    "fallback_api_key_env": "AGENT2_CODEX_API_KEY",
    "agent": "agent2",
    "input_usd_per_1m_tokens": 0.0,
    "output_usd_per_1m_tokens": 0.0,
}
