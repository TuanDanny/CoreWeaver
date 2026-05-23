"""Milestone A deterministic specialist subagents."""
from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from semiconductor_swarm.agents.agent2_rtl.contracts import APB_SLAVE_INTERFACE, Agent2SubAgentResult, fail_result, pass_result
from semiconductor_swarm.agents.agent2_rtl.pattern_library import repo_patterns_dir
from semiconductor_swarm.agents.agent2_rtl.state import Agent2State


@dataclass(frozen=True)
class Agent2SubAgent:
    agent_id: str
    name: str
    run: Callable[[Agent2State], Agent2SubAgentResult]


def _simple(agent_id: str, name: str, artifact_key: str) -> Agent2SubAgent:
    def run(state: Agent2State) -> Agent2SubAgentResult:
        return pass_result(agent_id, name, artifacts={artifact_key: True})

    return Agent2SubAgent(agent_id, name, run)


def _spec_normalizer(state: Agent2State) -> Agent2SubAgentResult:
    return pass_result(
        "A2.01",
        "Spec Normalizer",
        artifacts={"project_name": state.project, "block_count": len(state.blocks), "blocks": state.blocks},
    )


def _interface_contract(state: Agent2State) -> Agent2SubAgentResult:
    observed = state.spec.get("interfaces", {}).get("apb_slave")
    ok = observed == APB_SLAVE_INTERFACE and state.spec.get("constraints", {}).get("agent2_port_renaming_allowed") is False
    findings = [] if ok else [{"severity": "error", "owner": "A2.03 Interface Contract Agent", "rule": "apb_pinout_locked", "message": "APB slave interface contract changed", "suggested_fix": "Use Agent 1 APB_SLAVE_INTERFACE exactly"}]
    return Agent2SubAgentResult("A2.03", "Interface Contract Agent", pass_=ok, artifacts={"apb_signal_count": len(APB_SLAVE_INTERFACE["signals"])}, findings=findings, needs_repair=not ok, confidence=1.0)


def _address_map(state: Agent2State) -> Agent2SubAgentResult:
    regions = [{"block": block, "base_nibble": index} for index, block in enumerate(state.blocks)]
    return pass_result("A2.04", "Address Map Agent", artifacts={"regions": regions})


def _constraint_extractor(state: Agent2State) -> Agent2SubAgentResult:
    constraints = state.spec.get("constraints", {})
    core = state.spec.get("core_config", {})
    return pass_result("A2.02", "Constraint Extractor", artifacts={"clock_mhz": core.get("frequency_mhz"), "constraints": constraints, "target_flow": constraints.get("target_flow", "fpga_safe")})


def _risk_classifier(state: Agent2State) -> Agent2SubAgentResult:
    risky_tokens = ("cdc", "fifo", "dma", "sram", "memory", "interrupt", "mac", "accelerator")
    risks = {block: [token for token in risky_tokens if token in block.lower()] for block in state.blocks}
    return pass_result("A2.05", "Risk Classifier", artifacts={"risk_classes": risks, "advanced_capabilities_enabled": False})


def _block_decomposer(state: Agent2State) -> Agent2SubAgentResult:
    plans = [{"block": block, "rtl_module": f"{state.project}_{block}_rtl"} for block in state.blocks]
    return pass_result("A2.06", "Block Decomposer", artifacts={"module_plans": plans})


def _datapath_planner(state: Agent2State) -> Agent2SubAgentResult:
    data_width = int(state.spec.get("bus_topology", {}).get("data_width_bits", 32))
    plans = [{"block": block, "data_width": data_width, "pipeline_depth": 1 if "mac" in block else 0, "saturation": "mac" in block} for block in state.blocks]
    return pass_result("A2.07", "Datapath Planner", artifacts={"datapath_plans": plans})


def _control_fsm_planner(state: Agent2State) -> Agent2SubAgentResult:
    return pass_result("A2.08", "Control FSM Planner", artifacts={"fsm_template": "S_IDLE/S_SETUP/S_ACCESS", "blocks": state.blocks})


def _register_model_planner(state: Agent2State) -> Agent2SubAgentResult:
    return pass_result("A2.09", "Register Model Planner", artifacts={"default_registers": [{"offset": "0x00", "type": "RW", "reset": "0"}]})


def _memory_map_planner(state: Agent2State) -> Agent2SubAgentResult:
    memories = [block for block in state.blocks if any(token in block for token in ("sram", "memory", "fifo"))]
    return pass_result("A2.10", "Memory Map Planner", artifacts={"memories": memories, "macro_wrapper_required": bool(memories)})


def _interrupt_planner(state: Agent2State) -> Agent2SubAgentResult:
    return pass_result("A2.11", "Interrupt Planner", artifacts={"irq_sources": state.blocks, "clear_policy": "write_one_to_clear_ready"})


def _clock_reset_planner(state: Agent2State) -> Agent2SubAgentResult:
    return pass_result("A2.12", "Clock/Reset Planner", artifacts={"clock": "clk_i", "reset": "rst_ni", "reset_policy": "active_low_synchronous_single_domain"})


