"""Hierarchical Agent 1 planning artifacts with mandatory Codex evidence."""

from __future__ import annotations

import copy
import json
import re
import time
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from semiconductor_swarm.agents.agent1_planning.agent1_config import AGENT1_LLM_CONFIG
from semiconductor_swarm.agents.agent1_planning.agent1_llm_client import call_agent1_codex
from semiconductor_swarm.agents.agent1_planning.capability_registry import assess_requirement_capability
from semiconductor_swarm.agents.agent1_planning.architect import build_requirement_consistency_report, generate_architecture_plan_markdown, generate_architecture_spec, validate_architecture_spec, validate_plan_quality
from semiconductor_swarm.agents.agent1_planning.audit_v4 import build_agent1_audit_artifacts, validate_audit_cross_checks
from semiconductor_swarm.agents.agent1_planning.deep_expert_council import Agent1CouncilConfig, run_agent1_v51_council
from semiconductor_swarm.agents.agent1_planning.intake_council import build_intake_artifacts, build_requirement_clarification_markdown, intake_ready_for_council, run_agent1_intake_council
from semiconductor_swarm.agents.agent1_planning.proofs_v41 import attach_v41_artifacts
from semiconductor_swarm.agents.agent1_planning.spec_schema import attach_agent1_contract_manifest, attach_tool_provenance, validate_agent1_v37_spec_schema, validate_agent1_v4_spec_schema
from semiconductor_swarm.live_inputs import consume_live_inputs_for_requirement
from semiconductor_swarm.tracing import TRACE_FILES, trace_artifact_lineage, trace_completion, trace_event, trace_snapshot


MICRO_EXPERTS = [
    "Requirement_Intake_Expert",
    "Domain_Classifier_Expert",
    "Architecture_Option_Generator",
    "PPA_Bandwidth_Tool_Expert",
    "Memory_Map_Interface_Expert",
    "Verification_Strategy_Expert",
    "Mermaid_Diagram_Expert",
    "Principal_Architect_Reviewer",
]

V3_NEW_EXPERTS = [
    "HW_SW_CoDesign_Expert",
    "IO_Packaging_Expert",
    "Clock_Power_Expert",
    "Interconnect_QoS_Expert",
    "Memory_Hierarchy_Expert",
    "DFT_Lead",
    "Safety_Security_Analyst",
    "IP_Reuse_Cost_Analyst",
]

V3_VALIDATION_NODES = [
    "Safety_Security_vs_MemoryMap_Validator",
    "HWSW_vs_RegisterMap_Validator",
    "RDL_vs_CHeader_Validator",
    "RDL_vs_DVModel_Validator",
    "ClockPower_vs_Bus_Validator",
    "MemoryHierarchy_vs_QoS_Validator",
    "DFT_vs_IO_ClockPower_Validator",
    "Super_Committee_Review_Router",
]

V3_SUPER_COMMITTEE_NODES = MICRO_EXPERTS + V3_NEW_EXPERTS + V3_VALIDATION_NODES


class Agent1V3State(TypedDict):
    requirement: str
    project_name: str
    codex_evidence: dict[str, Any]
    artifacts: dict[str, str]
    spec_draft: dict[str, Any]
    validation_decisions: list[dict[str, Any]]
    revision_counts: dict[str, int]
    next_node: str | None
    last_repaired_validator: str | None
    last_repaired_target: str | None
    hitl_required: bool
    errors: list[str]


def route_validation_decision(state: Agent1V3State) -> str:
    decision = state["validation_decisions"][-1]
    if decision["decision"] == "ACCEPT":
        return "next"
    if decision["decision"] == "HITL_REQUIRED":
        return "hitl_plan_review"
    target = decision.get("target_node")
    if not target:
        return "hitl_plan_review"
    if state["revision_counts"].get(target, 0) >= decision.get("max_revisions", 3):
        return "hitl_plan_review"
    return target


def route_after_repair(state: Agent1V3State) -> str:
    validator = state.get("last_repaired_validator") or state.get("next_node")
    if validator in VALIDATOR_FUNCTIONS:
        return validator
    return "hitl_plan_review"


VALIDATOR_SEQUENCE = [
    "HWSW_vs_RegisterMap_Validator",
    "Safety_Security_vs_MemoryMap_Validator",
    "RDL_vs_CHeader_Validator",
    "RDL_vs_DVModel_Validator",
    "ClockPower_vs_Bus_Validator",
    "MemoryHierarchy_vs_QoS_Validator",
    "DFT_vs_IO_ClockPower_Validator",
]


VALIDATOR_FUNCTIONS = {
    "HWSW_vs_RegisterMap_Validator": lambda spec: _validate_hwsw_register_map(spec),
    "Safety_Security_vs_MemoryMap_Validator": lambda spec: _validate_safety_security_memory_map(spec),
    "RDL_vs_CHeader_Validator": lambda spec: _validate_rdl_c_header(spec),
    "RDL_vs_DVModel_Validator": lambda spec: _validate_rdl_dv_model(spec),
    "ClockPower_vs_Bus_Validator": lambda spec: _validate_clock_power_bus(spec),
    "MemoryHierarchy_vs_QoS_Validator": lambda spec: _validate_memory_hierarchy_qos(spec),
    "DFT_vs_IO_ClockPower_Validator": lambda spec: _validate_dft_io_clock_power(spec),
}


def build_agent1_v3_validation_graph():
    """Build conditional LangGraph for Agent 1 V3 validator feedback loops."""
    graph = StateGraph(Agent1V3State)

    for node in VALIDATOR_SEQUENCE:
        graph.add_node(node, _validator_node(node))
    for node in {"Memory_Map_Interface_Expert", "Clock_Power_Expert", "Memory_Hierarchy_Expert", "IO_Packaging_Expert"}:
        graph.add_node(node, _repair_node)
    graph.add_node("Super_Committee_Review_Router", _router_node)
    graph.add_node("hitl_plan_review", _hitl_node)

    graph.set_entry_point(VALIDATOR_SEQUENCE[0])
    for index, node in enumerate(VALIDATOR_SEQUENCE):
        next_node = VALIDATOR_SEQUENCE[index + 1] if index + 1 < len(VALIDATOR_SEQUENCE) else "Super_Committee_Review_Router"
        graph.add_conditional_edges(node, route_validation_decision, {"next": next_node, "hitl_plan_review": "hitl_plan_review", "Memory_Map_Interface_Expert": "Memory_Map_Interface_Expert", "HW_SW_CoDesign_Expert": "Memory_Map_Interface_Expert", "Verification_Strategy_Expert": "Memory_Map_Interface_Expert", "Clock_Power_Expert": "Clock_Power_Expert", "Memory_Hierarchy_Expert": "Memory_Hierarchy_Expert", "IO_Packaging_Expert": "IO_Packaging_Expert"})
    repair_routes = {validator: validator for validator in VALIDATOR_SEQUENCE}
    repair_routes["hitl_plan_review"] = "hitl_plan_review"
    for repair_node in ("Memory_Map_Interface_Expert", "Clock_Power_Expert", "Memory_Hierarchy_Expert", "IO_Packaging_Expert"):
        graph.add_conditional_edges(repair_node, route_after_repair, repair_routes)
    graph.add_conditional_edges("Super_Committee_Review_Router", route_validation_decision, {"next": END, "hitl_plan_review": "hitl_plan_review", "Memory_Map_Interface_Expert": "Memory_Map_Interface_Expert", "HW_SW_CoDesign_Expert": "Memory_Map_Interface_Expert", "Verification_Strategy_Expert": "Memory_Map_Interface_Expert", "Clock_Power_Expert": "Clock_Power_Expert", "Memory_Hierarchy_Expert": "Memory_Hierarchy_Expert", "IO_Packaging_Expert": "IO_Packaging_Expert"})
    graph.add_edge("hitl_plan_review", END)
    return graph.compile()


def _validator_node(validator_name: str):
    def node(state: Agent1V3State) -> dict[str, Any]:
        decision = VALIDATOR_FUNCTIONS[validator_name](state["spec_draft"])
        return {"validation_decisions": [*state.get("validation_decisions", []), decision], "next_node": route_validation_decision({**state, "validation_decisions": [*state.get("validation_decisions", []), decision]})}
    return node


