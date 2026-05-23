"""Agent 2 V3.1 registry facade.

This module is the stable registry boundary for Agent 2 subagent domains.
V3.1 keeps behavior identical by delegating to the legacy Milestone A module.
Later milestones can move implementations behind this facade without changing
public imports.
"""
from __future__ import annotations

from semiconductor_swarm.agents.agent2_rtl.subagents.milestone_a import (
    Agent2SubAgent,
    get_milestone_a_registry,
    get_milestone_b_registry,
    get_milestone_b_repair_registry,
    get_milestone_b_review_registry,
    get_milestone_e_signoff_registry,
    get_milestone_f_registry,
    get_milestone_g_registry,
)

__all__ = [
    "Agent2SubAgent",
    "get_milestone_a_registry",
    "get_milestone_b_registry",
    "get_milestone_b_repair_registry",
    "get_milestone_b_review_registry",
    "get_milestone_e_signoff_registry",
    "get_milestone_f_registry",
    "get_milestone_g_registry",
]