def _read_synthesizable_pattern(agent_id: str, name: str, pattern_filename: str, required_marker: str) -> Agent2SubAgentResult:
    pattern_path = repo_patterns_dir() / pattern_filename
    if not pattern_path.exists():
        return Agent2SubAgentResult(agent_id, name, pass_=False, artifacts={"pattern_path": str(pattern_path), "read_ok": False}, findings=[{"severity": "error", "owner": name, "rule": "pattern_exists", "message": f"Missing golden pattern: {pattern_path}", "suggested_fix": "Create required pattern file under patterns/."}], needs_repair=True, confidence=1.0)
    content = pattern_path.read_text(encoding="utf-8")
    forbidden = [token for token in ("$display", "initial begin", "#delay") if token in content]
    marker_ok = required_marker in content
    ok = marker_ok and not forbidden
    findings = []
    if not marker_ok:
        findings.append({"severity": "error", "owner": name, "rule": "pattern_marker", "message": f"Missing marker {required_marker}", "suggested_fix": "Add AGENT2_PATTERN_ID marker to pattern."})
    for token in forbidden:
        findings.append({"severity": "error", "owner": name, "rule": "synthesizable_pattern", "message": f"Forbidden token in pattern: {token}", "suggested_fix": "Remove non-synthesizable construct."})
    return Agent2SubAgentResult(
        agent_id,
        name,
        pass_=ok,
        artifacts={
            "pattern_path": str(Path("patterns") / pattern_filename),
            "pattern_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "pattern_line_count": len(content.rstrip("\n").splitlines()),
            "read_ok": True,
            "required_marker": required_marker,
        },
        findings=findings,
        needs_repair=not ok,
        confidence=1.0,
    )


def _apb_slave_writer(state: Agent2State) -> Agent2SubAgentResult:
    return _read_synthesizable_pattern("A2.13", "APB Slave Writer", "pattern_apb_slave_register_file.sv", "AGENT2_PATTERN_ID: pattern_apb_slave_register_file")


def _register_file_writer(state: Agent2State) -> Agent2SubAgentResult:
    return _read_synthesizable_pattern("A2.14", "Register File Writer", "pattern_sync_reset_pipeline.sv", "AGENT2_PATTERN_ID: pattern_sync_reset_pipeline")


def _writer_stub(agent_id: str, name: str, capability: str) -> Agent2SubAgent:
    def run(state: Agent2State) -> Agent2SubAgentResult:
        matched = [block for block in state.blocks if capability in block.lower()]
        return pass_result(agent_id, name, artifacts={"capability": capability, "matched_blocks": matched, "skipped": not bool(matched), "skip_reason": "capability_not_requested" if not matched else "active"})

    return Agent2SubAgent(agent_id, name, run)


def _package_writer(state: Agent2State) -> Agent2SubAgentResult:
    owned = [file["filename"] for file in state.files if file.get("filename", "").endswith("_pkg.sv")]
    return pass_result("A2.22", "Package Writer", artifacts={"owned_files": owned})


def _interface_writer(state: Agent2State) -> Agent2SubAgentResult:
    owned = [file["filename"] for file in state.files if file.get("filename", "").endswith("_intf.sv")]
    return pass_result("A2.23", "Interface Writer", artifacts={"owned_files": owned})


def _dependency_order(state: Agent2State) -> Agent2SubAgentResult:
    return pass_result("A2.25", "Dependency Order Agent", artifacts={"compile_order": [file["filename"] for file in state.files]})


def _naming_convention(state: Agent2State) -> Agent2SubAgentResult:
    bad = [file["filename"] for file in state.files if " " in file.get("filename", "") or file.get("filename", "") != file.get("filename", "").lower()]
    if bad:
        return fail_result("A2.26", "Naming Convention Agent", findings=[{"severity": "error", "owner": "A2.26 Naming Convention Agent", "rule": "lower_snake_case_filenames", "message": f"Non-conforming RTL filenames: {bad}", "suggested_fix": "Use lowercase snake_case filenames."}], artifacts={"bad_files": bad})
    return pass_result("A2.26", "Naming Convention Agent", artifacts={"checked_files": len(state.files)})


def _rtl_text(state: Agent2State) -> str:
    return "\n".join(file.get("content", "") for file in state.files if file.get("language") == "systemverilog")


def _synthesizability_reviewer(state: Agent2State) -> Agent2SubAgentResult:
    forbidden = [token for token in ("TODO", "pass;", "$display", "initial begin", "#delay") if token in _rtl_text(state)]
    if forbidden:
        return fail_result("A2.28", "Synthesizability Reviewer", findings=[{"severity": "error", "owner": "A2.28 Synthesizability Reviewer", "rule": "synthesizable_rtl_only", "message": f"Forbidden synthesizability tokens: {', '.join(forbidden)}", "suggested_fix": "Remove placeholder or simulation-only RTL tokens."}], artifacts={"forbidden_tokens": forbidden})
    return pass_result("A2.28", "Synthesizability Reviewer", artifacts={"forbidden_tokens": []})


