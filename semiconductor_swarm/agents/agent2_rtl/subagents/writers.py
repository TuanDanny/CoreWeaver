"""Agent 2 writer-domain registry view."""
from __future__ import annotations

from semiconductor_swarm.agents.agent2_rtl.subagents.registry import get_milestone_a_registry


def get_writer_registry():
    return tuple(agent for agent in get_milestone_a_registry() if "A2.13" <= agent.agent_id <= "A2.27")