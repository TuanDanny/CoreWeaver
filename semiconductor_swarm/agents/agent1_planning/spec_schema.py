"""Agent 1 V3.7/V4 schema gates and tool provenance checks."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from semiconductor_swarm.agents.agent1_planning.architect import APB_SLAVE_INTERFACE


AGENT1_V37_REQUIRED_KEYS = {
    "project_name",
    "requirements",
    "target_node",
    "isa",
    "core_config",
    "accelerator",
    "ppa_estimate",
    "bandwidth_estimate",
    "tool_provenance",
    "memory_map",
    "bus_topology",
    "ip_blocks",
    "clock_domains",
    "constraints",
    "interfaces",
    "firmware_contract",
    "io_packaging",
    "power_intent",
    "cdc_rdc_plan",
    "interconnect_qos",
    "memory_hierarchy",
    "dft_plan",
    "safety_security",
    "ip_reuse_cost",
}

AGENT1_V4_REQUIRED_KEYS = AGENT1_V37_REQUIRED_KEYS | {
    "tool_inputs",
    "agent1_contract_manifest",
}

AGENT1_V4_DOWNSTREAM_REQUIRED = {
    "agent2": {"inputs", "must_read_artifacts", "output_contract", "blocked_without"},
    "agent3": {"inputs", "must_read_artifacts", "output_contract", "blocked_without"},
    "agent4": {"inputs", "must_read_artifacts", "output_contract", "blocked_without"},
    "agent5": {"inputs", "must_read_artifacts", "output_contract", "blocked_without"},
}


def attach_tool_provenance(spec: dict[str, Any]) -> dict[str, Any]:
    """Attach immutable evidence that numeric estimates came from tools."""
    enriched = dict(spec)
    enriched["tool_provenance"] = {
        "ppa_estimate": _provenance("calculate_ppa", enriched.get("ppa_estimate", {})),
        "bandwidth_estimate": _provenance("calculate_bandwidth", enriched.get("bandwidth_estimate", {})),
    }
    return enriched


def validate_agent1_v37_spec_schema(spec: dict[str, Any]) -> None:
    """Reject Agent 1 specs that are not ready for Agent 2/3/4/5 handoff."""
    missing = AGENT1_V37_REQUIRED_KEYS - set(spec)
    if missing:
        raise ValueError(f"Agent1 V3.7 schema missing keys: {sorted(missing)}")
    _require_dict(spec, "requirements")
    _require_dict(spec, "core_config")
    _require_dict(spec, "accelerator")
    _require_dict(spec, "ppa_estimate")
    _require_dict(spec, "bandwidth_estimate")
    _require_dict(spec, "tool_provenance")
    _require_dict(spec, "memory_map")
    _require_dict(spec, "bus_topology")
    _require_list(spec, "ip_blocks")
    _require_list(spec, "clock_domains")
    _require_dict(spec, "constraints")
    _require_dict(spec, "interfaces")

    if not isinstance(spec.get("project_name"), str) or not spec["project_name"]:
        raise ValueError("Agent1 V3.7 schema field project_name must be non-empty string")
    if not re.match(r"^[a-z_][a-z0-9_]*$", spec["project_name"]):
        raise ValueError("Agent1 V3.7 schema field project_name must be RTL-safe ^[a-z_][a-z0-9_]*$")
    if spec.get("bus_topology", {}).get("protocol") != "APB":
        raise ValueError("Agent1 V3.7 schema requires APB bus_topology.protocol")
    if spec.get("interfaces", {}).get("apb_slave") != APB_SLAVE_INTERFACE:
        raise ValueError("Agent1 V3.7 schema requires exact locked APB slave pinout")
    if spec.get("constraints", {}).get("agent2_port_renaming_allowed") is not False:
        raise ValueError("Agent1 V3.7 schema requires locked Agent2 port names")
    if not spec.get("constraints", {}).get("formal_first"):
        raise ValueError("Agent1 V3.7 schema requires formal_first constraint")
    _validate_memory_map_semantics(spec)
    _validate_tool_provenance(spec)


def build_agent1_contract_manifest(spec: dict[str, Any]) -> dict[str, Any]:
    """Build strict Agent 1 handoff manifest for downstream agents."""
    project = spec.get("project_name", "unknown")
    common_inputs = [
        "architecture_plan.md",
        "spec.json",
        "agent1_v4_trace.jsonl",
        "agent1_v4_tool_ledger.jsonl",
        "agent1_v4_replay_bundle.json",
        "agent1_v4_audit_cross_check.json",
    ]
    return {
        "schema_version": "agent1_contract_manifest_v4",
        "project_name": project,
        "global_invariants": {
            "formal_first": spec.get("constraints", {}).get("formal_first") is True,
            "agent2_port_renaming_allowed": spec.get("constraints", {}).get("agent2_port_renaming_allowed"),
            "bus_protocol": spec.get("bus_topology", {}).get("protocol"),
            "apb_slave_pinout_locked": True,
        },
        "handoffs": {
            "agent2": {
                "inputs": common_inputs + ["agent1_memory_interface_plan.json", "agent1_register_map.rdl"],
                "must_read_artifacts": ["agent1_memory_interface_plan.json", "agent1_register_map.rdl", f"fw_{project}_regs.h"],
                "output_contract": ["SystemVerilog packages", "interfaces", "modules", "no APB port rename"],
                "blocked_without": ["PLAN_REVIEW_APPROVED", "agent1_v4_audit_cross_check.pass"],
            },
            "agent3": {
                "inputs": common_inputs + [f"tb_{project}_reg_model.py", "agent1_verification_strategy.md"],
                "must_read_artifacts": [f"tb_{project}_reg_model.py", "agent1_register_map.rdl", "agent1_verification_strategy.md"],
                "output_contract": ["cocotb tests", "scoreboards", "register model consistency"],
                "blocked_without": ["Agent2 RTL", "Agent5 formal plan"],
            },
            "agent4": {
                "inputs": common_inputs + ["agent1_clock_power_plan.json", "agent1_io_packaging_plan.json", "agent1_dft_plan.json"],
                "must_read_artifacts": ["agent1_clock_power_plan.json", "agent1_io_packaging_plan.json", "agent1_dft_plan.json"],
                "output_contract": ["QSF/SDC", "backend plan", "timing/resource report parsers"],
                "blocked_without": ["Agent2 RTL", "Agent3 DV smoke"],
            },
            "agent5": {
                "inputs": common_inputs + ["agent1_safety_security_plan.json", "agent1_verification_strategy.md"],
                "must_read_artifacts": ["agent1_safety_security_plan.json", "agent1_verification_strategy.md", "agent1_memory_interface_plan.json"],
                "output_contract": ["SVA wrappers", "SymbiYosys collateral", "formal decision"],
                "blocked_without": ["Agent2 RTL"],
            },
        },
    }


def attach_agent1_contract_manifest(spec: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(spec)
    enriched["agent1_contract_manifest"] = build_agent1_contract_manifest(enriched)
    return enriched


def validate_agent1_v4_spec_schema(spec: dict[str, Any]) -> None:
    """Reject Agent 1 V4 specs lacking audit/replay/downstream contracts."""
    validate_agent1_v37_spec_schema(spec)
    missing = AGENT1_V4_REQUIRED_KEYS - set(spec)
    if missing:
        raise ValueError(f"Agent1 V4 schema missing keys: {sorted(missing)}")
    _require_dict(spec, "tool_inputs")
    _require_dict(spec, "agent1_contract_manifest")
    tool_inputs = spec["tool_inputs"]
    for tool_name in ("calculate_ppa", "calculate_bandwidth"):
        if not isinstance(tool_inputs.get(tool_name), dict) or not tool_inputs[tool_name]:
            raise ValueError(f"Agent1 V4 schema requires tool_inputs.{tool_name}")
    manifest = spec["agent1_contract_manifest"]
    if manifest.get("schema_version") != "agent1_contract_manifest_v4":
        raise ValueError("Agent1 V4 contract manifest schema_version mismatch")
    handoffs = manifest.get("handoffs")
    if not isinstance(handoffs, dict):
        raise ValueError("Agent1 V4 contract manifest requires handoffs object")
    for agent, required_keys in AGENT1_V4_DOWNSTREAM_REQUIRED.items():
        handoff = handoffs.get(agent)
        if not isinstance(handoff, dict):
            raise ValueError(f"Agent1 V4 contract manifest missing {agent}")
        missing_handoff = required_keys - set(handoff)
        if missing_handoff:
            raise ValueError(f"Agent1 V4 contract manifest {agent} missing keys: {sorted(missing_handoff)}")
        for key in required_keys:
            if not isinstance(handoff.get(key), list) or not handoff[key]:
                raise ValueError(f"Agent1 V4 contract manifest {agent}.{key} must be non-empty list")
    invariants = manifest.get("global_invariants", {})
    if invariants.get("formal_first") is not True or invariants.get("agent2_port_renaming_allowed") is not False:
        raise ValueError("Agent1 V4 contract manifest invariant mismatch")


def _parse_int(value: Any, path: str) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as exc:
            raise ValueError(f"Agent1 V3.7 {path} must parse as integer") from exc
    raise ValueError(f"Agent1 V3.7 {path} must parse as integer")


def _validate_memory_map_semantics(spec: dict[str, Any]) -> None:
    ranges: list[tuple[int, int, str]] = []
    for block_name, block in spec.get("memory_map", {}).items():
        if not isinstance(block, dict):
            raise ValueError(f"Agent1 V3.7 memory_map.{block_name} must be object")
        base = _parse_int(block.get("base"), f"memory_map.{block_name}.base")
        size = _parse_int(block.get("size"), f"memory_map.{block_name}.size")
        if base <= 0 or size <= 0:
            raise ValueError(f"Agent1 V3.7 memory_map.{block_name} base/size must be positive")
        if base % 0x1000 != 0:
            raise ValueError(f"Agent1 V3.7 memory_map.{block_name}.base must be 4KB aligned")
        ranges.append((base, base + size, block_name))
        registers = block.get("registers", {})
        if not isinstance(registers, dict):
            raise ValueError(f"Agent1 V3.7 memory_map.{block_name}.registers must be object")
        has_irq_status = "irq_status" in registers
        has_irq_companion = "irq_enable" in registers or "irq_mask" in registers
        for reg_name, reg in registers.items():
            if not isinstance(reg, dict):
                raise ValueError(f"Agent1 V3.7 memory_map.{block_name}.registers.{reg_name} must be object")
            offset = _parse_int(reg.get("offset", 0), f"memory_map.{block_name}.registers.{reg_name}.offset")
            width = _parse_int(reg.get("width_bits", 32), f"memory_map.{block_name}.registers.{reg_name}.width_bits")
            if offset % 4 != 0:
                raise ValueError(f"Agent1 V3.7 memory_map.{block_name}.registers.{reg_name}.offset must be 4-byte aligned")
            if width <= 0 or width not in {1, 8, 16, 32, 64, 128}:
                raise ValueError(f"Agent1 V3.7 memory_map.{block_name}.registers.{reg_name}.width_bits invalid")
            if reg_name == "irq_status" and str(reg.get("clear", reg.get("access", ""))).lower() not in {"w1c", "read_clear"}:
                raise ValueError(f"Agent1 V3.7 memory_map.{block_name}.registers.irq_status must be W1C/read_clear")
            if reg.get("sensitive") and not (reg.get("privileged") or reg.get("access") in {"wo", "write_once"} or reg.get("clear") == "software_zeroize" or reg.get("no_readback")):
                raise ValueError(f"Agent1 V3.7 memory_map.{block_name}.registers.{reg_name} sensitive register requires protection policy")
        if has_irq_status and not has_irq_companion:
            raise ValueError(f"Agent1 V3.7 memory_map.{block_name} irq_status requires irq_enable or irq_mask")
    for index, (start, end, name) in enumerate(sorted(ranges)):
        for other_start, other_end, other_name in sorted(ranges)[index + 1:]:
            if start < other_end and other_start < end:
                raise ValueError(f"Agent1 V3.7 memory ranges overlap: {name} and {other_name}")


def _validate_tool_provenance(spec: dict[str, Any]) -> None:
    provenance = spec.get("tool_provenance", {})
    required = {
        "ppa_estimate": "calculate_ppa",
        "bandwidth_estimate": "calculate_bandwidth",
    }
    for field, tool in required.items():
        entry = provenance.get(field)
        if not isinstance(entry, dict):
            raise ValueError(f"Agent1 V3.7 missing provenance for {field}")
        if entry.get("source_tool") != tool:
            raise ValueError(f"Agent1 V3.7 {field} provenance must use {tool}")
        expected_hash = _artifact_hash(spec.get(field, {}))
        if entry.get("artifact_hash") != expected_hash:
            raise ValueError(f"Agent1 V3.7 {field} provenance hash mismatch")


def _provenance(source_tool: str, artifact: Any) -> dict[str, str]:
    return {
        "source_tool": source_tool,
        "artifact_hash": _artifact_hash(artifact),
        "contract": "numeric estimates must come only from deterministic tools",
    }


def _artifact_hash(artifact: Any) -> str:
    payload = json.dumps(artifact, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require_dict(spec: dict[str, Any], key: str) -> None:
    if not isinstance(spec.get(key), dict):
        raise ValueError(f"Agent1 V3.7 schema field {key} must be object")


def _require_list(spec: dict[str, Any], key: str) -> None:
    if not isinstance(spec.get(key), list):
        raise ValueError(f"Agent1 V3.7 schema field {key} must be array")