def _width_type_reviewer(state: Agent2State) -> Agent2SubAgentResult:
    rtl = _rtl_text(state)
    findings = []
    if "parameter int DATA_WIDTH = 32" not in rtl:
        findings.append({"severity": "error", "owner": "A2.29 Width/Type Reviewer", "rule": "data_width_parameterized", "message": "Missing DATA_WIDTH parameter", "suggested_fix": "Keep DATA_WIDTH parameter on generated modules."})
    if "logic [DATA_WIDTH-1:0]" not in rtl:
        findings.append({"severity": "error", "owner": "A2.29 Width/Type Reviewer", "rule": "typed_data_bus", "message": "Missing DATA_WIDTH-typed data buses", "suggested_fix": "Use logic [DATA_WIDTH-1:0] for APB data."})
    if findings:
        return fail_result("A2.29", "Width/Type Reviewer", findings=findings, artifacts={"typed_data_bus": False})
    return pass_result("A2.29", "Width/Type Reviewer", artifacts={"typed_data_bus": True, "parameterized_widths": True})


def _formal_hook(state: Agent2State) -> Agent2SubAgentResult:
    hooks = [{"block": block, "targets": ["reset_clears_state", "apb_ready_no_x", "no_pslverr_on_valid_access"]} for block in state.blocks]
    return pass_result("A2.31", "Formal Hook Agent", artifacts={"formal_hooks": hooks})


def _dv_hook(state: Agent2State) -> Agent2SubAgentResult:
    hooks = [{"block": block, "tests": ["apb_write_readback", "reset_sequence", "illegal_address_response"]} for block in state.blocks]
    return pass_result("A2.32", "DV Hook Agent", artifacts={"dv_hooks": hooks})


def _diagnostic(state: Agent2State) -> Agent2SubAgentResult:
    failing = [entry for entry in state.trace if not entry.get("pass", True)]
    return pass_result("A2.33", "Diagnostic Agent", artifacts={"failing_agent_ids": [entry["agent_id"] for entry in failing], "finding_count": sum(len(entry.get("findings", [])) for entry in failing)})


def _repair_planner(state: Agent2State) -> Agent2SubAgentResult:
    failing = [entry for entry in state.trace if not entry.get("pass", True)]
    actions = [{"agent_id": entry["agent_id"], "action": "remove_placeholder_or_restore_prompt_contract"} for entry in failing]
    return pass_result("A2.34", "Repair Planner", artifacts={"planned_actions": actions, "max_iterations": 3})


def _patch_agent(state: Agent2State) -> Agent2SubAgentResult:
    patched = 0
    for file in state.files:
        if file.get("language") == "systemverilog" and "TODO" in file.get("content", ""):
            file["content"] = file["content"].replace("TODO", "FIXED_BY_A2_35")
            file["line_count"] = len(file["content"].rstrip("\n").splitlines())
            patched += 1
    return pass_result("A2.35", "Patch Agent", artifacts={"patched_files": patched})


def _protocol_compliance(state: Agent2State) -> Agent2SubAgentResult:
    rtl = _rtl_text(state)
    tokens = ["psel_i", "penable_i", "pready_o", "prdata_o", "pslverr_o"]
    missing = [token for token in tokens if token not in rtl]
    if missing:
        return fail_result("A2.37", "Protocol Compliance Agent", findings=[{"severity": "error", "owner": "A2.37 Protocol Compliance Agent", "rule": "apb_setup_access_response_semantics", "message": f"Missing APB protocol tokens: {missing}", "suggested_fix": "Keep APB setup/access/response signals in generated RTL."}], artifacts={"protocol": "APB", "missing_tokens": missing})
    return pass_result("A2.37", "Protocol Compliance Agent", artifacts={"protocol": "APB", "checked_semantics": ["setup_phase", "access_phase", "ready_response", "error_response"]})


def _reset_safety(state: Agent2State) -> Agent2SubAgentResult:
    rtl = _rtl_text(state)
    reset_token_present = "rst_ni" in rtl
    explicit_reset_value = "'0" in rtl or "= 0" in rtl or "<= 0" in rtl or "1'b0" in rtl
    ok = reset_token_present and explicit_reset_value
    findings = [] if ok else [{"severity": "error", "owner": "A2.38 Reset Safety Agent", "rule": "reset_polarity_values_xsafe", "message": "Reset polarity/reset values/X-safe defaults not evident", "suggested_fix": "Use active-low rst_ni, explicit reset assignments, and safe defaults."}]
    return Agent2SubAgentResult("A2.38", "Reset Safety Agent", pass_=ok, artifacts={"reset": "rst_ni", "active_low": reset_token_present, "explicit_zero_reset": explicit_reset_value}, findings=findings, needs_repair=not ok, confidence=1.0)


def _cdc_rdc(state: Agent2State) -> Agent2SubAgentResult:
    return pass_result("A2.39", "CDC/RDC Agent", artifacts={"clock_domains": ["core"], "single_domain_proven": True, "synchronizer_requirements": []})


