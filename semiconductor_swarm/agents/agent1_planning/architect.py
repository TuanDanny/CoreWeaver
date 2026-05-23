"""Rule-based Agent 1 prototype with mandatory tool calls.

This module is deterministic for Phase 1. Later orchestration can wrap the
same tools and schema with CrewAI/LangGraph and an LLM backend.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from semiconductor_swarm.contracts.common import APB_SLAVE_INTERFACE
from semiconductor_swarm.agents.agent1_planning.capability_registry import assess_requirement_capability
from semiconductor_swarm.tools.bandwidth_calculator import calculate_bandwidth
from semiconductor_swarm.tools.ppa_calculator import calculate_ppa

SUPPORTED_EXTERNAL_PERIPHERALS = ("uart", "spi", "i2c", "gpio")
UART_REQUIRED_REGISTERS = ("txdata", "rxdata", "status", "ctrl", "baud_div", "irq_status", "irq_enable")
SPI_REQUIRED_REGISTERS = ("ctrl", "status", "txdata", "rxdata", "clk_div", "cs", "irq_status", "irq_enable", "irq_clear")
I2C_REQUIRED_REGISTERS = ("txdata", "rxdata", "status", "ctrl", "target_addr", "timing", "irq_status", "irq_enable")


@dataclass(frozen=True)
class ParsedRequirement:
    raw: str
    application_domain: str
    power_budget_mw: int | None
    target_node: str
    freq_mhz: int
    bus_width_bits: int
    logic_gates: int
    sram_kb: int
    mac_units: int
    cpu_requested: bool
    cpu_width_bits: int
    requested_bus_protocol: str | None
    external_peripherals: list[str]
    architecture_assumptions: list[str]


def parse_requirement(requirement: str) -> ParsedRequirement:
    """Extract architecture knobs without doing PPA or bandwidth math."""
    text = requirement.lower()
    ai_workload = _ai_design_requested(text)
    cpu_requested = _cpu_requested(text)
    cpu_width_bits = _extract_cpu_width_bits(text) or 32
    requested_bus_protocol = _extract_bus_protocol(text)
    external_peripherals = _extract_external_peripherals(text)
    target_node = "12nm" if "12nm" in text else "28nm"
    freq_mhz = _extract_int_before(text, "mhz") or (100 if "camera" in text or ai_workload else 50)
    power_budget_mw = _extract_power_budget_mw(text)
    explicit_bus_width = _extract_bus_width_bits(text)
    if explicit_bus_width:
        bus_width_bits = explicit_bus_width
    elif cpu_requested:
        bus_width_bits = max(32, cpu_width_bits)
    else:
        bus_width_bits = 64 if ai_workload or any(token in text for token in ("camera", "vision", "accelerator")) else 32

    if ai_workload or any(token in text for token in ("camera", "vision")):
        domain = "edge_ai_vision"
        logic_gates, sram_kb, mac_units = 250_000, 256, 64
    elif cpu_requested:
        domain = "embedded_cpu_platform"
        logic_gates, sram_kb, mac_units = 120_000, 64, 0
    elif external_peripherals:
        domain = "peripheral_controller"
        logic_gates, sram_kb, mac_units = 25_000, 16, 0
    else:
        domain = "embedded_control"
        logic_gates, sram_kb, mac_units = 75_000, 64, 0

    parsed = ParsedRequirement(
        raw=requirement,
        application_domain=domain,
        power_budget_mw=power_budget_mw,
        target_node=target_node,
        freq_mhz=freq_mhz,
        bus_width_bits=bus_width_bits,
        logic_gates=logic_gates,
        sram_kb=sram_kb,
        mac_units=mac_units,
        cpu_requested=cpu_requested,
        cpu_width_bits=cpu_width_bits,
        requested_bus_protocol=requested_bus_protocol,
        external_peripherals=external_peripherals,
        architecture_assumptions=[],
    )
    return ParsedRequirement(
        **{**parsed.__dict__, "architecture_assumptions": _architecture_assumptions(parsed)}
    )


def sanitize_project_name(project_name: str | None, fallback: str = "swarm_soc") -> str:
    """Return RTL/file safe project identifier."""
    raw = (project_name or fallback).strip().lower()
    safe = re.sub(r"[^a-z0-9_]", "_", raw)
    safe = re.sub(r"_+", "_", safe).strip("_")
    if not safe:
        safe = fallback
    if not re.match(r"^[a-z_]", safe):
        safe = f"p_{safe}"
    reserved = {"con", "prn", "aux", "nul", "com1", "com2", "com3", "com4", "lpt1", "lpt2", "lpt3"}
    if safe in reserved:
        safe = f"{safe}_project"
    return safe


def derive_project_name(requirement: str, fallback: str = "swarm_soc") -> str:
    """Derive safe project name when user omits explicit name."""
    text = requirement.lower()
    if any(token in text for token in ("temperature", "thermal")):
        return "thermal_sensor"
    if "spi" in text:
        return "spi_ctrl"
    if "i2c" in text:
        return "i2c_ctrl"
    if "uart" in text:
        return "uart_cpu_soc" if _cpu_requested(text) else "uart_ctrl"
    if any(token in text for token in ("camera", "vision")):
        return "vision_soc"
    if _ai_design_requested(text):
        return "ai_chip"
    return sanitize_project_name(fallback)


def requirement_needs_clarification(requirement: str) -> bool:
    """Return True when input has no actionable chip-design intent."""
    return not _has_substantive_chip_intent_text(requirement)

def generate_architecture_spec(requirement: str, project_name: str = "agent1_soc", ai_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate strict JSON-compatible architecture spec for Agent 2."""
    if requirement_needs_clarification(requirement):
        raise ValueError(
            "Agent 1 requirement needs clarification: no CPU, bus, peripheral, accelerator, "
            "or chip-design intent found in Project Requirement."
        )
    parsed = parse_requirement(requirement)
    analysis = ai_analysis if isinstance(ai_analysis, dict) else _deterministic_ai_analysis(parsed, project_name)
    selected = analysis.get("selected_architecture", {}) if isinstance(analysis.get("selected_architecture"), dict) else {}
    primary_protocol = str(selected.get("primary_protocol") or parsed.requested_bus_protocol or "APB").upper()
    peripheral_protocol = str(selected.get("peripheral_protocol") or ("APB" if primary_protocol in {"APB", "AHB"} else primary_protocol)).upper()
    extracted_intents = analysis.get("extracted_intents", {}) if isinstance(analysis.get("extracted_intents"), dict) else {}
    cpu_present = bool(parsed.cpu_requested or selected.get("cpu_requested") or extracted_intents.get("cpu_requested"))
    cpu_width_bits = int(selected.get("cpu_width_bits") or parsed.cpu_width_bits) if cpu_present else None
    master_name = "cpu_core" if cpu_present else "external_apb_host"
    capability = analysis.get("capability_assessment") if isinstance(analysis.get("capability_assessment"), dict) else assess_requirement_capability(analysis)
    ppa = calculate_ppa(parsed.target_node, parsed.logic_gates, parsed.sram_kb, parsed.mac_units, parsed.freq_mhz)
    bandwidth = calculate_bandwidth(parsed.bus_width_bits, parsed.freq_mhz)

    text = requirement.lower()
    wants_aes = "aes" in text or "secret key" in text or "khoa bi mat" in text
    accelerator = "aes128_crypto_core" if wants_aes else ("int8_mac_array" if parsed.mac_units else "none")
    if cpu_present:
        ip_blocks = ["apb_interconnect", "control_regs", "timer", "interrupt_ctrl"]
        if wants_aes:
            ip_blocks.append("aes128_core")
        if parsed.mac_units:
            ip_blocks.extend(["dma_engine", "sram_controller", "mac_array"])
    elif parsed.external_peripherals:
        ip_blocks = ["control_regs", "timer", "interrupt_ctrl"]
    else:
        ip_blocks = []
        if wants_aes:
            ip_blocks.append("aes128_core")
        if parsed.mac_units:
            ip_blocks.append("mac_array")
    for peripheral in parsed.external_peripherals:
        if peripheral not in ip_blocks:
            ip_blocks.append(peripheral)
    if not ip_blocks:
        ip_blocks.append("control_regs")

    memory_map = _memory_map(ip_blocks)
    for peripheral in parsed.external_peripherals:
        if peripheral == "uart":
            memory_map["uart"]["registers"] = _uart_registers()
        if peripheral == "spi":
            memory_map["spi"]["registers"] = _spi_registers()
        if peripheral == "i2c":
            memory_map["i2c"]["registers"] = _i2c_registers()

    cpu_subsystem = {
        "name": "cpu_core" if cpu_present else "external_apb_host",
        "isa": ("rv32imc" if cpu_width_bits == 32 else f"rv{cpu_width_bits}imc") if cpu_present else "none",
        "data_width_bits": cpu_width_bits or parsed.bus_width_bits,
        "address_width_bits": 32,
        "pipeline": "small_in_order_3_stage" if cpu_present else "not_applicable",
        "bus_role": f"{primary_protocol} master" if cpu_present else f"{primary_protocol} verification/host master",
        "data_access": _cpu_data_access(primary_protocol, peripheral_protocol, capability) if cpu_present else f"external memory-mapped {primary_protocol} access to requested IP blocks",
        "reset_vector": "0x00000000" if cpu_present else "not_applicable",
        "synthesized_cpu": cpu_present,
    }

    spec: dict[str, Any] = {
        "project_name": sanitize_project_name(project_name),
        "requirements": {
            "raw": parsed.raw,
            "application_domain": parsed.application_domain,
            "power_budget_mw": parsed.power_budget_mw,
            "cpu_requested": cpu_present,
            "external_peripherals": parsed.external_peripherals,
            "extracted_intents": {
                "cpu_requested": cpu_present,
                "cpu_width_bits": cpu_width_bits,
                "requested_bus_protocol": primary_protocol,
                "external_peripherals": parsed.external_peripherals,
                "frequency_mhz": parsed.freq_mhz,
                "target_node": parsed.target_node,
                "power_budget_mw": parsed.power_budget_mw,
                "unknowns": _intent_unknowns(parsed),
            },
        },
        "target_node": parsed.target_node,
        "isa": cpu_subsystem["isa"],
        "cpu_subsystem": cpu_subsystem,
        "core_config": {"cores": 1 if cpu_present else 0, "pipeline": cpu_subsystem["pipeline"], "frequency_mhz": parsed.freq_mhz},
        "accelerator": {
            "type": accelerator,
            "mac_units": parsed.mac_units,
            "data_type": "crypto" if wants_aes else ("int8" if parsed.mac_units else "none"),
        },
        "ppa_estimate": ppa,
        "bandwidth_estimate": bandwidth,
        "tool_inputs": {
            "calculate_ppa": {
                "tech_node": parsed.target_node,
                "logic_gates": parsed.logic_gates,
                "sram_kb": parsed.sram_kb,
                "mac_units": parsed.mac_units,
                "frequency_mhz": parsed.freq_mhz,
            },
            "calculate_bandwidth": {
                "bus_width_bits": parsed.bus_width_bits,
                "frequency_mhz": parsed.freq_mhz,
            },
        },
        "memory_map": memory_map,
        "bus_topology": {
            "protocol": peripheral_protocol,
            "data_width_bits": parsed.bus_width_bits,
            "address_width_bits": 32,
            "masters": [master_name],
            "slaves": ip_blocks,
        },
        "bus_architecture": {
            "primary_protocol": primary_protocol,
            "peripheral_protocol": peripheral_protocol,
            "data_width_bits": parsed.bus_width_bits,
            "address_width_bits": 32,
            "masters": [master_name],
            "slaves": ip_blocks,
            "bridges": selected.get("bridges") or ([capability["bridge"]] if capability.get("bridge") else []),
            "error_response": _protocol_error_response(primary_protocol),
            "ordering_model": _protocol_ordering_model(primary_protocol, peripheral_protocol),
        },
        "compatibility_strategy": {
            "mode": capability.get("mode", "native_supported"),
            "reason": capability.get("reason", ""),
            "downstream_impacts": capability.get("capability_gaps", []),
        },
        "capability_gaps": capability.get("capability_gaps", []),
        "agent1_ai_requirement_analysis": analysis,
        "ip_blocks": [{"name": block, "interface": "apb_slave"} for block in ip_blocks],
        "external_peripherals": [
            {
                "name": peripheral,
                "interface": "apb_slave",
                "bus": peripheral_protocol,
                "memory_map": memory_map.get(peripheral, {}),
                "interrupt": peripheral in {"uart", "spi", "i2c", "gpio"},
            }
            for peripheral in parsed.external_peripherals
        ],
        "architecture_assumptions": parsed.architecture_assumptions,
        "clock_domains": [{"name": "core_clk", "frequency_mhz": parsed.freq_mhz, "reset": "rst_ni"}],
        "constraints": {
            "power_budget_mw": parsed.power_budget_mw,
            "formal_first": True,
            "hitl_after_debug_iterations": 5,
            "agent2_port_renaming_allowed": False,
        },
        "interfaces": {"apb_slave": APB_SLAVE_INTERFACE},
    }
    firmware_contract = _firmware_contract(parsed, wants_aes)
    if firmware_contract:
        spec["firmware_contract"] = firmware_contract
    if wants_aes:
        spec["memory_map"]["aes128_core"]["registers"] = {
            "key": {"offset": "0x00", "width_bits": 128, "sensitive": True, "reset": "0", "access": "wo"},
            "ctrl": {"offset": "0x10", "width_bits": 32, "reset": "0", "access": "rw"},
            "status": {"offset": "0x14", "width_bits": 32, "reset": "0", "access": "ro"},
            "irq_status": {"offset": "0x18", "width_bits": 32, "reset": "0", "clear": "W1C", "access": "w1c"},
            "irq_enable": {"offset": "0x1C", "width_bits": 32, "reset": "0", "access": "rw"},
        }
    validate_architecture_spec(spec)
    return spec


