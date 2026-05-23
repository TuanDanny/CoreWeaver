"""Semantic validators and adapters for cross-agent contracts."""

from __future__ import annotations

import re
from typing import Any

from .common import APB_SLAVE_INTERFACE
from .constants import AGENT1_TO_AGENT2_V1
from .registry import ContractValidationError, validate_contract


def build_agent1_to_agent2_contract(spec: dict[str, Any]) -> dict[str, Any]:
    """Build versioned Agent 1 -> Agent 2 contract from Agent 1 architecture spec."""
    return {
        "contract_version": AGENT1_TO_AGENT2_V1,
        "project_name": spec.get("project_name"),
        "modules": spec.get("ip_blocks", []),
        "requirements": spec.get("requirements", {}),
        "target_node": spec.get("target_node"),
        "isa": spec.get("isa"),
        "core_config": spec.get("core_config", {}),
        "accelerator": spec.get("accelerator", {}),
        "ppa_estimate": spec.get("ppa_estimate", {}),
        "bandwidth_estimate": spec.get("bandwidth_estimate", {}),
        "tool_inputs": spec.get("tool_inputs", {}),
        "tool_provenance": spec.get("tool_provenance", {}),
        "memory_map": spec.get("memory_map", {}),
        "bus_topology": spec.get("bus_topology", {}),
        "ip_blocks": spec.get("ip_blocks", []),
        "clock_domains": spec.get("clock_domains", []),
        "constraints": spec.get("constraints", {}),
        "interfaces": spec.get("interfaces", {}),
        "agent1_contract_manifest": spec.get("agent1_contract_manifest", {}),
    }


def validate_agent1_to_agent2_contract(payload: dict[str, Any]) -> bool:
    """Validate Agent 1 -> Agent 2 v1 JSON shape plus hardware semantics."""
    validate_contract(AGENT1_TO_AGENT2_V1, payload)
    if not re.match(r"^[a-z_][a-z0-9_]*$", str(payload.get("project_name", ""))):
        raise ContractValidationError("agent1_to_agent2/v1 project_name must be RTL-safe ^[a-z_][a-z0-9_]*$")
    if payload.get("interfaces", {}).get("apb_slave") != APB_SLAVE_INTERFACE:
        raise ContractValidationError("agent1_to_agent2/v1 requires exact locked APB slave pinout")
    if payload.get("bus_topology", {}).get("protocol") != "APB":
        raise ContractValidationError("agent1_to_agent2/v1 requires APB bus_topology.protocol")
    if payload.get("constraints", {}).get("agent2_port_renaming_allowed") is not False:
        raise ContractValidationError("agent1_to_agent2/v1 requires Agent 2 port renaming disabled")
    if payload.get("constraints", {}).get("formal_first") is not True:
        raise ContractValidationError("agent1_to_agent2/v1 requires formal_first true")
    _validate_memory_map(payload.get("memory_map", {}))
    return True


def coerce_agent1_to_agent2_payload(payload_or_spec: dict[str, Any]) -> dict[str, Any]:
    """Accept v1 contract or legacy Agent 1 spec, return v1 contract payload."""
    if payload_or_spec.get("contract_version") == AGENT1_TO_AGENT2_V1:
        return payload_or_spec
    return build_agent1_to_agent2_contract(payload_or_spec)


def agent1_to_agent2_spec(payload_or_spec: dict[str, Any]) -> dict[str, Any]:
    """Validate v1 contract or legacy spec and return Agent 2 legacy spec view."""
    payload = coerce_agent1_to_agent2_payload(payload_or_spec)
    validate_agent1_to_agent2_contract(payload)
    spec = {key: value for key, value in payload.items() if key != "contract_version"}
    return spec


def _parse_int(value: Any, path: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as exc:
            raise ContractValidationError(f"agent1_to_agent2/v1 {path} must parse as integer") from exc
    raise ContractValidationError(f"agent1_to_agent2/v1 {path} must parse as integer")


def _validate_memory_map(memory_map: dict[str, Any]) -> None:
    if not isinstance(memory_map, dict) or not memory_map:
        raise ContractValidationError("agent1_to_agent2/v1 requires non-empty memory_map")
    ranges: list[tuple[int, int, str]] = []
    for block_name, block in memory_map.items():
        if not isinstance(block, dict):
            raise ContractValidationError(f"agent1_to_agent2/v1 memory_map.{block_name} must be object")
        base = _parse_int(block.get("base"), f"memory_map.{block_name}.base")
        size = _parse_int(block.get("size"), f"memory_map.{block_name}.size")
        if base <= 0 or size <= 0:
            raise ContractValidationError(f"agent1_to_agent2/v1 memory_map.{block_name} base/size must be positive")
        if base % 0x1000 != 0:
            raise ContractValidationError(f"agent1_to_agent2/v1 memory_map.{block_name}.base must be 4KB aligned")
        ranges.append((base, base + size, block_name))
    for index, (start, end, name) in enumerate(sorted(ranges)):
        for other_start, _other_end, other_name in sorted(ranges)[index + 1:]:
            if other_start < end:
                raise ContractValidationError(f"agent1_to_agent2/v1 memory_map overlap: {name} overlaps {other_name}")