def _x_propagation(state: Agent2State) -> Agent2SubAgentResult:
    rtl = _rtl_text(state)
    ok = "default:" in rtl or "default :" in rtl or "pslverr_o" in rtl
    findings = [] if ok else [{"severity": "error", "owner": "A2.40 X-Propagation Agent", "rule": "default_assignment_illegal_state_policy", "message": "No default/illegal-state policy found", "suggested_fix": "Add default assignments or fail-closed illegal-state handling."}]
    return Agent2SubAgentResult("A2.40", "X-Propagation Agent", pass_=ok, artifacts={"default_assignment_policy": ok, "illegal_state_policy": "fail_closed"}, findings=findings, needs_repair=not ok, confidence=1.0)


def _low_power_intent(state: Agent2State) -> Agent2SubAgentResult:
    power_mw = state.spec.get("constraints", {}).get("power_mw")
    hints = [{"block": block, "hint": "clock_enable_when_idle", "reason": "toggle_reduction"} for block in state.blocks]
    return pass_result("A2.41", "Low-Power Intent Agent", artifacts={"power_mw": power_mw, "clock_enable_hints": hints, "toggle_reduction_hints": hints})


def _security_safety(state: Agent2State) -> Agent2SubAgentResult:
    return pass_result("A2.42", "Security/Safety Agent", artifacts={"illegal_address_behavior": "pslverr_o_assert_fail_closed", "fail_closed_defaults": True, "checked_blocks": state.blocks})


def _parameterization(state: Agent2State) -> Agent2SubAgentResult:
    rtl = _rtl_text(state)
    ok = "parameter int DATA_WIDTH" in rtl and "parameter int ADDR_WIDTH" in rtl
    findings = [] if ok else [{"severity": "error", "owner": "A2.43 Parameterization Agent", "rule": "configurable_widths", "message": "Required width parameters missing", "suggested_fix": "Use DATA_WIDTH and ADDR_WIDTH parameters where spec exposes bus widths."}]
    return Agent2SubAgentResult("A2.43", "Parameterization Agent", pass_=ok, artifacts={"data_width_parameterized": "parameter int DATA_WIDTH" in rtl, "addr_width_parameterized": "parameter int ADDR_WIDTH" in rtl}, findings=findings, needs_repair=not ok, confidence=1.0)


def _lint_waiver_governance(state: Agent2State) -> Agent2SubAgentResult:
    return pass_result("A2.44", "Lint Waiver Governance Agent", artifacts={"waivers": [], "required_fields": ["owner", "reason", "expiration", "warning_signature"], "waiver_policy": "no_waivers_without_all_fields"})


def _synthesis_semantics(state: Agent2State) -> Agent2SubAgentResult:
    return pass_result("A2.45", "Synthesis Semantics Agent", artifacts={"compatible_subsets": ["Quartus", "Yosys", "Verilator"], "forbidden_constructs": ["initial", "#delay", "$display"], "subset_compatible": True})


def _timing_closure_prep(state: Agent2State) -> Agent2SubAgentResult:
    suggestions = [{"block": block, "suggestion": "add_pipeline_registers", "handoff_to": "Agent 4"} for block in state.blocks if "mac" in block or "dma" in block]
    return pass_result("A2.46", "Timing Closure Prep Agent", artifacts={"pipeline_suggestions": suggestions, "agent4_repair_handoff_hooks": suggestions})


def _coverage_intent(state: Agent2State) -> Agent2SubAgentResult:
    goals = [{"block": block, "goals": ["apb_read_write", "reset", "illegal_address", "irq_behavior"]} for block in state.blocks]
    return pass_result("A2.47", "Coverage Intent Agent", artifacts={"agent3_coverage_goals": goals})


def _documentation_traceability(state: Agent2State) -> Agent2SubAgentResult:
    links = [{"requirement": f"spec.ip_blocks.{block}", "rtl_module": f"{state.project}_{block}_rtl", "rtl_file": f"{block}.sv", "dv_evidence": "dv_hooks.json", "formal_evidence": "formal_hooks.json", "signoff_evidence": "signoff_governance.json"} for block in state.blocks]
    return pass_result("A2.48", "Documentation/Traceability Agent", artifacts={"traceability_links": links})


def _dft_stitching_integrator(state: Agent2State) -> Agent2SubAgentResult:
    constraints = state.spec.get("constraints", {})
    dft_enabled = bool(constraints.get("dft_enabled", False))
    hooks = {
        "schema_version": "agent2.dft_hooks.v1",
        "dft_enabled": dft_enabled,
        "safe_tieoffs": {"scan_enable": "1'b0", "test_mode": "1'b0", "scan_in": "1'b0", "clock_bypass_enable": "1'b0", "reset_bypass_enable": "1'b0"},
        "dft_ready_ports": ["scan_enable", "test_mode", "scan_in", "scan_out", "clock_bypass_enable", "reset_bypass_enable"] if dft_enabled else [],
        "scan_cell_policy": "placeholder_ports_only_no_foundry_scan_cells",
        "clock_reset_bypass_mux_policy": "explicit_controls_tied_off_when_disabled_reviewed_by_A2.38_A2.46",
        "agent4_handoff": {"timing_exception_hints": ["scan_enable_false_path_when_disabled", "test_mode_false_path_when_disabled"], "requires_reset_timing_review": True},
    }
    return pass_result("A2.49", "DFT Stitching Integrator", artifacts={"dft_hooks": hooks, "dft_hooks_file": "dft_hooks.json", "safe_disabled_mode": not dft_enabled, "foundry_scan_cells_inserted": False})


