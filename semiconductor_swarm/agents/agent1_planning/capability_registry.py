"""Agent 1 downstream capability registry.

This is intentionally local and deterministic. A future RAG/context provider can
populate the same shape without changing Agent 1 planning logic.
"""
from __future__ import annotations

from typing import Any


CAPABILITY_REGISTRY: dict[str, dict[str, Any]] = {
    "agent2": {
        "native_protocols": ["APB"],
        "bridge_supported_primary_protocols": ["AHB"],
        "unsupported_protocols": ["AXI", "Wishbone"],
        "notes": "Agent 2 currently generates APB-side RTL collateral and can consume an AHB-to-APB boundary contract.",
    },
    "agent3": {
        "native_protocols": ["APB"],
        "bridge_supported_primary_protocols": ["AHB"],
        "unsupported_protocols": ["AXI", "Wishbone"],
        "notes": "Agent 3 currently has APB cocotb helpers and can test APB-side peripherals behind a bridge.",
    },
    "agent5": {
        "native_protocols": ["APB"],
        "bridge_supported_primary_protocols": ["AHB"],
        "unsupported_protocols": ["AXI", "Wishbone"],
        "notes": "Agent 5 currently has APB protocol properties and needs a separate upgrade for full AHB proofs.",
    },
    "agent4": {
        "native_protocols": ["APB", "AHB"],
        "bridge_supported_primary_protocols": ["AHB"],
        "unsupported_protocols": [],
        "notes": "Agent 4 is mostly backend-collateral driven and depends on generated RTL.",
    },
}


def get_agent_capabilities(agent_id: str | None = None) -> dict[str, Any]:
    if agent_id:
        return dict(CAPABILITY_REGISTRY.get(agent_id, {}))
    return {key: dict(value) for key, value in CAPABILITY_REGISTRY.items()}


def assess_requirement_capability(analysis: dict[str, Any]) -> dict[str, Any]:
    selected = analysis.get("selected_architecture", {}) if isinstance(analysis.get("selected_architecture"), dict) else {}
    intents = analysis.get("extracted_intents", {}) if isinstance(analysis.get("extracted_intents"), dict) else {}
    if selected.get("status") == "requires_clarification":
        return {
            "schema_version": "agent1.capability_assessment.v1",
            "requested_primary_protocol": None,
            "mode": "requires_clarification",
            "reason": "No downstream capability can be assessed until the Project Requirement names actionable chip-design intent.",
            "bridge": None,
            "capability_gaps": [{"agent": "agent1", "capability": "requirement_intake", "status": "needs_user_clarification"}],
            "registry": get_agent_capabilities(),
        }
    requested_bus = str(selected.get("primary_protocol") or intents.get("requested_bus_protocol") or "APB").upper()
    raw = str(analysis.get("raw_requirement", "")).lower()
    pure_bus_requested = any(token in raw for token in ("pure ahb", "ahb only", "no apb", "without apb"))

    if requested_bus == "APB":
        mode = "native_supported"
        reason = "APB is supported end-to-end by Agent 2, Agent 3, and Agent 5."
        gaps: list[dict[str, str]] = []
        bridge = None
    elif requested_bus == "AHB" and not pure_bus_requested:
        mode = "bridge_supported"
        reason = "AHB is requested as the primary system bus; APB-side downstream collateral remains usable behind an AHB-to-APB bridge."
        gaps = [
            {"agent": "agent2", "capability": "full_native_ahb_rtl", "status": "partial"},
            {"agent": "agent3", "capability": "full_native_ahb_dv", "status": "partial"},
            {"agent": "agent5", "capability": "full_native_ahb_formal", "status": "partial"},
        ]
        bridge = {"name": "ahb_to_apb_bridge", "from_protocol": "AHB", "to_protocol": "APB", "boundary": "peripheral_subsystem"}
    else:
        mode = "unsupported_hitl"
        reason = f"{requested_bus} is not supported end-to-end by current downstream agents without an approved adapter or downstream upgrade."
        gaps = [
            {"agent": "agent2", "capability": f"native_{requested_bus.lower()}_rtl", "status": "unsupported"},
            {"agent": "agent3", "capability": f"native_{requested_bus.lower()}_dv", "status": "unsupported"},
            {"agent": "agent5", "capability": f"native_{requested_bus.lower()}_formal", "status": "unsupported"},
        ]
        bridge = None

    return {
        "schema_version": "agent1.capability_assessment.v1",
        "requested_primary_protocol": requested_bus,
        "mode": mode,
        "reason": reason,
        "bridge": bridge,
        "capability_gaps": gaps,
        "registry": get_agent_capabilities(),
    }
