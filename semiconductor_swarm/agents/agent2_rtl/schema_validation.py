"""Agent 2 V3.5 artifact schema validation.

Small dependency-free validator for debug JSON artifacts.  It intentionally
checks only contract-critical shape: required keys and Python value types.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


Schema = dict[str, type | tuple[type, ...]]

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"


ARTIFACT_SCHEMAS: dict[str, Schema] = {
    "agent2_debug_report.json": {"pass": bool, "checks": dict, "failures": list},
    "rtl_manifest.json": {"schema_version": str, "project": str, "top_module": str, "files": list, "handoff_artifacts": dict},
    "formal_hooks.json": {"schema_version": str, "project": str, "hooks": list},
    "dv_hooks.json": {"schema_version": str, "project": str, "hooks": list},
    "ppa_handoff.json": {"schema_version": str, "project": str, "agent4_constraints": dict, "rough_ppa_hints": dict},
    "signoff_governance.json": {"schema_version": str, "project": str, "agent_ids": list},
    "dft_hooks.json": {"schema_version": str},
    "upf_manifest.json": {"schema_version": str},
    "macro_wrappers.json": {"schema_version": str, "project": str, "wrappers": list},
    "fault_tolerance_manifest.json": {"schema_version": str, "policy": str, "enabled": bool, "protection_plan": list, "formal_targets": list, "dv_targets": list},
    "noc_coherency_manifest.json": {"schema_version": str, "enabled": bool, "endpoint_count": int, "ordering_rules": list},
    "dse_manifest.json": {"schema_version": str, "enabled": bool, "variants": list, "chosen_variant": (dict, type(None)), "design_space_axes": list},
    "hls_bridge_manifest.json": {"schema_version": str, "requested_blocks": list, "tool_detected": bool, "mode": str, "wrapper_policy": str},
    "eco_intent.json": {"schema_version": str, "auto_apply_netlist_patches": bool, "affected_cones": list, "signoff_checklist": list, "approval_gate_required": bool},
    "rtl_module_index.json": {"schema_version": str, "module_count": int, "modules": list},
    "semantic_module_index.json": {"schema_version": str, "module_count": int, "modules": list},
    "semantic_lint_report.json": {"schema_version": str, "pass": bool, "rules": list, "findings": list},
    "semantic_review_report.json": {"schema_version": str, "milestone": str, "reviewers": list, "findings": list},
    "tool_health_matrix.json": {"schema_version": str, "tools": dict, "valid_statuses": list, "swarm_mode": str, "fallback_policy": str, "requires_real_tools": bool, "real_tool_gate": dict},
    "compile_order_report.json": {"schema_version": str, "pass": bool, "compile_order": list, "compile_order_file": str, "compile_order_hash": str},
    "ast_dependency_graph.json": {"schema_version": str, "nodes": list, "edges": list, "source": str},
    "strict_eda_report.json": {"schema_version": str, "requires_real_tools": bool, "fallback_forbidden": bool, "pass": bool, "blocking_findings": list},
    "verilator_lint_report.json": {"schema_version": str, "tool": str, "tool_status": str, "ran": bool, "pass": bool, "blocking_findings": list, "environment": dict},
    "yosys_synth_report.json": {"schema_version": str, "tool": str, "tool_status": str, "ran": bool, "pass": bool, "blocking_findings": list, "environment": dict},
    "csr_codegen_report.json": {"schema_version": str, "pass": bool, "generator": str, "peakrdl_regblock_provenance": dict, "blocking_findings": list},
    "csr_integration_report.json": {"schema_version": str, "pass": bool, "rtl_files_checked": list, "csr_codegen_report": str, "blocking_findings": list},
    "peakrdl_regblock_provenance.json": {"schema_version": str, "project": str, "generator": str, "input": str, "present": bool, "fallback": bool, "generated_files": list, "pass": bool, "blocking_findings": list},
    "agent2_handoff_bundle.json": {"schema_version": str, "project": str, "rtl_files": list, "compile_order_file": str, "evidence": dict, "pass": bool, "blocking_findings": list},
    "pattern_coverage_report.json": {"schema_version": str, "pass": bool, "requirements": list, "blocking_findings": list},
    "semantic_deep_report.json": {"schema_version": str, "pass": bool, "checks": list, "blocking_findings": list},
    "rtl_style_report.json": {"schema_version": str, "pass": bool, "rules": list, "blocking_findings": list},
    "protocol_contract_report.json": {"schema_version": str, "pass": bool, "contracts": list, "contract_file": str, "blocking_findings": list},
    "cdc_rdc_screen_report.json": {"schema_version": str, "pass": bool, "clock_domains": list, "reset_domains": list, "crossings": list, "blocking_findings": list},
    "upf_consistency_report.json": {"schema_version": str, "pass": bool, "low_power_intent_present": bool, "power_domains": list, "checks": list, "blocking_findings": list},
    "synthesis_smoke_report.json": {"schema_version": str, "tool": str, "ran": bool, "pass": bool, "blocking_findings": list},
    "formal_smoke_report.json": {"schema_version": str, "tool": str, "ran": bool, "pass": bool, "blocking_findings": list},
    "agent2_subgraph_trace.json": {"schema_version": str, "ordered_agent_ids": list, "results": list},
    "repair_trace.json": {"schema_version": str, "iterations": list},
    "repair_v4_report.json": {"schema_version": str, "milestone": str, "pass": bool, "classification": dict, "patches": list, "rerun_matrix": dict, "lec": dict, "rollback": dict, "hitl_gate": dict, "blocking_findings": list},
    "lec_equivalence_report.json": {"schema_version": str, "project": str, "required": bool, "mode": str, "tool": str, "ran": bool, "pass": bool, "blocking_findings": list},
    "hitl_repair_package.json": {"schema_version": str, "project": str, "required": bool, "status": str, "attempts": int, "patches": list, "blocking_findings": list},
    "agent2_release_decision.json": {"schema_version": str, "milestone": str, "project": str, "decision": str, "pass": bool, "handoff_ready": bool, "waivers": list, "degraded_tooling": bool, "degraded_reasons": list, "swarm_mode": str, "fallback_policy": str, "requires_real_tools": bool, "real_tool_gate": dict, "tool_gate_blocking": bool},
}


def validate_payload(filename: str, payload: Any) -> dict[str, Any]:
    """Validate one decoded JSON payload against known Agent 2 schema."""
    schema = ARTIFACT_SCHEMAS.get(filename)
    findings: list[dict[str, Any]] = []
    if schema is None:
        return {"artifact": filename, "schema_known": False, "valid": True, "findings": []}
    if not isinstance(payload, dict):
        return {"artifact": filename, "schema_known": True, "valid": False, "findings": [{"severity": "error", "rule": "payload_object", "message": "payload must be JSON object", "expected_type": "dict", "actual_type": type(payload).__name__}]}
    jsonschema_result = _validate_with_jsonschema(filename, payload)
    if jsonschema_result is not None:
        return jsonschema_result
    for key, expected_type in schema.items():
        if key not in payload:
            findings.append({"severity": "error", "rule": "required_key", "key": key, "message": f"missing required key: {key}"})
            continue
        if not isinstance(payload[key], expected_type):
            expected_names = _type_names(expected_type)
            findings.append({"severity": "error", "rule": "type", "key": key, "message": f"key {key} has wrong type", "expected_type": expected_names, "actual_type": type(payload[key]).__name__})
    return {"artifact": filename, "schema_known": True, "valid": not findings, "findings": findings}


def schema_file_for_artifact(filename: str) -> Path:
    return SCHEMA_DIR / filename.replace(".json", ".schema.json")


def _validate_with_jsonschema(filename: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    schema_path = schema_file_for_artifact(filename)
    if not schema_path.exists():
        return None
    try:
        import jsonschema  # type: ignore
    except Exception:
        return None
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    findings: list[dict[str, Any]] = []
    validator = jsonschema.Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path)):
        path = ".".join(str(part) for part in error.path)
        findings.append({"severity": "error", "rule": "jsonschema", "key": path, "message": error.message, "schema_file": str(schema_path).replace("\\", "/")})
    return {"artifact": filename, "schema_known": True, "schema_file": str(schema_path).replace("\\", "/"), "validator": "jsonschema", "valid": not findings, "findings": findings}


def build_schema_validation_report(files: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate all Agent 2 debug JSON artifacts and emit V3.5 report."""
    checked = []
    deferred = []
    all_findings: list[dict[str, Any]] = []
    for file in files:
        if file.get("language") != "json":
            continue
        filename = str(file.get("filename", ""))
        if filename == "schema_validation_report.json":
            continue
        try:
            payload = json.loads(str(file.get("content", "")))
        except json.JSONDecodeError as exc:
            result = {"artifact": filename, "schema_known": filename in ARTIFACT_SCHEMAS, "valid": False, "findings": [{"severity": "error", "rule": "json_parse", "message": str(exc)}]}
        else:
            result = validate_payload(filename, payload)
        checked.append(result)
        if not result["schema_known"]:
            deferred.append(filename)
        for finding in result["findings"]:
            all_findings.append({"artifact": filename, **finding})
    valid = not any(finding.get("severity") in {"error", "fatal"} for finding in all_findings)
    return {
        "schema_version": "agent2.schema_validation_report.v1",
        "milestone": "AGENT_2_V3.5_MF",
        "schema_dir": str(SCHEMA_DIR).replace("\\", "/"),
        "validator_policy": "jsonschema_if_installed_else_dependency_free_fallback",
        "valid": valid,
        "checked_artifacts": checked,
        "checked_count": len(checked),
        "deferred_artifacts": deferred,
        "findings": all_findings,
        "blocking_findings": [finding for finding in all_findings if finding.get("severity") in {"error", "fatal"}],
    }


def _type_names(expected_type: type | tuple[type, ...]) -> str:
    if isinstance(expected_type, tuple):
        return "|".join(item.__name__ for item in expected_type)
    return expected_type.__name__