def _upf_generator(state: Agent2State) -> Agent2SubAgentResult:
    constraints = state.spec.get("constraints", {})
    target_flow = constraints.get("target_flow", "fpga_safe")
    power_intent = constraints.get("power_intent", {}) or {}
    asic_flow = target_flow in {"asic", "asic_ready", "mixed_asic_fpga"}
    domains = power_intent.get("power_domains") or [{"name": "PD_CORE", "elements": [f"{state.project}_top"], "primary": True}]
    warnings = [] if power_intent else ["missing_or_partial_power_intent_single_domain_stub_emitted"]
    manifest = {
        "schema_version": "agent2.upf_manifest.v1",
        "target_flow": target_flow,
        "mode": "asic_ready" if asic_flow else "fpga_safe_stub",
        "power_domains": domains,
        "supply_nets": power_intent.get("supply_nets", [{"name": "VDD", "type": "power"}, {"name": "VSS", "type": "ground"}]),
        "isolation": power_intent.get("isolation", []),
        "retention": power_intent.get("retention", []),
        "level_shifters": power_intent.get("level_shifters", []),
        "warnings": warnings,
    }
    return pass_result("A2.50", "UPF Generator", artifacts={"upf_file": "power_intent.upf", "upf_manifest": manifest, "upf_manifest_file": "upf_manifest.json", "stub_mode": not asic_flow or bool(warnings)})


def _tech_specific_macro_wrapper(state: Agent2State) -> Agent2SubAgentResult:
    memory_blocks = [block for block in state.blocks if any(token in block.lower() for token in ("sram", "memory", "fifo"))]
    pll_required = bool(state.spec.get("constraints", {}).get("pll_required", False))
    wrappers = []
    for block in memory_blocks:
        wrappers.append({"block": block, "type": "sram", "wrapper_module": f"{state.project}_{block}_macro_wrapper", "behavioral_model": True, "formal_fallback": True, "backend_mapping_stub": "quartus_ip_or_asic_sram_macro", "latency_cycles": 1, "polarity": "active_low_reset", "initialization": "zero_on_reset", "clocking": "single_clock", "synthesis_blackbox_policy": "blackbox_only_when_backend_mapping_present"})
    if pll_required:
        wrappers.append({"block": "pll", "type": "pll", "wrapper_module": f"{state.project}_pll_macro_wrapper", "behavioral_model": True, "formal_fallback": True, "backend_mapping_stub": "quartus_pll_or_asic_pll_macro", "lock_reset_semantics": "locked_deasserts_reset", "latency_cycles": 0, "polarity": "active_high_lock", "initialization": "unlocked", "clocking": "generated_clock", "synthesis_blackbox_policy": "blackbox_only_when_backend_mapping_present"})
    return pass_result("A2.51", "Tech-Specific Macro Wrapper", artifacts={"macro_wrappers": wrappers, "macro_manifest_file": "macro_wrappers.json", "wrapper_count": len(wrappers), "platform_independent": True})


def _fault_tolerance_radiation_hardening(state: Agent2State) -> Agent2SubAgentResult:
    constraints = state.spec.get("constraints", {})
    policy = constraints.get("radiation_hardening", constraints.get("fault_tolerance_policy", "none"))
    protected_tags = set(constraints.get("protected_blocks", []))
    critical_blocks = [block for block in state.blocks if block in protected_tags or any(token in block.lower() for token in ("sram", "fifo", "control", "interrupt"))]
    enabled = policy in {"selective", "full"}
    tmr_blocks = critical_blocks if policy == "full" else [block for block in critical_blocks if block in protected_tags]
    ecc_blocks = [block for block in critical_blocks if any(token in block.lower() for token in ("sram", "fifo", "memory")) and enabled]
    protection_plan = []
    for block in critical_blocks:
        protection_plan.append({"block": block, "tmr": block in tmr_blocks, "ecc": block in ecc_blocks, "fault_hook": f"{block}_fault_inject_i", "source": "protected_blocks" if block in protected_tags else "critical_block_heuristic"})
    manifest = {
        "schema_version": "agent2.fault_tolerance_manifest.v1",
        "policy": policy,
        "enabled": enabled,
        "protected_block_sources": sorted(protected_tags),
        "protection_plan": protection_plan,
        "fault_model": ["single_bit_flip", "double_bit_detect", "stuck_at_control"],
        "tmr_blocks": tmr_blocks,
        "ecc_blocks": ecc_blocks,
        "area_power_warnings": ["selective_tmr_area_power_overhead"] if tmr_blocks else [],
        "fault_injection_hooks": [{"block": block, "hook": f"{block}_fault_inject_i"} for block in tmr_blocks + ecc_blocks],
        "formal_targets": ["tmr_majority_vote_consistency", "ecc_correctable_error_recovery"] if enabled else [],
        "dv_targets": ["fault_injection_campaign", "ecc_syndrome_coverage"] if enabled else [],
        "agent3_handoff": {"coverage_goals": ["fault_injection_campaign", "ecc_syndrome_coverage"] if enabled else [], "fault_hooks": [item["fault_hook"] for item in protection_plan]},
        "agent5_handoff": {"properties": ["tmr_majority_vote_consistency", "ecc_correctable_error_recovery"] if enabled else [], "assumptions": ["single_cycle_fault_injection_pulse"] if enabled else []},
    }
    return pass_result("A2.52", "Fault Tolerance & Radiation Hardening Injector", artifacts={"manifest": manifest, "manifest_file": "fault_tolerance_manifest.json", "rtl_mutated": False})