def spec_to_json(spec: dict[str, Any]) -> str:
    return json.dumps(spec, indent=2, sort_keys=True)


def generate_architecture_plan_markdown(spec: dict[str, Any]) -> str:
    """Generate human-readable architecture plan for first HITL checkpoint."""
    blocks = [block["name"] for block in spec.get("ip_blocks", [])]
    memory_map = spec.get("memory_map", {})
    clock = spec.get("clock_domains", [{}])[0]
    cpu = spec.get("cpu_subsystem", {})
    cpu_width = cpu.get("data_width_bits", 32)
    bus = spec.get("bus_topology", {})
    bus_arch = spec.get("bus_architecture", {})
    primary_protocol = str(bus_arch.get("primary_protocol") or bus.get("protocol", "APB")).upper()
    peripheral_protocol = str(bus_arch.get("peripheral_protocol") or bus.get("protocol", primary_protocol)).upper()
    cpu_present = _cpu_is_generated(spec)
    bridge_names = [bridge.get("name", "bridge") for bridge in bus_arch.get("bridges", []) if isinstance(bridge, dict)]
    bridge_text = ", ".join(bridge_names) if bridge_names else "none"
    assumptions = spec.get("architecture_assumptions", [])
    power_budget = spec.get("constraints", {}).get("power_budget_mw")
    power_text = f"{power_budget} mW" if power_budget is not None else "unspecified"
    cpu_decision = (
        f"{cpu_width}-bit CPU, ISA {cpu.get('isa', spec.get('isa', 'rv32imc'))}, role {cpu.get('bus_role', f'{primary_protocol} master')}"
        if cpu_present
        else "not generated; no CPU intent was cited"
    )
    cpu_impact = (
        "Agent 2 keeps cpu_core role aligned with the selected architecture and does not model it as a peripheral slave."
        if cpu_present
        else "Agent 2 receives APB-attached IP blocks controlled by an external verification/host master."
    )
    lines = [
        "# Architecture Plan",
        "",
        f"Project: {spec.get('project_name', 'unknown')}",
        f"Requirement: {spec.get('requirements', {}).get('raw', '')}",
        f"Target node: {spec.get('target_node', 'unknown')}",
        f"Frequency: {clock.get('frequency_mhz', 'unknown')} MHz",
        f"Power budget: {power_text}",
        "",
        "## Executive Summary",
        "",
        _executive_summary(spec),
        "",
        "## AI Expert Council Summary",
        "",
        *_ai_expert_council_section(spec),
        "",
        "## Selected Architecture",
        "",
        *_selected_architecture_section(spec),
        "",
        "## Rejected Alternatives",
        "",
        *_rejected_alternatives_section(spec),
        "",
        "## Requirement Extraction",
        "",
        "| Requirement item | Extracted decision | Downstream impact |",
        "|---|---|---|",
        f"| CPU | {cpu_decision} | {cpu_impact} |",
        f"| Bus | Primary {primary_protocol}, peripheral side {peripheral_protocol}, bridge {bridge_text}, data width {bus.get('data_width_bits', 'unknown')} bits | Downstream agents receive an explicit compatibility boundary instead of a silent protocol rewrite. |",
        f"| External peripherals | {', '.join(spec.get('requirements', {}).get('external_peripherals', [])) or 'none declared'} | External peripherals appear only when requested and carry register-level contracts. |",
        f"| Frequency | {clock.get('frequency_mhz', 'unknown')} MHz | Timing, PPA, bandwidth, SDC, and DV timeout defaults use this clock. |",
        f"| Power | {power_text} | Numeric PPA is tool-backed; no invented power target when unspecified. |",
        "",
        "## Block Diagram",
        "",
        "```mermaid",
        "flowchart TD",
        f"  REQ[Engineer Requirement] --> A1[Agent 1 Hierarchical Architect: {spec.get('project_name', 'unknown')} ]",
        *((
            f"  CPU[{cpu_width}-bit CPU cpu_core / {cpu.get('isa', spec.get('isa', 'rv32imc'))}] -->|{primary_protocol} master| FABRIC[{primary_protocol} Fabric]",
            "  A1 --> CPU",
        ) if cpu_present else (
            f"  HOST[External {primary_protocol} host or verification master] --> FABRIC[{primary_protocol} Fabric]",
            "  A1 --> HOST",
        )),
        "  A1 --> FABRIC",
        *(["  FABRIC --> BRIDGE[AHB-to-APB Bridge]", "  BRIDGE --> PERIPH[APB Peripheral Subsystem]"] if primary_protocol == "AHB" and peripheral_protocol == "APB" else []),
        *[f"  FABRIC --> { _mermaid_id(block) }[{block}]" for block in blocks],
        "  A1 --> RTL[Agent 2 RTL]",
        "  RTL --> FORMAL[Agent 5 Formal]",
        "  FORMAL --> DV[Agent 3 DV]",
        "  DV --> PHY[Agent 4 Physical]",
        "```",
        "",
        "## Lifecycle State Diagram",
        "",
        "```mermaid",
        "stateDiagram-v2",
        "  [*] --> Planning",
        "  Planning --> HITL_Plan_Review",
        "  HITL_Plan_Review --> Planning: change requested",
        "  HITL_Plan_Review --> RTL_Generation: approved",
        "  RTL_Generation --> Formal_First",
        "  Formal_First --> HITL_Code_Review",
        "  HITL_Code_Review --> DV",
        "  DV --> Physical",
        "  Physical --> Signoff",
        "```",
        "",
        "## CPU Subsystem" if cpu_present else "## Control Master",
        "",
        *((
            f"- {cpu_width}-bit CPU core: `{cpu.get('name', 'cpu_core')}`.",
            f"- ISA: `{cpu.get('isa', spec.get('isa', 'rv32imc'))}`.",
            f"- Pipeline: `{cpu.get('pipeline', spec.get('core_config', {}).get('pipeline', 'small_in_order_3_stage'))}`.",
            f"- Bus role: `{cpu.get('bus_role', f'{primary_protocol} master')}`.",
            f"- Data path: {cpu.get('data_width_bits', 32)} bits; address path: {cpu.get('address_width_bits', 32)} bits.",
            f"- Memory access: {cpu.get('data_access', 'memory-mapped APB peripheral access')}.",
        ) if cpu_present else (
            "- No CPU core is generated because the Project Requirement did not cite CPU/ISA intent.",
            f"- Control access uses `{cpu.get('name', 'external_apb_host')}` as an external {primary_protocol} verification/host master.",
            f"- Data path: {cpu.get('data_width_bits', bus.get('data_width_bits', 32))} bits; address path: {cpu.get('address_width_bits', 32)} bits.",
            f"- Memory access: {cpu.get('data_access', f'external memory-mapped {primary_protocol} access')}.",
        )),
        "",
        f"## {primary_protocol} Bus Architecture",
        "",
        f"- Primary protocol: {primary_protocol}.",
        f"- Peripheral protocol: {peripheral_protocol}.",
        f"- Masters: {', '.join(bus_arch.get('masters', bus.get('masters', []))) or 'none'}.",
        f"- Slaves: {', '.join(bus.get('slaves', [])) or 'none'}.",
        f"- Data width: {bus.get('data_width_bits', 'unknown')} bits.",
        f"- Address width: {bus.get('address_width_bits', 'unknown')} bits.",
        "- Decode granularity: one 4KB window per APB slave.",
        f"- Error response: {bus_arch.get('error_response', 'defined slave error response')}.",
        f"- Ordering model: {bus_arch.get('ordering_model', 'memory-mapped IO ordering')}.",
        "- APB slave pinout remains locked only at the APB peripheral boundary used by current downstream generators.",
        "",
        "## Interfaces",
        "",
        f"Primary bus protocol: {primary_protocol}",
        f"Downstream peripheral protocol: {peripheral_protocol}",
        f"Data width: {bus.get('data_width_bits', 'unknown')} bits",
        f"Address width: {bus.get('address_width_bits', 'unknown')} bits",
        "APB slave pinout is locked only for APB-side generated peripheral blocks.",
        "",
        "## IP Blocks",
        "",
    ]
    lines.extend(f"- {block}" for block in blocks)
    if primary_protocol == "AHB" and peripheral_protocol == "APB":
        lines.extend(["", "## Bridge And Downstream Compatibility", ""])
        strategy = spec.get("compatibility_strategy", {})
        lines.extend([
            "- AHB primary system bus requested by the user.",
            "- Current downstream Agent 2/3/5 collateral is APB-centric.",
            "- Selected practical strategy: AHB-to-APB bridge for the peripheral subsystem.",
            f"- Compatibility mode: {strategy.get('mode', 'bridge_supported')}.",
            f"- Reason: {strategy.get('reason', 'AHB primary bus with APB peripheral bridge keeps current downstream flow usable.')}",
        ])
    lines.extend(["", "## Downstream Capability Assessment", ""])
    lines.extend(_downstream_capability_section(spec))
    if "uart" in memory_map:
        lines.extend(["", *_uart_plan_section(memory_map["uart"])])
    if "spi" in memory_map:
        lines.extend(["", *_spi_plan_section(memory_map["spi"], primary_protocol, peripheral_protocol)])
    if "i2c" in memory_map:
        lines.extend(["", *_i2c_plan_section(memory_map["i2c"])])
    lines.extend(["", "## Memory Map", ""])
    lines.extend(f"- {name}: base {entry['base']}, size {entry['size']}" for name, entry in memory_map.items())
    lines.extend(["", "## Register Map Details", ""])
    lines.extend(_register_map_section(memory_map))
    lines.extend([
        "",
        "## Assumptions And Open Questions",
        "",
    ])
    lines.extend(f"- {item}" for item in assumptions)
    open_questions = ["- Open question: confirm firmware-visible memory map base addresses before software SDK freeze."]
    if "uart" in memory_map:
        open_questions.append("- Open question: confirm interrupt topology and whether UART IRQ is level or pulse at top level.")
    lines.extend(open_questions)
    lines.extend([
        "",
        "## Downstream Acceptance Criteria",
        "",
        f"- Acceptance Criteria: Agent 2 RTL must preserve the selected {primary_protocol} architecture boundary and instantiate requested peripheral register blocks without renaming locked APB-side ports.",
        f"- Acceptance Criteria: Agent 5 formal must prove reset, decode, handshake, and register access properties for the selected {primary_protocol}/{peripheral_protocol} boundary before DV signoff.",
        "- Acceptance Criteria: Agent 3 DV must include cocotb read/write/readback tests for every requested register and interrupt clear/mask behavior when interrupts exist.",
        *_peripheral_acceptance_criteria(memory_map),
        "",
        "## Timeline",
        "",
        "1. Planning: create architecture_plan.md and wait for engineer approval/change.",
        "2. RTL: generate SystemVerilog package/interface/module files.",
        "3. Formal: generate SVA wrappers and SymbiYosys collateral.",
        "4. DV: generate cocotb tests and simulation Makefile.",
        "5. Physical: generate Quartus/QSF/SDC backend package.",
        "",
    ])
    return "\n".join(lines)