def _repair_node(state: Agent1V3State) -> dict[str, Any]:
    decision = state["validation_decisions"][-1]
    revision_counts = dict(state.get("revision_counts", {}))
    target = decision.get("target_node") or "hitl_plan_review"
    revision_counts[target] = revision_counts.get(target, 0) + 1
    revision = _repair_spec_for_decision(state["spec_draft"], decision)
    artifacts = dict(state.get("artifacts", {}))
    artifacts.setdefault("agent1_revision_history.jsonl", "")
    repair_record = _repair_record(state["spec_draft"], revision, decision, revision_counts[target])
    artifacts["agent1_revision_history.jsonl"] += json.dumps(repair_record, sort_keys=True) + "\n"
    source_validator = decision.get("validator") if decision.get("validator") in VALIDATOR_FUNCTIONS else None
    return {"spec_draft": revision, "revision_counts": revision_counts, "artifacts": artifacts, "last_repaired_validator": source_validator, "last_repaired_target": target, "next_node": source_validator or "hitl_plan_review"}


def _router_node(state: Agent1V3State) -> dict[str, Any]:
    latest_by_validator: dict[str, dict[str, Any]] = {}
    for item in state.get("validation_decisions", []):
        validator = item.get("validator")
        if validator in VALIDATOR_FUNCTIONS:
            latest_by_validator[validator] = item
    active_failures = [d for d in latest_by_validator.values() if d.get("decision") in {"REJECT", "HITL_REQUIRED"}]
    if not active_failures:
        decision = _decision("Super_Committee_Review_Router", "ACCEPT", None, [])
    else:
        latest = active_failures[-1]
        decision = _decision("Super_Committee_Review_Router", "REJECT", latest.get("target_node"), latest.get("findings", []))
    return {"validation_decisions": [*state.get("validation_decisions", []), decision], "next_node": route_validation_decision({**state, "validation_decisions": [*state.get("validation_decisions", []), decision]})}


def _hitl_node(state: Agent1V3State) -> dict[str, Any]:
    return {"hitl_required": True, "next_node": None}


@dataclass(frozen=True)
class Agent1CodexUnavailable(RuntimeError):
    """Raised when mandatory Agent 1 Codex endpoint cannot produce evidence."""

    message: str

    def __str__(self) -> str:
        return self.message