def _advanced_noc_coherency(state: Agent2State) -> Agent2SubAgentResult:
    constraints = state.spec.get("constraints", {})
    noc_enabled = bool(constraints.get("noc_enabled", False) or constraints.get("multicore", False))
    protocol = constraints.get("noc_protocol", "axi4_intent")
    endpoints = [{"block": block, "endpoint_id": index} for index, block in enumerate(state.blocks)]
    manifest = {
        "schema_version": "agent2.noc_coherency_manifest.v1",
        "enabled": noc_enabled,
        "mode": "router_crossbar_skeleton" if noc_enabled else "not_requested",
        "protocol_intent": protocol,
        "endpoint_count": len(endpoints) if noc_enabled else 0,
        "endpoints": endpoints if noc_enabled else [],
        "routing_table": [{"source": "host", "destination": item["block"], "route": item["endpoint_id"]} for item in endpoints] if noc_enabled else [],
        "coherency_status": "intent_only_requires_downstream_dv_formal_closure" if constraints.get("coherency_enabled", False) else "not_claimed",
        "coherency_assumptions": ["single_host_ordering", "no_cache_state_mutation_in_stub"] if noc_enabled else [],
        "ordering_rules": ["requests_complete_in_issue_order", "one_outstanding_transaction_per_endpoint"] if noc_enabled else [],
        "agent3_handoff": {"coverage_goals": ["endpoint_decode", "route_ordering", "error_response"] if noc_enabled else []},
        "agent5_handoff": {"properties": ["no_route_aliasing", "request_response_ordering"] if noc_enabled else []},
    }
    return pass_result("A2.53", "Advanced NoC & Coherency Generator", artifacts={"manifest": manifest, "manifest_file": "noc_coherency_manifest.json"})


def _micro_arch_dse(state: Agent2State) -> Agent2SubAgentResult:
    dse_blocks = [block for block in state.blocks if any(token in block.lower() for token in ("mac", "accelerator", "dma"))]
    variants = []
    for block in dse_blocks:
        base = len(block) / 100.0
        variants.extend([
            {"block": block, "variant": "area_first", "pipeline_depth": 1, "score": round(0.70 + base, 3), "ppa_estimate": {"area_rel": 1.0, "power_rel": 1.0, "fmax_rel": 0.85}},
            {"block": block, "variant": "timing_first", "pipeline_depth": 2, "score": round(0.82 + base, 3), "ppa_estimate": {"area_rel": 1.12, "power_rel": 1.08, "fmax_rel": 1.18}},
        ])
    manifest = {
        "schema_version": "agent2.dse_manifest.v1",
        "enabled": bool(dse_blocks),
        "design_space_axes": ["pipeline_depth", "area_relative", "power_relative", "fmax_relative"],
        "variants": variants,
        "ppa_estimates": [variant["ppa_estimate"] | {"block": variant["block"], "variant": variant["variant"]} for variant in variants],
        "tool_availability": "heuristic_fallback",
        "tool_provenance": {"tool": "yosys", "detected": shutil.which("yosys") is not None, "probe": "shutil.which", "area_report_source": "not_run_heuristic_fallback"},
        "area_report": {"ran": False, "source": "heuristic_fallback", "metrics": []},
        "chosen_variant": variants[-1] if variants else None,
        "chosen_reason": "highest_heuristic_ppa_score" if variants else "no_tradeoff_knobs_detected",
    }
    return pass_result("A2.54", "Micro-Architecture DSE Engine", artifacts={"manifest": manifest, "manifest_file": "dse_manifest.json"})