def build_plan_quality_report(spec: dict[str, Any], plan_markdown: str) -> dict[str, Any]:
    """Build deterministic evidence that the review plan covers parsed user intent."""
    raw = spec.get("requirements", {}).get("raw", "")
    text = raw.lower()
    required_width = _extract_cpu_width_bits(text)
    requested_bus = _extract_bus_protocol(text)
    cpu_required = bool(spec.get("requirements", {}).get("cpu_requested")) or _cpu_requested(text)
    uart_required = "uart" in text or "uart" in spec.get("requirements", {}).get("external_peripherals", [])
    spi_required = "spi" in text or "spi" in spec.get("requirements", {}).get("external_peripherals", [])
    i2c_required = "i2c" in text or "i2c" in spec.get("requirements", {}).get("external_peripherals", [])
    block_names = {block.get("name") for block in spec.get("ip_blocks", []) if isinstance(block, dict)}
    slaves = set(spec.get("bus_topology", {}).get("slaves", []))
    uart_regs = set(spec.get("memory_map", {}).get("uart", {}).get("registers", {}))
    spi_regs = set(spec.get("memory_map", {}).get("spi", {}).get("registers", {}))
    i2c_regs = set(spec.get("memory_map", {}).get("i2c", {}).get("registers", {}))
    lower_plan = plan_markdown.lower()
    requires_clarification = requirement_needs_clarification(raw)
    cpu = spec.get("cpu_subsystem", {})
    bus_arch = spec.get("bus_architecture", {})
    primary_protocol = str(bus_arch.get("primary_protocol") or spec.get("bus_topology", {}).get("protocol", "APB")).upper()
    peripheral_protocol = str(bus_arch.get("peripheral_protocol") or spec.get("bus_topology", {}).get("protocol", primary_protocol)).upper()
    expected_width = required_width or cpu.get("data_width_bits", 32)
    expected_bus_role = f"{primary_protocol} master"
    has_valid_bridge_text = primary_protocol == peripheral_protocol or f"{primary_protocol.lower()}-to-{peripheral_protocol.lower()}" in lower_plan or f"{primary_protocol.lower()} to {peripheral_protocol.lower()}" in lower_plan
    negative_tokens = []
    if not uart_required and ("uart `baud_div`" in lower_plan or "uart external peripheral" in lower_plan):
        negative_tokens.append("unrequested_uart")
    if not i2c_required and ("i2c `target_addr`" in lower_plan or "i2c external peripheral" in lower_plan):
        negative_tokens.append("unrequested_i2c")
    if expected_width != 32 and "rv32" in lower_plan:
        negative_tokens.append("stale_rv32")
    if requested_bus == "AHB" and "apb fabric" in lower_plan:
        negative_tokens.append("ahb_rewritten_to_apb_fabric")
    checks = {
        "plan_has_executive_summary": "## executive summary" in lower_plan,
        "plan_has_ai_expert_council_summary": "## ai expert council summary" in lower_plan,
        "plan_has_selected_architecture": "## selected architecture" in lower_plan,
        "plan_has_rejected_alternatives": "## rejected alternatives" in lower_plan,
        "plan_has_downstream_capability": "## downstream capability assessment" in lower_plan,
        "plan_has_requirement_extraction": "## requirement extraction" in lower_plan,
        "plan_has_acceptance_criteria": "acceptance criteria" in lower_plan,
        "clarification_gate_satisfied": not requires_clarification,
        "assumptions_recorded": bool(spec.get("architecture_assumptions")) and "assumptions and open questions" in lower_plan,
        "cpu_intent_satisfied": (not cpu_required) or (
            bool(cpu)
            and cpu.get("bus_role") == expected_bus_role
            and (required_width is None or cpu.get("data_width_bits") == required_width)
            and f"{expected_width}-bit cpu" in lower_plan
            and str(cpu.get("isa", "")).lower() in lower_plan
            and expected_bus_role.lower() in lower_plan
        ),
        "bus_intent_satisfied": (requested_bus is None) or (
            primary_protocol == requested_bus
            and requested_bus.lower() in lower_plan
            and has_valid_bridge_text
        ),
        "uart_intent_satisfied": (not uart_required) or (
            "uart" in block_names
            and "uart" in slaves
            and set(UART_REQUIRED_REGISTERS).issubset(uart_regs)
            and "uart" in lower_plan
            and "baud_div" in lower_plan
            and "irq_status" in lower_plan
        ),
        "spi_intent_satisfied": (not spi_required) or (
            "spi" in block_names
            and "spi" in slaves
            and set(SPI_REQUIRED_REGISTERS).issubset(spi_regs)
            and "spi external peripheral" in lower_plan
            and "clk_div" in lower_plan
            and "irq_status" in lower_plan
        ),
        "i2c_intent_satisfied": (not i2c_required) or (
            "i2c" in block_names
            and "i2c" in slaves
            and set(I2C_REQUIRED_REGISTERS).issubset(i2c_regs)
            and "i2c external peripheral" in lower_plan
            and "target_addr" in lower_plan
            and "timing" in lower_plan
            and "irq_status" in lower_plan
        ),
        "negative_token_clean": not negative_tokens,
        "downstream_capability_declared": requested_bus not in {"AHB", "AXI", "WISHBONE"} or bool(spec.get("compatibility_strategy")) and ("compatibility" in lower_plan or "capability" in lower_plan or "bridge" in lower_plan),
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": "agent1_plan_quality/v2",
        "pass": not failures,
        "intent": {
            "cpu_required": cpu_required,
            "cpu_width_bits": required_width or cpu.get("data_width_bits"),
            "uart_required": uart_required,
            "spi_required": spi_required,
            "i2c_required": i2c_required,
            "requested_bus_protocol": requested_bus,
            "external_peripherals": spec.get("requirements", {}).get("external_peripherals", []),
            "requires_clarification": requires_clarification,
            "negative_tokens": negative_tokens,
        },
        "checks": checks,
        "failures": failures,
    }


