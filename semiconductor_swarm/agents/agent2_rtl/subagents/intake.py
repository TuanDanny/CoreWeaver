"""Agent 2 intake-domain registry view."""
from __future__ import annotations

from semiconductor_swarm.agents.agent2_rtl.subagents.registry import get_milestone_a_registry


def get_intake_registry():
    return tuple(agent for agent in get_milestone_a_registry() if agent.agent_id in {"A2.01", "A2.02", "A2.03", "A2.04", "A2.05"})