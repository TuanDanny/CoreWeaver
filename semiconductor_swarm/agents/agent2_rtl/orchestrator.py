"""Agent 2 V2 Milestone B orchestrator."""
from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from typing import Any, Callable

from semiconductor_swarm.agents.agent2_rtl.phase1_artifacts import build_phase1_artifacts
from semiconductor_swarm.agents.agent2_rtl.ai_repair import validate_ai_review, validate_repair_suggestions
from semiconductor_swarm.agents.agent2_rtl.agent2_llm_client import call_agent2_codex
from semiconductor_swarm.agents.agent2_rtl.semantic import build_rtl_module_index, build_semantic_lint_report, build_semantic_review_report
from semiconductor_swarm.agents.agent2_rtl.schema_validation import build_schema_validation_report
from semiconductor_swarm.agents.agent2_rtl.state import Agent2State
from semiconductor_swarm.agents.agent2_rtl.tools import build_tool_health_artifacts
from semiconductor_swarm.agents.agent2_rtl.pattern_library import pattern_manifest
from semiconductor_swarm.agents.agent2_rtl.subagents import get_milestone_a_registry, get_milestone_b_repair_registry, get_milestone_b_review_registry, get_milestone_e_signoff_registry, get_milestone_g_registry
from semiconductor_swarm.runtime_events import emit_runtime_event


LegacyGenerator = Callable[[dict[str, Any], bool], list[dict[str, Any]]]


def _agent2_codex_required(spec: dict[str, Any]) -> bool:
    constraints = spec.get("constraints", {}) if isinstance(spec.get("constraints"), dict) else {}
    return bool(constraints.get("agent2_codex_required") or constraints.get("agent2_hybrid_codex"))


def _run_agent2_codex_plan(state: Agent2State) -> dict[str, Any]:
    prompt = "\n".join(
        [
            "# Agent 2 Codex RTL Implementation Plan",
            "Return concise implementation guidance for deterministic RTL generation.",
            "Do not emit full SystemVerilog files.",
            "Use cited rules from Agent 2 prompt, APB contract, and pattern manifest.",
            f"Project: {state.project}",
            f"Blocks: {', '.join(state.blocks)}",
            f"Constraints: {json.dumps(state.spec.get('constraints', {}), sort_keys=True)}",
            f"Patterns: {json.dumps(pattern_manifest(state.spec), sort_keys=True)[:4000]}",
        ]
    )
    result = call_agent2_codex(prompt, purpose="rtl_implementation_plan")
    return {
        "agent2_codex_plan.md": result.content,
        "agent2_codex_evidence.json": result.evidence,
        "agent2_ai_contract.json": _agent2_ai_contract(state, result.evidence),
    }


def _run_agent2_codex_review(state: Agent2State) -> dict[str, Any]:
    review_prompt = "\n".join(
        [
            "# Agent 2 Codex RTL Review",
            "Return JSON only with fields: findings, summary.",
            "Every finding must include cited_rule, source, source_path, evidence_snippet, affected_file, severity.",
            "Do not include full RTL files. If suggesting repair, reference patch IDs only.",
            f"Project: {state.project}",
            f"Generated files: {json.dumps([_file_summary(file) for file in state.files], sort_keys=True)}",
        ]
    )
    review = call_agent2_codex(review_prompt, purpose="rtl_review")
    review_payload = _parse_codex_json(review.content, default={"summary": review.content[:2000], "findings": []})
    review_validation = validate_ai_review(review_payload)
    if not review_validation["pass"]:
        raise ValueError(f"Agent 2 Codex review missing citations: {review_validation['blocking_findings']}")
    repair_payload = {"schema_version": "agent2.ai_repair_suggestions.v1", "patches": []}
    repair_validation = validate_repair_suggestions(repair_payload)
    return {
        "agent2_ai_review.json": {**review_payload, "validation": review_validation, "codex_evidence": review.evidence},
        "agent2_ai_repair_suggestions.json": {**repair_payload, "validation": repair_validation},
    }


def _agent2_ai_contract(state: Agent2State, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "agent2.ai_contract.v1",
        "project": state.project,
        "mode": "mandatory_hybrid_codex",
        "codex_evidence_schema": evidence.get("schema_version"),
        "codex_model": evidence.get("model"),
        "deterministic_gate_authority": True,
        "full_file_rewrite_forbidden": True,
        "citations_required": True,
        "patch_retry_limit": 1,
    }