def build_requirement_consistency_report(spec: dict[str, Any], plan_markdown: str) -> dict[str, Any]:
    quality = build_plan_quality_report(spec, plan_markdown)
    return {
        "schema_version": "agent1.requirement_consistency.v1",
        "pass": quality["pass"],
        "raw_requirement_extracted": quality["checks"].get("cpu_intent_satisfied", False) and quality["checks"].get("bus_intent_satisfied", False),
        "extraction_to_spec_consistent": quality["checks"].get("bus_intent_satisfied", False) and quality["checks"].get("spi_intent_satisfied", True),
        "spec_to_plan_consistent": quality["checks"].get("cpu_intent_satisfied", False) and quality["checks"].get("bus_intent_satisfied", False),
        "negative_token_clean": quality["checks"].get("negative_token_clean", False),
        "downstream_capability_declared": quality["checks"].get("downstream_capability_declared", False),
        "quality_report": quality,
        "failures": quality["failures"],
    }


def validate_plan_quality(spec: dict[str, Any], plan_markdown: str) -> dict[str, Any]:
    report = build_plan_quality_report(spec, plan_markdown)
    if not report["pass"]:
        raise ValueError(f"Agent 1 plan quality failed: {report['failures']}")
    return report


def validate_architecture_spec(spec: dict[str, Any]) -> None:
    required = {
        "project_name", "target_node", "isa", "core_config", "accelerator",
        "ppa_estimate", "bandwidth_estimate", "memory_map", "bus_topology",
        "ip_blocks", "clock_domains", "constraints", "interfaces",
    }
    missing = required - set(spec)
    if missing:
        raise ValueError(f"Missing spec keys: {sorted(missing)}")
    if spec["interfaces"].get("apb_slave") != APB_SLAVE_INTERFACE:
        raise ValueError("APB slave pinout was modified")


