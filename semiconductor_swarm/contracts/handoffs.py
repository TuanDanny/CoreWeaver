"""Dataclass builders and semantic validators for v1 swarm handoff contracts."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .constants import (
    AGENT2_TO_AGENT3_V1,
    AGENT2_TO_AGENT4_V1,
    AGENT2_TO_AGENT5_V1,
    AGENT3_RESULT_V1,
    AGENT4_RESULT_V1,
    AGENT5_RESULT_V1,
    SWARM_ARTIFACT_INDEX_V1,
    SWARM_TO_DOCS_AGENT_V1,
)
from .registry import ContractValidationError, validate_contract

RTLFile = dict[str, Any]


def _rtl_sv_files(rtl_files: list[RTLFile]) -> list[RTLFile]:
    return [f for f in rtl_files if f.get("language") == "systemverilog" and str(f.get("filename", "")).endswith(".sv")]


def _module_names(spec: dict[str, Any]) -> list[str]:
    blocks = [b.get("name") for b in spec.get("ip_blocks", []) if isinstance(b, dict) and b.get("name")]
    top = spec.get("top_module") or f"{spec.get('project_name', 'swarm_soc')}_top"
    return [*blocks, top]


def _compile_order(spec: dict[str, Any], rtl_files: list[RTLFile]) -> list[str]:
    names = {f.get("filename") for f in _rtl_sv_files(rtl_files)}
    order: list[str] = []
    for module in _module_names(spec):
        for suffix in ("_pkg.sv", "_intf.sv", ".sv"):
            fn = f"{module}{suffix}"
            if fn in names and fn not in order:
                order.append(fn)
    for f in _rtl_sv_files(rtl_files):
        fn = f.get("filename")
        if fn not in order:
            order.append(fn)
    return order


def _clock_constraints(spec: dict[str, Any]) -> dict[str, Any]:
    domains = spec.get("clock_domains") or spec.get("clocking") or []
    if isinstance(domains, dict):
        freq = domains.get("frequency_mhz") or domains.get("freq_mhz") or 100
        return {"primary_clock": "clk_i", "primary_reset": "rst_ni", "frequency_mhz": int(freq)}
    if domains and isinstance(domains, list) and isinstance(domains[0], dict):
        freq = domains[0].get("frequency_mhz") or domains[0].get("freq_mhz") or 100
        return {"primary_clock": domains[0].get("clock", "clk_i"), "primary_reset": domains[0].get("reset", "rst_ni"), "frequency_mhz": int(freq)}
    return {"primary_clock": "clk_i", "primary_reset": "rst_ni", "frequency_mhz": 100}


@dataclass(frozen=True)
class Agent2ToAgent3ContractV1:
    contract_version: str = AGENT2_TO_AGENT3_V1
    project_name: str = ""
    top_module: str = ""
    rtl_files: list[RTLFile] = field(default_factory=list)
    compile_order: list[str] = field(default_factory=list)
    test_targets: list[str] = field(default_factory=list)
    clock_constraints: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Agent2ToAgent4ContractV1:
    contract_version: str = AGENT2_TO_AGENT4_V1
    project_name: str = ""
    top_module: str = ""
    rtl_files: list[RTLFile] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    compile_order: list[str] = field(default_factory=list)
    target_backend: str = "quartus"
    clock_constraints: dict[str, Any] = field(default_factory=dict)
    physical_constraints: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Agent2ToAgent5ContractV1:
    contract_version: str = AGENT2_TO_AGENT5_V1
    project_name: str = ""
    top_module: str = ""
    rtl_files: list[RTLFile] = field(default_factory=list)
    compile_order: list[str] = field(default_factory=list)
    formal_targets: list[str] = field(default_factory=list)
    properties_requested: list[str] = field(default_factory=list)
    assumption_policy: str = "bounded_environment"
    bounded_depth: int = 20
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentResultContractV1:
    contract_version: str
    project_name: str
    agent: str
    pass_: bool
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    reports: dict[str, Any] = field(default_factory=dict)
    findings: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["pass"] = data.pop("pass_")
        return data


@dataclass(frozen=True)
class SwarmArtifactIndexV1:
    contract_version: str = SWARM_ARTIFACT_INDEX_V1
    run_id: str = ""
    project_name: str = ""
    created_at: str = ""
    status: str = "not_run"
    agents: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    contracts: list[str] = field(default_factory=list)
    dependency_graph: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_agent2_to_agent3_contract(spec: dict[str, Any], rtl_files: list[RTLFile]) -> dict[str, Any]:
    payload = Agent2ToAgent3ContractV1(project_name=spec["project_name"], top_module=spec.get("top_module") or f"{spec['project_name']}_top", rtl_files=_rtl_sv_files(rtl_files), compile_order=_compile_order(spec, rtl_files), test_targets=_module_names(spec), clock_constraints=_clock_constraints(spec), artifacts=[{"kind": "rtl", "count": len(_rtl_sv_files(rtl_files))}]).as_dict()
    validate_agent2_to_agent3_contract(payload)
    return payload


def build_agent2_to_agent4_contract(spec: dict[str, Any], rtl_files: list[RTLFile]) -> dict[str, Any]:
    payload = Agent2ToAgent4ContractV1(project_name=spec["project_name"], top_module=spec.get("top_module") or f"{spec['project_name']}_top", rtl_files=_rtl_sv_files(rtl_files), constraints=spec.get("constraints", {}), compile_order=_compile_order(spec, rtl_files), target_backend=spec.get("target_backend", "quartus"), clock_constraints=_clock_constraints(spec), physical_constraints=spec.get("physical_constraints", {"sdc_required": True, "qsf_required": True}), artifacts=[{"kind": "rtl", "count": len(_rtl_sv_files(rtl_files))}]).as_dict()
    validate_agent2_to_agent4_contract(payload)
    return payload


def build_agent2_to_agent5_contract(spec: dict[str, Any], rtl_files: list[RTLFile]) -> dict[str, Any]:
    payload = Agent2ToAgent5ContractV1(project_name=spec["project_name"], top_module=spec.get("top_module") or f"{spec['project_name']}_top", rtl_files=_rtl_sv_files(rtl_files), compile_order=_compile_order(spec, rtl_files), formal_targets=_module_names(spec), properties_requested=spec.get("properties_requested", ["reset_clean", "no_x_on_outputs", "apb_protocol", "bounded_liveness"]), assumption_policy=spec.get("assumption_policy", "bounded_environment"), bounded_depth=int(spec.get("bounded_depth", 20)), artifacts=[{"kind": "rtl", "count": len(_rtl_sv_files(rtl_files))}]).as_dict()
    validate_agent2_to_agent5_contract(payload)
    return payload


def build_agent_result_contract(contract_version: str, project_name: str, agent: str, passed: bool, artifacts: list[dict[str, Any]], reports: dict[str, Any], findings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    payload = AgentResultContractV1(contract_version, project_name, agent, passed, artifacts, reports, findings or []).as_dict()
    status = "pass" if passed else "fail"
    if contract_version == AGENT3_RESULT_V1:
        payload.update({
            "pass_fail_status": status,
            "coverage_summary": reports.get("coverage_summary", reports.get("coverage", {})) if isinstance(reports, dict) else {},
            "failures": reports.get("failures", findings or []) if isinstance(reports, dict) else (findings or []),
            "tool_availability": reports.get("tool_availability", {}) if isinstance(reports, dict) else {},
            "commands": reports.get("commands", []) if isinstance(reports, dict) else [],
        })
    elif contract_version == AGENT4_RESULT_V1:
        metrics = reports.get("metrics", {}) if isinstance(reports, dict) else {}
        payload.update({
            "backend_used": reports.get("backend_used", reports.get("backend", "quartus")) if isinstance(reports, dict) else "quartus",
            "pass_fail_status": status,
            "timing_summary": reports.get("timing_summary", {"fmax_mhz": metrics.get("fmax_mhz"), "setup_slack_ns": metrics.get("setup_slack_ns"), "hold_slack_ns": metrics.get("hold_slack_ns"), "critical_path": metrics.get("critical_path")}) if isinstance(reports, dict) else {},
            "resource_summary": reports.get("resource_summary", {"alm_usage_pct": metrics.get("alm_usage_pct")}) if isinstance(reports, dict) else {},
            "constraints_generated": reports.get("constraints_generated", [a.get("filename") for a in artifacts if str(a.get("filename", "")).endswith((".sdc", ".qsf", ".xdc"))]) if isinstance(reports, dict) else [],
            "commands": reports.get("commands", []) if isinstance(reports, dict) else [],
            "tool_availability": reports.get("tool_availability", {}) if isinstance(reports, dict) else {},
        })
    elif contract_version == AGENT5_RESULT_V1:
        payload.update({
            "formal_targets": reports.get("formal_targets", [a.get("filename", "").removesuffix(".sby") for a in artifacts if str(a.get("filename", "")).endswith(".sby")]) if isinstance(reports, dict) else [],
            "properties_generated": reports.get("properties_generated", [a.get("filename") for a in artifacts if str(a.get("filename", "")).startswith("fv_")]) if isinstance(reports, dict) else [],
            "proof_results": reports.get("proof_results", [reports] if isinstance(reports, dict) and reports else []) if isinstance(reports, dict) else [],
            "counterexamples": reports.get("counterexamples", []) if isinstance(reports, dict) else [],
            "engines": reports.get("engines", ["smtbmc"]) if isinstance(reports, dict) else ["smtbmc"],
            "bounded_depth": int(reports.get("bounded_depth", 20)) if isinstance(reports, dict) else 20,
            "commands": reports.get("commands", []) if isinstance(reports, dict) else [],
            "tool_availability": reports.get("tool_availability", {}) if isinstance(reports, dict) else {},
        })
    validate_contract(contract_version, payload)
    return payload


def build_swarm_artifact_index(project_name: str, state: dict[str, Any]) -> dict[str, Any]:
    output_root = Path(state["output_root"]) if state.get("output_root") else None
    artifacts: list[dict[str, Any]] = []
    stage_meta = {
        "rtl_files": ("rtl", "agent2", ["agent3", "agent4", "agent5"], ["agent2_to_agent3_contract", "agent2_to_agent4_contract", "agent2_to_agent5_contract"]),
        "dv_files": ("dv", "agent3", ["agent6_docs"], ["agent3_result_contract"]),
        "formal_files": ("formal", "agent5", ["agent6_docs"], ["agent5_result_contract"]),
        "physical_files": ("physical", "agent4", ["agent6_docs"], ["agent4_result_contract"]),
    }
    stage_paths = {"rtl": "rtl", "dv": "tb", "formal": "formal", "physical": "fpga"}
    for key in ("rtl_files", "dv_files", "formal_files", "physical_files"):
        stage, producer, consumers, contract_refs = stage_meta[key]
        for file in state.get(key, []) or []:
            filename = file.get("filename")
            rel_path = str(file.get("output_path") or (f"{stage_paths[stage]}/{filename}" if filename else stage_paths[stage])).replace("\\", "/")
            meta = _file_meta(output_root, rel_path, file.get("content"))
            artifacts.append({
                "trace_id": f"{stage}:{filename}",
                "stage": stage,
                "filename": filename,
                "path": rel_path,
                "language": file.get("language"),
                "state_key": key,
                "producer_agent": producer,
                "consumer_agents": consumers,
                "contract_refs": [ref for ref in contract_refs if isinstance(state.get(ref), dict)],
                "sha256": meta["sha256"],
                "bytes": meta["bytes"],
                "exists": meta["exists"],
            })
    preferred_contracts = [
        "agent1_to_agent2",
        "agent2_to_agent3_contract",
        "agent2_to_agent4_contract",
        "agent2_to_agent5_contract",
        "agent3_result_contract",
        "agent4_result_contract",
        "agent5_result_contract",
    ]
    contract_keys = [k for k in preferred_contracts if isinstance(state.get(k), dict)]
    contract_keys.extend(k for k in state.keys() if k.startswith("agent") and k.endswith("contract") and k not in contract_keys and isinstance(state.get(k), dict))
    contracts = [_contract_index_entry(k, state[k], output_root) for k in contract_keys]
    agents = _agent_status_map(state, artifacts, contracts)
    statuses = [a.get("status", "not_run") for a in agents.values()]
    active_statuses = [status for status in statuses if status != "not_run"]
    status = "fail" if "fail" in active_statuses else "partial" if not active_statuses else "pass"
    stage_counts = {stage: sum(1 for item in artifacts if item["stage"] == stage) for stage in ("rtl", "dv", "formal", "physical")}
    payload = SwarmArtifactIndexV1(
        run_id=str(state.get("run_id") or uuid4()),
        project_name=project_name,
        created_at=datetime.now(UTC).isoformat(),
        status=status,
        agents=agents,
        artifacts=artifacts,
        contracts=contracts,
        dependency_graph=[edge for edge in [
            {"from": "agent2_to_agent3_contract", "to": "agent3_result_contract"},
            {"from": "agent2_to_agent4_contract", "to": "agent4_result_contract"},
            {"from": "agent2_to_agent5_contract", "to": "agent5_result_contract"},
            {"from": "agent3_result_contract", "to": "swarm_artifact_index"},
            {"from": "agent4_result_contract", "to": "swarm_artifact_index"},
            {"from": "agent5_result_contract", "to": "swarm_artifact_index"},
        ] if edge["from"] in contract_keys or edge["from"].startswith("agent2_to_")],
        summary={"artifact_count": len(artifacts), "contract_count": len(contracts), "stage_counts": stage_counts, "traceability_complete": all(bool(a.get("trace_id") and a.get("producer_agent") and a.get("contract_refs")) for a in artifacts), "reports": state.get("reports", {})},
    ).as_dict()
    validate_contract(SWARM_ARTIFACT_INDEX_V1, payload)
    return payload


def build_swarm_to_docs_agent_contract(project_name: str, index: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "contract_version": SWARM_TO_DOCS_AGENT_V1,
        "run_id": index.get("run_id", ""),
        "project_name": project_name,
        "artifact_index": index,
        "docs_requested": ["run_summary", "architecture_summary", "rtl_module_index", "dv_report", "physical_signoff_report", "formal_proof_report", "traceability_matrix", "known_limitations"],
        "artifact_index_path": "contracts/swarm_artifact_index.json",
    }
    validate_contract(SWARM_TO_DOCS_AGENT_V1, payload)
    return payload


def _file_meta(root: Path | None, rel_path: str, fallback_content: Any = None) -> dict[str, Any]:
    path = root / rel_path if root else None
    if path and path.is_file():
        content = path.read_bytes()
        return {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content), "exists": True}
    if fallback_content is not None:
        data = str(fallback_content).encode("utf-8")
        return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "exists": False}
    return {"sha256": None, "bytes": 0, "exists": False}


def _contract_filename(key: str) -> str:
    return {
        "agent1_to_agent2": "agent1_to_agent2.json",
        "agent2_to_agent3_contract": "agent2_to_agent3.json",
        "agent2_to_agent4_contract": "agent2_to_agent4.json",
        "agent2_to_agent5_contract": "agent2_to_agent5.json",
        "agent3_result_contract": "agent3_result.json",
        "agent4_result_contract": "agent4_result.json",
        "agent5_result_contract": "agent5_result.json",
    }.get(key, f"{key}.json")


def _contract_index_entry(key: str, payload: dict[str, Any], root: Path | None) -> dict[str, Any]:
    rel_path = f"contracts/{_contract_filename(key)}"
    meta = _file_meta(root, rel_path, json.dumps(payload, sort_keys=True))
    return {"key": key, "contract_version": payload.get("contract_version"), "path": rel_path, "producer_agent": _contract_producer(key), "consumer_agents": _contract_consumers(key), "sha256": meta["sha256"], "bytes": meta["bytes"], "exists": meta["exists"]}


def _contract_producer(key: str) -> str:
    if key.startswith("agent1"):
        return "agent1"
    if key.startswith("agent2"):
        return "agent2"
    if key.startswith("agent3"):
        return "agent3"
    if key.startswith("agent4"):
        return "agent4"
    if key.startswith("agent5"):
        return "agent5"
    return "swarm_graph"


def _contract_consumers(key: str) -> list[str]:
    return {
        "agent1_to_agent2": ["agent2"],
        "agent2_to_agent3_contract": ["agent3"],
        "agent2_to_agent4_contract": ["agent4"],
        "agent2_to_agent5_contract": ["agent5"],
        "agent3_result_contract": ["agent6_docs", "swarm_artifact_index"],
        "agent4_result_contract": ["agent6_docs", "swarm_artifact_index"],
        "agent5_result_contract": ["agent6_docs", "swarm_artifact_index"],
    }.get(key, ["swarm_artifact_index"])


def _agent_status_map(state: dict[str, Any], artifacts: list[dict[str, Any]], contracts: list[dict[str, Any]]) -> dict[str, Any]:
    reports = state.get("reports", {})
    result_keys = {"agent1": "agent1_to_agent2", "agent2": "agent2_to_agent3_contract", "agent3": "agent3_result_contract", "agent4": "agent4_result_contract", "agent5": "agent5_result_contract"}
    agents: dict[str, Any] = {}
    for agent in ("agent1", "agent2", "agent3", "agent4", "agent5"):
        report = reports.get(agent, {}) if isinstance(reports, dict) else {}
        result = state.get(result_keys.get(agent, ""), {})
        if result:
            status = "pass" if result.get("pass", result.get("pass_fail_status", "pass") == "pass") else "fail"
        elif report:
            status = "pass" if report.get("pass", True) else "fail"
        else:
            status = "not_run"
        agents[agent] = {"status": status, "outputs": [a["path"] for a in artifacts if a.get("producer_agent") == agent], "contracts": [c["path"] for c in contracts if c.get("producer_agent") == agent]}
    return agents


def _validate_common_handoff(contract_name: str, payload: dict[str, Any]) -> None:
    validate_contract(contract_name, payload)
    filenames = {f.get("filename") for f in payload.get("rtl_files", [])}
    if not filenames:
        raise ContractValidationError(f"{contract_name} requires non-empty rtl_files")
    top_file = f"{payload.get('top_module')}.sv"
    if top_file not in filenames:
        raise ContractValidationError(f"{contract_name} top_module file missing from rtl_files: {top_file}")
    missing = [fn for fn in payload.get("compile_order", []) if fn not in filenames]
    if missing:
        raise ContractValidationError(f"{contract_name} compile_order references missing files: {missing}")
    cc = payload.get("clock_constraints", {})
    if cc and int(cc.get("frequency_mhz", 0)) <= 0:
        raise ContractValidationError(f"{contract_name} clock_constraints.frequency_mhz must be positive")


def validate_agent2_to_agent3_contract(payload: dict[str, Any]) -> bool:
    _validate_common_handoff(AGENT2_TO_AGENT3_V1, payload)
    if not payload.get("test_targets"):
        raise ContractValidationError("agent2_to_agent3/v1 requires test_targets")
    return True


def validate_agent2_to_agent4_contract(payload: dict[str, Any]) -> bool:
    _validate_common_handoff(AGENT2_TO_AGENT4_V1, payload)
    if payload.get("target_backend") not in {"quartus", "vivado", "openroad"}:
        raise ContractValidationError("agent2_to_agent4/v1 target_backend must be quartus/vivado/openroad")
    return True


def validate_agent2_to_agent5_contract(payload: dict[str, Any]) -> bool:
    _validate_common_handoff(AGENT2_TO_AGENT5_V1, payload)
    if int(payload.get("bounded_depth", 0)) <= 0:
        raise ContractValidationError("agent2_to_agent5/v1 bounded_depth must be positive")
    if not payload.get("formal_targets"):
        raise ContractValidationError("agent2_to_agent5/v1 requires formal_targets")
    if not payload.get("properties_requested"):
        raise ContractValidationError("agent2_to_agent5/v1 requires properties_requested")
    return True


def spec_from_handoff(payload: dict[str, Any]) -> dict[str, Any]:
    return {"project_name": payload["project_name"], "top_module": payload["top_module"], "clock_domains": [payload.get("clock_constraints", {})], "ip_blocks": [{"name": t} for t in payload.get("test_targets") or payload.get("formal_targets") or [] if t != payload.get("top_module")], "target_backend": payload.get("target_backend", "quartus")}
