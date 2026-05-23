"""Agent 2 advanced-domain registry view."""
from __future__ import annotations

from semiconductor_swarm.agents.agent2_rtl.subagents.registry import get_milestone_e_signoff_registry


def get_advanced_registry():
    return tuple(agent for agent in get_milestone_e_signoff_registry() if "A2.52" <= agent.agent_id <= "A2.56")