def _extract_int_before(text: str, unit: str) -> int | None:
    match = re.search(rf"(\d+)\s*{re.escape(unit)}", text)
    return int(match.group(1)) if match else None


def _extract_power_budget_mw(text: str) -> int | None:
    watt_match = re.search(r"<\s*(\d+(?:\.\d+)?)\s*w", text)
    if watt_match:
        return int(float(watt_match.group(1)) * 1000)
    mw_match = re.search(r"<\s*(\d+)\s*mw", text)
    return int(mw_match.group(1)) if mw_match else None


def _extract_bus_protocol(text: str) -> str | None:
    for bus in ("ahb", "apb", "axi", "wishbone"):
        if re.search(rf"\b{bus}\b", text):
            return bus.upper()
    return None


def _extract_bus_width_bits(text: str) -> int | None:
    match = re.search(r"(\d+)\s*[- ]?bit", text)
    return int(match.group(1)) if match else None


def _extract_cpu_width_bits(text: str) -> int | None:
    if re.search(r"\brv32\b|\brv32i\b|\brv32imc\b", text):
        return 32
    if re.search(r"\brv64\b|\brv64i\b|\brv64gc\b", text):
        return 64
    match = re.search(r"(\d+)\s*[- ]?bit\s+(?:cpu|processor|core)", text)
    if match:
        return int(match.group(1))
    match = re.search(r"(?:cpu|processor|core).{0,24}?(\d+)\s*[- ]?bit", text)
    return int(match.group(1)) if match else None


def _cpu_requested(text: str) -> bool:
    return bool(re.search(r"\b(cpu|processor|risc[- ]?v|riscv|rv32|rv64|multi[- ]?core|multicore)\b", text))


def _extract_external_peripherals(text: str) -> list[str]:
    return [peripheral for peripheral in SUPPORTED_EXTERNAL_PERIPHERALS if re.search(rf"\b{peripheral}\b", text)]


def _has_substantive_chip_intent_text(requirement: str) -> bool:
    text = requirement.lower().strip()
    if not text:
        return False
    if re.fullmatch(r"(hi|hello|hey|test|ok|okay|alo|chao|xin chao|hello world)[\s!.,?_-]*", text):
        return False
    if _cpu_requested(text) or _extract_bus_protocol(text) or _extract_external_peripherals(text):
        return True
    technical_tokens = (
        "chip", "soc", "asic", "fpga", "rtl", "module", "ip", "peripheral",
        "controller", "sensor", "monitor", "counter", "timer", "aes", "crypto",
        "camera", "vision", "accelerator", "mac", "sram", "register",
        "interrupt", "gpio", "pwm", "dma", "uart", "spi", "i2c",
    )
    if any(re.search(rf"\b{re.escape(token)}\b", text) for token in technical_tokens):
        return True
    if _ai_design_requested(text):
        return True
    return bool(_extract_cpu_width_bits(text) and re.search(r"\b(bit|architecture|design|generate|create)\b", text))

def _ai_design_requested(text: str) -> bool:
    """Return True for technical AI intent, not Vietnamese identity word 'ai'."""
    if not re.search(r"\b(ai|tri tue nhan tao|trí tuệ nhân tạo)\b", text):
        return False
    if re.search(r"\b(ban|bạn)\s+(la|là)\s+ai\b", text):
        return False
    return bool(re.search(r"\b(chip|soc|asic|accelerator|camera|vision|npu|mac|inference|ml|cnn|ai\s+camera|ai\s+chip)\b", text))