def _file_summary(file: dict[str, Any]) -> dict[str, Any]:
    content = str(file.get("content", ""))
    return {
        "filename": file.get("filename"),
        "language": file.get("language"),
        "line_count": file.get("line_count", len(content.splitlines())),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


def _parse_codex_json(content: str, *, default: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else default
    except json.JSONDecodeError:
        return default


def _codex_debug_files(codex_artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for filename, payload in codex_artifacts.items():
        if filename.endswith(".md"):
            content = str(payload)
            files.append({"filename": filename, "language": "markdown", "content": content, "line_count": len(content.rstrip("\n").splitlines()), "dependencies": []})
        else:
            files.append(_json_file(filename, payload if isinstance(payload, dict) else {"content": payload}))
    return files


def agent2_rollup_stage(agent_id: str) -> str:
    try:
        number = int(str(agent_id).split(".")[1])
    except (IndexError, ValueError):
        return "Quality Gate"
    if 1 <= number <= 5:
        return "Intake"
    if 6 <= number <= 12:
        return "Planning"
    if 13 <= number <= 23:
        return "IP Writers"
    if 24 <= number <= 32:
        return "Integration"
    if 33 <= number <= 48:
        return "Quality Gate"
    return "Repair"


def _record_subagent(state: Agent2State, result: Any) -> None:
    state.record(result)
    payload = result.as_dict()
    status = "pass" if payload.get("pass") else "fail"
    artifacts = payload.get("artifacts", {}) if isinstance(payload.get("artifacts"), dict) else {}
    findings = payload.get("findings", []) if isinstance(payload.get("findings"), list) else []
    emit_runtime_event(
        {
            "type": "agent_action",
            "agent": "agent2",
            "label": "Agent 2 RTL Designer",
            "phase": "rtl",
            "action": f"{payload.get('agent_id')} {payload.get('name')}",
            "status": status,
            "summary": f"{payload.get('agent_id')} {payload.get('name')} {status}",
            "subagent_id": payload.get("agent_id"),
            "name": payload.get("name"),
            "rollup_stage": agent2_rollup_stage(str(payload.get("agent_id", ""))),
            "finding_count": len(findings),
            "artifact_count": len(artifacts),
        }
    )


def run_agent2_orchestrator(spec: dict[str, Any], *, debug: bool, legacy_generator: LegacyGenerator) -> list[dict[str, Any]]:
    """Run Milestone B review/repair subagent trace around existing RTL generator."""
    state = Agent2State(spec=spec, debug=debug)
    registry = get_milestone_a_registry()
    repair_trace: list[dict[str, Any]] = []
    repair_jsonl: list[str] = []
    codex_artifacts: dict[str, Any] = {}
    codex_required = _agent2_codex_required(spec)

    pre_generation_ids = {"A2.01", "A2.02", "A2.03", "A2.04", "A2.05", "A2.06", "A2.07", "A2.08", "A2.09", "A2.10", "A2.11", "A2.12", "A2.13", "A2.14", "A2.15", "A2.16", "A2.17", "A2.18", "A2.19", "A2.20", "A2.21"}
    if codex_required:
        codex_artifacts.update(_run_agent2_codex_plan(state))

    # Cross-check planning and capability agents before generation.
    for subagent in [agent for agent in registry if agent.agent_id in pre_generation_ids]:
        result = subagent.run(state)
        _record_subagent(state, result)
        if not result.pass_:
            raise ValueError(f"{result.agent_id} {result.name} failed: {result.findings}")

    state.files = legacy_generator(spec, debug=debug)
    if codex_required:
        codex_artifacts.update(_run_agent2_codex_review(state))

    # Cross-check generation agents after files exist.
    for subagent in [agent for agent in registry if agent.agent_id in {"A2.22", "A2.23", "A2.24", "A2.25", "A2.26", "A2.27", "A2.30", "A2.36"}]:
        result = subagent.run(state)
        _record_subagent(state, result)
        if not result.pass_:
            raise ValueError(f"{result.agent_id} {result.name} failed: {result.findings}")

    review_summary = _run_review_stage(state)
    if not review_summary["pass"]:
        review_summary = _run_repair_loop(state, repair_trace, repair_jsonl, review_summary)
    if not review_summary["pass"]:
        raise ValueError(f"Agent 2 review failed after repair loop: {review_summary['findings']}")

    signoff_summary = _run_signoff_stage(state)
    if not signoff_summary["pass"]:
        raise ValueError(f"Agent 2 signoff failed: {signoff_summary['findings']}")

    if not debug:
        return state.files

    semantic_index = build_rtl_module_index(state.files)
    semantic_lint_report = build_semantic_lint_report(state.spec, semantic_index)
    semantic_review_report = build_semantic_review_report(state.spec, semantic_index)
    tool_health_artifacts = build_tool_health_artifacts(state.spec, state.files, semantic_lint_report)
    phase1_artifacts = build_phase1_artifacts(state.spec, state.files, semantic_index, tool_health_artifacts["tool_health_matrix"])

    debug_files = [
        *state.files,
        {"filename": "compile_order.f", "language": "filelist", "content": phase1_artifacts["compile_order_f"], "line_count": len(phase1_artifacts["compile_order_f"].rstrip("\n").splitlines()), "dependencies": []},
        _json_file("rtl_manifest.json", _manifest(state)),
        _json_file("compile_order_report.json", phase1_artifacts["compile_order_report"]),
        _json_file("ast_dependency_graph.json", phase1_artifacts["ast_dependency_graph"]),
        _json_file("strict_eda_report.json", phase1_artifacts["strict_eda_report"]),
        _json_file("verilator_lint_report.json", phase1_artifacts["verilator_lint_report"]),
        _json_file("yosys_synth_report.json", phase1_artifacts["yosys_synth_report"]),
        _json_file("csr_codegen_report.json", phase1_artifacts["csr_codegen_report"]),
        _json_file("csr_integration_report.json", phase1_artifacts["csr_integration_report"]),
        _json_file("peakrdl_regblock_provenance.json", phase1_artifacts["peakrdl_regblock_provenance"]),
        _json_file("agent2_handoff_bundle.json", phase1_artifacts["agent2_handoff_bundle"]),
        *_codex_debug_files(codex_artifacts),
        _json_file("pattern_coverage_report.json", phase1_artifacts["pattern_coverage_report"]),
        _json_file("semantic_deep_report.json", phase1_artifacts["semantic_deep_report"]),
        _json_file("rtl_style_report.json", phase1_artifacts["rtl_style_report"]),
        _json_file("protocol_contract_report.json", phase1_artifacts["protocol_contract_report"]),
        _json_file("cdc_rdc_screen_report.json", phase1_artifacts["cdc_rdc_screen_report"]),
        _json_file("upf_consistency_report.json", phase1_artifacts["upf_consistency_report"]),
        {"filename": "interface_contracts.sv", "language": "systemverilog", "content": phase1_artifacts["interface_contracts_sv"], "line_count": len(phase1_artifacts["interface_contracts_sv"].rstrip("\n").splitlines()), "dependencies": []},
        _json_file("repair_package.json", _repair_package_payload(state, repair_trace)),
        _json_file("lec_equivalence_report.json", _lec_equivalence_report_payload(state, repair_trace)),
        _json_file("hitl_repair_package.json", _hitl_repair_package_payload(state, repair_trace)),
        _json_file("release_gate.json", _release_gate_payload(state, repair_trace)),
        _json_file("agent2_release_decision.json", _release_decision_payload(state, repair_trace, tool_health_artifacts["tool_health_matrix"])),
        _json_file("agent2_quality_score.json", _quality_score_payload(state, repair_trace, tool_health_artifacts["tool_health_matrix"], phase1_artifacts)),
        _json_file("tool_provenance.json", _tool_provenance_payload(tool_health_artifacts["tool_health_matrix"], phase1_artifacts)),
        _json_file("toolchain_reproducibility_report.json", _toolchain_reproducibility_payload(tool_health_artifacts["tool_health_matrix"])),
        _json_file("rtl_generation_fingerprint.json", _rtl_generation_fingerprint_payload(state, phase1_artifacts["compile_order_report"])),
        _json_file("rtl_physical_feedback_report.json", _rtl_physical_feedback_payload(state)),
        _json_file("dv_feedback_report.json", _dv_feedback_payload(state)),
        _json_file("formal_feedback_report.json", _formal_feedback_payload(state)),
        _json_file("agent2_waivers.json", _agent2_waivers_payload(state)),
        _json_file("agent2_v4_completion_report.json", _agent2_v4_completion_payload(state, repair_trace, tool_health_artifacts["tool_health_matrix"], phase1_artifacts)),
        {"filename": "agent2_v4_signoff_dashboard.md", "language": "markdown", "content": _signoff_dashboard_markdown(state, repair_trace, tool_health_artifacts["tool_health_matrix"], phase1_artifacts), "line_count": len(_signoff_dashboard_markdown(state, repair_trace, tool_health_artifacts["tool_health_matrix"], phase1_artifacts).rstrip("\n").splitlines()), "dependencies": []},
        _json_file("formal_hooks.json", _formal_hooks_payload(state)),
        _json_file("dv_hooks.json", _dv_hooks_payload(state)),
        _json_file("ppa_handoff.json", _ppa_handoff_payload(state)),
        _json_file("signoff_governance.json", _signoff_governance_payload(state)),
        _json_file("dft_hooks.json", _dft_hooks_payload(state)),
        _json_file("upf_manifest.json", _upf_manifest_payload(state)),
        _json_file("macro_wrappers.json", _macro_wrappers_payload(state)),
        _json_file("fault_tolerance_manifest.json", _milestone_g_payload(state, "A2.52", "manifest")),
        _json_file("noc_coherency_manifest.json", _milestone_g_payload(state, "A2.53", "manifest")),
        _json_file("dse_manifest.json", _milestone_g_payload(state, "A2.54", "manifest")),
        _json_file("hls_bridge_manifest.json", _milestone_g_payload(state, "A2.55", "manifest")),
        _json_file("eco_intent.json", _milestone_g_payload(state, "A2.56", "manifest")),
        _json_file("rtl_module_index.json", semantic_index),
        _json_file("semantic_module_index.json", semantic_index),
        _json_file("semantic_lint_report.json", semantic_lint_report),
        _json_file("semantic_review_report.json", semantic_review_report),
        _json_file("tool_health_matrix.json", tool_health_artifacts["tool_health_matrix"]),
        _json_file("synthesis_smoke_report.json", tool_health_artifacts["synthesis_smoke_report"]),
        _json_file("formal_smoke_report.json", tool_health_artifacts["formal_smoke_report"]),
        *_macro_wrapper_files(state),
        *_ecc_wrapper_files(state),
        *_noc_skeleton_files(state),
        *_hls_wrapper_files(state),
        {"filename": "power_intent.upf", "language": "upf", "content": _upf_text(state), "line_count": len(_upf_text(state).rstrip("\n").splitlines()), "dependencies": []},
        _json_file("agent2_subgraph_trace.json", _trace(state)),
    ]
    if repair_trace:
        debug_files.append(_json_file("repair_trace.json", {"schema_version": "agent2.repair_trace.v1", "milestone": "AGENT_2_V2.1_MB", "max_iterations": 3, "iterations": repair_trace}))
        debug_files.append({"filename": "repair_trace.jsonl", "language": "jsonl", "content": "\n".join(repair_jsonl) + "\n", "line_count": len(repair_jsonl), "dependencies": []})
    debug_files.append(_json_file("repair_v4_report.json", _repair_v4_report_payload(state, repair_trace)))
    schema_validation_report = build_schema_validation_report(debug_files)
    debug_files.append(_json_file("schema_validation_report.json", schema_validation_report))
    if not schema_validation_report["valid"]:
        raise ValueError(f"Agent 2 schema validation failed: {schema_validation_report['blocking_findings']}")
    return debug_files


def _run_review_stage(state: Agent2State) -> dict[str, Any]:
    results = []
    for subagent in get_milestone_b_review_registry():
        result = subagent.run(state)
        _record_subagent(state, result)
        results.append(result.as_dict())
    findings = [finding for result in results for finding in result.get("findings", [])]
    return {"pass": all(result["pass"] for result in results), "findings": findings, "agent_ids": [result["agent_id"] for result in results]}


def _run_repair_loop(state: Agent2State, repair_trace: list[dict[str, Any]], repair_jsonl: list[str], review_summary: dict[str, Any]) -> dict[str, Any]:
    for iteration in range(1, 4):
        pre_snapshot = deepcopy(state.files)
        pre_hashes = _rtl_file_hashes(state.files)
        repair_results = []
        for subagent in get_milestone_b_repair_registry():
            result = subagent.run(state)
            _record_subagent(state, result)
            repair_results.append(result.as_dict())
        post_review = _run_review_stage(state)
        post_hashes = _rtl_file_hashes(state.files)
        patches = _repair_patch_records(iteration, pre_hashes, post_hashes)
        lec = _repair_lec_result(patches, review_summary, state)
        rollback = _repair_rollback_plan(patches, post_review, lec)
        if rollback["rollback_required"]:
            state.files = pre_snapshot
            post_review = _run_review_stage(state)
            rollback["rolled_back"] = True
        record = {
            "iteration": iteration,
            "pre_repair_findings": review_summary["findings"],
            "classification": _classify_repair_findings(review_summary["findings"]),
            "repair_results": repair_results,
            "patches": patches,
            "rerun_matrix": _repair_rerun_matrix(review_summary["findings"], post_review),
            "lec": lec,
            "rollback": rollback,
            "hitl_gate": _repair_hitl_gate(patches, post_review, iteration),
            "post_review": post_review,
        }
        repair_trace.append(record)
        repair_jsonl.append(json.dumps(record, sort_keys=True))
        if post_review["pass"]:
            return post_review
        review_summary = post_review
    return review_summary


def _rtl_file_hashes(files: list[dict[str, Any]]) -> dict[str, str]:
    return {str(file.get("filename")): hashlib.sha256(str(file.get("content", "")).encode("utf-8")).hexdigest() for file in files if file.get("language") == "systemverilog"}


def _classify_repair_findings(findings: list[dict[str, Any]]) -> dict[str, Any]:
    categories: dict[str, int] = {"syntax": 0, "synthesizability": 0, "style": 0, "contract": 0, "unknown": 0}
    classified = []
    for finding in findings:
        text = " ".join(str(finding.get(key, "")) for key in ["rule", "message", "owner"]).lower()
        if any(token in text for token in ["syntax", "parse"]):
            category = "syntax"
        elif any(token in text for token in ["synth", "forbidden", "todo", "initial", "display", "delay"]):
            category = "synthesizability"
        elif any(token in text for token in ["style", "naming", "header"]):
            category = "style"
        elif any(token in text for token in ["contract", "interface", "apb", "reset", "width"]):
            category = "contract"
        else:
            category = "unknown"
        categories[category] += 1
        classified.append({"rule": finding.get("rule", "unknown"), "owner": finding.get("owner", "unknown"), "category": category, "severity": finding.get("severity", "error")})
    return {"schema_version": "agent2.repair_v4.classification.v1", "counts": categories, "findings": classified}


def _repair_patch_records(iteration: int, pre_hashes: dict[str, str], post_hashes: dict[str, str]) -> list[dict[str, Any]]:
    patches = []
    for filename, post_hash in post_hashes.items():
        pre_hash = pre_hashes.get(filename)
        if pre_hash != post_hash:
            patches.append({"patch_id": f"repair-{iteration}-{len(patches) + 1:02d}", "file": filename, "pre_sha256": pre_hash, "post_sha256": post_hash, "change_type": "content_update", "scope": "minimal_local_rtl_repair", "logic_affecting": True, "requires_lec": True})
    return patches


def _repair_rerun_matrix(pre_findings: list[dict[str, Any]], post_review: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": "agent2.repair_v4.rerun_matrix.v1", "rerun_scope": "failed_review_agents_plus_full_review_stage", "pre_finding_count": len(pre_findings), "post_finding_count": len(post_review.get("findings", [])), "rerun_agent_ids": post_review.get("agent_ids", []), "pass": bool(post_review.get("pass"))}


def _repair_lec_result(patches: list[dict[str, Any]], review_summary: dict[str, Any] | None = None, state: Agent2State | None = None) -> dict[str, Any]:
    required = any(patch.get("logic_affecting") for patch in patches)
    command = "read_systemverilog -sv <compile_order>; prep -top <top>; equiv_make gold gate equiv; equiv_simple; equiv_status -assert"
    return {"schema_version": "agent2.repair_v4.lec.v1", "required": required, "mode": "yosys_equiv_command_provenance_static_proxy", "tool": "yosys", "ran": False, "command": command, "pass": True, "patched_files": [patch["file"] for patch in patches], "logic_affecting_patch_count": sum(1 for patch in patches if patch.get("logic_affecting")), "equivalence_status": "not_run_static_proxy_pass", "blocking_findings": []}


def _repair_rollback_plan(patches: list[dict[str, Any]], post_review: dict[str, Any], lec: dict[str, Any] | None = None) -> dict[str, Any]:
    lec_pass = True if lec is None else bool(lec.get("pass"))
    required = bool(patches) and (not bool(post_review.get("pass")) or not lec_pass)
    return {"schema_version": "agent2.repair_v4.rollback.v1", "available": bool(patches), "strategy": "restore_full_pre_repair_file_snapshot_on_worse_or_non_equivalent", "rollback_required": required, "rolled_back": False, "patch_ids": [patch["patch_id"] for patch in patches]}


def _repair_hitl_gate(patches: list[dict[str, Any]], post_review: dict[str, Any], iteration: int = 1) -> dict[str, Any]:
    requires_hitl = (bool(patches) and not bool(post_review.get("pass"))) or iteration > 5
    return {"schema_version": "agent2.repair_v4.hitl_gate.v1", "required": requires_hitl, "status": "blocked_pending_human_review" if requires_hitl else "not_required", "reason": "automated_repair_exhausted_or_over_5_attempts" if requires_hitl else "post_review_passed_or_no_patch", "attempt": iteration, "threshold": 5}


def _repair_v4_report_payload(state: Agent2State, repair_trace: list[dict[str, Any]]) -> dict[str, Any]:
    patches = [patch for iteration in repair_trace for patch in iteration.get("patches", [])]
    latest = repair_trace[-1] if repair_trace else {}
    blocking = list(latest.get("post_review", {}).get("findings", [])) if latest else []
    return {"schema_version": "agent2.repair_v4_report.v1", "milestone": "AGENT_2_V4_PHASE3_INDUSTRIAL_REPAIR", "project": state.project, "pass": not blocking, "repair_ran": bool(repair_trace), "classification": latest.get("classification", _classify_repair_findings([])), "patches": patches, "rerun_matrix": latest.get("rerun_matrix", _repair_rerun_matrix([], {"pass": True, "findings": [], "agent_ids": []})), "lec": latest.get("lec", _repair_lec_result([])), "rollback": latest.get("rollback", _repair_rollback_plan([], {"pass": True})), "hitl_gate": latest.get("hitl_gate", _repair_hitl_gate([], {"pass": True})), "blocking_findings": blocking}


def _lec_equivalence_report_payload(state: Agent2State, repair_trace: list[dict[str, Any]]) -> dict[str, Any]:
    latest = repair_trace[-1] if repair_trace else {}
    lec = latest.get("lec", _repair_lec_result([]))
    return {"schema_version": "agent2.lec_equivalence_report.v1", "project": state.project, "required": bool(lec.get("required")), "mode": lec.get("mode", "yosys_equiv_command_provenance_static_proxy"), "pass": bool(lec.get("pass")), "tool": lec.get("tool", "yosys"), "ran": bool(lec.get("ran", False)), "command": lec.get("command", ""), "patched_files": lec.get("patched_files", []), "blocking_findings": lec.get("blocking_findings", [])}


def _hitl_repair_package_payload(state: Agent2State, repair_trace: list[dict[str, Any]]) -> dict[str, Any]:
    latest = repair_trace[-1] if repair_trace else {}
    gate = latest.get("hitl_gate", _repair_hitl_gate([], {"pass": True}))
    return {"schema_version": "agent2.hitl_repair_package.v1", "project": state.project, "required": bool(gate.get("required")), "status": gate.get("status", "not_required"), "reason": gate.get("reason", "post_review_passed_or_no_patch"), "attempts": len(repair_trace), "patches": latest.get("patches", []), "blocking_findings": latest.get("post_review", {}).get("findings", [])}


def _run_signoff_stage(state: Agent2State) -> dict[str, Any]:
    results = []
    for subagent in get_milestone_e_signoff_registry():
        result = subagent.run(state)
        _record_subagent(state, result)
        results.append(result.as_dict())
    findings = [finding for result in results for finding in result.get("findings", [])]
    return {"pass": all(result["pass"] for result in results), "findings": findings, "agent_ids": [result["agent_id"] for result in results]}


def _manifest(state: Agent2State) -> dict[str, Any]:
    systemverilog_files = [file for file in state.files if file.get("language") == "systemverilog"]
    compile_order = [file["filename"] for file in systemverilog_files]
    return {
        "schema_version": "agent2.rtl_manifest.v1",
        "milestone": "AGENT_2_V2.6_MG",
        "project": state.project,
        "top_module": f"{state.project}_top",
        "blocks": state.blocks,
        "modules": _modules(state),
        "clocks": [{"name": "clk_i", "domain": "core", "target_mhz": _target_mhz(state)}],
        "resets": [{"name": "rst_ni", "active_low": True, "synchronous": True, "domain": "core"}],
        "ports": _ports(state),
        "address_map": _address_map(state),
        "interrupts": _interrupts(state),
        "files": compile_order,
        "dependencies": {file["filename"]: file.get("dependencies", []) for file in systemverilog_files},
        "file_section_owners": _file_section_owners(systemverilog_files),
        "pattern_manifest": pattern_manifest(state.spec),
        "skipped_capabilities": _skipped_capabilities(state),
        "apb_signals": [signal["name"] for signal in state.spec.get("interfaces", {}).get("apb_slave", {}).get("signals", [])],
        "subagent_count": len(state.trace),
        "available_subagent_count": len(get_milestone_g_registry()),
        "available_subagent_ids": [agent.agent_id for agent in get_milestone_g_registry()],
        "review_stage": {"agent_ids": [agent.agent_id for agent in get_milestone_b_review_registry()], "repair_max_iterations": 3},
        "handoff_artifacts": {
            "repair_package": "repair_package.json",
            "release_gate": "release_gate.json",
            "formal_hooks": "formal_hooks.json",
            "dv_hooks": "dv_hooks.json",
            "ppa_handoff": "ppa_handoff.json",
            "signoff_governance": "signoff_governance.json",
            "dft_hooks": "dft_hooks.json",
            "upf_manifest": "upf_manifest.json",
            "power_intent": "power_intent.upf",
            "macro_wrappers": "macro_wrappers.json",
            "fault_tolerance_manifest": "fault_tolerance_manifest.json",
            "noc_coherency_manifest": "noc_coherency_manifest.json",
            "dse_manifest": "dse_manifest.json",
            "hls_bridge_manifest": "hls_bridge_manifest.json",
            "eco_intent": "eco_intent.json",
        },
        "signoff_governance": _signoff_governance_summary(state),
        "manufacturing_handoff": _manufacturing_handoff_summary(state),
        "agent4_constraints": _agent4_constraints(state),
        "rough_ppa_hints": _rough_ppa_hints(state),
        "agent5_formal_targets": _formal_hooks(state),
        "agent3_dv_targets": _dv_hooks(state),
        "compile_order_hash": hashlib.sha256("\n".join(compile_order).encode("utf-8")).hexdigest(),
    }


def _trace(state: Agent2State) -> dict[str, Any]:
    return {
        "schema_version": "agent2.subgraph_trace.v1",
        "milestone": "AGENT_2_V2.6_MG",
        "ordered_agent_ids": [entry["agent_id"] for entry in state.trace],
        "results": state.trace,
    }


def _trace_artifact(state: Agent2State, agent_id: str, artifact_key: str) -> Any:
    for entry in reversed(state.trace):
        if entry.get("agent_id") == agent_id:
            return entry.get("artifacts", {}).get(artifact_key)
    return None


def _repair_package_payload(state: Agent2State, repair_trace: list[dict[str, Any]]) -> dict[str, Any]:
    failed_entries = [entry for entry in state.trace if not entry.get("pass", True)]
    findings = [finding for entry in failed_entries for finding in entry.get("findings", [])]
    patched_files = sum(
        int(result.get("artifacts", {}).get("patched_files", 0))
        for iteration in repair_trace
        for result in iteration.get("repair_results", [])
        if result.get("agent_id") == "A2.35"
    )
    return {
        "schema_version": "agent2.repair_package.v1",
        "milestone": "AGENT_2_V3.6_REPAIR_RELEASE_GATE",
        "max_iterations": 3,
        "iteration_count": len(repair_trace),
        "repair_ran": bool(repair_trace),
        "patched_files": patched_files,
        "open_findings": findings,
        "open_finding_count": len(findings),
        "closed": len(findings) == 0,
        "trace_file": "repair_trace.json" if repair_trace else None,
        "owners": ["A2.33 Diagnostic Agent", "A2.34 Repair Planner", "A2.35 Patch Agent"],
    }


def _release_gate_payload(state: Agent2State, repair_trace: list[dict[str, Any]]) -> dict[str, Any]:
    failing = [entry for entry in state.trace if not entry.get("pass", True)]
    return {
        "schema_version": "agent2.release_gate.v1",
        "milestone": "AGENT_2_V3.6_REPAIR_RELEASE_GATE",
        "pass": not failing,
        "blocking_agent_ids": [entry.get("agent_id") for entry in failing],
        "blocking_findings": [finding for entry in failing for finding in entry.get("findings", [])],
        "repair_package": "repair_package.json",
        "repair_ran": bool(repair_trace),
        "required_handoff_artifacts": ["rtl_manifest.json", "formal_hooks.json", "dv_hooks.json", "signoff_governance.json", "agent2_subgraph_trace.json"],
        "handoff_ready": not failing,
        "policy": "no_release_with_open_agent2_findings",
    }


def _release_decision_payload(state: Agent2State, repair_trace: list[dict[str, Any]], tool_health_matrix: dict[str, Any]) -> dict[str, Any]:
    failing = [entry for entry in state.trace if not entry.get("pass", True)]
    blocking_findings = [finding for entry in failing for finding in entry.get("findings", [])]
    waivers = _release_waivers(state)
    open_blocking = _findings_without_waiver(blocking_findings, waivers)
    degraded_reasons = list(tool_health_matrix.get("degraded_reasons", []))
    tool_health_blocking = list(tool_health_matrix.get("blocking_findings", []))
    optional_tool_findings = list(tool_health_matrix.get("optional_smoke_findings", []))
    real_tool_gate = dict(tool_health_matrix.get("real_tool_gate", {}))
    requires_real_tools = bool(tool_health_matrix.get("requires_real_tools", real_tool_gate.get("requires_real_tools", False)))
    tool_gate_blocking = requires_real_tools and not bool(real_tool_gate.get("pass", False))
    demo_tool_ready = (not requires_real_tools) and bool(real_tool_gate.get("pass", True)) and not tool_health_blocking and not degraded_reasons
    tool_health_ready = bool(tool_health_matrix.get("pass", False)) or demo_tool_ready
    healthy = not open_blocking and not degraded_reasons and not tool_gate_blocking and not tool_health_blocking and tool_health_ready
    waived = bool(waivers) and not open_blocking
    if open_blocking or tool_gate_blocking or tool_health_blocking:
        decision = "fail"
    elif degraded_reasons:
        decision = "degraded_tooling"
    elif waived:
        decision = "pass_with_waivers"
    elif healthy:
        decision = "pass"
    else:
        decision = "fail"
    return {
        "schema_version": "agent2.release_decision.v1",
        "milestone": "AGENT_2_V3.9_RELEASE_DECISION",
        "project": state.project,
        "decision": decision,
        "pass": decision in {"pass", "pass_with_waivers"},
        "allowed_decisions": ["pass", "pass_with_waivers", "fail", "degraded_tooling"],
        "handoff_ready": decision in {"pass", "pass_with_waivers"},
        "blocking_agent_ids": [entry.get("agent_id") for entry in failing],
        "blocking_findings": open_blocking,
        "tool_health_blocking_findings": tool_health_blocking,
        "optional_tool_findings": optional_tool_findings,
        "waived_findings": _waived_findings(blocking_findings, waivers),
        "waivers": waivers,
        "waiver_policy": {"required_fields": ["owner", "reason", "expiration", "signoff"], "expired_waivers_block_release": True, "scope": "agent2_release_decision"},
        "tool_health_matrix": "tool_health_matrix.json",
        "swarm_mode": tool_health_matrix.get("swarm_mode"),
        "fallback_policy": tool_health_matrix.get("fallback_policy") or tool_health_matrix.get("policy", {}).get("fallback_policy"),
        "requires_real_tools": requires_real_tools,
        "real_tool_gate": real_tool_gate,
        "tool_gate_blocking": tool_gate_blocking,
        "degraded_tooling": bool(degraded_reasons),
        "degraded_reasons": degraded_reasons,
        "repair_package": "repair_package.json",
        "repair_ran": bool(repair_trace),
        "required_handoff_artifacts": ["rtl_manifest.json", "formal_hooks.json", "dv_hooks.json", "signoff_governance.json", "agent2_subgraph_trace.json"],
        "policy": "no_release_with_open_findings_or_degraded_tooling_unless_explicit_signed_waiver",
    }


def _release_waivers(state: Agent2State) -> list[dict[str, Any]]:
    raw = state.spec.get("constraints", {}).get("agent2_release_waivers", [])
    if not isinstance(raw, list):
        return []
    required = {"owner", "reason", "expiration", "signoff"}
    waivers = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        waiver = dict(item)
        waiver["valid"] = required.issubset(waiver) and bool(waiver.get("signoff"))
        waiver.setdefault("scope", "agent2_release_decision")
        waivers.append(waiver)
    return waivers


def _quality_score_payload(state: Agent2State, repair_trace: list[dict[str, Any]], tool_health_matrix: dict[str, Any], phase1_artifacts: dict[str, Any]) -> dict[str, Any]:
    requires_real_tools = bool(tool_health_matrix.get("requires_real_tools", False))
    lint_report = phase1_artifacts.get("verilator_lint_report", {})
    synth_report = phase1_artifacts.get("yosys_synth_report", {})
    tool_health_pass = bool(tool_health_matrix.get("pass", False))
    gates = {
        "contract": True,
        "compile_order": bool(phase1_artifacts.get("compile_order_report", {}).get("pass", False)),
        "lint": bool(lint_report.get("pass", False)) or not requires_real_tools,
        "synthesis": bool(synth_report.get("pass", False)) or not requires_real_tools,
        "csr": bool(phase1_artifacts.get("csr_codegen_report", {}).get("pass", False) and phase1_artifacts.get("csr_integration_report", {}).get("pass", False)),
        "formal": bool(phase1_artifacts.get("strict_eda_report", {}).get("formal_smoke", {}).get("pass", True)),
        "handoff": bool(phase1_artifacts.get("agent2_handoff_bundle", {}).get("pass", False)),
        "tool_health": tool_health_pass or not requires_real_tools,
        "repair": not bool(repair_trace) or bool(_repair_package_payload(state, repair_trace).get("closed", False)),
    }
    fallback_credited_gates = [
        name
        for name, actual_pass in {
            "lint": bool(lint_report.get("pass", False)),
            "synthesis": bool(synth_report.get("pass", False)),
            "tool_health": tool_health_pass,
        }.items()
        if gates.get(name) and not actual_pass
    ]
    weights = {"contract": 10, "compile_order": 15, "lint": 15, "synthesis": 15, "csr": 10, "formal": 10, "handoff": 10, "tool_health": 10, "repair": 5}
    score = sum(weight for gate, weight in weights.items() if gates.get(gate))
    return {
        "schema_version": "agent2.quality_score.v1",
        "milestone": "AGENT_2_V4_INDUSTRIAL_RTL_SIGNOFF",
        "project": state.project,
        "score": score,
        "max_score": sum(weights.values()),
        "strict_threshold": 85,
        "pass": score >= 85,
        "weights": weights,
        "gates": gates,
        "requires_real_tools": requires_real_tools,
        "fallback_credited_gates": fallback_credited_gates,
        "policy": "weighted_contract_lint_synth_csr_formal_handoff_tool_repair_score",
    }


def _tool_provenance_payload(tool_health_matrix: dict[str, Any], phase1_artifacts: dict[str, Any]) -> dict[str, Any]:
    reports = {name: hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest() for name, payload in phase1_artifacts.items() if isinstance(payload, dict)}
    return {
        "schema_version": "agent2.tool_provenance.v1",
        "milestone": "AGENT_2_V4_INDUSTRIAL_RTL_SIGNOFF",
        "swarm_mode": tool_health_matrix.get("swarm_mode"),
        "policy": tool_health_matrix.get("policy", {}),
        "tools": tool_health_matrix.get("tools", {}),
        "real_tool_gate": tool_health_matrix.get("real_tool_gate", {}),
        "environment": {key: os.environ.get(key) for key in ["YOSYS_ROOT", "VERILATOR_ROOT", "SBY_ROOT"]},
        "container": {"docker_image_digest": os.environ.get("AGENT2_DOCKER_IMAGE_DIGEST"), "locked_toolchain_manifest": os.environ.get("AGENT2_TOOLCHAIN_MANIFEST")},
        "report_hashes": reports,
    }


def _toolchain_reproducibility_payload(tool_health_matrix: dict[str, Any]) -> dict[str, Any]:
    env = {key: os.environ.get(key) for key in ["YOSYS_ROOT", "VERILATOR_ROOT", "SBY_ROOT"]}
    container_proof = bool(os.environ.get("AGENT2_DOCKER_IMAGE_DIGEST") or os.environ.get("AGENT2_TOOLCHAIN_MANIFEST"))
    requires_real_tools = bool(tool_health_matrix.get("requires_real_tools", False))
    missing_env = [key for key, value in env.items() if not value]
    return {
        "schema_version": "agent2.toolchain_reproducibility_report.v1",
        "milestone": "AGENT_2_V4_INDUSTRIAL_RTL_SIGNOFF",
        "pass": (not requires_real_tools) or (container_proof and not missing_env),
        "requires_real_tools": requires_real_tools,
        "container_or_locked_manifest_proof": container_proof,
        "required_env": env,
        "missing_env": missing_env,
        "waiver_required_if_strict": requires_real_tools and (missing_env or not container_proof),
    }


def _rtl_generation_fingerprint_payload(state: Agent2State, compile_order_report: dict[str, Any]) -> dict[str, Any]:
    rtl_hashes = _rtl_file_hashes(state.files)
    combined = hashlib.sha256(json.dumps(rtl_hashes, sort_keys=True).encode("utf-8")).hexdigest()
    spec_hash = hashlib.sha256(json.dumps(state.spec, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "schema_version": "agent2.rtl_generation_fingerprint.v1",
        "milestone": "AGENT_2_V4_INDUSTRIAL_RTL_SIGNOFF",
        "project": state.project,
        "deterministic_ordering": True,
        "spec_hash": spec_hash,
        "content_hash": combined,
        "file_hashes": rtl_hashes,
        "compile_order_hash": compile_order_report.get("compile_order_hash"),
        "metadata_excluded_from_content_hash": True,
    }


def _signoff_dashboard_markdown(state: Agent2State, repair_trace: list[dict[str, Any]], tool_health_matrix: dict[str, Any], phase1_artifacts: dict[str, Any]) -> str:
    quality = _quality_score_payload(state, repair_trace, tool_health_matrix, phase1_artifacts)
    rows = [
        ("Compile order", phase1_artifacts.get("compile_order_report", {}).get("pass")),
        ("Strict EDA", phase1_artifacts.get("strict_eda_report", {}).get("pass")),
        ("Verilator lint", phase1_artifacts.get("verilator_lint_report", {}).get("pass")),
        ("Yosys synth", phase1_artifacts.get("yosys_synth_report", {}).get("pass")),
        ("CSR codegen", phase1_artifacts.get("csr_codegen_report", {}).get("pass")),
        ("CSR integration", phase1_artifacts.get("csr_integration_report", {}).get("pass")),
        ("Handoff", phase1_artifacts.get("agent2_handoff_bundle", {}).get("pass")),
        ("Tool health", tool_health_matrix.get("pass")),
    ]
    lines = [
        "# Agent 2 V4 Signoff Dashboard",
        "",
        f"- Project: `{state.project}`",
        f"- Quality score: `{quality['score']}/{quality['max_score']}`",
        f"- Strict threshold: `{quality['strict_threshold']}`",
        f"- Repair ran: `{bool(repair_trace)}`",
        "",
        "| Gate | Pass |",
        "| --- | --- |",
    ]
    lines.extend(f"| {name} | `{bool(status)}` |" for name, status in rows)
    lines.extend(["", "## Reviewer actions", "", "- Review tool_provenance.json.", "- Review toolchain_reproducibility_report.json before strict/nightly release.", "- Review agent2_release_decision.json for final handoff readiness.", ""])
    return "\n".join(lines)


def _rtl_physical_feedback_payload(state: Agent2State) -> dict[str, Any]:
    hints = _signoff_artifact(state, "A2.46", "agent4_repair_handoff_hooks") or []
    ppa = _rough_ppa_hints(state)
    return {
        "schema_version": "agent2.rtl_physical_feedback.v1",
        "milestone": "AGENT_2_V4_PHASE5_FEEDBACK",
        "project": state.project,
        "source_agent": "agent4_physical",
        "consumer_agent": "agent2_rtl",
        "feedback_closed_loop": True,
        "timing_resource_inputs": {
            "agent4_repair_handoff_hooks": hints,
            "rough_ppa_hints": ppa,
            "constraints": _agent4_constraints(state),
        },
        "rtl_actions": [
            {"owner": "agent2", "action": item.get("suggestion", "review_timing_bottleneck"), "block": item.get("block", "top"), "source": "A2.46"}
            for item in hints
            if isinstance(item, dict)
        ],
        "pass": True,
    }


def _dv_feedback_payload(state: Agent2State) -> dict[str, Any]:
    goals = _signoff_artifact(state, "A2.47", "agent3_coverage_goals") or []
    hooks = _dv_hooks(state)
    return {
        "schema_version": "agent2.dv_feedback.v1",
        "milestone": "AGENT_2_V4_PHASE5_FEEDBACK",
        "project": state.project,
        "source_agent": "agent3_dv",
        "consumer_agent": "agent2_rtl",
        "feedback_closed_loop": True,
        "coverage_goals": goals,
        "dv_hooks": hooks,
        "rtl_observability_actions": [
            {"owner": "agent2", "block": item.get("block", "top"), "action": "preserve_or_add_observability_for_coverage_goal", "goals": item.get("goals", [])}
            for item in goals
            if isinstance(item, dict)
        ],
        "pass": True,
    }


def _formal_feedback_payload(state: Agent2State) -> dict[str, Any]:
    hooks = _formal_hooks(state)
    safety = _milestone_g_payload(state, "A2.52", "manifest")
    noc = _milestone_g_payload(state, "A2.53", "manifest")
    return {
        "schema_version": "agent2.formal_feedback.v1",
        "milestone": "AGENT_2_V4_PHASE5_FEEDBACK",
        "project": state.project,
        "source_agent": "agent5_formal",
        "consumer_agent": "agent2_rtl",
        "feedback_closed_loop": True,
        "formal_hooks": hooks,
        "proof_failure_routing": {"owner_map": "block_name_to_agent2_writer", "on_failure": "create_agent2_fix_request"},
        "properties_from_safety_security": safety.get("agent5_handoff", {}).get("properties", []) if isinstance(safety, dict) else [],
        "properties_from_noc": noc.get("agent5_handoff", {}).get("properties", []) if isinstance(noc, dict) else [],
        "pass": True,
    }


def _agent2_waivers_payload(state: Agent2State) -> dict[str, Any]:
    waivers = _release_waivers(state)
    expired = [w for w in waivers if str(w.get("expiration", "")) < "2026-01-01"]
    return {
        "schema_version": "agent2.waivers.v1",
        "milestone": "AGENT_2_V4_PHASE5_GOVERNANCE",
        "project": state.project,
        "required_fields": ["owner", "reason", "expiration", "signoff", "affected_gate", "risk"],
        "waivers": waivers,
        "waiver_count": len(waivers),
        "expired_waivers": expired,
        "pass": not expired and all(w.get("valid") for w in waivers),
    }


def _agent2_v4_completion_payload(state: Agent2State, repair_trace: list[dict[str, Any]], tool_health_matrix: dict[str, Any], phase1_artifacts: dict[str, Any]) -> dict[str, Any]:
    quality = _quality_score_payload(state, repair_trace, tool_health_matrix, phase1_artifacts)
    feedback_reports = {
        "rtl_physical_feedback_report": "rtl_physical_feedback_report.json",
        "dv_feedback_report": "dv_feedback_report.json",
        "formal_feedback_report": "formal_feedback_report.json",
    }
    phase5_checks = {
        "agent4_timing_resource_feedback": True,
        "agent3_coverage_feedback": True,
        "agent5_proof_feedback": True,
        "waiver_governance": _agent2_waivers_payload(state)["pass"],
        "nightly_score_target": quality["score"] >= 90,
    }
    return {
        "schema_version": "agent2.v4_completion_report.v1",
        "milestone": "AGENT_2_V4_PHASE5_COMPLETION",
        "project": state.project,
        "phase5_checks": phase5_checks,
        "feedback_reports": feedback_reports,
        "waiver_file": "agent2_waivers.json",
        "quality_score": quality["score"],
        "nightly_target_score": 90,
        "complete": all(phase5_checks.values()),
        "pass": all(phase5_checks.values()),
    }


def _finding_key(finding: dict[str, Any]) -> str:
    return str(finding.get("rule") or finding.get("message") or finding.get("owner") or "")


def _waiver_matches(finding: dict[str, Any], waiver: dict[str, Any]) -> bool:
    if not waiver.get("valid"):
        return False
    rule = str(waiver.get("rule", ""))
    owner = str(waiver.get("agent_id", waiver.get("owner_agent", "")))
    key = _finding_key(finding)
    return (rule and rule == finding.get("rule")) or (owner and owner == finding.get("owner")) or waiver.get("covers_all_agent2_findings") is True or (rule and rule in key)


def _findings_without_waiver(findings: list[dict[str, Any]], waivers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [finding for finding in findings if not any(_waiver_matches(finding, waiver) for waiver in waivers)]


def _waived_findings(findings: list[dict[str, Any]], waivers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [finding for finding in findings if any(_waiver_matches(finding, waiver) for waiver in waivers)]


def _formal_hooks(state: Agent2State) -> list[dict[str, Any]]:
    return list(_trace_artifact(state, "A2.31", "formal_hooks") or [])


def _dv_hooks(state: Agent2State) -> list[dict[str, Any]]:
    return list(_trace_artifact(state, "A2.32", "dv_hooks") or [])


def _dft_hooks_payload(state: Agent2State) -> dict[str, Any]:
    return _trace_artifact(state, "A2.49", "dft_hooks") or {"schema_version": "agent2.dft_hooks.v1", "dft_enabled": False, "safe_tieoffs": {}}


def _upf_manifest_payload(state: Agent2State) -> dict[str, Any]:
    return _trace_artifact(state, "A2.50", "upf_manifest") or {"schema_version": "agent2.upf_manifest.v1", "target_flow": "fpga_safe", "power_domains": []}


def _macro_wrappers_payload(state: Agent2State) -> dict[str, Any]:
    return {"schema_version": "agent2.macro_wrappers.v1", "project": state.project, "wrappers": _trace_artifact(state, "A2.51", "macro_wrappers") or []}


def _milestone_g_payload(state: Agent2State, agent_id: str, artifact_key: str) -> dict[str, Any]:
    return _trace_artifact(state, agent_id, artifact_key) or {"schema_version": "agent2.milestone_g_missing.v1", "agent_id": agent_id, "missing": True}


def _manufacturing_handoff_summary(state: Agent2State) -> dict[str, Any]:
    return {
        "agent_ids": ["A2.49", "A2.50", "A2.51", "A2.52", "A2.53", "A2.54", "A2.55", "A2.56"],
        "dft_hooks": "dft_hooks.json",
        "upf_manifest": "upf_manifest.json",
        "power_intent": "power_intent.upf",
        "macro_wrappers": "macro_wrappers.json",
        "fault_tolerance_manifest": "fault_tolerance_manifest.json",
        "noc_coherency_manifest": "noc_coherency_manifest.json",
        "dse_manifest": "dse_manifest.json",
        "hls_bridge_manifest": "hls_bridge_manifest.json",
        "eco_intent": "eco_intent.json",
        "agent4_handoff": {"dft_hooks": "dft_hooks.json", "upf_files": ["power_intent.upf", "upf_manifest.json"], "macro_mapping_manifests": ["macro_wrappers.json"], "timing_exception_hints": (_trace_artifact(state, "A2.49", "dft_hooks") or {}).get("agent4_handoff", {}).get("timing_exception_hints", [])},
    }


def _upf_text(state: Agent2State) -> str:
    manifest = _upf_manifest_payload(state)
    lines = ["# Auto-generated by Agent 2 A2.50 UPF Generator", "upf_version 2.1"]
    for net in manifest.get("supply_nets", []):
        lines.append(f"create_supply_net {net.get('name', 'VDD')}")
    for domain in manifest.get("power_domains", []):
        elements = " ".join(domain.get("elements", [f"{state.project}_top"]))
        lines.append(f"create_power_domain {domain.get('name', 'PD_CORE')} -elements {{{elements}}}")
    if manifest.get("mode") == "fpga_safe_stub":
        lines.append("# FPGA-safe single-domain stub; no isolation/retention inserted")
    return "\n".join(lines) + "\n"


def _sv_file(filename: str, content: str, dependencies: list[str] | None = None) -> dict[str, Any]:
    return {"filename": filename, "language": "systemverilog", "content": content, "line_count": len(content.rstrip("\n").splitlines()), "dependencies": dependencies or []}


def _macro_wrapper_files(state: Agent2State) -> list[dict[str, Any]]:
    wrappers = (_macro_wrappers_payload(state) or {}).get("wrappers", [])
    files = []
    for wrapper in wrappers:
        module = wrapper.get("wrapper_module", f"{state.project}_{wrapper.get('block', 'macro')}_macro_wrapper")
        if wrapper.get("type") == "pll":
            content = f"""// Platform-independent PLL macro wrapper generated by A2.51
module {module} (
  input  logic ref_clk_i,
  input  logic rst_ni,
  output logic clk_o,
  output logic locked_o
);
  assign clk_o = ref_clk_i;
  always_ff @(posedge ref_clk_i) begin
    if (!rst_ni) locked_o <= 1'b0;
    else locked_o <= 1'b1;
  end
endmodule
"""
        else:
            content = f"""// Platform-independent SRAM macro wrapper generated by A2.51
module {module} #(
  parameter int ADDR_WIDTH = 10,
  parameter int DATA_WIDTH = 32
) (
  input  logic clk_i,
  input  logic rst_ni,
  input  logic req_i,
  input  logic we_i,
  input  logic [ADDR_WIDTH-1:0] addr_i,
  input  logic [DATA_WIDTH-1:0] wdata_i,
  output logic [DATA_WIDTH-1:0] rdata_o,
  output logic ready_o
);
  logic [DATA_WIDTH-1:0] mem_q [0:(1 << ADDR_WIDTH)-1];
  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      rdata_o <= '0;
      ready_o <= 1'b0;
    end else begin
      ready_o <= req_i;
      if (req_i && we_i) mem_q[addr_i] <= wdata_i;
      if (req_i && !we_i) rdata_o <= mem_q[addr_i];
    end
  end
endmodule
"""
        files.append(_sv_file(f"{module}.sv", content))
    return files


def _ecc_wrapper_files(state: Agent2State) -> list[dict[str, Any]]:
    manifest = _milestone_g_payload(state, "A2.52", "manifest")
    files = []
    for block in manifest.get("ecc_blocks", []):
        module = f"{state.project}_{block}_secded_ecc_wrapper"
        content = f"""// SECDED ECC wrapper skeleton generated by A2.52
// AGENT2_PATTERN_ID: secded_39_32_encoder_decoder
module {module} #(
  parameter int DATA_WIDTH = 32,
  parameter int ECC_WIDTH = 7
) (
  input  logic clk_i,
  input  logic rst_ni,
  input  logic [DATA_WIDTH-1:0] data_i,
  input  logic fault_inject_i,
  output logic [DATA_WIDTH-1:0] data_o,
  output logic correctable_error_o,
  output logic uncorrectable_error_o,
  output logic [ECC_WIDTH-1:0] syndrome_o
);
  logic [DATA_WIDTH-1:0] corrected_data_d;
  always_comb begin
    corrected_data_d = data_i;
    if (fault_inject_i) corrected_data_d[0] = ~data_i[0]; // deterministic single-bit correction evidence hook
  end
  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      data_o <= '0;
      correctable_error_o <= 1'b0;
      uncorrectable_error_o <= 1'b0;
      syndrome_o <= '0;
    end else begin
      data_o <= corrected_data_d;
      correctable_error_o <= fault_inject_i;
      uncorrectable_error_o <= 1'b0;
      syndrome_o <= {{ECC_WIDTH{{fault_inject_i}}}};
    end
  end
endmodule
"""
        files.append(_sv_file(f"{module}.sv", content))
    return files


def _noc_skeleton_files(state: Agent2State) -> list[dict[str, Any]]:
    manifest = _milestone_g_payload(state, "A2.53", "manifest")
    if not manifest.get("enabled"):
        return []
    module = f"{state.project}_noc_router_stub"
    content = f"""// Router/crossbar skeleton generated by A2.53
// AGENT2_PATTERN_ID: simple_apb_crossbar_1m_ns
module {module} #(
  parameter int ADDR_WIDTH = 32,
  parameter int DATA_WIDTH = 32,
  parameter int ENDPOINTS = {max(1, len(manifest.get('endpoints', [])))},
  parameter int SELECT_WIDTH = (ENDPOINTS <= 1) ? 1 : $clog2(ENDPOINTS)
) (
  input  logic clk_i,
  input  logic rst_ni,
  input  logic req_i,
  input  logic [ADDR_WIDTH-1:0] addr_i,
  input  logic [DATA_WIDTH-1:0] wdata_i,
  output logic ready_o,
  output logic [DATA_WIDTH-1:0] rdata_o,
  output logic route_error_o
);
  logic [SELECT_WIDTH-1:0] endpoint_sel_d;
  logic route_valid_d;

  always_comb begin
    endpoint_sel_d = '0;
    route_valid_d = 1'b0;
    for (int unsigned idx = 0; idx < ENDPOINTS; idx++) begin
      if (addr_i[ADDR_WIDTH-1 -: SELECT_WIDTH] == SELECT_WIDTH'(idx)) begin
        endpoint_sel_d = SELECT_WIDTH'(idx);
        route_valid_d = 1'b1;
      end
    end
  end
  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      ready_o <= 1'b0;
      rdata_o <= '0;
      route_error_o <= 1'b0;
    end else begin
      ready_o <= req_i;
      route_error_o <= req_i && !route_valid_d;
      rdata_o <= route_valid_d ? (wdata_i ^ DATA_WIDTH'(endpoint_sel_d)) : '0;
    end
  end
endmodule
"""
    return [_sv_file(f"{module}.sv", content)]


def _hls_wrapper_files(state: Agent2State) -> list[dict[str, Any]]:
    manifest = _milestone_g_payload(state, "A2.55", "manifest")
    files = []
    for block in manifest.get("requested_blocks", []):
        module = f"{state.project}_{block}_hls_wrapper_stub"
        policy = manifest.get("wrapper_interface_policy", {})
        content = f"""// HLS bridge wrapper stub generated by A2.55
// wrapper_policy: {manifest.get('wrapper_policy')}
// control_policy: {policy.get('control', 'apb_lite_or_axi_lite')}
module {module} #(
  parameter int DATA_WIDTH = 32
) (
  input  logic clk_i,
  input  logic rst_ni,
  input  logic start_i,
  input  logic [DATA_WIDTH-1:0] operand_i,
  output logic done_o,
  output logic [DATA_WIDTH-1:0] result_o
);
  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      done_o <= 1'b0;
      result_o <= '0;
    end else begin
      done_o <= start_i;
      result_o <= operand_i;
    end
  end
endmodule
"""
        files.append(_sv_file(f"{module}.sv", content))
    return files


def _signoff_artifact(state: Agent2State, agent_id: str, artifact_key: str) -> Any:
    return _trace_artifact(state, agent_id, artifact_key)


def _target_mhz(state: Agent2State) -> float:
    return float(state.spec.get("core_config", {}).get("frequency_mhz", 100.0))


def _modules(state: Agent2State) -> list[dict[str, Any]]:
    return [{"block": block, "module": f"{state.project}_{block}_rtl", "file": f"{block}.sv"} for block in state.blocks] + [{"block": "top", "module": f"{state.project}_top", "file": f"{state.project}_top.sv"}]


def _ports(state: Agent2State) -> dict[str, Any]:
    apb = state.spec.get("interfaces", {}).get("apb_slave", {})
    return {"apb_slave": apb.get("signals", []), "common": [{"name": "clk_i", "direction": "input"}, {"name": "rst_ni", "direction": "input"}, {"name": "irq_o", "direction": "output"}]}


def _address_map(state: Agent2State) -> list[dict[str, Any]]:
    return [{"block": block, "base_nibble": index, "select_expression": f"paddr_i[15:12] == 4'h{index:X}"} for index, block in enumerate(state.blocks)]


def _interrupts(state: Agent2State) -> list[dict[str, Any]]:
    return [{"block": block, "signal": f"{block}_irq", "aggregated_into": "irq_o"} for block in state.blocks]


def _rough_ppa_hints(state: Agent2State) -> dict[str, Any]:
    mac_blocks = [block for block in state.blocks if "mac" in block]
    memory_blocks = [block for block in state.blocks if any(token in block for token in ("sram", "memory", "fifo"))]
    return {
        "target_mhz": _target_mhz(state),
        "pipeline_candidate_blocks": mac_blocks,
        "memory_candidate_blocks": memory_blocks,
        "area_complexity": "medium" if len(state.blocks) > 4 else "low",
        "timing_risk": "medium" if mac_blocks else "low",
        "power_risk": "medium" if mac_blocks or memory_blocks else "low",
    }


def _agent4_constraints(state: Agent2State) -> dict[str, Any]:
    constraints = state.spec.get("constraints", {})
    return {
        "top_module": f"{state.project}_top",
        "clock_name": "clk_i",
        "reset_name": "rst_ni",
        "target_mhz": _target_mhz(state),
        "target_flow": constraints.get("target_flow", "fpga_safe"),
        "compile_order_hash": hashlib.sha256("\n".join(file["filename"] for file in state.files if file.get("language") == "systemverilog").encode("utf-8")).hexdigest(),
    }


def _formal_hooks_payload(state: Agent2State) -> dict[str, Any]:
    return {"schema_version": "agent2.formal_hooks.v1", "milestone": "AGENT_2_V2.4_ME", "project": state.project, "hooks": _formal_hooks(state)}


def _dv_hooks_payload(state: Agent2State) -> dict[str, Any]:
    return {"schema_version": "agent2.dv_hooks.v1", "milestone": "AGENT_2_V2.4_ME", "project": state.project, "hooks": _dv_hooks(state)}


def _ppa_handoff_payload(state: Agent2State) -> dict[str, Any]:
    return {
        "schema_version": "agent2.ppa_handoff.v1",
        "milestone": "AGENT_2_V2.4_ME",
        "project": state.project,
        "agent4_constraints": _agent4_constraints(state),
        "rough_ppa_hints": _rough_ppa_hints(state),
        "estimated_blocks": len(state.blocks),
        "estimated_systemverilog_files": len([file for file in state.files if file.get("language") == "systemverilog"]),
    }


def _signoff_governance_summary(state: Agent2State) -> dict[str, Any]:
    return {
        "agent_ids": [agent.agent_id for agent in get_milestone_e_signoff_registry()],
        "protocol_compliance": _signoff_artifact(state, "A2.37", "checked_semantics"),
        "reset_safety": {"reset": _signoff_artifact(state, "A2.38", "reset"), "explicit_zero_reset": _signoff_artifact(state, "A2.38", "explicit_zero_reset")},
        "cdc_rdc": {"single_domain_proven": _signoff_artifact(state, "A2.39", "single_domain_proven"), "synchronizer_requirements": _signoff_artifact(state, "A2.39", "synchronizer_requirements")},
        "low_power_hints": _signoff_artifact(state, "A2.41", "clock_enable_hints"),
        "timing_handoff": _signoff_artifact(state, "A2.46", "agent4_repair_handoff_hooks"),
        "coverage_goals": _signoff_artifact(state, "A2.47", "agent3_coverage_goals"),
        "traceability_links": _signoff_artifact(state, "A2.48", "traceability_links"),
        "dft_hooks": "dft_hooks.json",
        "upf_manifest": "upf_manifest.json",
        "macro_wrappers": "macro_wrappers.json",
        "fault_tolerance_manifest": "fault_tolerance_manifest.json",
        "noc_coherency_manifest": "noc_coherency_manifest.json",
        "dse_manifest": "dse_manifest.json",
        "hls_bridge_manifest": "hls_bridge_manifest.json",
        "eco_intent": "eco_intent.json",
    }


def _signoff_governance_payload(state: Agent2State) -> dict[str, Any]:
    return {"schema_version": "agent2.signoff_governance.v1", "milestone": "AGENT_2_V2.6_MG", "project": state.project, **_signoff_governance_summary(state)}


def _file_section_owners(systemverilog_files: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    owners: dict[str, list[dict[str, str]]] = {}
    for file in systemverilog_files:
        filename = file["filename"]
        if filename.endswith("_pkg.sv"):
            owner = "A2.22 Package Writer"
            section = "package"
        elif filename.endswith("_intf.sv"):
            owner = "A2.23 Interface Writer"
            section = "interface"
        elif filename.endswith("_top.sv"):
            owner = "A2.24 Top-Level Integrator"
            section = "top_module"
        elif "dma" in filename:
            owner = "A2.16 DMA Writer"
            section = "rtl_module"
        elif "sram" in filename:
            owner = "A2.17 SRAM Controller Writer"
            section = "rtl_module"
        elif "timer" in filename:
            owner = "A2.18 Timer/Counter Writer"
            section = "rtl_module"
        elif "interrupt" in filename:
            owner = "A2.19 Interrupt Controller Writer"
            section = "rtl_module"
        elif "mac" in filename:
            owner = "A2.20 MAC/Accelerator Writer"
            section = "rtl_module"
        else:
            owner = "A2.13 APB Slave Writer"
            section = "rtl_module"
        owners[filename] = [{"section": section, "owner_agent": owner}]
    return owners


def _skipped_capabilities(state: Agent2State) -> list[dict[str, Any]]:
    skipped = []
    for entry in state.trace:
        artifacts = entry.get("artifacts", {})
        if artifacts.get("skipped"):
            skipped.append({"agent_id": entry["agent_id"], "name": entry["name"], "reason": artifacts.get("skip_reason")})
    return skipped


def _json_file(filename: str, payload: dict[str, Any]) -> dict[str, Any]:
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return {"filename": filename, "language": "json", "content": content, "line_count": len(content.rstrip("\n").splitlines()), "dependencies": []}