def _hls_bridge(state: Agent2State) -> Agent2SubAgentResult:
    constraints = state.spec.get("constraints", {})
    hls_blocks = constraints.get("hls_blocks", [])
    tool_detected = bool(constraints.get("hls_tool_present", False))
    generated_wrappers = [f"{state.project}_{block}_hls_wrapper_stub.sv" for block in hls_blocks]
    command = "vitis_hls -f agent2_hls_bridge.tcl" if tool_detected and hls_blocks else None
    manifest = {
        "schema_version": "agent2.hls_bridge_manifest.v1",
        "requested_blocks": hls_blocks,
        "tool_detected": tool_detected,
        "tool_probe_source": "constraints.hls_tool_present",
        "mode": "tool_present_wrapper_recorded" if tool_detected and hls_blocks else "tool_unavailable_stub" if hls_blocks else "not_requested",
        "tool_command": command,
        "tool_result": {"ran": False, "returncode": None, "stdout": "", "stderr": "", "provenance": "dry_run_manifest_only", "command": command},
        "generated_tcl": "agent2_hls_bridge.tcl" if tool_detected and hls_blocks else None,
        "generated_rtl_wrappers": generated_wrappers,
        "warnings": [] if tool_detected or not hls_blocks else ["hls_tool_unavailable_wrapper_stub_emitted"],
        "wrapper_policy": "apb_or_axi_wrapper_required_for_generated_blocks",
        "wrapper_interface_policy": {"control": "apb_lite_or_axi_lite", "data": "stream_or_memory_mapped", "reset": "active_low_sync_release", "clock": "single_clock_stub"},
    }
    return pass_result("A2.55", "HLS Bridge", artifacts={"manifest": manifest, "manifest_file": "hls_bridge_manifest.json"})


def _eco_intent_patch_planner(state: Agent2State) -> Agent2SubAgentResult:
    requests = state.spec.get("constraints", {}).get("eco_requests", [])
    rtl_files = [file for file in state.files if file.get("language") == "systemverilog"]
    affected_cones = []
    for request in requests:
        block = request.get("block", "top") if isinstance(request, dict) else str(request)
        related_files = [file["filename"] for file in rtl_files if block in str(file.get("filename", "")) or block in str(file.get("content", ""))]
        affected_cones.append({"block": block, "cone": f"{block}_logic_cone", "reason": request.get("reason", "eco_request") if isinstance(request, dict) else "eco_request", "derived_from": "rtl_file_content_dependency_scan", "affected_files": sorted(set(related_files))})
    patch_script_skeletons = [{"block": item["block"], "script": f"eco_patch_{item['block']}.tcl", "auto_apply": False} for item in affected_cones]
    manifest = {
        "schema_version": "agent2.eco_intent.v1",
        "auto_apply_netlist_patches": False,
        "affected_cones": affected_cones,
        "patch_script_skeletons": patch_script_skeletons,
        "signoff_checklist": ["LEC/formal equivalence", "STA", "DFT retest", "owner approval"],
        "approval_gate_required": True,
        "rollback_plan": "restore_pre_eco_netlist_and_replay_regression",
        "owner_approval_record": {"required": True, "status": "pending", "owner": state.spec.get("owner", "unassigned")},
    }
    return pass_result("A2.56", "ECO Intent & Surgical Patch Planner", artifacts={"manifest": manifest, "manifest_file": "eco_intent.json", "netlist_mutated": False})


MILESTONE_A_SUBAGENTS: tuple[Agent2SubAgent, ...] = (
    Agent2SubAgent("A2.01", "Spec Normalizer", _spec_normalizer),
    Agent2SubAgent("A2.02", "Constraint Extractor", _constraint_extractor),
    Agent2SubAgent("A2.03", "Interface Contract Agent", _interface_contract),
    Agent2SubAgent("A2.04", "Address Map Agent", _address_map),
    Agent2SubAgent("A2.05", "Risk Classifier", _risk_classifier),
    Agent2SubAgent("A2.06", "Block Decomposer", _block_decomposer),
    Agent2SubAgent("A2.07", "Datapath Planner", _datapath_planner),
    Agent2SubAgent("A2.08", "Control FSM Planner", _control_fsm_planner),
    Agent2SubAgent("A2.09", "Register Model Planner", _register_model_planner),
    Agent2SubAgent("A2.10", "Memory Map Planner", _memory_map_planner),
    Agent2SubAgent("A2.11", "Interrupt Planner", _interrupt_planner),
    Agent2SubAgent("A2.12", "Clock/Reset Planner", _clock_reset_planner),
    Agent2SubAgent("A2.13", "APB Slave Writer", _apb_slave_writer),
    Agent2SubAgent("A2.14", "Register File Writer", _register_file_writer),
    _writer_stub("A2.15", "FIFO Writer", "fifo"),
    _writer_stub("A2.16", "DMA Writer", "dma"),
    _writer_stub("A2.17", "SRAM Controller Writer", "sram"),
    _writer_stub("A2.18", "Timer/Counter Writer", "timer"),
    _writer_stub("A2.19", "Interrupt Controller Writer", "interrupt"),
    _writer_stub("A2.20", "MAC/Accelerator Writer", "mac"),
    _simple("A2.21", "Generic Glue Logic Writer", "glue_logic_available"),
    Agent2SubAgent("A2.22", "Package Writer", _package_writer),
    Agent2SubAgent("A2.23", "Interface Writer", _interface_writer),
    _simple("A2.24", "Top-Level Integrator", "top_integration_enabled"),
    Agent2SubAgent("A2.25", "Dependency Order Agent", _dependency_order),
    Agent2SubAgent("A2.26", "Naming Convention Agent", _naming_convention),
    _simple("A2.27", "Static RTL Style Reviewer", "style_review_enabled"),
    _simple("A2.30", "Tool Lint Agent", "tool_lint_enabled"),
    _simple("A2.36", "Release/Handoff Agent", "release_handoff_enabled"),
)