def _architecture_assumptions(parsed: ParsedRequirement) -> list[str]:
    text = parsed.raw.lower()
    assumptions = []
    if "mhz" not in text:
        assumptions.append(f"No explicit frequency provided; Agent 1 assumes {parsed.freq_mhz} MHz core_clk.")
    if "12nm" not in text and "28nm" not in text:
        assumptions.append("No process node provided; Agent 1 assumes 28nm for deterministic PPA estimation.")
    if parsed.power_budget_mw is None:
        assumptions.append("No power budget provided; Agent 1 records power as unspecified instead of inventing a limit.")
    if parsed.cpu_requested and "rv32" not in text and "rv64" not in text and "risc-v" not in text and "riscv" not in text:
        assumptions.append(f"CPU ISA not specified; Agent 1 assumes rv{parsed.cpu_width_bits}imc for the {parsed.cpu_width_bits}-bit CPU subsystem.")
    if parsed.requested_bus_protocol == "AHB":
        assumptions.append("AHB requested as primary system bus; current downstream APB generators require an explicit AHB-to-APB peripheral bridge unless pure AHB is approved as a capability gap.")
    if "uart" in parsed.external_peripherals and "baud" not in text:
        assumptions.append("UART baud rate not provided; Agent 1 exposes programmable baud_div register.")
    if "i2c" in parsed.external_peripherals and "khz" not in text and "i2c" in text:
        assumptions.append("I2C bus speed not provided; Agent 1 exposes programmable timing register.")
    return assumptions or ["All critical architecture assumptions were specified in the user requirement."]


def _intent_unknowns(parsed: ParsedRequirement) -> list[str]:
    text = parsed.raw.lower()
    unknowns = []
    if parsed.requested_bus_protocol is None:
        unknowns.append("bus_protocol")
    if parsed.cpu_requested and _extract_cpu_width_bits(text) is None:
        unknowns.append("cpu_width_bits")
    if not parsed.external_peripherals:
        unknowns.append("external_peripherals")
    if "mhz" not in text:
        unknowns.append("frequency_mhz")
    if "12nm" not in text and "28nm" not in text:
        unknowns.append("target_node")
    if parsed.power_budget_mw is None:
        unknowns.append("power_budget_mw")
    return unknowns


def _deterministic_ai_analysis(parsed: ParsedRequirement, project_name: str) -> dict[str, Any]:
    primary = parsed.requested_bus_protocol or "APB"
    peripheral = "APB" if primary in {"APB", "AHB"} else primary
    analysis: dict[str, Any] = {
        "schema_version": "agent1.ai_requirement_analysis.v1",
        "project_name": sanitize_project_name(project_name),
        "raw_requirement": parsed.raw,
        "extracted_intents": {
            "cpu_requested": parsed.cpu_requested,
            "cpu_width_bits": parsed.cpu_width_bits,
            "requested_bus_protocol": primary,
            "external_peripherals": parsed.external_peripherals,
            "frequency_mhz": parsed.freq_mhz,
            "target_node": parsed.target_node,
            "power_budget_mw": parsed.power_budget_mw,
            "unknowns": _intent_unknowns(parsed),
        },
        "expert_outputs": [],
        "selected_architecture": {
            "project_name": sanitize_project_name(project_name),
            "cpu_width_bits": parsed.cpu_width_bits,
            "isa": "rv32imc" if parsed.cpu_width_bits == 32 else f"rv{parsed.cpu_width_bits}imc",
            "primary_protocol": primary,
            "peripheral_protocol": peripheral,
            "bridges": [{"name": "ahb_to_apb_bridge", "from_protocol": "AHB", "to_protocol": "APB", "boundary": "peripheral_subsystem"}] if primary == "AHB" else [],
            "external_peripherals": parsed.external_peripherals,
        },
        "rejected_alternatives": [],
        "assumptions": _architecture_assumptions(parsed),
        "open_questions": [],
        "citations": [],
        "confidence": 0.8,
    }
    analysis["capability_assessment"] = assess_requirement_capability(analysis)
    return analysis


def _cpu_data_access(primary_protocol: str, peripheral_protocol: str, capability: dict[str, Any]) -> str:
    if capability.get("mode") == "bridge_supported" and primary_protocol != peripheral_protocol:
        return f"memory-mapped {primary_protocol} system access through {primary_protocol}-to-{peripheral_protocol} bridge for peripheral registers"
    return f"memory-mapped {primary_protocol} peripheral access"


def _protocol_error_response(primary_protocol: str) -> str:
    if primary_protocol == "AHB":
        return "AHB ERROR response for illegal address or bridge fault"
    if primary_protocol == "AXI":
        return "AXI SLVERR/DECERR for illegal address or slave fault"
    return "APB PSLVERR for illegal address or slave fault"


def _protocol_ordering_model(primary_protocol: str, peripheral_protocol: str) -> str:
    if primary_protocol == "AHB" and peripheral_protocol == "APB":
        return "AHB strongly ordered MMIO at bridge boundary; APB peripheral side has setup/access ordering"
    return f"{primary_protocol} memory-mapped IO ordering"


def _memory_map(ip_blocks: list[str]) -> dict[str, dict[str, Any]]:
    return {
        block: {"base": f"0x{0x40000000 + index * 0x1000:08X}", "size": "0x1000"}
        for index, block in enumerate(ip_blocks)
    }


def _uart_registers() -> dict[str, dict[str, Any]]:
    return {
        "txdata": {"offset": "0x00", "width_bits": 32, "reset": "0", "access": "wo", "description": "Write transmit byte/data word."},
        "rxdata": {"offset": "0x04", "width_bits": 32, "reset": "0", "access": "ro", "description": "Read received byte/data word."},
        "status": {"offset": "0x08", "width_bits": 32, "reset": "0", "access": "ro", "fields": ["tx_ready", "rx_valid", "rx_overrun", "framing_error"]},
        "ctrl": {"offset": "0x0C", "width_bits": 32, "reset": "0", "access": "rw", "fields": ["tx_enable", "rx_enable", "parity_enable", "irq_enable_global"]},
        "baud_div": {"offset": "0x10", "width_bits": 32, "reset": "0", "access": "rw", "description": "Clock divider for UART baud generation."},
        "irq_status": {"offset": "0x14", "width_bits": 32, "reset": "0", "access": "w1c", "clear": "W1C", "fields": ["rx_irq", "tx_irq", "error_irq"]},
        "irq_enable": {"offset": "0x18", "width_bits": 32, "reset": "0", "access": "rw", "fields": ["rx_irq_en", "tx_irq_en", "error_irq_en"]},
    }


def _spi_registers() -> dict[str, dict[str, Any]]:
    return {
        "ctrl": {"offset": "0x00", "width_bits": 32, "reset": "0", "access": "rw", "fields": ["enable", "master", "cpol", "cpha", "start"]},
        "status": {"offset": "0x04", "width_bits": 32, "reset": "0", "access": "ro", "fields": ["busy", "tx_ready", "rx_valid", "error"]},
        "txdata": {"offset": "0x08", "width_bits": 32, "reset": "0", "access": "wo", "description": "Write SPI transmit data."},
        "rxdata": {"offset": "0x0C", "width_bits": 32, "reset": "0", "access": "ro", "description": "Read SPI received data."},
        "clk_div": {"offset": "0x10", "width_bits": 32, "reset": "0", "access": "rw", "description": "SPI serial clock divider."},
        "cs": {"offset": "0x14", "width_bits": 32, "reset": "0", "access": "rw", "fields": ["chip_select", "cs_polarity"]},
        "irq_status": {"offset": "0x18", "width_bits": 32, "reset": "0", "access": "w1c", "clear": "W1C", "fields": ["done_irq", "rx_irq", "error_irq"]},
        "irq_enable": {"offset": "0x1C", "width_bits": 32, "reset": "0", "access": "rw", "fields": ["done_irq_en", "rx_irq_en", "error_irq_en"]},
        "irq_clear": {"offset": "0x20", "width_bits": 32, "reset": "0", "access": "wo", "description": "Optional explicit interrupt clear alias."},
    }


