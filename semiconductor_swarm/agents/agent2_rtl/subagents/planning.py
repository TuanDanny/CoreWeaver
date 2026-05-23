"""Agent 2 planning-domain registry view."""
from __future__ import annotations

from semiconductor_swarm.agents.agent2_rtl.subagents.registry import get_milestone_a_registry


def get_planning_registry():
    return tuple(agent for agent in get_milestone_a_registry() if "A2.06" <= agent.agent_id <= "A2.12")