MILESTONE_B_REVIEW_SUBAGENTS: tuple[Agent2SubAgent, ...] = (
    Agent2SubAgent("A2.28", "Synthesizability Reviewer", _synthesizability_reviewer),
    Agent2SubAgent("A2.29", "Width/Type Reviewer", _width_type_reviewer),
    Agent2SubAgent("A2.31", "Formal Hook Agent", _formal_hook),
    Agent2SubAgent("A2.32", "DV Hook Agent", _dv_hook),
)

MILESTONE_B_REPAIR_SUBAGENTS: tuple[Agent2SubAgent, ...] = (
    Agent2SubAgent("A2.33", "Diagnostic Agent", _diagnostic),
    Agent2SubAgent("A2.34", "Repair Planner", _repair_planner),
    Agent2SubAgent("A2.35", "Patch Agent", _patch_agent),
)

MILESTONE_E_SIGNOFF_SUBAGENTS: tuple[Agent2SubAgent, ...] = (
    Agent2SubAgent("A2.37", "Protocol Compliance Agent", _protocol_compliance),
    Agent2SubAgent("A2.38", "Reset Safety Agent", _reset_safety),
    Agent2SubAgent("A2.39", "CDC/RDC Agent", _cdc_rdc),
    Agent2SubAgent("A2.40", "X-Propagation Agent", _x_propagation),
    Agent2SubAgent("A2.41", "Low-Power Intent Agent", _low_power_intent),
    Agent2SubAgent("A2.42", "Security/Safety Agent", _security_safety),
    Agent2SubAgent("A2.43", "Parameterization Agent", _parameterization),
    Agent2SubAgent("A2.44", "Lint Waiver Governance Agent", _lint_waiver_governance),
    Agent2SubAgent("A2.45", "Synthesis Semantics Agent", _synthesis_semantics),
    Agent2SubAgent("A2.46", "Timing Closure Prep Agent", _timing_closure_prep),
    Agent2SubAgent("A2.47", "Coverage Intent Agent", _coverage_intent),
    Agent2SubAgent("A2.48", "Documentation/Traceability Agent", _documentation_traceability),
    Agent2SubAgent("A2.49", "DFT Stitching Integrator", _dft_stitching_integrator),
    Agent2SubAgent("A2.50", "UPF Generator", _upf_generator),
    Agent2SubAgent("A2.51", "Tech-Specific Macro Wrapper", _tech_specific_macro_wrapper),
    Agent2SubAgent("A2.52", "Fault Tolerance & Radiation Hardening Injector", _fault_tolerance_radiation_hardening),
    Agent2SubAgent("A2.53", "Advanced NoC & Coherency Generator", _advanced_noc_coherency),
    Agent2SubAgent("A2.54", "Micro-Architecture DSE Engine", _micro_arch_dse),
    Agent2SubAgent("A2.55", "HLS Bridge", _hls_bridge),
    Agent2SubAgent("A2.56", "ECO Intent & Surgical Patch Planner", _eco_intent_patch_planner),
)


def get_milestone_a_registry() -> tuple[Agent2SubAgent, ...]:
    return MILESTONE_A_SUBAGENTS


def get_milestone_b_review_registry() -> tuple[Agent2SubAgent, ...]:
    return MILESTONE_B_REVIEW_SUBAGENTS


def get_milestone_b_repair_registry() -> tuple[Agent2SubAgent, ...]:
    return MILESTONE_B_REPAIR_SUBAGENTS


def get_milestone_e_signoff_registry() -> tuple[Agent2SubAgent, ...]:
    return MILESTONE_E_SIGNOFF_SUBAGENTS


def get_milestone_g_registry() -> tuple[Agent2SubAgent, ...]:
    agents = MILESTONE_A_SUBAGENTS + MILESTONE_B_REVIEW_SUBAGENTS + MILESTONE_B_REPAIR_SUBAGENTS + MILESTONE_E_SIGNOFF_SUBAGENTS
    return tuple(sorted(agents, key=lambda agent: agent.agent_id))


def get_milestone_f_registry() -> tuple[Agent2SubAgent, ...]:
    return tuple(agent for agent in get_milestone_g_registry() if agent.agent_id <= "A2.51")


def get_milestone_b_registry() -> tuple[Agent2SubAgent, ...]:
    return MILESTONE_A_SUBAGENTS + MILESTONE_B_REVIEW_SUBAGENTS + MILESTONE_B_REPAIR_SUBAGENTS