def run_agent1_hierarchical_planning(requirement: str, project_name: str, planning_mode: str | None = None) -> dict[str, Any]:
    """Produce final Agent 1 spec plus reviewable micro-expert artifacts.

    Codex call is mandatory for architecture reasoning evidence. Numeric PPA/bandwidth
    still come only from deterministic tools via ``generate_architecture_spec``.
    """
    planning_mode = planning_mode or "normal"
    requirement, consumed = consume_live_inputs_for_requirement(requirement, "agent1.intake.before")
    if consumed:
        trace_event(
            TRACE_FILES["agent1_intake"],
            phase="planning",
            agent="agent1",
            node_id="LIVE_INPUT.CONSUME",
            event_type="live_input_checkpoint",
            status="pass",
            payload={"checkpoint": "agent1.intake.before", "count": len(consumed)},
        )
    trace_event(
        TRACE_FILES["agent1_intake"],
        phase="planning",
        agent="agent1",
        node_id="GRAPH.AGENT1_ENTER",
        event_type="node_enter",
        status="running",
        payload={"project_name": project_name, "planning_mode": planning_mode, "input_preview": requirement[:600]},
    )
    try:
        intake_report = run_agent1_intake_council(requirement, project_name, call_agent1_codex)
    except Exception as exc:  # pragma: no cover - exact urllib errors vary by OS
        raise Agent1CodexUnavailable(str(exc)) from exc
    after_intake_requirement, consumed = consume_live_inputs_for_requirement(requirement, "agent1.council.before")
    if consumed:
        requirement = after_intake_requirement
        trace_event(
            TRACE_FILES["agent1_intake"],
            phase="planning",
            agent="agent1",
            node_id="LIVE_INPUT.CONSUME",
            event_type="live_input_checkpoint",
            status="pass",
            payload={"checkpoint": "agent1.council.before", "count": len(consumed), "rerun_intake": True},
        )
        try:
            intake_report = run_agent1_intake_council(requirement, project_name, call_agent1_codex)
        except Exception as exc:  # pragma: no cover - exact urllib errors vary by OS
            raise Agent1CodexUnavailable(str(exc)) from exc
    intake_artifacts = build_intake_artifacts(intake_report)
    if not intake_ready_for_council(intake_report):
        trace_event(
            TRACE_FILES["agent1_council"],
            phase="planning",
            agent="agent1",
            node_id="AGENT1.COUNCIL_ENTER",
            event_type="node_skipped",
            status="paused",
            parent_node_id="AGENT1.READY_GATE",
            payload={"skip_reason": "intake_not_ready", "classification": intake_report.get("classification")},
        )
        return _clarification_result(requirement, project_name, planning_mode, intake_report, intake_artifacts)

    effective_requirement = intake_report.get("normalized_requirement") or requirement
    try:
        trace_event(
            TRACE_FILES["agent1_council"],
            phase="planning",
            agent="agent1",
            node_id="AGENT1.COUNCIL_ENTER",
            event_type="node_started",
            status="running",
            parent_node_id="AGENT1.READY_GATE",
            payload={"planning_mode": planning_mode, "classification": intake_report.get("classification")},
        )
        v51_result = run_agent1_v51_council(
            effective_requirement,
            project_name,
            call_agent1_codex,
            config=Agent1CouncilConfig(planning_mode=planning_mode),
            intake_report=intake_report,
        )
        effective_requirement = str(v51_result.get("effective_requirement") or effective_requirement)
        trace_event(
            TRACE_FILES["agent1_council"],
            phase="planning",
            agent="agent1",
            node_id="AGENT1.COUNCIL_ENTER",
            event_type="node_completed",
            status="pass" if v51_result.get("status") != "HITL_REQUIRED" else "fail",
            parent_node_id="AGENT1.READY_GATE",
            payload={"status": v51_result.get("status"), "iteration_count": len(v51_result.get("iterations", []))},
        )
    except Exception as exc:  # pragma: no cover - exact urllib errors vary by OS
        raise Agent1CodexUnavailable(str(exc)) from exc
    if v51_result.get("status") == "HITL_REQUIRED":
        blocked_report = copy.deepcopy(intake_report)
        blocked_report["classification"] = "DESIGN_NEEDS_CLARIFICATION"
        blocked_report["ready_for_council"] = False
        blocked_report["missing_fields"] = sorted(set(_coerce_text_list(blocked_report.get("missing_fields", [])) + ["resolve Agent 1 council conflicts"]))
        blocked_report["user_response"] = "Agent 1 council found unresolved conflicts. Review Agent 1 traces before releasing architecture."
        blocked_report["policy_matrix"] = copy.deepcopy(blocked_report.get("policy_matrix", {}))
        blocked_report["policy_matrix"].setdefault("policies", []).append(
            {
                "policy_id": "P-A1-007",
                "name": "council_conflicts_resolved",
                "status": "fail",
                "failure_reason": "Agent 1 council status is HITL_REQUIRED.",
                "evidence": {"status": v51_result.get("status")},
                "source_artifact": "agent1_conflict_matrix.json",
            }
        )
        blocked_artifacts = {**build_intake_artifacts(blocked_report), **v51_result.get("artifacts", {})}
        blocked_artifacts["agent1_requirement_clarification.md"] = build_requirement_clarification_markdown(blocked_report)
        return _clarification_result(requirement, project_name, planning_mode, blocked_report, blocked_artifacts)

    ai_analysis = _ai_analysis_from_intake_and_council(intake_report, v51_result, project_name, planning_mode)
    codex_evidence = _primary_codex_evidence(intake_report)
    codex_response = json.dumps(
        {
            "schema_version": ai_analysis.get("schema_version"),
            "intake_classification": intake_report.get("classification"),
            "selected_architecture": ai_analysis.get("selected_architecture"),
            "capability_assessment": ai_analysis.get("capability_assessment"),
            "intake_expert_count": len(intake_report.get("codex_evidence", {}).get("experts", [])),
            "v51_status": v51_result.get("status"),
        },
        indent=2,
        sort_keys=True,
    )

    trace_event(
        TRACE_FILES["agent1_final_decision"],
        phase="planning",
        agent="agent1",
        node_id="AGENT1.SPEC_GENERATE",
        event_type="node_started",
        status="running",
        parent_node_id="AGENT1.COUNCIL_ENTER",
        payload={"selected_architecture": ai_analysis.get("selected_architecture", {})},
    )
    spec = generate_architecture_spec(effective_requirement, project_name, ai_analysis=ai_analysis)
    blocks = [block["name"] for block in spec["ip_blocks"]]
    v3 = _run_v3_super_committee(spec)
    spec.update(v3["spec_extensions"])
    spec = attach_tool_provenance(spec)
    spec = attach_agent1_contract_manifest(spec)
    v41_artifacts = attach_v41_artifacts(spec)
    validate_agent1_v37_spec_schema(spec)
    validate_agent1_v4_spec_schema(spec)
    trace_event(
        TRACE_FILES["agent1_final_decision"],
        phase="planning",
        agent="agent1",
        node_id="AGENT1.SCHEMA_VALIDATE_FINAL_SPEC",
        event_type="node_completed",
        status="pass",
        parent_node_id="AGENT1.SPEC_GENERATE",
        payload={"ip_blocks": blocks, "project_name": project_name},
    )
    plan_markdown = generate_architecture_plan_markdown(spec) + "\n" + _v3_committee_markdown(v3)
    plan_quality_report = validate_plan_quality(spec, plan_markdown)
    requirement_consistency_report = build_requirement_consistency_report(spec, plan_markdown)
    intake = _intake_artifact(effective_requirement, spec)
    domain = _domain_artifact(spec)
    memory_interface = _memory_interface_artifact(spec)
    rdl = _systemrdl_artifact(spec)
    fw_header = _firmware_header_artifact(spec)
    fw_stub = _firmware_driver_stub_artifact(spec)
    dv_reg_model = _cocotb_reg_model_artifact(spec)
    artifacts = {
        "agent1_codex_response.md": codex_response,
        "agent1_codex_evidence.json": json.dumps(codex_evidence, indent=2, sort_keys=True),
        "agent1_ai_requirement_analysis.json": json.dumps(ai_analysis, indent=2, sort_keys=True),
        "agent1_expert_council_trace.jsonl": ai_analysis.get("expert_trace_jsonl", ""),
        "agent1_capability_assessment.json": json.dumps(ai_analysis.get("capability_assessment", {}), indent=2, sort_keys=True),
        "agent1_intake.json": json.dumps(intake, indent=2, sort_keys=True),
        "agent1_domain_classification.json": json.dumps(domain, indent=2, sort_keys=True),
        "agent1_architecture_options.md": _architecture_options(spec),
        "agent1_tool_evidence.json": json.dumps({"ppa_estimate": spec["ppa_estimate"], "bandwidth_estimate": spec["bandwidth_estimate"], "tool_provenance": spec["tool_provenance"]}, indent=2),
        "agent1_contract_manifest.json": json.dumps(spec["agent1_contract_manifest"], indent=2, sort_keys=True),
        "agent1_memory_interface_plan.json": json.dumps(memory_interface, indent=2, sort_keys=True),
        "agent1_register_map.rdl": rdl,
        f"fw_{spec['project_name']}_regs.h": fw_header,
        f"fw_{spec['project_name']}_driver_stub.c": fw_stub,
        f"tb_{spec['project_name']}_reg_model.py": dv_reg_model,
        "agent1_verification_strategy.md": _verification_strategy(blocks),
        "agent1_review_scorecard.md": _review_scorecard(spec),
        "agent1_plan_quality_report.json": json.dumps(plan_quality_report, indent=2, sort_keys=True),
        "agent1_requirement_consistency_report.json": json.dumps(requirement_consistency_report, indent=2, sort_keys=True),
        **intake_artifacts,
        **v41_artifacts,
        **v3["artifacts"],
    }
    artifacts.update(v51_result.get("artifacts", {}))
    for artifact_name in sorted(artifacts):
        trace_artifact_lineage(
            artifact_name,
            source_nodes=["AGENT1.INTAKE_COUNCIL", "AGENT1.COUNCIL_ENTER", "AGENT1.SPEC_GENERATE"],
            artifact_path=f"reports/agent1/{artifact_name}" if artifact_name != "architecture_plan.md" else "reports/architecture_plan.md",
        )
    trace_event(
        TRACE_FILES["agent1_final_decision"],
        phase="planning",
        agent="agent1",
        node_id="AGENT1.ARTIFACT_WRITE",
        event_type="node_completed",
        status="pass",
        parent_node_id="AGENT1.SPEC_GENERATE",
        payload={"artifact_count": len(artifacts), "artifacts": sorted(artifacts)[:80]},
    )
    artifacts["agent1_v51_mode_bridge.json"] = json.dumps(
        {
            "schema_version": "agent1.v51_mode_bridge.v1",
            "planning_mode": planning_mode,
            "status": v51_result.get("status"),
            "minimum_planned_calls": v51_result.get("config", {}).get("minimum_planned_calls"),
            "iteration_count": len(v51_result.get("iterations", [])),
            "timestamp": time.time(),
        },
        indent=2,
        sort_keys=True,
    )
    validation = validate_agent1_micro_experts(spec, plan_markdown, artifacts, codex_evidence)
    artifacts["agent1_micro_expert_validation.json"] = json.dumps(validation, indent=2, sort_keys=True)
    audit_artifacts = build_agent1_audit_artifacts(effective_requirement, project_name, spec, artifacts, codex_evidence, validation, AGENT1_LLM_CONFIG)
    artifacts.update(audit_artifacts)
    audit_cross_check = validate_audit_cross_checks(artifacts)
    artifacts["agent1_v4_audit_cross_check.json"] = json.dumps(audit_cross_check, indent=2, sort_keys=True)
    report = {
        "pass": validation["pass"],
        "planning_mode": planning_mode,
        "v51_council": {
            "enabled": True,
            "status": v51_result.get("status"),
            "iteration_count": len(v51_result.get("iterations", [])),
        },
        "intake_router": intake_report,
        "micro_experts": V3_SUPER_COMMITTEE_NODES,
        "codex_contract": {"required": True, **AGENT1_LLM_CONFIG},
        "codex_evidence": codex_evidence,
        "ai_requirement_analysis": ai_analysis,
        "artifacts": sorted(artifacts),
        "mermaid_diagrams": "```mermaid" in plan_markdown and "stateDiagram-v2" in plan_markdown,
        "tool_backed_estimates": bool(spec.get("ppa_estimate") and spec.get("bandwidth_estimate")),
        "micro_expert_validation": validation,
        "plan_quality_report": plan_quality_report,
        "v4_audit_cross_check": audit_cross_check,
        "v41_proof_report": json.loads(artifacts["agent1_v41_proof_report.json"]),
        "v41_risk_register": json.loads(artifacts["agent1_v41_risk_register.json"]),
    }
    if not validation["pass"]:
        raise ValueError(f"Agent 1 micro-expert validation failed: {validation['failures']}")
    if not audit_cross_check["pass"]:
        raise ValueError(f"Agent 1 V4 audit cross-check failed: {audit_cross_check['failures']}")
    trace_completion(
        status="pass",
        decision="PLAN_REVIEW",
        decision_reason="Agent 1 architecture plan ready for human review.",
        artifact_refs=sorted(artifacts),
    )
    trace_snapshot(
        "after_final_spec_generation",
        {
            "classification": intake_report.get("classification"),
            "ready_for_council": intake_report.get("ready_for_council"),
            "current_stage": "planning",
            "spec_project": spec.get("project_name"),
            "artifact_count": len(artifacts),
        },
    )
    return {"spec": spec, "plan_markdown": plan_markdown, "agent1_artifacts": artifacts, "report": report}


def _clarification_result(requirement: str, project_name: str, planning_mode: str, intake_report: dict[str, Any], artifacts: dict[str, str]) -> dict[str, Any]:
    artifacts = dict(artifacts)
    artifacts.setdefault("agent1_requirement_clarification.md", build_requirement_clarification_markdown(intake_report))
    for artifact_name in sorted(artifacts):
        trace_artifact_lineage(
            artifact_name,
            source_nodes=["AGENT1.INTAKE_COUNCIL", "AGENT1.READY_GATE"],
            artifact_path=f"reports/agent1/{artifact_name}",
        )
    trace_completion(
        status="paused",
        decision="REQUIREMENT_CLARIFICATION",
        decision_reason="Agent 1 intake did not release architecture planning.",
        blocking_reasons=intake_report.get("missing_fields", []),
        artifact_refs=sorted(artifacts),
    )
    report = {
        "pass": False,
        "requires_clarification": True,
        "planning_mode": planning_mode,
        "intake_router": intake_report,
        "codex_contract": {"required": True, **AGENT1_LLM_CONFIG},
        "codex_evidence": _primary_codex_evidence(intake_report),
        "artifacts": sorted(artifacts),
        "failure_reason": "Agent 1 intake did not release architecture planning.",
        "project_name": project_name,
        "raw_requirement": requirement,
    }
    return {
        "requires_clarification": True,
        "intake_report": intake_report,
        "plan_markdown": "",
        "clarification_markdown": artifacts["agent1_requirement_clarification.md"],
        "agent1_artifacts": artifacts,
        "report": report,
    }

