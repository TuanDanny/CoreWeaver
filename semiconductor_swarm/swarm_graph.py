"""LangGraph orchestrator for the five-agent semiconductor swarm."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Literal, Sequence, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from semiconductor_swarm.agents.agent1_planning.agent1_subgraph import Agent1CodexUnavailable, run_agent1_hierarchical_planning
from semiconductor_swarm.agents.agent1_planning.architect import generate_architecture_plan_markdown, generate_architecture_spec, requirement_needs_clarification, sanitize_project_name
from semiconductor_swarm.agents.agent3_dv.dv_engineer import generate_dv_files, run_cocotb_sim, verify_dv_files, write_agent3_runtime_failure
from semiconductor_swarm.agents.agent5_formal.formal_verifier import generate_formal_files, prove_formal_with_symbiyosys, verify_formal_files
from semiconductor_swarm.agents.agent4_physical.physical_designer import compile_physical_design, decide_backend_action, generate_physical_design_files, verify_physical_design_files
from semiconductor_swarm.agents.agent2_rtl.rtl_designer import apply_agent2_fix_request, generate_rtl_files, synthesize_rtl_with_quartus, verify_rtl_files
from semiconductor_swarm.contracts.handoffs import (
    build_agent2_to_agent3_contract,
    build_agent2_to_agent4_contract,
    build_agent2_to_agent5_contract,
    build_agent_result_contract,
    build_swarm_artifact_index,
    build_swarm_to_docs_agent_contract,
)
from semiconductor_swarm.contracts.envelope import ContractEnvelope
from semiconductor_swarm.contracts.validators import build_agent1_to_agent2_contract, validate_agent1_to_agent2_contract
from semiconductor_swarm.runtime_events import emit_runtime_event
from semiconductor_swarm.tools.tool_detection import detect_real_tools


class SwarmState(TypedDict, total=False):
    """Shared state passed through all LangGraph nodes."""

    requirement: str
    project_name: str
    output_dir: str
    thread_id: str
    spec: dict[str, Any]
    rtl_files: list[dict[str, Any]]
    formal_files: list[dict[str, Any]]
    dv_files: list[dict[str, Any]]
    physical_files: list[dict[str, Any]]
    reports: dict[str, Any]
    run_real_tools: bool
    strict_signoff: bool
    max_debug_iterations: int
    debug_iterations: int
    hitl_reviews: list[dict[str, Any]]
    hitl_approved: bool
    status: str
    plan_path: str
    plan_markdown: str
    plan_approved: bool
    incremental_changes: list[dict[str, Any]]
    agent2_fix_request: dict[str, Any]
    agent2_codex_required: bool
    timing_closure_history: list[dict[str, Any]]
    agent1_artifacts: dict[str, str]
    agent2_to_agent3_contract: dict[str, Any]
    agent2_to_agent4_contract: dict[str, Any]
    agent2_to_agent5_contract: dict[str, Any]
    agent3_result_contract: dict[str, Any]
    agent4_result_contract: dict[str, Any]
    agent5_result_contract: dict[str, Any]
    swarm_artifact_index: dict[str, Any]
    contract_envelopes: dict[str, dict[str, Any]]


def agent1_architect_node(state: SwarmState) -> dict[str, Any]:
    current_requirement = state["requirement"]
    working_state: SwarmState = dict(state)
    for _attempt in range(3):
        result = _run_agent1_or_pause(working_state, current_requirement)
        if result.get("requires_clarification"):
            _write_agent1_artifacts(working_state, result["agent1_artifacts"])
            clarification_path = _write_requirement_clarification(working_state, result.get("clarification_markdown", ""))
            intake_report = result.get("intake_report", {})
            _log_status(working_state, "Planning", f"requirement clarification requested at {clarification_path}")
            payload = {
                "action_required": "REQUIREMENT_CLARIFICATION",
                "message": intake_report.get("user_response") or "Agent 1 needs a concrete chip requirement before architecture planning.",
                "project_name": working_state.get("project_name", "swarm_soc"),
                "plan_path": str(clarification_path),
                "artifact_path": str(clarification_path),
                "missing_fields": intake_report.get("missing_fields", []),
                "brief_form": intake_report.get("brief_form", {}),
                "classification": intake_report.get("classification"),
                "consensus_score": intake_report.get("consensus_score"),
                "calibrated_confidence": intake_report.get("calibrated_confidence"),
                "policy_matrix": intake_report.get("policy_matrix", {}),
                "resume_with": {"response": "Generate a 32-bit CPU using APB with UART, 50MHz, 28nm"},
            }
            answer = interrupt(payload)
            response = answer.get("response", answer.get("notes", answer.get("change", ""))) if isinstance(answer, dict) else str(answer)
            current_requirement = f"{current_requirement}\nClarification: {response}".strip()
            working_state = {**working_state, "requirement": current_requirement, "clarification_done": True}
            continue
        return _release_agent1_plan(working_state, current_requirement, result)
    raise RuntimeError("Agent 1 still needs clarification after 3 attempts; stop before Agent 2.")

    if _requirement_is_ambiguous(state.get("requirement", "")) and not state.get("clarification_done"):
        payload = {
            "action_required": "REQUIREMENT_CLARIFICATION",
            "message": "Yêu cầu quá rộng. Sếp cần chuẩn giao tiếp nào (AXI/APB)? Tốc độ bao nhiêu MHz? Giới hạn Power là bao nhiêu?",
            "resume_with": {"response": "APB, 100MHz, <1W"},
        }
        answer = interrupt(payload)
        response = answer.get("response", answer.get("notes", "")) if isinstance(answer, dict) else str(answer)
        requirement = f"{state.get('requirement', '')}\nClarification: {response}".strip()
        result = _run_agent1_or_pause(state, requirement)
        spec = result["spec"]
        plan_markdown = result["plan_markdown"]
        plan_path = _write_architecture_plan({**state, "requirement": requirement, "spec": spec}, plan_markdown)
        _write_agent1_artifacts({**state, "spec": spec}, result["agent1_artifacts"])
        _log_status(state, "Planning", f"requirement clarified: {response}")
        return {"requirement": requirement, "clarification_done": True, "spec": spec, "plan_markdown": plan_markdown, "plan_path": str(plan_path), "agent1_artifacts": result["agent1_artifacts"], "reports": {**state.get("reports", {}), "agent1": result["report"]}, "status": "PLANNING_READY"}
    result = _run_agent1_or_pause(state, state["requirement"])
    spec = result["spec"]
    agent1_to_agent2 = build_agent1_to_agent2_contract(spec)
    validate_agent1_to_agent2_contract(agent1_to_agent2)
    envelopes = _with_contract_envelope(state, "agent1_to_agent2", agent1_to_agent2, "agent1", "agent2")
    result["agent1_artifacts"]["agent1_to_agent2_contract"] = json.dumps(agent1_to_agent2, indent=2, sort_keys=True)
    plan_markdown = result["plan_markdown"]
    plan_path = _write_architecture_plan({**state, "spec": spec}, plan_markdown)
    _write_agent1_artifacts({**state, "spec": spec}, result["agent1_artifacts"])
    _log_status(state, "Planning", f"architecture_plan.md created at {plan_path}")
    return {"project_name": spec["project_name"], "spec": spec, "agent1_to_agent2": agent1_to_agent2, "contract_envelopes": envelopes, "plan_markdown": plan_markdown, "plan_path": str(plan_path), "agent1_artifacts": result["agent1_artifacts"], "reports": {**state.get("reports", {}), "agent1": result["report"]}, "status": "PLANNING_READY"}


def _release_agent1_plan(state: SwarmState, requirement: str, result: dict[str, Any]) -> dict[str, Any]:
    spec = result["spec"]
    agent1_to_agent2 = build_agent1_to_agent2_contract(spec)
    validate_agent1_to_agent2_contract(agent1_to_agent2)
    envelopes = _with_contract_envelope(state, "agent1_to_agent2", agent1_to_agent2, "agent1", "agent2")
    result["agent1_artifacts"]["agent1_to_agent2_contract"] = json.dumps(agent1_to_agent2, indent=2, sort_keys=True)
    plan_markdown = result["plan_markdown"]
    plan_path = _write_architecture_plan({**state, "requirement": requirement, "spec": spec}, plan_markdown)
    _write_agent1_artifacts({**state, "requirement": requirement, "spec": spec}, result["agent1_artifacts"])
    _log_status(state, "Planning", f"architecture_plan.md created at {plan_path}")
    return {
        "requirement": requirement,
        "project_name": spec["project_name"],
        "spec": spec,
        "agent1_to_agent2": agent1_to_agent2,
        "contract_envelopes": envelopes,
        "plan_markdown": plan_markdown,
        "plan_path": str(plan_path),
        "agent1_artifacts": result["agent1_artifacts"],
        "reports": {**state.get("reports", {}), "agent1": result["report"]},
        "status": "PLANNING_READY",
    }

def plan_review_node(state: SwarmState) -> dict[str, Any]:
    payload = {
        "action_required": "PLAN_REVIEW",
        "message": f"Plan đã được tạo tại {state.get('plan_path')}. Sếp có muốn thay đổi gì không? (Gõ 'ok' để đi tiếp, hoặc gõ yêu cầu thay đổi)",
        "project_name": state.get("project_name", state.get("spec", {}).get("project_name", "swarm_soc")),
        "plan_path": state.get("plan_path"),
        "resume_with": {"response": "ok"},
    }
    review = interrupt(payload)
    response = review.get("response", review.get("notes", "ok")) if isinstance(review, dict) else str(review)
    response = response.strip()
    if response.lower() != "ok":
        old_requirement = state["requirement"]
        new_requirement = f"{old_requirement}\nIncremental update: {response}"
        result = _run_agent1_or_pause(state, new_requirement)
        spec = result["spec"]
        plan_markdown = result["plan_markdown"]
        plan_path = _write_architecture_plan({**state, "requirement": new_requirement}, plan_markdown)
        _write_agent1_artifacts({**state, "spec": spec}, result["agent1_artifacts"])
        _log_status(state, "Planning", f"plan updated by engineer request: {response}")
        return {
            "requirement": new_requirement,
            "spec": spec,
            "plan_markdown": plan_markdown,
            "plan_path": str(plan_path),
            "agent1_artifacts": result["agent1_artifacts"],
            "reports": {**state.get("reports", {}), "agent1": result["report"]},
            "status": "PLANNING_READY",
        }
    _log_status(state, "Planning", "plan approved")
    return {"plan_approved": True, "status": "PLAN_APPROVED"}


def agent2_rtl_node(state: SwarmState) -> dict[str, Any]:
    _log_status(state, "RTL", "Agent 2 generating RTL")
    agent1_to_agent2 = _contract_payload(state, "agent1_to_agent2") or build_agent1_to_agent2_contract(state["spec"])
    if state.get("agent2_codex_required"):
        agent1_to_agent2 = {**agent1_to_agent2, "constraints": {**agent1_to_agent2.get("constraints", {}), "agent2_codex_required": True}}
    validate_agent1_to_agent2_contract(agent1_to_agent2)
    if state.get("agent2_fix_request") and state.get("rtl_files"):
        _log_status(state, "RTL", f"Agent 2 applying fix request: {state['agent2_fix_request'].get('fix_type')}")
        rtl_files = apply_agent2_fix_request(agent1_to_agent2, state["rtl_files"], state["agent2_fix_request"])
    else:
        rtl_files = generate_rtl_files(agent1_to_agent2, debug=True)
    reports = {**state.get("reports", {})}
    if state.get("run_real_tools"):
        work = _work_dir(state, "agent2_quartus")
        reports["agent2_quartus"] = synthesize_rtl_with_quartus(agent1_to_agent2, rtl_files, work)
    a23 = build_agent2_to_agent3_contract(state["spec"], rtl_files)
    a24 = build_agent2_to_agent4_contract(state["spec"], rtl_files)
    a25 = build_agent2_to_agent5_contract(state["spec"], rtl_files)
    envelopes = _with_contract_envelope(state, "agent2_to_agent3_contract", a23, "agent2", "agent3")
    envelopes = _with_contract_envelope({**state, "contract_envelopes": envelopes}, "agent2_to_agent4_contract", a24, "agent2", "agent4")
    envelopes = _with_contract_envelope({**state, "contract_envelopes": envelopes}, "agent2_to_agent5_contract", a25, "agent2", "agent5")
    return {"agent1_to_agent2": agent1_to_agent2, "rtl_files": rtl_files, "agent2_to_agent3_contract": a23, "agent2_to_agent4_contract": a24, "agent2_to_agent5_contract": a25, "contract_envelopes": envelopes, "reports": reports, "agent2_fix_request": {}, "status": "AGENT2_RTL_DONE"}


def rtl_lint_node(state: SwarmState) -> dict[str, Any]:
    _log_status(state, "RTL-Lint", "Agent 2 static/tool lint gate")
    report = verify_rtl_files(state["spec"], state["rtl_files"])
    reports = {**state.get("reports", {}), "agent2": report, "agent2_lint": report}
    status = "AGENT2_LINT_PASS" if report["pass"] else "AGENT2_LINT_REJECT"
    payload: dict[str, Any] = {"reports": reports, "status": status}
    if not report["pass"]:
        payload["agent2_fix_request"] = {
            "action": "REQUEST_AGENT2_FIX",
            "fix_type": "RTL_LINT_FIX",
            "severity": "critical",
            "failures": report.get("failures", report.get("findings", [])),
            "required_until": "Agent2_Syntax_Linter pass",
        }
    return payload


def agent2_syntax_linter_node(state: SwarmState) -> dict[str, Any]:
    """AGENT_2_Upgrade_V1 node alias for Agent2_Syntax_Linter."""
    return rtl_lint_node(state)


def agent5_formal_node(state: SwarmState) -> dict[str, Any]:
    _log_status(state, "Formal", "Agent 5 generating formal collateral")
    rtl_sv = [file for file in state["rtl_files"] if file.get("language") == "systemverilog"]
    formal_files = generate_formal_files(state["spec"], rtl_sv, debug=True)
    report = verify_formal_files(state["spec"], rtl_sv, formal_files)
    reports = {**state.get("reports", {}), "agent5": report}
    pass_all = report["pass"]
    if state.get("run_real_tools"):
        try:
            real = prove_formal_with_symbiyosys(state["spec"], rtl_sv, formal_files, _work_dir(state, "agent5_formal"))
        except Exception as exc:
            return _toolchain_failure_interrupt(state, "SymbiYosys", exc, _work_dir(state, "agent5_formal"), "agent5_real")
        reports["agent5_real"] = real
        pass_all = pass_all and real["pass"]
    status = "AGENT5_FORMAL_PASS" if pass_all else "AGENT5_FORMAL_FAIL"
    contract_report = {**report, "formal_targets": [block["name"] for block in state["spec"].get("ip_blocks", [])], "properties_generated": [file["filename"] for file in formal_files if file.get("filename", "").startswith("fv_")], "proof_results": reports.get("agent5_real", {}).get("runs", []), "counterexamples": reports.get("agent5_real", {}).get("failures", []), "engines": [report.get("formal_engine", "smtbmc z3")], "bounded_depth": int(report.get("formal_depth", 50)), "tool_availability": detect_real_tools() if state.get("run_real_tools") else {}, "commands": [["sby", "-f", file["filename"]] for file in formal_files if file.get("filename", "").endswith(".sby")]}
    result_contract = build_agent_result_contract("agent5_result/v1", state["spec"]["project_name"], "agent5", pass_all, formal_files, contract_report, report.get("failures", []))
    return {"formal_files": formal_files, "agent5_result_contract": result_contract, "reports": reports, "status": status}


def human_review_node(state: SwarmState) -> dict[str, Any]:
    """Pause the graph until a human approves or rejects generated RTL/formal collateral."""
    payload = {
        "action_required": "HUMAN_REVIEW",
        "message": "Review Agent 2 RTL and Agent 5 formal files before simulation/physical design.",
        "project_name": state["spec"]["project_name"],
        "rtl_files": [file["filename"] for file in state.get("rtl_files", [])],
        "formal_files": [file["filename"] for file in state.get("formal_files", [])],
        "resume_with": {"approved": True, "reviewer": "your-name", "notes": "approved after code review"},
    }
    review = interrupt(payload)
    approved = bool(review.get("approved")) if isinstance(review, dict) else bool(review)
    if not approved:
        raise RuntimeError(f"Human rejected generated code: {review}")
    reviews = [*state.get("hitl_reviews", []), review if isinstance(review, dict) else {"approved": approved}]
    return {"hitl_approved": True, "hitl_reviews": reviews, "status": "HITL_APPROVED"}


def agent3_dv_node(state: SwarmState) -> dict[str, Any]:
    _log_status(state, "DV", "Agent 3 generating DV collateral")
    rtl_sv = [file for file in state["rtl_files"] if file.get("language") == "systemverilog"]
    spec = _agent3_spec_for_state(state)
    dv_files = generate_dv_files(spec, rtl_sv, debug=True)
    report = verify_dv_files(spec, rtl_sv, dv_files)
    reports = {**state.get("reports", {}), "agent3": report}
    result_contract = _json_payload_from_files(dv_files, "agent3_result.json")
    release_decision = _json_payload_from_files(dv_files, "agent3_release_decision.json")
    if state.get("run_real_tools"):
        work = _work_dir(state, "agent3_dv")
        _write_stage_files(work / "rtl", rtl_sv)
        _write_stage_files(work / "tb", dv_files)
        try:
            reports["agent3_real"] = run_cocotb_sim(work / "tb", require_tools=True)
        except Exception as exc:
            reports["agent3_real"] = write_agent3_runtime_failure(work / "tb", exc, requires_real_tools=True)
        dv_files = _refresh_stage_files_from_disk(dv_files, work / "tb")
        report = verify_dv_files(spec, rtl_sv, dv_files)
        reports["agent3"] = report
        result_contract = _json_payload_from_file(work / "tb" / "agent3_result.json") or result_contract
        release_decision = _json_payload_from_file(work / "tb" / "agent3_release_decision.json") or release_decision
    if release_decision:
        reports["agent3_release_decision"] = release_decision
    return {"dv_files": dv_files, "agent3_result_contract": result_contract, "reports": reports, "status": "AGENT3_DV_DONE"}


def apply_incremental_change(app, thread_id: str, change: str) -> SwarmState:
    """Patch checkpointed project state without restarting graph from entry point."""
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = app.get_state(config)
    state: SwarmState = dict(snapshot.values or {})
    if not state:
        raise RuntimeError(f"No checkpoint state found for thread_id={thread_id}")

    old_requirement = state.get("requirement", "")
    new_requirement = f"{old_requirement}\nIncremental update: {change}" if old_requirement else change
    result = _run_agent1_or_raise(state, new_requirement)
    spec = result["spec"]
    plan_markdown = result["plan_markdown"]
    plan_path = _write_architecture_plan({**state, "requirement": new_requirement, "spec": spec}, plan_markdown)
    _write_agent1_artifacts({**state, "spec": spec}, result["agent1_artifacts"])

    updates: dict[str, Any] = {
        "requirement": new_requirement,
        "spec": spec,
        "plan_markdown": plan_markdown,
        "plan_path": str(plan_path),
        "incremental_changes": [*state.get("incremental_changes", []), {"change": change, "from_status": state.get("status", "UNKNOWN")}],
    }
    _log_status(state, "Incremental", f"Agent 1 updated spec from checkpoint: {change}")

    if state.get("rtl_files"):
        rtl_files = generate_rtl_files(spec, debug=True)
        updates["rtl_files"] = rtl_files
        updates["reports"] = {**state.get("reports", {}), "agent2": verify_rtl_files(spec, rtl_files)}
        _log_status(state, "Incremental", "Agent 2 patched RTL affected by spec change")
        state = {**state, **updates}

    if state.get("dv_files") and updates.get("rtl_files"):
        rtl_sv = [file for file in updates["rtl_files"] if file.get("language") == "systemverilog"]
        dv_files = generate_dv_files(spec, rtl_sv, debug=True)
        updates["dv_files"] = dv_files
        updates["reports"] = {**updates.get("reports", state.get("reports", {})), "agent3": verify_dv_files(spec, rtl_sv, dv_files)}
        _log_status(state, "Incremental", "Agent 3 updated DV collateral for patched RTL")

    updates["status"] = "INCREMENTAL_PATCHED"
    app.update_state(config, updates)
    return {**state, **updates}


def agent4_physical_node(state: SwarmState) -> dict[str, Any]:
    _log_status(state, "Physical", "Agent 4 generating physical collateral")
    rtl_sv = [file for file in state["rtl_files"] if file.get("language") == "systemverilog"]
    physical_files = generate_physical_design_files(state["spec"], rtl_sv, debug=True)
    report = verify_physical_design_files(state["spec"], rtl_sv, physical_files)
    reports = {**state.get("reports", {}), "agent4": report}
    status = "SIGNOFF_READY"
    compile_report: dict[str, Any] = {}
    action: dict[str, Any] = {"action": "STATIC_ONLY", "signoff_status": "PASS" if report.get("pass", True) else "FAIL"}
    if state.get("run_real_tools"):
        try:
            compile_report = compile_physical_design(state["spec"], rtl_sv, _work_dir(state, "agent4_quartus"))
        except Exception as exc:
            return _toolchain_failure_interrupt(state, "Quartus", exc, _work_dir(state, "agent4_quartus"), "agent4_quartus")
        reports["agent4_quartus"] = compile_report
        action = decide_backend_action(compile_report["metrics"], state.get("debug_iterations", 0))
        reports["agent4_decision"] = action
        if _has_setup_slack_violation(compile_report):
            fix_request = _timing_closure_fix_request(compile_report, state.get("debug_iterations", 0))
            reports["agent4_timing_fix_request"] = fix_request
            history = [*state.get("timing_closure_history", []), fix_request]
            _log_status(state, "TimingClosure", f"Setup Slack < 0; sending critical path to Agent 2: {fix_request.get('critical_path')}")
            return {"physical_files": physical_files, "reports": reports, "agent2_fix_request": fix_request,
                    "timing_closure_history": history, "status": "AGENT4_TIMING_VIOLATION"}
        status = "SIGNOFF_READY" if action["action"] == "SIGNOFF_PASS" else "AGENT4_BACKEND_FAIL"
    metrics = compile_report.get("metrics", {})
    agent4_pass = bool(report.get("pass", True)) and status == "SIGNOFF_READY"
    agent2_to_agent4 = _contract_payload(state, "agent2_to_agent4_contract") or state.get("agent2_to_agent4_contract", {})
    contract_report = {**report, "backend_used": agent2_to_agent4.get("target_backend", "quartus"), "metrics": metrics, "timing_summary": {"fmax_mhz": metrics.get("fmax_mhz"), "setup_slack_ns": metrics.get("setup_slack_ns"), "hold_slack_ns": metrics.get("hold_slack_ns"), "critical_path": metrics.get("critical_path")}, "resource_summary": {"alm_usage_pct": metrics.get("alm_usage_pct"), "alm_usage_limit_pct": report.get("alm_usage_limit_pct"), "device": report.get("device")}, "constraints_generated": [file["filename"] for file in physical_files if str(file.get("filename", "")).endswith((".sdc", ".qsf", ".xdc"))], "commands": compile_report.get("commands", []), "tool_availability": detect_real_tools() if state.get("run_real_tools") else {}, "backend_action": action}
    result_contract = build_agent_result_contract("agent4_result/v1", state["spec"]["project_name"], "agent4", agent4_pass, physical_files, contract_report, report.get("failures", []))
    index = build_swarm_artifact_index(state["spec"]["project_name"], {**state, "physical_files": physical_files, "reports": reports, "agent4_result_contract": result_contract})
    return {"physical_files": physical_files, "agent4_result_contract": result_contract, "swarm_artifact_index": index, "reports": reports, "status": status}


def formal_gate(state: SwarmState) -> Literal["human_review", "agent3_dv", "auto_debug_agent2"]:
    reports = state.get("reports", {})
    static_ok = reports.get("agent5", {}).get("pass")
    real_ok = reports.get("agent5_real", {"pass": static_ok}).get("pass")
    if static_ok and real_ok:
        if state.get("hitl_approved"):
            return "agent3_dv"
        return "human_review"
    if state.get("debug_iterations", 0) >= state.get("max_debug_iterations", 5):
        return "human_review"
    return "auto_debug_agent2"


def rtl_lint_gate(state: SwarmState) -> Literal["agent5_formal", "auto_debug_agent2", "human_review"]:
    report = state.get("reports", {}).get("agent2_lint", state.get("reports", {}).get("agent2", {}))
    if report.get("pass"):
        return "agent5_formal"
    if state.get("debug_iterations", 0) >= state.get("max_debug_iterations", 5):
        return "human_review"
    return "auto_debug_agent2"


def backend_gate(state: SwarmState) -> Literal["done", "auto_debug_agent2"]:
    if state.get("status") == "SIGNOFF_READY":
        return "done"
    if state.get("debug_iterations", 0) >= state.get("max_debug_iterations", 5):
        return "done"
    return "auto_debug_agent2"


def _has_setup_slack_violation(compile_report: dict[str, Any]) -> bool:
    return compile_report.get("metrics", {}).get("setup_slack_ns", 0) < 0


def _timing_closure_fix_request(compile_report: dict[str, Any], debug_iterations: int) -> dict[str, Any]:
    metrics = compile_report.get("metrics", {})
    critical_path = metrics.get("critical_path") or compile_report.get("critical_path") or "Quartus STA critical path unavailable; inspect TimeQuest setup report"
    return {"action": "REQUEST_AGENT2_FIX", "fix_type": "PIPELINE_CRITICAL_PATH", "severity": "critical",
            "reason": "Setup Slack < 0", "setup_slack_ns": metrics.get("setup_slack_ns"),
            "hold_slack_ns": metrics.get("hold_slack_ns"), "fmax_mhz": metrics.get("fmax_mhz"),
            "target_mhz": metrics.get("target_mhz"), "critical_path": critical_path,
            "debug_iterations": debug_iterations, "required_until": "Setup Slack > 0"}


def plan_gate(state: SwarmState) -> Literal["agent2_rtl", "plan_review"]:
    return "agent2_rtl" if state.get("plan_approved") else "plan_review"


def auto_debug_agent2_node(state: SwarmState) -> dict[str, Any]:
    iteration = state.get("debug_iterations", 0) + 1
    _log_status(state, "AutoDebug", f"Agent 2 regenerate iteration {iteration}")
    reports = {**state.get("reports", {}), "auto_debug_iteration": iteration}
    return {"debug_iterations": iteration, "reports": reports, "status": "AUTO_DEBUG_AGENT2_REGENERATE"}


def _requirement_is_ambiguous(requirement: str) -> bool:
    text = requirement.lower()
    asks_ai_chip = bool(re.search(r"\b(ai|trí tuệ nhân tạo)\b", text)) and bool(re.search(r"\b(chip|soc|con)\b", text))
    has_interface = bool(re.search(r"\b(apb|axi|ahb|wishbone|spi|i2c)\b", text))
    has_freq = bool(re.search(r"\d+\s*mhz", text))
    has_power = bool(re.search(r"(<|<=|under|dưới)?\s*\d+(\.\d+)?\s*(w|mw)\b", text))
    return requirement_needs_clarification(requirement) or (asks_ai_chip and not (has_freq and has_power))


def _toolchain_failure_interrupt(state: SwarmState, tool: str, exc: Exception, work_dir: Path, report_key: str) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    log_path = work_dir / "toolchain_error.log"
    log_path.write_text(f"{tool} crash/failure\n{type(exc).__name__}: {exc}\n", encoding="utf-8")
    reports = {**state.get("reports", {}), report_key: {"pass": False, "tool_crash": True, "tool": tool, "error": str(exc), "log_file": str(log_path)}}
    _log_status(state, "Toolchain", f"{tool} failed, log: {log_path}")
    payload = {
        "action_required": "TOOLCHAIN_FAILURE",
        "message": "Sếp muốn tự fix bằng tay hay để Agent 5 tự debug?",
        "tool": tool,
        "error": str(exc),
        "log_file": str(log_path),
        "resume_with": {"response": "agent5_debug"},
    }
    decision = interrupt(payload)
    response = decision.get("response", decision.get("notes", "")) if isinstance(decision, dict) else str(decision)
    if "agent" in response.lower() or "debug" in response.lower():
        return {"reports": reports, "status": "AUTO_DEBUG_AGENT2_REGENERATE"}
    return {"reports": reports, "status": "PAUSED_FOR_MANUAL_TOOLCHAIN_FIX"}


def _work_dir(state: SwarmState, phase: str) -> Path:
    root = Path(state.get("output_dir", "runs")) / state.get("thread_id", state.get("project_name", "swarm"))
    return root / phase


def _agent3_spec_for_state(state: SwarmState) -> dict[str, Any]:
    spec = json.loads(json.dumps(state["spec"]))
    constraints = dict(spec.get("constraints", {}))
    if state.get("strict_signoff"):
        constraints["swarm_mode"] = "strict"
        constraints["requires_real_tools"] = True
    spec["constraints"] = constraints
    return spec

def _json_payload_from_files(files: list[dict[str, Any]], filename: str) -> dict[str, Any]:
    for file in files:
        if file.get("filename") != filename:
            continue
        try:
            payload = json.loads(file.get("content", "{}"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}

def _json_payload_from_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}

def _refresh_stage_files_from_disk(files: list[dict[str, Any]], root: Path) -> list[dict[str, Any]]:
    refreshed = []
    for file in files:
        path = root / Path(file["filename"]).name
        if path.is_file():
            content = path.read_text(encoding="utf-8")
            refreshed.append({**file, "content": content, "line_count": len(content.rstrip("\n").splitlines())})
        else:
            refreshed.append(file)
    return refreshed

def _write_stage_files(target: Path, files: list[dict[str, Any]]) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for file in files:
        filename = Path(file["filename"]).name
        (target / filename).write_text(file["content"], encoding="utf-8")


def _output_root(state: SwarmState) -> Path:
    return Path(state.get("output_dir", "swarm_out"))


def _write_architecture_plan(state: SwarmState, plan_markdown: str) -> Path:
    reports_dir = _output_root(state) / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "architecture_plan.md"
    path.write_text(plan_markdown, encoding="utf-8")
    return path


def _write_requirement_clarification(state: SwarmState, clarification_markdown: str) -> Path:
    reports_dir = _output_root(state) / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "agent1_requirement_clarification.md"
    path.write_text(clarification_markdown, encoding="utf-8")
    emit_runtime_event({"type": "artifact", "agent": "agent1", "kind": "markdown", "path": str(path), "bytes": path.stat().st_size})
    return path

def _write_agent1_artifacts(state: SwarmState, artifacts: dict[str, str]) -> list[str]:
    reports_dir = _output_root(state) / "reports" / "agent1"
    reports_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, content in artifacts.items():
        safe_name = Path(filename).name
        path = reports_dir / safe_name
        path.write_text(content, encoding="utf-8")
        written.append(str(path))
        if safe_name == "agent1_codex_evidence.json":
            emit_runtime_event({"type": "artifact", "agent": "agent1", "kind": "json", "path": str(path), "bytes": path.stat().st_size})
            emit_runtime_event({"type": "agent_action", "agent": "agent1", "label": "Agent 1 Architect", "phase": "planning", "action": "Codex evidence artifact ready", "status": "pass", "summary": f"Agent 1 Codex evidence written to {path}", "artifact": str(path)})
    return written


def _run_agent1_or_pause(state: SwarmState, requirement: str) -> dict[str, Any]:
    try:
        return _run_agent1_or_raise(state, requirement)
    except Agent1CodexUnavailable as exc:
        _log_status(state, "Planning", f"Agent 1 Codex unavailable: {exc}")
        payload = {
            "action_required": "AGENT1_CODEX_UNAVAILABLE",
            "message": "Agent 1 Codex API unavailable. Workflow paused before Agent 2; no deterministic fallback allowed.",
            "endpoint": "http://localhost:20128/v1",
            "model": "cx/gpt-5.5",
            "error": str(exc),
            "resume_with": {"response": "retry after starting Codex endpoint"},
        }
        interrupt(payload)
        return _run_agent1_or_raise(state, requirement)


def _run_agent1_or_raise(state: SwarmState, requirement: str) -> dict[str, Any]:
    return run_agent1_hierarchical_planning(requirement, state.get("project_name", "swarm_soc"), planning_mode=state.get("agent1_planning_mode"))


def _log_status(state: SwarmState, phase: str, message: str) -> None:
    out = _output_root(state)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "status.log").open("a", encoding="utf-8") as handle:
        handle.write(f"[{phase}] {message}\n")


def _with_contract_envelope(state: SwarmState | dict[str, Any], key: str, payload: dict[str, Any], producer: str, consumer: str | None) -> dict[str, dict[str, Any]]:
    """Return updated envelope bus while keeping legacy raw payload fields intact."""
    envelopes = {**state.get("contract_envelopes", {})}
    envelopes[key] = ContractEnvelope(
        contract_version=str(payload.get("contract_version", key)),
        payload=payload,
        producer=producer,
        consumer=consumer,
        run_id=state.get("thread_id") or state.get("project_name"),
    ).to_dict()
    return envelopes


def _contract_payload(state: SwarmState | dict[str, Any], key: str) -> dict[str, Any] | None:
    """Read payload from Phase 7 envelope bus, fallback to legacy raw state field."""
    envelope = state.get("contract_envelopes", {}).get(key)
    if isinstance(envelope, dict) and isinstance(envelope.get("payload"), dict):
        return envelope["payload"]
    legacy = state.get(key)
    return legacy if isinstance(legacy, dict) else None


def build_swarm_graph(checkpointer: InMemorySaver | None = None, *, interrupt_after: Sequence[str] | None = None):
    graph = StateGraph(SwarmState)
    graph.add_node("agent1_architect", agent1_architect_node)
    graph.add_node("plan_review", plan_review_node)
    graph.add_node("agent2_rtl", agent2_rtl_node)
    graph.add_node("agent2_syntax_linter", agent2_syntax_linter_node)
    graph.add_node("agent5_formal", agent5_formal_node)
    graph.add_node("auto_debug_agent2", auto_debug_agent2_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("agent3_dv", agent3_dv_node)
    graph.add_node("agent4_physical", agent4_physical_node)

    graph.set_entry_point("agent1_architect")
    graph.add_edge("agent1_architect", "plan_review")
    graph.add_conditional_edges("plan_review", plan_gate, {"agent2_rtl": "agent2_rtl", "plan_review": "plan_review"})
    graph.add_edge("agent2_rtl", "agent2_syntax_linter")
    graph.add_conditional_edges("agent2_syntax_linter", rtl_lint_gate, {"agent5_formal": "agent5_formal", "auto_debug_agent2": "auto_debug_agent2", "human_review": "human_review"})
    graph.add_conditional_edges("agent5_formal", formal_gate, {"human_review": "human_review", "agent3_dv": "agent3_dv", "auto_debug_agent2": "auto_debug_agent2"})
    graph.add_edge("auto_debug_agent2", "agent2_rtl")
    graph.add_edge("human_review", "agent3_dv")
    graph.add_edge("agent3_dv", "agent4_physical")
    graph.add_conditional_edges("agent4_physical", backend_gate, {"done": END, "auto_debug_agent2": "auto_debug_agent2"})
    compile_kwargs: dict[str, Any] = {"checkpointer": checkpointer or InMemorySaver()}
    if interrupt_after:
        compile_kwargs["interrupt_after"] = list(interrupt_after)
    return graph.compile(**compile_kwargs)


@contextmanager
def persistent_swarm_graph(checkpoint_path: str | Path = "swarm_checkpoints.sqlite"):
    """Build a graph with a SQLite checkpointer so CLI pause/resume works across processes."""
    checkpoint_file = Path(checkpoint_path)
    checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(checkpoint_file)) as checkpointer:
        yield build_swarm_graph(checkpointer)


def run_until_interrupt(requirement: str, project_name: str, *, thread_id: str = "semiconductor-swarm", run_real_tools: bool = False) -> dict[str, Any]:
    app = build_swarm_graph()
    config = {"configurable": {"thread_id": thread_id}}
    return app.invoke({"requirement": requirement, "project_name": project_name, "thread_id": thread_id,
                       "run_real_tools": run_real_tools, "debug_iterations": 0, "max_debug_iterations": 5,
                       "plan_approved": False,
                       "reports": {}}, config=config)


def resume_after_human_review(app, thread_id: str, approved: bool = True, reviewer: str = "human", notes: str = "approved") -> dict[str, Any]:
    config = {"configurable": {"thread_id": thread_id}}
    return app.invoke(Command(resume={"approved": approved, "reviewer": reviewer, "notes": notes}), config=config)


def write_outputs(state: SwarmState, output_dir: str | Path) -> None:
    out = Path(output_dir)
    groups = {"rtl": state.get("rtl_files", []), "formal": state.get("formal_files", []), "tb": state.get("dv_files", []), "fpga": state.get("physical_files", [])}
    written: list[dict[str, Any]] = []
    for group, files in groups.items():
        for file in files:
            path = out / _stage_file_rel_path(group, file)
            path.parent.mkdir(parents=True, exist_ok=True)
            content = file["content"]
            path.write_text(content, encoding="utf-8")
            encoded = content.encode("utf-8")
            written.append({
                "path": str(path.relative_to(out)).replace("\\", "/"),
                "sha256": hashlib.sha256(encoded).hexdigest(),
                "bytes": len(encoded),
            })

    written.extend(_write_engineer_launcher_scripts(state, out))
    project = state.get("spec", {}).get("project_name", state.get("project_name", "swarm_soc"))
    _write_contract_outputs(state, out, project, written)
    _write_signoff_reports(state, out, written)


def _write_contract_outputs(state: SwarmState, out: Path, project: str, written: list[dict[str, Any]]) -> None:
    contracts_dir = out / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    contract_payloads = {
        "agent1_to_agent2.json": state.get("agent1_to_agent2"),
        "agent2_to_agent3.json": state.get("agent2_to_agent3_contract"),
        "agent2_to_agent4.json": state.get("agent2_to_agent4_contract"),
        "agent2_to_agent5.json": state.get("agent2_to_agent5_contract"),
        "agent3_result.json": state.get("agent3_result_contract"),
        "agent4_result.json": state.get("agent4_result_contract"),
        "agent5_result.json": state.get("agent5_result_contract"),
    }
    for filename, payload in contract_payloads.items():
        if isinstance(payload, dict):
            path = contracts_dir / filename
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            written.append(_manifest_entry(out, path))
            if filename.startswith("agent2_to_"):
                rtl_contracts_dir = out / "rtl" / "contracts"
                rtl_contracts_dir.mkdir(parents=True, exist_ok=True)
                rtl_contract_path = rtl_contracts_dir / filename
                rtl_contract_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
                written.append(_manifest_entry(out, rtl_contract_path))

    envelopes = state.get("contract_envelopes", {})
    if envelopes:
        envelopes_dir = contracts_dir / "envelopes"
        envelopes_dir.mkdir(parents=True, exist_ok=True)
        bus_path = contracts_dir / "contract_envelopes.json"
        bus_path.write_text(json.dumps(envelopes, indent=2, sort_keys=True), encoding="utf-8")
        written.append(_manifest_entry(out, bus_path))
        for key, envelope in sorted(envelopes.items()):
            if isinstance(envelope, dict):
                path = envelopes_dir / f"{key}.json"
                path.write_text(json.dumps(envelope, indent=2, sort_keys=True), encoding="utf-8")
                written.append(_manifest_entry(out, path))

    index_state = {**state, "output_root": str(out), "rtl_files": _with_routed_rtl_paths(state.get("rtl_files", []))}
    index = build_swarm_artifact_index(project, index_state)
    for path in (contracts_dir / "swarm_artifact_index.json", out / "swarm_artifact_index.json"):
        path.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
        written.append(_manifest_entry(out, path))

    docs_contract = build_swarm_to_docs_agent_contract(project, index)
    docs_path = contracts_dir / "swarm_to_docs_agent.json"
    docs_path.write_text(json.dumps(docs_contract, indent=2, sort_keys=True), encoding="utf-8")
    written.append(_manifest_entry(out, docs_path))

_RTL_ROOT_METADATA = {
    "rtl_manifest.json",
    "compile_order.f",
    "compile_order_report.json",
    "ast_dependency_graph.json",
    "agent2_v4_signoff_dashboard.md",
    "agent2_quality_score.json",
    "agent2_release_decision.json",
}

_RTL_REPORT_ARTIFACTS = {
    "strict_eda_report.json",
    "verilator_lint_report.json",
    "yosys_synth_report.json",
    "formal_smoke_report.json",
    "csr_codegen_report.json",
    "csr_integration_report.json",
    "peakrdl_regblock_provenance.json",
    "semantic_deep_report.json",
    "pattern_coverage_report.json",
    "cdc_rdc_screen_report.json",
    "rtl_style_report.json",
    "protocol_contract_report.json",
    "tool_provenance.json",
    "toolchain_reproducibility_report.json",
    "upf_consistency_report.json",
    "rtl_generation_fingerprint.json",
    "agent2_codex_evidence.json",
    "agent2_ai_review.json",
    "agent2_ai_repair_suggestions.json",
    "agent2_ai_contract.json",
    "agent2_context_slices.json",
    "agent2_patch_apply_report.json",
    "agent2_patch_retry_report.json",
    "agent2_codex_plan.md",
}

_RTL_CONTRACT_ARTIFACTS = {
    "interface_contracts.sv",
    "agent2_handoff_bundle.json",
    "formal_hooks.json",
    "dv_hooks.json",
    "dft_hooks.json",
    "ppa_handoff.json",
    "signoff_governance.json",
    "release_gate.json",
}

_RTL_REPAIR_ARTIFACTS = {
    "repair_trace.json",
    "repair_trace.jsonl",
    "repair_package.json",
    "hitl_repair_package.json",
    "lec_equivalence_report.json",
    "repair_v4_report.json",
}

def _stage_file_rel_path(group: str, file: dict[str, Any]) -> Path:
    filename = Path(str(file["filename"])).name
    if group == "rtl":
        return _rtl_file_rel_path(filename, str(file.get("language", "")))
    return Path(group) / filename

def _rtl_file_rel_path(filename: str, language: str = "") -> Path:
    if filename in _RTL_CONTRACT_ARTIFACTS:
        return Path("rtl") / "contracts" / filename
    if filename in _RTL_REPAIR_ARTIFACTS:
        return Path("rtl") / "repair" / filename
    if filename in _RTL_REPORT_ARTIFACTS:
        return Path("rtl") / "reports" / filename
    if filename in _RTL_ROOT_METADATA:
        return Path("rtl") / filename
    if filename.endswith(".json") or filename.endswith(".jsonl"):
        if "hook" in filename or "handoff" in filename or "contract" in filename or filename in {"macro_wrappers.json"}:
            return Path("rtl") / "contracts" / filename
        if "repair" in filename or filename.startswith("lec_"):
            return Path("rtl") / "repair" / filename
        return Path("rtl") / "reports" / filename
    if filename.endswith(".md") and filename not in _RTL_ROOT_METADATA:
        return Path("rtl") / "reports" / filename
    return Path("rtl") / filename

def _with_routed_rtl_paths(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    routed = []
    for file in files or []:
        filename = Path(str(file.get("filename", ""))).name
        rel_path = _rtl_file_rel_path(filename, str(file.get("language", "")))
        routed.append({**file, "output_path": str(rel_path).replace("\\", "/")})
    return routed

def _write_engineer_launcher_scripts(state: SwarmState, out: Path) -> list[dict[str, Any]]:
    project = state.get("spec", {}).get("project_name", state.get("project_name", "swarm_soc"))
    top = f"{project}_top"
    fpga_dir = out / "fpga"
    tb_dir = out / "tb"
    fpga_dir.mkdir(parents=True, exist_ok=True)
    tb_dir.mkdir(parents=True, exist_ok=True)

    qpf_path = fpga_dir / f"{project}.qpf"
    if not qpf_path.exists():
        qpf_path.write_text(_quartus_qpf(project), encoding="ascii")

    gui_do_path = tb_dir / "sim_gui.do"
    gui_do_path.write_text(_modelsim_gui_do(top), encoding="ascii")

    scripts = {
        "run_modelsim_gui.bat": _modelsim_gui_bat(top),
        "open_quartus_project.bat": _quartus_gui_bat(project),
    }
    written = [_manifest_entry(out, qpf_path), _manifest_entry(out, gui_do_path)]
    for filename, content in scripts.items():
        path = out / filename
        path.write_text(content, encoding="ascii", newline="\r\n")
        written.append(_manifest_entry(out, path))
    return written


def _modelsim_gui_bat(top: str) -> str:
    return f'''@echo off
setlocal
cd /d "%~dp0"
if not exist "tb\\sim_gui.do" (
  echo Missing tb\\sim_gui.do. Run swarm output generation first.
  pause
  exit /b 1
)
where vsim >nul 2>nul
if errorlevel 1 (
  echo ModelSim/Questa vsim not found on PATH.
  echo Please open Siemens ModelSim/Questa command prompt or add vsim to PATH.
  pause
  exit /b 1
)
cd tb
vsim -gui -do "do sim_gui.do"
endlocal
'''


def _modelsim_gui_do(top: str) -> str:
    return f'''# ModelSim/Questa GUI launch script generated by Semiconductor Swarm AI.
transcript file transcript_gui
if {{[file exists work]}} {{ vdel -lib work -all }}
vlib work
vmap work work
vlog -sv ../rtl/*.sv
vsim -wlf wave.wlf work.{top}
view wave
log -r /*
add wave -r /*
run -all
echo "Simulation finished. Design remains loaded in GUI for waveform inspection."
'''


def _quartus_gui_bat(project: str) -> str:
    return f'''@echo off
setlocal
cd /d "%~dp0"
if not exist "fpga\\{project}.qpf" (
  echo Missing fpga\\{project}.qpf. Run swarm output generation first.
  pause
  exit /b 1
)
where quartus >nul 2>nul
if errorlevel 1 (
  echo Quartus Prime UI executable 'quartus' not found on PATH.
  echo Please open Intel FPGA command prompt or add Quartus bin directory to PATH.
  pause
  exit /b 1
)
quartus "fpga\\{project}.qpf"
endlocal
'''


def _quartus_qpf(project: str) -> str:
    return f'''QUARTUS_VERSION = "24.1"
DATE = "Generated by Semiconductor Swarm AI"

PROJECT_REVISION = "{project}"
'''


def _manifest_entry(root: Path, path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    return {"path": str(path.relative_to(root)).replace("\\", "/"), "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}


def _write_signoff_reports(state: SwarmState, out: Path, written: list[dict[str, Any]]) -> None:
    reports_dir = out / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    spec = state.get("spec", {})
    reports = state.get("reports", {})
    status = state.get("status", "UNKNOWN")

    report_files = {
        "architecture.md": _architecture_report(spec),
        "architecture_plan.md": state.get("plan_markdown") or generate_architecture_plan_markdown(spec),
        "rtl_quality.md": _generic_report("RTL Quality", reports.get("agent2", {})),
        "formal_summary.md": _generic_report("Formal Summary", reports.get("agent5", {})),
        "dv_coverage.md": _generic_report("DV Coverage", reports.get("agent3", {})),
        "timing_summary.md": _generic_report("Timing Summary", reports.get("agent4", {})),
    }
    for filename, content in report_files.items():
        (reports_dir / filename).write_text(content, encoding="utf-8")

    tool_detection = state.get("tool_detection") or detect_real_tools()
    strict_signoff = bool(state.get("strict_signoff", False))
    evidence = _signoff_evidence(state, tool_detection)
    signoff_blockers = _signoff_blockers(strict_signoff, evidence)
    full_signoff_ready = _full_signoff_evidence_ready(evidence)
    demo_ready = status == "SIGNOFF_READY" and not signoff_blockers and not full_signoff_ready
    manifest_status = _manifest_signoff_status(status, signoff_blockers, full_signoff_ready, demo_ready)
    manifest = {
        "project_name": spec.get("project_name", state.get("project_name", "unknown")),
        "status": manifest_status,
        "raw_status": status,
        "readiness_label": manifest_status,
        "strict_signoff": strict_signoff,
        "formal_first": bool(spec.get("constraints", {}).get("formal_first", True)),
        "hitl_approved": bool(state.get("hitl_approved", False)),
        "agent_reports_present": sorted(reports.keys()),
        "evidence": evidence,
        "tool_detection": tool_detection,
        "signoff_blockers": signoff_blockers,
        "demo_ready": demo_ready,
        "full_signoff_evidence_ready": full_signoff_ready,
        "generated_file_count": len(written),
        "generated_files": written,
        "required_directories": ["rtl", "tb", "formal", "fpga", "reports"],
        "signoff_ready": status == "SIGNOFF_READY" and not signoff_blockers and full_signoff_ready,
    }
    (reports_dir / "signoff_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def _signoff_evidence(state: SwarmState, tool_detection: dict[str, Any]) -> dict[str, Any]:
    reports = state.get("reports", {})
    agent3_release = reports.get("agent3_release_decision", {})
    return {
        "formal_static_pass": bool(reports.get("agent5", {}).get("pass")),
        "formal_real_pass": bool(reports.get("agent5_real", {}).get("pass")),
        "formal_tools_available": bool(tool_detection.get("groups", {}).get("formal", {}).get("available")),
        "dv_static_pass": bool(reports.get("agent3", {}).get("pass")),
        "dv_real_pass": bool(reports.get("agent3_real", {}).get("pass")),
        "dv_release_decision": agent3_release.get("decision_label", "DV_NOT_RUN"),
        "dv_strict_pass": agent3_release.get("decision_label") == "DV_STRICT_PASS",
        "dv_tools_available": bool(tool_detection.get("groups", {}).get("dv", {}).get("available")),
        "quartus_real_pass": bool(reports.get("agent4_quartus", {}).get("metrics", {}).get("compile_pass")),
        "quartus_tools_available": bool(tool_detection.get("groups", {}).get("quartus", {}).get("available")),
        "backend_static_pass": bool(reports.get("agent4", {}).get("pass")),
    }


def _signoff_blockers(strict_signoff: bool, evidence: dict[str, Any]) -> list[str]:
    if not strict_signoff:
        return []
    blockers = []
    if not evidence["formal_real_pass"]:
        blockers.append("strict_signoff_requires_formal_real_pass")
    if not evidence["dv_real_pass"]:
        blockers.append("strict_signoff_requires_dv_real_pass")
    if not evidence["dv_strict_pass"]:
        blockers.append("strict_signoff_requires_agent3_dv_strict_pass")
    if not evidence["quartus_real_pass"]:
        blockers.append("strict_signoff_requires_quartus_real_pass")
    return blockers

def _full_signoff_evidence_ready(evidence: dict[str, Any]) -> bool:
    return bool(
        evidence.get("formal_real_pass")
        and evidence.get("dv_real_pass")
        and evidence.get("dv_strict_pass")
        and evidence.get("quartus_real_pass")
    )

def _manifest_signoff_status(status: str, blockers: list[str], full_signoff_ready: bool, demo_ready: bool) -> str:
    if blockers:
        return "SIGNOFF_BLOCKED"
    if status == "SIGNOFF_READY" and full_signoff_ready:
        return "SIGNOFF_READY"
    if demo_ready:
        return "DEMO_SIGNOFF_READY"
    return status


def _architecture_report(spec: dict[str, Any]) -> str:
    return "\n".join([
        "# Architecture Report",
        "",
        f"Project: {spec.get('project_name', 'unknown')}",
        f"Target node: {spec.get('target_node', 'unknown')}",
        f"ISA: {spec.get('isa', 'unknown')}",
        f"IP blocks: {len(spec.get('ip_blocks', []))}",
        f"Formal first: {spec.get('constraints', {}).get('formal_first', True)}",
        "",
    ])


def _generic_report(title: str, report: dict[str, Any]) -> str:
    return "\n".join([
        f"# {title}",
        "",
        "```json",
        json.dumps(report, indent=2, sort_keys=True),
        "```",
        "",
    ])