def _i2c_registers() -> dict[str, dict[str, Any]]:
    return {
        "txdata": {"offset": "0x00", "width_bits": 32, "reset": "0", "access": "wo", "description": "Write transmit byte/data word."},
        "rxdata": {"offset": "0x04", "width_bits": 32, "reset": "0", "access": "ro", "description": "Read received byte/data word."},
        "status": {"offset": "0x08", "width_bits": 32, "reset": "0", "access": "ro", "fields": ["busy", "rx_valid", "ack_error", "arbitration_lost"]},
        "ctrl": {"offset": "0x0C", "width_bits": 32, "reset": "0", "access": "rw", "fields": ["enable", "start", "stop", "read", "write"]},
        "target_addr": {"offset": "0x10", "width_bits": 32, "reset": "0", "access": "rw", "fields": ["addr_7bit", "ten_bit_mode"]},
        "timing": {"offset": "0x14", "width_bits": 32, "reset": "0", "access": "rw", "description": "Clock divider and setup/hold timing control."},
        "irq_status": {"offset": "0x18", "width_bits": 32, "reset": "0", "access": "w1c", "clear": "W1C", "fields": ["done_irq", "rx_irq", "error_irq"]},
        "irq_enable": {"offset": "0x1C", "width_bits": 32, "reset": "0", "access": "rw", "fields": ["done_irq_en", "rx_irq_en", "error_irq_en"]},
    }


def _firmware_contract(parsed: ParsedRequirement, wants_aes: bool) -> dict[str, Any] | None:
    hal_modules = []
    interrupt_flow = []
    semantics: dict[str, Any] = {}
    if wants_aes:
        hal_modules.append("aes128_hal")
        interrupt_flow.extend(["irq_status.done W1C", "irq_status.error W1C"])
        semantics.update({
            "aes128_core.key": {"width_bits": 128, "reset": "0", "access": "wo", "clear": "software_zeroize"},
            "aes128_core.status": {"width_bits": 32, "reset": "0", "access": "ro"},
            "aes128_core.ctrl.start": {"type": "write_one_pulse"},
            "aes128_core.irq_status": {"type": "W1C"},
        })
    if "uart" in parsed.external_peripherals:
        hal_modules.append("uart_hal")
        interrupt_flow.extend(["uart.irq_status.rx_irq W1C", "uart.irq_status.tx_irq W1C", "uart.irq_status.error_irq W1C"])
        semantics.update({
            "uart.txdata": {"access": "wo", "producer": "firmware"},
            "uart.rxdata": {"access": "ro", "consumer": "firmware"},
            "uart.status": {"access": "ro", "fields": ["tx_ready", "rx_valid", "rx_overrun", "framing_error"]},
            "uart.ctrl": {"access": "rw"},
            "uart.baud_div": {"access": "rw", "purpose": "baud rate divider"},
            "uart.irq_status": {"access": "w1c", "clear": "W1C"},
            "uart.irq_enable": {"access": "rw"},
        })
    if "spi" in parsed.external_peripherals:
        hal_modules.append("spi_hal")
        interrupt_flow.extend(["spi.irq_status.done_irq W1C", "spi.irq_status.rx_irq W1C", "spi.irq_status.error_irq W1C"])
        semantics.update({
            "spi.ctrl": {"access": "rw", "purpose": "SPI enable/mode/start control"},
            "spi.status": {"access": "ro", "fields": ["busy", "tx_ready", "rx_valid", "error"]},
            "spi.txdata": {"access": "wo", "producer": "firmware"},
            "spi.rxdata": {"access": "ro", "consumer": "firmware"},
            "spi.clk_div": {"access": "rw", "purpose": "SPI clock divider"},
            "spi.cs": {"access": "rw", "purpose": "chip-select control"},
            "spi.irq_status": {"access": "w1c", "clear": "W1C"},
            "spi.irq_enable": {"access": "rw"},
        })
    if "i2c" in parsed.external_peripherals:
        hal_modules.append("i2c_hal")
        interrupt_flow.extend(["i2c.irq_status.done_irq W1C", "i2c.irq_status.rx_irq W1C", "i2c.irq_status.error_irq W1C"])
        semantics.update({
            "i2c.txdata": {"access": "wo", "producer": "firmware"},
            "i2c.rxdata": {"access": "ro", "consumer": "firmware"},
            "i2c.status": {"access": "ro", "fields": ["busy", "rx_valid", "ack_error", "arbitration_lost"]},
            "i2c.ctrl": {"access": "rw", "purpose": "start/stop/read/write command control"},
            "i2c.target_addr": {"access": "rw", "purpose": "7-bit target address"},
            "i2c.timing": {"access": "rw", "purpose": "SCL timing divider"},
            "i2c.irq_status": {"access": "w1c", "clear": "W1C"},
            "i2c.irq_enable": {"access": "rw"},
        })
    if not hal_modules:
        return None
    return {
        "hal_modules": hal_modules,
        "interrupt_flow": interrupt_flow,
        "register_access_semantics": semantics,
    }


def _cpu_is_generated(spec: dict[str, Any]) -> bool:
    cpu = spec.get("cpu_subsystem", {}) if isinstance(spec.get("cpu_subsystem"), dict) else {}
    if "synthesized_cpu" in cpu:
        return bool(cpu.get("synthesized_cpu"))
    return bool(spec.get("requirements", {}).get("cpu_requested"))

def _executive_summary(spec: dict[str, Any]) -> str:
    cpu = spec.get("cpu_subsystem", {})
    bus = spec.get("bus_topology", {})
    bus_arch = spec.get("bus_architecture", {})
    primary = str(bus_arch.get("primary_protocol") or bus.get("protocol", "APB")).upper()
    peripheral = str(bus_arch.get("peripheral_protocol") or bus.get("protocol", primary)).upper()
    peripherals = spec.get("requirements", {}).get("external_peripherals", [])
    blocks = [block.get("name", "") for block in spec.get("ip_blocks", []) if isinstance(block, dict)]
    peripheral_text = ", ".join(peripherals) if peripherals else (", ".join(blocks) if blocks else "the requested IP blocks")
    bridge = ""
    if primary != peripheral:
        bridge = f" The selected compatibility strategy uses a {primary}-to-{peripheral} bridge for the peripheral subsystem."
    if not _cpu_is_generated(spec):
        return (
            f"This plan defines {primary}-attached IP controlled by an external verification/host master. "
            "No CPU core or ISA is generated because the Project Requirement did not cite CPU intent. "
            f"The generated IP set is {peripheral_text}; each block is locked into the memory map before RTL generation "
            f"so Agent 2, Agent 3, Agent 4, and Agent 5 share one contract.{bridge}"
        )
    return (
        f"This plan defines a {cpu.get('data_width_bits', 32)}-bit CPU subsystem using "
        f"{cpu.get('isa', spec.get('isa', 'rv32imc'))} as the architectural master on a "
        f"{bus.get('data_width_bits', 32)}-bit {primary} primary fabric. "
        f"The external peripheral set is {peripheral_text}; each peripheral is locked into "
        f"the memory map before RTL generation so Agent 2, Agent 3, Agent 4, and Agent 5 share one contract.{bridge}"
    )