def _primary_codex_evidence(intake_report: dict[str, Any]) -> dict[str, Any]:
    experts = intake_report.get("codex_evidence", {}).get("experts", [])
    if experts:
        evidence = experts[0].get("evidence", {})
        if isinstance(evidence, dict):
            return evidence
    adjudicator = intake_report.get("codex_evidence", {}).get("adjudicator", {})
    evidence = adjudicator.get("evidence", {}) if isinstance(adjudicator, dict) else {}
    return evidence if isinstance(evidence, dict) else {}

def _ai_analysis_from_intake_and_council(intake_report: dict[str, Any], v51_result: dict[str, Any], project_name: str, planning_mode: str) -> dict[str, Any]:
    canonical = intake_report.get("canonical_intent", {}) if isinstance(intake_report.get("canonical_intent"), dict) else {}
    selected = _selected_architecture_from_canonical(canonical, project_name)
    analysis: dict[str, Any] = {
        "schema_version": "agent1.ai_requirement_analysis.v64",
        "project_name": project_name,
        "raw_requirement": intake_report.get("raw_requirement", ""),
        "planning_mode": planning_mode,
        "intake_classification": intake_report.get("classification"),
        "canonical_intent": canonical,
        "extracted_intents": _extracted_intents_from_canonical(canonical),
        "expert_outputs": intake_report.get("codex_evidence", {}).get("experts", []),
        "selected_architecture": selected,
        "rejected_alternatives": [],
        "assumptions": _assumptions_from_intake(intake_report),
        "open_questions": _coerce_text_list(intake_report.get("missing_fields", [])),
        "citations": intake_report.get("citations", []),
        "confidence": intake_report.get("calibrated_confidence", 0.0),
        "expert_trace_jsonl": _intake_trace_jsonl(intake_report, v51_result),
    }
    capability = assess_requirement_capability(analysis)
    selected["compatibility_mode"] = capability["mode"]
    selected["bridge"] = capability.get("bridge")
    selected["capability_gaps"] = capability["capability_gaps"]
    analysis["capability_assessment"] = capability
    analysis["v51_council"] = {
        "status": v51_result.get("status"),
        "iteration_count": len(v51_result.get("iterations", [])),
        "minimum_planned_calls": v51_result.get("config", {}).get("minimum_planned_calls"),
    }
    return analysis

def _selected_architecture_from_canonical(canonical: dict[str, Any], project_name: str) -> dict[str, Any]:
    cpu = canonical.get("cpu") if isinstance(canonical.get("cpu"), dict) else {}
    bus = canonical.get("bus") if isinstance(canonical.get("bus"), dict) else canonical.get("bus")
    primary_protocol = _protocol_from_value(bus) or "APB"
    cpu_width = _cpu_width_from_value(cpu)
    return {
        "project_name": project_name,
        "status": "candidate_ready",
        "summary": "Architecture candidate released from Agent 1 V6.4 Intake + Deep Council.",
        "cpu_width_bits": cpu_width,
        "isa": "rv32imc" if cpu_width == 32 else (f"rv{cpu_width}imc" if cpu_width else None),
        "primary_protocol": primary_protocol,
        "peripheral_protocol": "APB" if primary_protocol in {"APB", "AHB"} else primary_protocol,
        "bridges": [{"name": "ahb_to_apb_bridge", "from_protocol": "AHB", "to_protocol": "APB", "boundary": "peripheral_subsystem"}] if primary_protocol == "AHB" else [],
        "external_peripherals": _list_from_value(canonical.get("peripheral")),
        "accelerator": canonical.get("accelerator"),
        "source_experts": ["agent1_v64_intake", "agent1_v51_deep_council"],
    }

def _extracted_intents_from_canonical(canonical: dict[str, Any]) -> dict[str, Any]:
    cpu = canonical.get("cpu") if isinstance(canonical.get("cpu"), dict) else {}
    return {
        "cpu_requested": bool(cpu),
        "cpu_width_bits": _cpu_width_from_value(cpu),
        "requested_bus_protocol": _protocol_from_value(canonical.get("bus")),
        "external_peripherals": _list_from_value(canonical.get("peripheral")),
        "frequency_mhz": _clock_mhz_from_value(canonical.get("clock")),
        "target_node": canonical.get("node"),
        "power_budget_mw": canonical.get("power"),
        "unknowns": [],
    }

def _assumptions_from_intake(intake_report: dict[str, Any]) -> list[str]:
    missing = _coerce_text_list(intake_report.get("missing_fields", []))
    if not missing:
        return ["Agent 1 V6.4 Intake Council found enough cited requirement intent for planning."]
    return [f"Open requirement field: {item}" for item in missing]

