"""Agent 2 review-domain registry view."""
from __future__ import annotations

from semiconductor_swarm.agents.agent2_rtl.subagents.registry import get_milestone_b_review_registry, get_milestone_e_signoff_registry


def get_review_registry():
    return get_milestone_b_review_registry() + get_milestone_e_signoff_registry()