def _ai_expert_council_section(spec: dict[str, Any]) -> list[str]:
    analysis = spec.get("agent1_ai_requirement_analysis", {}) if isinstance(spec.get("agent1_ai_requirement_analysis"), dict) else {}
    experts = analysis.get("expert_outputs", []) if isinstance(analysis.get("expert_outputs"), list) else []
    lines = [
        f"- Expert calls: {len(experts)}.",
        f"- Analysis schema: {analysis.get('schema_version', 'agent1.ai_requirement_analysis.v1')}.",
        f"- Confidence: {analysis.get('confidence', 'unknown')}.",
    ]
    for item in experts[:8]:
        if isinstance(item, dict):
            output = item.get("output", {}) if isinstance(item.get("output"), dict) else {}
            lines.append(f"- {item.get('title', item.get('expert_id', 'expert'))}: {output.get('summary', 'completed')}")
    if not experts:
        lines.append("- Deterministic fallback analysis used when no live expert trace is attached.")
    return lines


def _selected_architecture_section(spec: dict[str, Any]) -> list[str]:
    bus_arch = spec.get("bus_architecture", {})
    cpu = spec.get("cpu_subsystem", {})
    strategy = spec.get("compatibility_strategy", {})
    cpu_lines = (
        [
            f"- CPU: {cpu.get('data_width_bits', 'unknown')}-bit `{cpu.get('name', 'cpu_core')}` using `{cpu.get('isa', spec.get('isa', 'unknown'))}`.",
            f"- CPU bus role: `{cpu.get('bus_role', 'unknown')}`.",
        ]
        if _cpu_is_generated(spec)
        else [
            "- CPU: not generated because no CPU/ISA intent was cited.",
            f"- Control master: `{cpu.get('name', 'external_apb_host')}` ({cpu.get('bus_role', 'external host master')}).",
        ]
    )
    return [
        *cpu_lines,
        f"- Primary protocol: {bus_arch.get('primary_protocol', 'unknown')}.",
        f"- Peripheral protocol: {bus_arch.get('peripheral_protocol', 'unknown')}.",
        f"- Compatibility mode: {strategy.get('mode', 'unknown')}.",
        f"- External peripherals: {', '.join(spec.get('requirements', {}).get('external_peripherals', [])) or 'none declared'}.",
    ]


def _rejected_alternatives_section(spec: dict[str, Any]) -> list[str]:
    analysis = spec.get("agent1_ai_requirement_analysis", {}) if isinstance(spec.get("agent1_ai_requirement_analysis"), dict) else {}
    rejected = analysis.get("rejected_alternatives", []) if isinstance(analysis.get("rejected_alternatives"), list) else []
    if not rejected:
        return ["- No conflicting architecture alternative was rejected for this requirement."]
    lines = []
    for item in rejected:
        if isinstance(item, dict):
            lines.append(f"- {item.get('name', 'alternative')}: {item.get('reason', 'rejected by principal architect synthesis')}")
    return lines


def _downstream_capability_section(spec: dict[str, Any]) -> list[str]:
    strategy = spec.get("compatibility_strategy", {})
    gaps = spec.get("capability_gaps", [])
    lines = [
        f"- Mode: {strategy.get('mode', 'unknown')}.",
        f"- Reason: {strategy.get('reason', 'not recorded')}",
    ]
    if gaps:
        for gap in gaps:
            if isinstance(gap, dict):
                lines.append(f"- Gap: {gap.get('agent', 'agent')} {gap.get('capability', 'capability')} is {gap.get('status', 'unknown')}.")
    else:
        lines.append("- No blocking downstream capability gap declared.")
    return lines


def _uart_plan_section(uart_map: dict[str, Any]) -> list[str]:
    return [
        "## UART External Peripheral",
        "",
        f"- Bus attachment: UART is an APB slave at base {uart_map.get('base', 'unknown')}.",
        "- Function: memory-mapped serial TX/RX peripheral controlled through the selected bus master.",
        "- Interrupts: `irq_status` is W1C and paired with `irq_enable` for maskable UART events.",
        "- Baud control: `baud_div` is firmware-programmable because the user did not provide a fixed baud rate.",
        "- DV focus: APB read/write/readback, TX write path, RX read path, interrupt clear/mask behavior, and reset values.",
    ]


def _spi_plan_section(spi_map: dict[str, Any], primary_protocol: str, peripheral_protocol: str) -> list[str]:
    attach = f"{peripheral_protocol} slave behind the {primary_protocol}-to-{peripheral_protocol} bridge" if primary_protocol != peripheral_protocol else f"{primary_protocol} memory-mapped slave"
    return [
        "## SPI External Peripheral",
        "",
        f"- Bus attachment: SPI is an {attach} at base {spi_map.get('base', 'unknown')}.",
        "- Function: firmware-controlled SPI master peripheral for external device communication.",
        "- Mode control: `ctrl` contains enable/master/CPOL/CPHA/start intent.",
        "- Data path: `txdata` is firmware write path and `rxdata` is firmware read path.",
        "- Timing/control: `clk_div` programs SPI serial clock and `cs` controls chip-select behavior.",
        "- Interrupts: `irq_status` is W1C and paired with `irq_enable` for done/RX/error events.",
        "- DV focus: register reset, mode programming, TX/RX access, chip-select control, interrupt clear/mask, and illegal address response.",
    ]


def _i2c_plan_section(i2c_map: dict[str, Any]) -> list[str]:
    return [
        "## I2C External Peripheral",
        "",
        f"- Bus attachment: I2C is an APB slave at base {i2c_map.get('base', 'unknown')}.",
        "- Function: memory-mapped I2C controller for CPU-driven external serial transactions.",
        "- Control: `ctrl` carries enable/start/stop/read/write command bits.",
        "- Addressing: `target_addr` stores the 7-bit target address and future ten-bit-mode hook.",
        "- Timing: `timing` is firmware-programmable because the user did not provide a fixed I2C bus speed.",
        "- Interrupts: `irq_status` is W1C and paired with `irq_enable` for done/RX/error events.",
        "- DV focus: APB register read/write/readback, command bit behavior, interrupt clear/mask behavior, and reset values.",
    ]


def _peripheral_acceptance_criteria(memory_map: dict[str, Any]) -> list[str]:
    criteria: list[str] = []
    if "uart" in memory_map:
        criteria.append("- Acceptance Criteria: UART `baud_div`, `irq_status`, and `irq_enable` registers must appear consistently in JSON, SystemRDL, firmware header, and DV register model.")
    if "spi" in memory_map:
        criteria.append("- Acceptance Criteria: SPI `ctrl`, `status`, `txdata`, `rxdata`, `clk_div`, `cs`, `irq_status`, and `irq_enable` registers must appear consistently in JSON, SystemRDL, firmware header, and DV register model.")
    if "i2c" in memory_map:
        criteria.append("- Acceptance Criteria: I2C `target_addr`, `timing`, `irq_status`, and `irq_enable` registers must appear consistently in JSON, SystemRDL, firmware header, and DV register model.")
    return criteria


def _register_map_section(memory_map: dict[str, Any]) -> list[str]:
    lines = ["| Block | Base | Register | Offset | Access | Width | Reset |", "|---|---:|---|---:|---|---:|---:|"]
    for block, entry in memory_map.items():
        regs = entry.get("registers", {})
        if not regs:
            lines.append(f"| {block} | {entry.get('base', '')} | window reserved | 0x00 | n/a | n/a | n/a |")
            continue
        for reg, meta in regs.items():
            lines.append(
                f"| {block} | {entry.get('base', '')} | {reg} | {meta.get('offset', '0x00')} | "
                f"{meta.get('access', 'rw')} | {meta.get('width_bits', 32)} | {meta.get('reset', '0')} |"
            )
    return lines


def _mermaid_id(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name).upper()