def _coerce_text_list(value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    raw_items = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in raw_items:
        if isinstance(item, dict):
            text = item.get("field") or item.get("name") or item.get("message") or item.get("type") or json.dumps(item, sort_keys=True, default=str)
        else:
            text = item
        if str(text).strip():
            result.append(str(text).strip())
    return result

def _intake_trace_jsonl(intake_report: dict[str, Any], v51_result: dict[str, Any]) -> str:
    lines = []
    for record in intake_report.get("codex_evidence", {}).get("experts", []):
        lines.append(json.dumps({"node_id": record.get("node_id"), "title": record.get("title"), "evidence": record.get("evidence", {}), "parse_status": record.get("parse_status")}, sort_keys=True))
    adjudicator = intake_report.get("codex_evidence", {}).get("adjudicator")
    if adjudicator:
        lines.append(json.dumps({"node_id": adjudicator.get("node_id"), "title": adjudicator.get("title"), "evidence": adjudicator.get("evidence", {}), "parse_status": adjudicator.get("parse_status")}, sort_keys=True))
    lines.append(json.dumps({"node_id": "agent1_v51_council", "status": v51_result.get("status"), "iteration_count": len(v51_result.get("iterations", []))}, sort_keys=True))
    return "\n".join(lines) + "\n"

def _protocol_from_value(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("protocol", "primary_protocol", "name"):
            if value.get(key):
                return str(value[key]).upper()
        value = json.dumps(value)
    if isinstance(value, str):
        text = value.upper()
        for protocol in ("APB", "AHB", "AXI", "WISHBONE"):
            if protocol in text:
                return protocol
    return None

def _cpu_width_from_value(value: Any) -> int | None:
    if isinstance(value, dict):
        for key in ("data_width_bits", "width_bits", "bits"):
            try:
                if value.get(key) is not None:
                    return int(value[key])
            except (TypeError, ValueError):
                pass
        text = json.dumps(value).lower()
    else:
        text = str(value).lower() if value is not None else ""
    if "rv64" in text or "64-bit" in text or "64 bit" in text:
        return 64
    if "rv32" in text or "32-bit" in text or "32 bit" in text:
        return 32
    return None

def _clock_mhz_from_value(value: Any) -> int | None:
    if isinstance(value, dict):
        for key in ("frequency_mhz", "mhz", "clock_mhz"):
            try:
                if value.get(key) is not None:
                    return int(value[key])
            except (TypeError, ValueError):
                pass
        value = json.dumps(value)
    match = re.search(r"(\d+)\s*mhz", str(value).lower())
    return int(match.group(1)) if match else None

def _list_from_value(value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    raw_items = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in raw_items:
        if isinstance(item, dict):
            text = str(item.get("name") or item.get("type") or item.get("peripheral") or "")
        else:
            text = str(item)
        for candidate in ("uart", "spi", "i2c", "gpio"):
            if re.search(rf"\b{candidate}\b", text.lower()) and candidate not in result:
                result.append(candidate)
    return result

def validate_agent1_micro_experts(spec: dict[str, Any], plan_markdown: str, artifacts: dict[str, str], codex_evidence: dict[str, Any]) -> dict[str, Any]:
    """Validate Agent 1 micro-expert handoffs before parent graph accepts spec."""
    validate_architecture_spec(spec)
    validate_agent1_v37_spec_schema(spec)
    validate_agent1_v4_spec_schema(spec)
    required_artifacts = {
        "agent1_codex_response.md",
        "agent1_codex_evidence.json",
        "agent1_ai_requirement_analysis.json",
        "agent1_expert_council_trace.jsonl",
        "agent1_capability_assessment.json",
        "agent1_requirement_consistency_report.json",
        "agent1_intake_router_report.json",
        "agent1_requirement_citation_ledger.json",
        "agent1_policy_matrix.json",
        "agent1_prompt_pack_manifest.json",
        "agent1_intake.json",
        "agent1_domain_classification.json",
        "agent1_architecture_options.md",
        "agent1_tool_evidence.json",
        "agent1_contract_manifest.json",
        "agent1_memory_interface_plan.json",
        "agent1_register_map.rdl",
        f"fw_{spec['project_name']}_regs.h",
        f"fw_{spec['project_name']}_driver_stub.c",
        f"tb_{spec['project_name']}_reg_model.py",
        "agent1_verification_strategy.md",
        "agent1_review_scorecard.md",
        "agent1_plan_quality_report.json",
        "agent1_hw_sw_codesign_plan.json",
        "agent1_io_packaging_plan.json",
        "agent1_clock_power_plan.json",
        "agent1_interconnect_qos_plan.json",
        "agent1_memory_hierarchy_plan.json",
        "agent1_dft_plan.json",
        "agent1_safety_security_plan.json",
        "agent1_ip_reuse_cost_plan.json",
        "agent1_cross_validation_matrix.json",
        "agent1_validation_decisions.json",
        "agent1_revision_history.json",
        "agent1_v3_super_committee_report.md",
    }
    checks = {
        "all_micro_experts_present": len(V3_SUPER_COMMITTEE_NODES) >= 20,
        "required_artifacts_present": required_artifacts.issubset(artifacts),
        "codex_evidence_present": all(codex_evidence.get(key) for key in ("base_url", "model")) and "timestamp" in codex_evidence,
        "tool_evidence_present": bool(spec.get("ppa_estimate") and spec.get("bandwidth_estimate")),
        "mermaid_plan_present": "```mermaid" in plan_markdown and "flowchart TD" in plan_markdown and "stateDiagram-v2" in plan_markdown,
        "ascii_block_diagram_absent": "```text" not in plan_markdown,
        "dynamic_project_in_plan": f"Project: {spec['project_name']}" in plan_markdown,
        "apb_pinout_locked": spec["constraints"].get("agent2_port_renaming_allowed") is False,
        "v3_feedback_loops_present": "REJECT" in plan_markdown and "Safety_Security_vs_MemoryMap_Validator" in plan_markdown,
        "v35_artifacts_present": all(name in artifacts for name in ("agent1_register_map.rdl", f"fw_{spec['project_name']}_regs.h", f"fw_{spec['project_name']}_driver_stub.c", f"tb_{spec['project_name']}_reg_model.py")),
        "v35_cross_checks_present": "RDL_vs_CHeader_Validator" in artifacts.get("agent1_validation_decisions.json", "") and "RDL_vs_DVModel_Validator" in artifacts.get("agent1_validation_decisions.json", ""),
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {"pass": not failures, "checks": checks, "failures": failures}


def _codex_prompt(requirement: str, project_name: str) -> str:
    return "\n".join([
        "# SYSTEM PROMPT — Agent 1: Semiconductor System Architect",
        "You are a senior semiconductor system architect with 20+ years experience.",
        "Do not calculate PPA or bandwidth. Tools calculate numeric values.",
        "Return architecture reasoning only: parsed requirement, domain, candidates, risks.",
        "Run 16+ expert Super Committee V3.5 review with SystemRDL, firmware header/driver, cocotb reg model, and cross-validation; validators must emit ACCEPT/REJECT/HITL_REQUIRED JSON.",
        f"Project: {project_name}",
        f"Requirement: {requirement}",
    ])


def _run_v3_super_committee(spec: dict[str, Any]) -> dict[str, Any]:
    artifacts: dict[str, str] = {}
    decisions: list[dict[str, Any]] = []
    revisions: list[dict[str, Any]] = []
    spec_ext = _build_v3_spec_extensions(spec)
    artifacts.update(_build_v3_artifacts(spec, spec_ext))

    for validator in (_validate_hwsw_register_map, _validate_safety_security_memory_map, _validate_rdl_c_header, _validate_rdl_dv_model, _validate_clock_power_bus, _validate_memory_hierarchy_qos, _validate_dft_io_clock_power):
        decision = validator(spec)
        decisions.append(decision)
        print(f"[Validation] {decision['validator']} checking -> Result: {decision['decision']} ({'; '.join(f['problem'] for f in decision['findings']) or 'OK'})")
        if decision["decision"] == "REJECT":
            repaired = _repair_spec_for_decision(spec, decision)
            revisions.append(_repair_record(spec, repaired, decision, 1))
            spec.clear()
            spec.update(repaired)
            decision2 = validator(spec)
            decisions.append(decision2)
            print(f"[Validation] {decision2['validator']} recheck after repair -> Result: {decision2['decision']} ({'; '.join(f['problem'] for f in decision2['findings']) or 'OK'})")

    artifacts["agent1_cross_validation_matrix.json"] = json.dumps({"validators": V3_VALIDATION_NODES, "nodes": V3_SUPER_COMMITTEE_NODES}, indent=2, sort_keys=True)
    artifacts["agent1_validation_decisions.json"] = json.dumps(decisions, indent=2, sort_keys=True)
    artifacts["agent1_revision_history.json"] = json.dumps(revisions, indent=2, sort_keys=True)
    artifacts["agent1_v3_super_committee_report.md"] = _v3_report(decisions, revisions)
    return {"artifacts": artifacts, "spec_extensions": spec_ext, "decisions": decisions, "revisions": revisions}


def _build_v3_spec_extensions(spec: dict[str, Any]) -> dict[str, Any]:
    clocks = spec.get("clock_domains", [])
    masters = spec.get("bus_topology", {}).get("masters") or ["external_apb_host"]
    priority_map = {str(master): index for index, master in enumerate(masters)}
    return {
        "firmware_contract": spec.get("firmware_contract", {"hal_modules": ["generic_hal"], "interrupt_flow": [], "register_access_semantics": {}}),
        "io_packaging": {"pins": ["clk_i", "rst_ni"], "power_pins": ["VDD"], "ground_pins": ["VSS"], "esd_assumptions": ["standard digital IO ESD cells"]},
        "power_intent": {"power_domains": ["PD_CORE"], "upf_required": False, "isolation_rules": [], "retention_rules": []},
        "cdc_rdc_plan": {"clock_crossings": [], "reset_crossings": [{"reset": c.get("reset", "rst_ni"), "domain": c.get("name", "core_clk")} for c in clocks], "required_cells": []},
        "interconnect_qos": {"arbitration": "fixed_priority", "priority_map": priority_map, "timeout_policy": {"cycles": 16}, "deadlock_avoidance": ["single APB master/access path"]},
        "memory_hierarchy": {"levels": ["APB register file"], "latency_budget_cycles": {"apb": 2}, "bandwidth_budget_mb_s": {"apb": spec.get("bandwidth_estimate", {}).get("bandwidth_mb_s", 0)}},
        "dft_plan": {"jtag": {"planned": True}, "scan_chains": ["core_scan_chain_0"], "mbist": [], "test_modes": ["scan_enable", "test_reset"]},
        "safety_security": {"iso26262_assumptions": ["not certified unless safety plan expanded"], "threat_model": ["APB software may attempt unauthorized secret register write"], "protected_registers": []},
        "ip_reuse_cost": {"reuse_candidates": [block["name"] for block in spec.get("ip_blocks", [])], "buy_vs_build": ["build baseline RTL"], "die_area_risk": "medium"},
    }


def _build_v3_artifacts(spec: dict[str, Any], ext: dict[str, Any]) -> dict[str, str]:
    return {
        "agent1_hw_sw_codesign_plan.json": json.dumps(ext["firmware_contract"], indent=2, sort_keys=True),
        "agent1_io_packaging_plan.json": json.dumps(ext["io_packaging"], indent=2, sort_keys=True),
        "agent1_clock_power_plan.json": json.dumps({"power_intent": ext["power_intent"], "cdc_rdc_plan": ext["cdc_rdc_plan"]}, indent=2, sort_keys=True),
        "agent1_interconnect_qos_plan.json": json.dumps(ext["interconnect_qos"], indent=2, sort_keys=True),
        "agent1_memory_hierarchy_plan.json": json.dumps(ext["memory_hierarchy"], indent=2, sort_keys=True),
        "agent1_dft_plan.json": json.dumps(ext["dft_plan"], indent=2, sort_keys=True),
        "agent1_safety_security_plan.json": json.dumps(ext["safety_security"], indent=2, sort_keys=True),
        "agent1_ip_reuse_cost_plan.json": json.dumps(ext["ip_reuse_cost"], indent=2, sort_keys=True),
    }


def _iter_registers(spec: dict[str, Any]):
    for block, entry in spec.get("memory_map", {}).items():
        base = entry.get("base", "0x00000000")
        for reg, meta in entry.get("registers", {}).items():
            yield block, base, reg, meta


def _access(meta: dict[str, Any]) -> str:
    if str(meta.get("access", "")).lower() in {"rw", "ro", "wo", "w1c"}:
        return str(meta["access"]).lower()
    if meta.get("clear") == "W1C":
        return "w1c"
    name = str(meta.get("name", "")).lower()
    if "status" in name:
        return "ro"
    if meta.get("write_only") or meta.get("sensitive"):
        return "wo"
    return "rw"


def _reg_define_prefix(project: str, block: str, reg: str) -> str:
    return f"{project}_{block}_{reg}".upper()


def _systemrdl_artifact(spec: dict[str, Any]) -> str:
    lines = ["// Auto-generated by Agent 1 V3.5", "addrmap agent1_register_map {"]
    for block, entry in spec.get("memory_map", {}).items():
        base = entry.get("base", "0x00000000")
        lines.append(f"  // block {block} base {base}")
        for reg, meta in entry.get("registers", {}).items():
            access = _access({**meta, "name": reg})
            reset = meta.get("reset", "0")
            width = int(meta.get("width_bits", 32))
            sw = "r" if access == "ro" else ("w" if access == "wo" else "rw")
            hw = "rw" if access in {"ro", "w1c"} else "r"
            lines.extend([
                f"  reg {reg} {{",
                f"    field {{ sw = {sw}; hw = {hw}; reset = {reset}; }} value[{width - 1}:0];",
                f"    // access={access} sw_mask=0xFFFFFFFF hw_mask=0xFFFFFFFF",
                f"  }} {reg} @ {meta.get('offset', '0x00')};",
            ])
    lines.append("};")
    return "\n".join(lines) + "\n"


def _firmware_header_artifact(spec: dict[str, Any]) -> str:
    project = spec["project_name"]
    guard = f"FW_{project}_REGS_H".upper()
    lines = ["/* Auto-generated by Agent 1 V3.5 */", f"#ifndef {guard}", f"#define {guard}", "", "#include <stdint.h>", ""]
    for block, entry in spec.get("memory_map", {}).items():
        lines.append(f"#define {_reg_define_prefix(project, block, 'base')}  {entry.get('base', '0x00000000')}u")
        for reg, meta in entry.get("registers", {}).items():
            prefix = _reg_define_prefix(project, block, reg)
            lines.append(f"#define {prefix}_OFFSET  {meta.get('offset', '0x00')}u")
            lines.append(f"#define {prefix}_RESET   {meta.get('reset', '0')}u")
            lines.append(f"#define {prefix}_MASK    0xFFFFFFFFu")
    lines.extend(["", f"#endif /* {guard} */", ""])
    return "\n".join(lines)


def _firmware_driver_stub_artifact(spec: dict[str, Any]) -> str:
    project = spec["project_name"]
    lines = ["/* Auto-generated by Agent 1 V3.5 */", f"#include \"fw_{project}_regs.h\"", "", "static inline uint32_t reg_read(uintptr_t addr) { return *(volatile uint32_t *)addr; }", "static inline void reg_write(uintptr_t addr, uint32_t value) { *(volatile uint32_t *)addr = value; }", "", f"void {project}_init(void) {{", "  /* reset software-visible RW registers to documented reset values */", "}", "", f"void {project}_clear_interrupt(uintptr_t block_base, uint32_t mask) {{", "  reg_write(block_base + 0x14u, mask);", "}", ""]
    for block, base, reg, meta in _iter_registers(spec):
        access = _access({**meta, "name": reg})
        fn = f"{project}_{block}_{reg}"
        lines.append(f"uint32_t {fn}_read(void) {{ return reg_read({_reg_define_prefix(project, block, 'base')} + {_reg_define_prefix(project, block, reg)}_OFFSET); }}")
        if access != "ro":
            lines.append(f"void {fn}_write(uint32_t value) {{ reg_write({_reg_define_prefix(project, block, 'base')} + {_reg_define_prefix(project, block, reg)}_OFFSET, value); }}")
    return "\n".join(lines) + "\n"


def _cocotb_reg_model_artifact(spec: dict[str, Any]) -> str:
    project = spec["project_name"]
    lines = ["# Auto-generated by Agent 1 V3.5", "from dataclasses import dataclass", "", "@dataclass(frozen=True)", "class Register:", "    name: str", "    block: str", "    base: int", "    offset: int", "    width_bits: int", "    reset: int", "    access: str", "", f"class {project.title().replace('_', '')}RegModel:", "    def __init__(self):", "        self.registers = {}"]
    for block, base, reg, meta in _iter_registers(spec):
        access = _access({**meta, "name": reg})
        attr = f"{block}_{reg}"
        lines.append(f"        self.{attr} = Register('{reg}', '{block}', int('{base}', 16), int('{meta.get('offset', '0x00')}', 16), {int(meta.get('width_bits', 32))}, int('{meta.get('reset', '0')}', 0), '{access}')")
        lines.append(f"        self.registers['{block}.{reg}'] = self.{attr}")
    lines.extend(["", "    def addr(self, name: str) -> int:", "        reg = self.registers[name]", "        return reg.base + reg.offset", ""])
    return "\n".join(lines)


def _expected_v35_tokens(spec: dict[str, Any]) -> dict[str, list[str]]:
    project = spec["project_name"]
    header = []
    model = []
    for block, _base, reg, meta in _iter_registers(spec):
        header.append(f"#define {_reg_define_prefix(project, block, reg)}_OFFSET  {meta.get('offset', '0x00')}u")
        model.append(f"self.{block}_{reg} = Register")
    return {"header": header, "model": model}


def _validate_safety_security_memory_map(spec: dict[str, Any]) -> dict[str, Any]:
    findings = []
    findings.extend(_validate_memory_ranges(spec.get("memory_map", {})))
    for block, entry in spec.get("memory_map", {}).items():
        for reg, meta in entry.get("registers", {}).items():
            name = f"{block}.{reg}".lower()
            sensitive = meta.get("sensitive") or any(t in name for t in ("secret", "key", "debug", "boot", "dma"))
            protected = meta.get("privileged") or meta.get("write_once") or meta.get("lock_bit") or meta.get("keyed_unlock")
            if sensitive and not protected:
                findings.append({"id": "SEC_REG_001", "artifact": "agent1_memory_interface_plan.json", "field": f"memory_map.{block}.{reg}", "problem": "Sensitive register lacks privileged/write_once/lock_bit protection.", "required_change": "Add privileged=True, write_once=True, lock_bit, safe reset, and formal property."})
    return _decision("Safety_Security_vs_MemoryMap_Validator", "REJECT" if findings else "ACCEPT", "Memory_Map_Interface_Expert" if findings else None, findings)


def _parse_int_value(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            return None
    return None


def _validate_memory_ranges(memory_map: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    ranges: list[tuple[int, int, str]] = []
    for block, entry in memory_map.items():
        base = _parse_int_value(entry.get("base"))
        size = _parse_int_value(entry.get("size", entry.get("size_bytes", entry.get("range_bytes"))))
        if base is None:
            findings.append({"id": "MEM_RANGE_001", "artifact": "agent1_memory_interface_plan.json", "field": f"memory_map.{block}.base", "problem": "Memory block has missing or invalid base address.", "required_change": "Set base to valid integer or hex string."})
            continue
        if size is None:
            size = _infer_block_size_bytes(entry)
        if size is None or size <= 0:
            findings.append({"id": "MEM_RANGE_002", "artifact": "agent1_memory_interface_plan.json", "field": f"memory_map.{block}.size", "problem": f"Memory block has invalid size {entry.get('size', entry.get('size_bytes', entry.get('range_bytes')))}.", "required_change": "Set size/size_bytes/range_bytes to positive value or define registers with offsets."})
            continue
        if base % 0x1000 != 0:
            findings.append({"id": "MEM_RANGE_003", "artifact": "agent1_memory_interface_plan.json", "field": f"memory_map.{block}.base", "problem": f"memory_map.{block} base 0x{base:X} is not 4KB aligned", "required_change": "Align base address to 4KB boundary."})
        ranges.append((base, base + size, block))
    ranges.sort(key=lambda item: item[0])
    for previous, current in zip(ranges, ranges[1:]):
        prev_start, prev_end, prev_block = previous
        cur_start, cur_end, cur_block = current
        if cur_start < prev_end:
            findings.append({"id": "MEM_RANGE_004", "artifact": "agent1_memory_interface_plan.json", "field": f"memory_map.{cur_block}.base", "problem": f"memory_map.{cur_block} range 0x{cur_start:X}-0x{cur_end:X} overlaps {prev_block} range 0x{prev_start:X}-0x{prev_end:X}", "required_change": "Move block base or shrink size so address ranges do not overlap."})
    return findings


def _infer_block_size_bytes(entry: dict[str, Any]) -> int | None:
    max_end = 0
    for meta in entry.get("registers", {}).values():
        offset = _parse_int_value(meta.get("offset", "0x0"))
        width_bits = _parse_int_value(meta.get("width_bits", 32))
        if offset is None or width_bits is None or width_bits <= 0:
            return None
        width_bytes = max(4, (width_bits + 7) // 8)
        max_end = max(max_end, offset + width_bytes)
    if max_end <= 0:
        return None
    return ((max_end + 0xFFF) // 0x1000) * 0x1000


def _validate_hwsw_register_map(spec: dict[str, Any]) -> dict[str, Any]:
    findings = []
    for block, entry in spec.get("memory_map", {}).items():
        regs = entry.get("registers", {})
        if "irq_status" in regs and regs["irq_status"].get("clear") not in {"W1C", "read_clear"}:
            findings.append({"id": "HWSW_IRQ_001", "artifact": "agent1_memory_interface_plan.json", "field": f"memory_map.{block}.irq_status", "problem": "Interrupt status clear semantics missing W1C/read_clear.", "required_change": "Set clear to W1C."})
        if "irq_status" in regs and "irq_enable" not in regs and "irq_mask" not in regs:
            findings.append({"id": "HWSW_IRQ_002", "artifact": "agent1_memory_interface_plan.json", "field": f"memory_map.{block}", "problem": "Interrupt source lacks irq_enable/irq_mask.", "required_change": "Add irq_enable or irq_mask register."})
    return _decision("HWSW_vs_RegisterMap_Validator", "REJECT" if findings else "ACCEPT", "Memory_Map_Interface_Expert" if findings else None, findings)


def _validate_rdl_c_header(spec: dict[str, Any]) -> dict[str, Any]:
    findings = []
    rdl = _systemrdl_artifact(spec)
    header = _firmware_header_artifact(spec)
    stub = _firmware_driver_stub_artifact(spec)
    for block, _base, reg, meta in _iter_registers(spec):
        if f"reg {reg}" not in rdl or str(meta.get("offset", "0x00")) not in rdl:
            findings.append({"id": "RDL_HDR_001", "artifact": "agent1_register_map.rdl", "field": f"memory_map.{block}.{reg}", "problem": "RDL missing register or offset.", "required_change": "Regenerate SystemRDL from JSON memory_map."})
    for token in _expected_v35_tokens(spec)["header"]:
        if token not in header:
            findings.append({"id": "RDL_HDR_002", "artifact": f"fw_{spec['project_name']}_regs.h", "field": token, "problem": "C header offset mismatches JSON/RDL.", "required_change": "Regenerate firmware header from JSON memory_map."})
    if f"void {spec['project_name']}_init(void)" not in stub:
        findings.append({"id": "RDL_HDR_003", "artifact": f"fw_{spec['project_name']}_driver_stub.c", "field": "init", "problem": "Firmware reset/init function missing.", "required_change": "Add init/reset skeleton."})
    return _decision("RDL_vs_CHeader_Validator", "REJECT" if findings else "ACCEPT", "HW_SW_CoDesign_Expert" if findings else None, findings)


def _validate_rdl_dv_model(spec: dict[str, Any]) -> dict[str, Any]:
    findings = []
    model = _cocotb_reg_model_artifact(spec)
    for token in _expected_v35_tokens(spec)["model"]:
        if token not in model:
            findings.append({"id": "RDL_DV_001", "artifact": f"tb_{spec['project_name']}_reg_model.py", "field": token, "problem": "Cocotb register model missing JSON/RDL register.", "required_change": "Regenerate DV register model from JSON memory_map."})
    return _decision("RDL_vs_DVModel_Validator", "REJECT" if findings else "ACCEPT", "Verification_Strategy_Expert" if findings else None, findings)


def _validate_clock_power_bus(spec: dict[str, Any]) -> dict[str, Any]:
    findings = []
    if len(spec.get("clock_domains", [])) > 1 and not spec.get("cdc_rdc_plan", {}).get("clock_crossings"):
        findings.append({"id": "CDC_001", "artifact": "agent1_clock_power_plan.json", "field": "cdc_rdc_plan.clock_crossings", "problem": "Multiple clocks without CDC plan.", "required_change": "Add CDC bridge/synchronizer/async FIFO."})
    return _decision("ClockPower_vs_Bus_Validator", "REJECT" if findings else "ACCEPT", "Clock_Power_Expert" if findings else None, findings)


def _validate_memory_hierarchy_qos(spec: dict[str, Any]) -> dict[str, Any]:
    findings = []
    hierarchy = spec.get("memory_hierarchy", {})
    qos = spec.get("interconnect_qos", {})
    latency = hierarchy.get("latency_budget_cycles", {})
    timeout_cycles = qos.get("timeout_policy", {}).get("cycles")
    if timeout_cycles is not None and latency and max(latency.values()) > timeout_cycles:
        findings.append({"id": "MEM_QOS_001", "artifact": "agent1_memory_hierarchy_plan.json", "field": "memory_hierarchy.latency_budget_cycles", "problem": "Memory latency budget exceeds interconnect timeout policy.", "required_change": "Increase timeout policy or reduce latency budget."})
    if qos.get("arbitration") == "fixed_priority" and len(spec.get("bus_topology", {}).get("slaves", [])) > 8 and not qos.get("starvation_policy"):
        findings.append({"id": "MEM_QOS_002", "artifact": "agent1_interconnect_qos_plan.json", "field": "interconnect_qos.starvation_policy", "problem": "Many slaves with fixed priority lack starvation policy.", "required_change": "Add aging/round-robin/weighted fairness policy."})
    return _decision("MemoryHierarchy_vs_QoS_Validator", "REJECT" if findings else "ACCEPT", "Memory_Hierarchy_Expert" if findings else None, findings)


def _validate_dft_io_clock_power(spec: dict[str, Any]) -> dict[str, Any]:
    findings = []
    dft = spec.get("dft_plan", {})
    io = spec.get("io_packaging", {})
    pins = set(io.get("pins", []))
    test_modes = set(dft.get("test_modes", []))
    if dft.get("jtag", {}).get("planned") and not {"tck", "tms", "tdi", "tdo"}.issubset(pins):
        findings.append({"id": "DFT_IO_001", "artifact": "agent1_io_packaging_plan.json", "field": "io_packaging.pins", "problem": "JTAG planned but JTAG pins missing from IO package plan.", "required_change": "Add tck/tms/tdi/tdo or mark JTAG not planned."})
    if dft.get("scan_chains") and not {"scan_enable", "test_reset"}.issubset(test_modes):
        findings.append({"id": "DFT_CLK_001", "artifact": "agent1_dft_plan.json", "field": "dft_plan.test_modes", "problem": "Scan chains lack explicit scan_enable/test_reset modes.", "required_change": "Add scan_enable and test_reset modes."})
    return _decision("DFT_vs_IO_ClockPower_Validator", "REJECT" if findings else "ACCEPT", "IO_Packaging_Expert" if findings else None, findings)


def _decision(validator: str, decision: str, target_node: str | None, findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {"validator": validator, "decision": decision, "target_node": target_node, "severity": "BLOCKER" if findings else "INFO", "findings": findings, "revision": 1, "max_revisions": 3}


def _repair_spec_for_decision(spec: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    spec = copy.deepcopy(spec)
    changed = []
    if decision["validator"] == "Safety_Security_vs_MemoryMap_Validator":
        for block, entry in spec.get("memory_map", {}).items():
            for reg, meta in entry.get("registers", {}).items():
                name = f"{block}.{reg}".lower()
                if meta.get("sensitive") or any(t in name for t in ("secret", "key", "debug", "boot", "dma")):
                    meta.update({"privileged": True, "write_once": True, "lock_bit": f"{reg}_lock", "formal_property": "assert_no_unprivileged_write_after_lock"})
                    changed.append(f"{block}.{reg}")
    if decision["validator"] == "DFT_vs_IO_ClockPower_Validator":
        pins = spec.setdefault("io_packaging", {}).setdefault("pins", [])
        for pin in ("tck", "tms", "tdi", "tdo"):
            if pin not in pins:
                pins.append(pin)
                changed.append(f"io_packaging.pins.{pin}")
    if decision["validator"] == "MemoryHierarchy_vs_QoS_Validator":
        spec.setdefault("interconnect_qos", {}).setdefault("starvation_policy", "round_robin_aging")
        changed.append("interconnect_qos.starvation_policy")
    spec.setdefault("_agent1_repair_metadata", []).append({"validator": decision["validator"], "target_node": decision["target_node"], "changed": changed})
    return spec


def _repair_record(before: dict[str, Any], after: dict[str, Any], decision: dict[str, Any], revision_count: int) -> dict[str, Any]:
    metadata = after.get("_agent1_repair_metadata", [])[-1] if after.get("_agent1_repair_metadata") else {}
    return {
        "validator": decision.get("validator"),
        "target_node": decision.get("target_node"),
        "decision": decision.get("decision"),
        "findings": decision.get("findings", []),
        "revision_count": revision_count,
        "before_summary": _spec_summary(before),
        "after_summary": _spec_summary(after),
        "changed": metadata.get("changed", []),
        "route_back_to": decision.get("validator") if decision.get("validator") in VALIDATOR_FUNCTIONS else "hitl_plan_review",
    }


def _spec_summary(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "memory_blocks": sorted(spec.get("memory_map", {}).keys()),
        "repair_count": len(spec.get("_agent1_repair_metadata", [])),
        "has_safety_security": bool(spec.get("safety_security")),
    }


def _v3_report(decisions: list[dict[str, Any]], revisions: list[dict[str, Any]]) -> str:
    lines = ["# Agent 1 V3.5 Super Committee Report", "", f"Nodes: {len(V3_SUPER_COMMITTEE_NODES)}", "", "## Validation Decisions"]
    lines.extend(f"- {d['validator']}: {d['decision']} findings={len(d['findings'])}" for d in decisions)
    lines.extend(["", "## Revision History"])
    lines.extend(f"- {r['target_node']}: {', '.join(r.get('changed', [])) or 'no change'} -> {r.get('route_back_to')}" for r in revisions)
    return "\n".join(lines) + "\n"


def _v3_committee_markdown(v3: dict[str, Any]) -> str:
    return "\n".join(["## Agent 1 V3.5 Super Committee LangGraph", "", "```mermaid", "flowchart TD", "  MEM[Memory_Map_Interface_Expert] --> RDL[agent1_register_map.rdl]", "  MEM --> HWSW[HW_SW_CoDesign_Expert]", "  HWSW --> FW[fw_project_regs.h + fw_project_driver_stub.c]", "  MEM --> VER[Verification_Strategy_Expert]", "  VER --> DVM[tb_project_reg_model.py]", "  HWSW --> VALH{HWSW_vs_RegisterMap_Validator}", "  VALH -- ACCEPT --> SEC[Safety_Security_Analyst]", "  VALH -- REJECT --> MEM", "  SEC --> VALS{Safety_Security_vs_MemoryMap_Validator}", "  VALS -- ACCEPT --> VALFH{RDL_vs_CHeader_Validator}", "  VALS -- REJECT --> MEM", "  RDL --> VALFH", "  FW --> VALFH", "  VALFH -- ACCEPT --> VALDV{RDL_vs_DVModel_Validator}", "  VALFH -- REJECT --> HWSW", "  RDL --> VALDV", "  DVM --> VALDV", "  VALDV -- ACCEPT --> QOS[Interconnect_QoS_Expert]", "  VALDV -- REJECT --> VER", "  CP[Clock_Power_Expert] --> VALC{ClockPower_vs_Bus_Validator}", "  QOS --> VALC", "  VALC -- ACCEPT --> VALM{MemoryHierarchy_vs_QoS_Validator}", "  VALC -- REJECT --> CP", "  MEMH[Memory_Hierarchy_Expert] --> VALM", "  QOS --> VALM", "  VALM -- ACCEPT --> DFT[DFT_Lead]", "  VALM -- REJECT --> MEMH", "  DFT --> VALD{DFT_vs_IO_ClockPower_Validator}", "  IO[IO_Packaging_Expert] --> VALD", "  CP --> VALD", "  VALD -- ACCEPT --> REVIEW[Principal_Architect_Reviewer]", "  VALD -- REJECT --> IO", "  VALH --> ROUTER{Super_Committee_Review_Router}", "  VALS --> ROUTER", "  VALFH --> ROUTER", "  VALDV --> ROUTER", "  VALC --> ROUTER", "  VALM --> ROUTER", "  VALD --> ROUTER", "  ROUTER -- all validators ACCEPT --> REVIEW", "  ROUTER -- targeted REJECT --> MEM", "  ROUTER -- targeted REJECT --> HWSW", "  ROUTER -- targeted REJECT --> VER", "  ROUTER -- too many revisions --> HITL[HITL_Plan_Review]", "  VALC -- HITL_REQUIRED --> HITL", "```", "", "## V3.5 Decisions", *[f"- {d['validator']}: {d['decision']}" for d in v3['decisions']], ""])


def _intake_artifact(requirement: str, spec: dict[str, Any]) -> dict[str, Any]:
    constraints = spec["constraints"]
    clock = spec["clock_domains"][0]
    return {
        "requirement_raw": requirement,
        "project_name": spec["project_name"],
        "must": {
            "frequency_mhz": clock["frequency_mhz"],
            "formal_first": constraints["formal_first"],
            "locked_apb_pinout": True,
        },
        "should": {"power_budget_mw": constraints.get("power_budget_mw")},
        "could": {"accelerator": spec["accelerator"]["type"]},
        "unknown": [field for field, value in {"power_budget_mw": constraints.get("power_budget_mw")}.items() if value is None],
    }


def _domain_artifact(spec: dict[str, Any]) -> dict[str, Any]:
    domain = spec["requirements"]["application_domain"]
    return {
        "project_type": domain,
        "domain": domain,
        "ambiguity_risk": "low" if spec["constraints"].get("power_budget_mw") is not None else "medium",
        "missing_information": ["power_budget_mw"] if spec["constraints"].get("power_budget_mw") is None else [],
        "interfaces": sorted(spec["interfaces"].keys()),
    }


def _memory_interface_artifact(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "memory_map": spec["memory_map"],
        "bus_topology": spec["bus_topology"],
        "interfaces": spec["interfaces"],
        "clock_reset": spec["clock_domains"],
        "interrupt_owners": [
            block["name"]
            for block in spec["ip_blocks"]
            if "interrupt" in block["name"]
            or block["name"] in {"timer", "dma_engine"}
            or "irq_status" in spec.get("memory_map", {}).get(block["name"], {}).get("registers", {})
        ],
    }


def _architecture_options(spec: dict[str, Any]) -> str:
    freq = spec['core_config']['frequency_mhz']
    bus = spec['bus_topology']['protocol']
    sram_blocks = "yes" if any(block["name"] == "sram_controller" for block in spec["ip_blocks"]) else "no"
    return "\n".join([
        "# Agent 1 Architecture Options",
        "",
        "| Option | Bus | Memory | Accelerator | Clocking | Verification risk | Decision |",
        "|---|---|---|---|---|---|---|",
        f"| Selected formal-first baseline | {bus} | SRAM controller: {sram_blocks} | {spec['accelerator']['type']} | single {freq}MHz core_clk | Low | Selected |",
        f"| Wider APB data path | {bus} wider data width | same map | {spec['accelerator']['type']} | single {freq}MHz core_clk | Medium | Use only if bandwidth fails |",
        f"| Split accelerator clock | {bus} bridge | same map plus CDC | {spec['accelerator']['type']} | core_clk + accel_clk | High | Reject until CDC need exists |",
        "",
    ])


def _verification_strategy(blocks: list[str]) -> str:
    lines = ["# Agent 1 Verification Strategy", "", "Formal-first properties per block:"]
    lines.extend(f"- {block}: reset safety, APB handshake, no X-visible outputs" for block in blocks)
    lines.extend(["", "DV scenarios: APB read/write, reset, interrupt, DMA/MAC paths when present.", "Cocotb register model required: tb_<project_name>_reg_model.py mirrors JSON/SystemRDL register map for named register access.", ""])
    return "\n".join(lines)


def _review_scorecard(spec: dict[str, Any]) -> str:
    return "\n".join([
        "# Agent 1 Review Scorecard",
        "",
        f"Project: {spec['project_name']}",
        "Schema compatibility: PASS",
        "APB pinout locked: PASS",
        "Tool-backed PPA/bandwidth: PASS",
        "Mermaid diagrams: PASS",
        "",
    ])
