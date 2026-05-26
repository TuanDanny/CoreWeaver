"""Agent 1 V5.1 hierarchical deep expert council primitives."""
from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from semiconductor_swarm.agents.agent1_planning.ai_expert_council import _extract_intents
from semiconductor_swarm.agents.agent1_planning.architect import (
    build_requirement_consistency_report,
    generate_architecture_plan_markdown,
    generate_architecture_spec,
    requirement_needs_clarification,
    validate_architecture_spec,
    validate_plan_quality,
)
from semiconductor_swarm.agents.agent1_planning.context_provider import Agent1ContextProvider
from semiconductor_swarm.live_inputs import consume_live_inputs_for_requirement
from semiconductor_swarm.runtime_events import emit_runtime_event
from semiconductor_swarm.tracing import TRACE_FILES, trace_debug_issue, trace_event

CodexCall = Callable[..., Any]
TOPOLOGY_MANIFEST_PATH = Path(__file__).with_name("agent1_topology_manifest.json")
DEFAULT_COUNCIL_MODE = os.getenv("AGENT1_COUNCIL_MODE", "group_session")


@dataclass(frozen=True)
class ExpertNode:
    expert_id: str
    title: str
    domain: str
    mission: str


@dataclass(frozen=True)
class ManagerNode:
    manager_id: str
    title: str
    domain: str
    leaf_expert_ids: tuple[str, ...]


LEAF_EXPERTS: tuple[ExpertNode, ...] = (
    ExpertNode("L01", "Requirement Intake Expert", "requirement", "Extract explicit requirements, constraints, assumptions, and unknowns."),
    ExpertNode("L02", "Domain Classifier Expert", "requirement", "Classify chip domain, workload, SoC class, and ambiguity level."),
    ExpertNode("L03", "Architecture Option Expert", "requirement", "Generate feasible architecture options without rewriting explicit requirements."),
    ExpertNode("L04", "CPU ISA Expert", "cpu", "Select CPU width, ISA profile, privilege assumptions, and extension constraints."),
    ExpertNode("L05", "CPU Pipeline Expert", "cpu", "Select pipeline depth, hazard assumptions, debug hooks, and implementation risks."),
    ExpertNode("L06", "Reset Boot Trap Expert", "cpu", "Define reset, boot, trap, interrupt-entry, and ROM/RAM expectations."),
    ExpertNode("L07", "Memory Map Expert", "memory", "Build address map intent, decode boundaries, and overlap risks."),
    ExpertNode("L08", "Memory Hierarchy Expert", "memory", "Define memory hierarchy, SRAM/ROM/cache assumptions, and coherency scope."),
    ExpertNode("L09", "Protocol AHB/APB/AXI Expert", "protocol", "Select primary protocol and preserve requested bus semantics."),
    ExpertNode("L10", "Bridge Adapter Expert", "protocol", "Define required protocol bridge, boundary, and capability-gap policy."),
    ExpertNode("L11", "Interconnect QoS Expert", "protocol", "Define interconnect topology, arbitration, QoS, and backpressure assumptions."),
    ExpertNode("L12", "Peripheral SPI Expert", "peripheral", "Plan SPI external peripheral behavior, registers, interrupts, and DV hooks."),
    ExpertNode("L13", "Peripheral UART/I2C/GPIO Expert", "peripheral", "Plan UART/I2C/GPIO behavior, registers, interrupts, and DV hooks."),
    ExpertNode("L14", "Register/SystemRDL Expert", "register", "Normalize register map, access policy, reset values, and SystemRDL needs."),
    ExpertNode("L15", "Firmware ABI Expert", "firmware", "Define firmware-facing ABI, headers, driver stubs, and interrupt flow."),
    ExpertNode("L16", "DV Strategy Expert", "verification", "Define DV plan, scoreboards, coverage bins, and negative cases."),
    ExpertNode("L17", "Formal Property Expert", "formal", "Define formal-first properties, assumptions, and proof obligations."),
    ExpertNode("L18", "Physical Clock/Timing Expert", "physical", "Define clocks, resets, timing constraints, and implementation risks."),
    ExpertNode("L19", "Power Intent Expert", "physical", "Define power assumptions, clock gating, UPF needs, and unknowns."),
    ExpertNode("L20", "DFT/Testability Expert", "physical", "Define scan/test hooks, observability, controllability, and exclusions."),
    ExpertNode("L21", "Safety/Security Expert", "safety", "Define privilege, sensitive registers, misuse cases, and safety/security risks."),
    ExpertNode("L22", "IP Reuse/Cost Expert", "capability", "Assess reuse, build cost, and unsupported feature risk."),
    ExpertNode("L23", "Downstream Agent Contract Expert", "capability", "Define Agent2/3/4/5 handoff contract and capability gaps."),
    ExpertNode("L24", "Plan Readability/Diagram Expert", "planning", "Ensure final plan is readable, diagrammable, and acceptance-driven."),
)


MIDDLE_MANAGERS: tuple[ManagerNode, ...] = (
    ManagerNode("M01", "Requirement/Product Manager", "requirement_product", ("L01", "L02", "L03")),
    ManagerNode("M02", "CPU/Memory Manager", "cpu_memory", ("L04", "L05", "L06", "L07", "L08")),
    ManagerNode("M03", "Protocol/Interconnect Manager", "protocol_interconnect", ("L09", "L10", "L11")),
    ManagerNode("M04", "Peripheral/Register/Firmware Manager", "peripheral_register_firmware", ("L12", "L13", "L14", "L15")),
    ManagerNode("M05", "Verification/Formal Manager", "verification_formal", ("L16", "L17")),
    ManagerNode("M06", "Physical/Power/DFT Manager", "physical_power_dft", ("L18", "L19", "L20", "L21")),
    ManagerNode("M07", "Downstream Contract/Capability Manager", "downstream_contract_capability", ("L22", "L23", "L24")),
)


PRINCIPAL_ARCHITECT = ExpertNode(
    "P01",
    "Principal Architect",
    "principal",
    "Synthesize manager decisions, resolve conflicts, and select final architecture candidate.",
)


@dataclass(frozen=True)
class Agent1CouncilConfig:
    planning_mode: str = "normal"
    council_mode: str = DEFAULT_COUNCIL_MODE
    min_iterations: int | None = None
    max_iterations: int = 7
    max_concurrent_leaf_calls: int = int(os.getenv("AGENT1_MAX_CONCURRENT_LEAF_CALLS", "8"))
    max_concurrent_middle_calls: int = int(os.getenv("AGENT1_MAX_CONCURRENT_MIDDLE_CALLS", "4"))
    max_concurrent_group_calls: int = int(os.getenv("AGENT1_MAX_CONCURRENT_GROUP_CALLS", "2"))
    expert_call_timeout_s: float | None = None
    leaf_transient_max_retries: int = int(os.getenv("AGENT1_LEAF_TRANSIENT_MAX_RETRIES", "1"))
    leaf_retry_backoff_s: float = float(os.getenv("AGENT1_LEAF_RETRY_BACKOFF_S", "0.05"))
    group_infra_failure_hitl_threshold: int = int(os.getenv("AGENT1_GROUP_INFRA_FAILURE_HITL_THRESHOLD", "2"))

    def resolved_min_iterations(self) -> int:
        if self.min_iterations is not None:
            return self.min_iterations
        return 3 if self.planning_mode == "deep_planning" else 1

    def normalized(self) -> "Agent1CouncilConfig":
        if self.planning_mode not in {"normal", "deep_planning"}:
            raise ValueError(f"Unsupported Agent1 V5.1 planning mode: {self.planning_mode}")
        if self.council_mode not in {"legacy", "group_session"}:
            raise ValueError(f"Unsupported Agent1 council mode: {self.council_mode}")
        return Agent1CouncilConfig(
            planning_mode=self.planning_mode,
            council_mode=self.council_mode,
            min_iterations=max(1, self.resolved_min_iterations()),
            max_iterations=max(1, self.max_iterations),
            max_concurrent_leaf_calls=_clamp_int(self.max_concurrent_leaf_calls, 1, len(LEAF_EXPERTS)),
            max_concurrent_middle_calls=_clamp_int(self.max_concurrent_middle_calls, 1, len(MIDDLE_MANAGERS)),
            max_concurrent_group_calls=_clamp_int(self.max_concurrent_group_calls, 1, len(MIDDLE_MANAGERS)),
            expert_call_timeout_s=self.expert_call_timeout_s,
            leaf_transient_max_retries=_clamp_int(self.leaf_transient_max_retries, 0, 3),
            leaf_retry_backoff_s=max(0.0, float(self.leaf_retry_backoff_s)),
            group_infra_failure_hitl_threshold=_clamp_int(self.group_infra_failure_hitl_threshold, 1, len(MIDDLE_MANAGERS)),
        )


def load_topology_manifest(path: str | Path | None = None) -> dict[str, Any]:
    manifest_path = Path(path) if path else TOPOLOGY_MANIFEST_PATH
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Agent1 topology manifest must be a JSON object")
    return payload

def topology_manifest_hash(manifest: dict[str, Any] | None = None) -> str:
    payload = manifest or load_topology_manifest()
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def validate_topology_manifest(manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = manifest or load_topology_manifest()
    failures: list[str] = []
    if payload.get("schema_version") != "agent1.topology_manifest.v1":
        failures.append("schema_version")
    if not payload.get("topology_version"):
        failures.append("topology_version")
    principal = payload.get("principal") if isinstance(payload.get("principal"), dict) else {}
    if not principal.get("expert_id"):
        failures.append("principal_missing")
    leaves = payload.get("leaf_experts") if isinstance(payload.get("leaf_experts"), list) else []
    groups = payload.get("groups") if isinstance(payload.get("groups"), list) else []
    leaf_ids = [str(item.get("expert_id") or "") for item in leaves if isinstance(item, dict)]
    manager_ids = [str(item.get("manager_id") or "") for item in groups if isinstance(item, dict)]
    if len(set(leaf_ids)) != len(leaf_ids):
        failures.append("duplicate_leaf_ids")
    if len(set(manager_ids)) != len(manager_ids):
        failures.append("duplicate_manager_ids")
    known_leaves = set(leaf_ids)
    covered: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            failures.append("invalid_group")
            continue
        if not group.get("manager_id"):
            failures.append("group_manager_missing")
        for leaf_id in group.get("leaf_expert_ids") or []:
            leaf_text = str(leaf_id)
            covered.append(leaf_text)
            if leaf_text not in known_leaves:
                failures.append(f"unknown_leaf_ref:{leaf_text}")
    if known_leaves - set(covered):
        failures.append("leaf_without_group")
    return {
        "pass": not failures,
        "failures": sorted(set(failures)),
        "topology_version": str(payload.get("topology_version") or ""),
        "leaf_count": len(leaf_ids),
        "middle_count": len(manager_ids),
        "principal_count": 1 if principal.get("expert_id") else 0,
        "topology_hash": topology_manifest_hash(payload),
    }

def topology_manifest(config: Agent1CouncilConfig | None = None) -> dict[str, Any]:
    cfg = (config or Agent1CouncilConfig()).normalized()
    registry = load_topology_manifest()
    return {
        "schema_version": "agent1.deep_council_config.v1",
        "planning_mode": cfg.planning_mode,
        "council_mode": cfg.council_mode,
        "min_iterations": cfg.resolved_min_iterations(),
        "max_iterations": cfg.max_iterations,
        "max_concurrent_leaf_calls": cfg.max_concurrent_leaf_calls,
        "max_concurrent_middle_calls": cfg.max_concurrent_middle_calls,
        "max_concurrent_group_calls": cfg.max_concurrent_group_calls,
        "leaf_transient_max_retries": cfg.leaf_transient_max_retries,
        "leaf_retry_backoff_s": cfg.leaf_retry_backoff_s,
        "group_infra_failure_hitl_threshold": cfg.group_infra_failure_hitl_threshold,
        "topology_version": registry.get("topology_version"),
        "topology_hash": topology_manifest_hash(registry),
        "leaf_experts": [asdict(item) for item in LEAF_EXPERTS],
        "middle_managers": [asdict(item) for item in MIDDLE_MANAGERS],
        "principal_architect": asdict(PRINCIPAL_ARCHITECT),
        "planned_calls_per_iteration": planned_calls_per_iteration(cfg),
        "minimum_planned_calls": planned_minimum_calls(cfg),
    }


def cluster_map() -> dict[str, tuple[str, ...]]:
    return {manager.manager_id: manager.leaf_expert_ids for manager in MIDDLE_MANAGERS}


def planned_calls_per_iteration(config: Agent1CouncilConfig | None = None) -> int:
    cfg = (config or Agent1CouncilConfig()).normalized()
    if cfg.council_mode == "group_session":
        return 1 + len(MIDDLE_MANAGERS) + 1
    return 1 + len(MIDDLE_MANAGERS) + len(LEAF_EXPERTS) + len(MIDDLE_MANAGERS) + 1


def planned_minimum_calls(config: Agent1CouncilConfig | None = None) -> int:
    cfg = (config or Agent1CouncilConfig()).normalized()
    return planned_calls_per_iteration(cfg) * cfg.resolved_min_iterations()


def validate_topology() -> dict[str, Any]:
    manifest_report = validate_topology_manifest()
    leaf_ids = [item.expert_id for item in LEAF_EXPERTS]
    covered = [leaf_id for manager in MIDDLE_MANAGERS for leaf_id in manager.leaf_expert_ids]
    failures = list(manifest_report.get("failures", []))
    if len(LEAF_EXPERTS) != 24:
        failures.append("leaf_expert_count")
    if len(MIDDLE_MANAGERS) != 7:
        failures.append("middle_manager_count")
    if len(set(leaf_ids)) != len(leaf_ids):
        failures.append("duplicate_leaf_ids")
    if sorted(covered) != sorted(leaf_ids):
        failures.append("cluster_map_leaf_coverage")
    if len(set(covered)) != len(covered):
        failures.append("cluster_map_duplicate_leaf")
    return {
        "pass": not failures,
        "failures": failures,
        "leaf_count": len(LEAF_EXPERTS),
        "middle_count": len(MIDDLE_MANAGERS),
        "principal_count": 1,
        "topology_version": manifest_report.get("topology_version", ""),
        "topology_hash": manifest_report.get("topology_hash", ""),
    }


def route_agent1_clusters(
    requirement: str,
    *,
    config: Agent1CouncilConfig | None = None,
    manifest: dict[str, Any] | None = None,
    iteration: int = 1,
    intake_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = (config or Agent1CouncilConfig()).normalized()
    topology = manifest or load_topology_manifest()
    leaf_by_id = {
        str(item.get("expert_id")): item
        for item in topology.get("leaf_experts", [])
        if isinstance(item, dict) and item.get("expert_id")
    }
    group_items = [item for item in topology.get("groups", []) if isinstance(item, dict)]
    text = _routing_text(requirement, intake_report)
    assignments: list[dict[str, Any]] = []
    for group in group_items:
        group_id = str(group.get("manager_id") or "")
        default_leaf_ids = [str(item) for item in group.get("leaf_expert_ids") or []]
        group_tags = [str(item).lower() for item in group.get("tags") or []]
        matched_keywords = sorted({tag for tag in group_tags if tag and tag in text})
        score = len(matched_keywords) * 3
        leaf_hits: dict[str, list[str]] = {}
        for leaf_id in default_leaf_ids:
            hits = _leaf_keyword_hits(leaf_by_id.get(leaf_id, {}), text)
            if hits:
                leaf_hits[leaf_id] = hits
                score += len(hits)
        guest_ids: list[str] = []
        guest_candidates = _guest_candidates_for_group(group_id)
        if group.get("guest_expert_eligible", True):
            for leaf_id in guest_candidates:
                if leaf_id in default_leaf_ids or leaf_id not in leaf_by_id:
                    continue
                hits = _leaf_keyword_hits(leaf_by_id[leaf_id], text)
                if hits:
                    guest_ids.append(leaf_id)
                    leaf_hits[leaf_id] = hits
                    score += len(hits)
        assignments.append(
            {
                "group_id": group_id,
                "manager_id": group_id,
                "title": str(group.get("title") or group_id),
                "domain": str(group.get("domain") or ""),
                "default_leaf_expert_ids": default_leaf_ids,
                "leaf_expert_ids": default_leaf_ids,
                "guest_expert_ids": guest_ids[:3],
                "all_expert_ids": [*default_leaf_ids, *guest_ids[:3]],
                "matched_keywords": matched_keywords,
                "leaf_keyword_hits": leaf_hits,
                "score": score,
                "rationale": _cluster_rationale(group_id, matched_keywords, guest_ids[:3], score),
            }
        )
    assignment = {
        "schema_version": "agent1.cluster_assignment.v1",
        "mode": cfg.council_mode,
        "iteration": iteration,
        "topology_version": str(topology.get("topology_version") or ""),
        "topology_hash": topology_manifest_hash(topology),
        "requirement_sha256": _sha256(requirement),
        "groups": assignments,
    }
    assignment["cluster_assignment_hash"] = _sha256(json.dumps(assignment, sort_keys=True, ensure_ascii=False))
    return assignment

def execute_leaf_experts(
    requirement: str,
    project_name: str,
    codex_call: CodexCall,
    *,
    config: Agent1CouncilConfig | None = None,
    iteration: int = 1,
    feedback: dict[str, Any] | None = None,
    context_provider: Agent1ContextProvider | None = None,
) -> list[dict[str, Any]]:
    cfg = (config or Agent1CouncilConfig()).normalized()
    intents = _extract_intents(requirement)
    provider = context_provider or Agent1ContextProvider()
    _emit_batch_event("Leaf Experts", "started", iteration, total=len(LEAF_EXPERTS), max_workers=cfg.max_concurrent_leaf_calls)
    records = _run_parallel_nodes(
        nodes=LEAF_EXPERTS,
        max_workers=cfg.max_concurrent_leaf_calls,
        call_builder=lambda node: _call_leaf_expert(node, requirement, project_name, codex_call, cfg, iteration, intents, feedback or {}, provider),
    )
    failed = sum(1 for record in records if any(conflict.get("severity") == "critical" for conflict in record.get("conflicts", [])))
    _emit_batch_event("Leaf Experts", "completed", iteration, total=len(LEAF_EXPERTS), max_workers=cfg.max_concurrent_leaf_calls, completed=len(records), failed=failed)
    return sorted(records, key=lambda item: item["expert_id"])

def execute_principal_charter(
    requirement: str,
    project_name: str,
    codex_call: CodexCall,
    *,
    config: Agent1CouncilConfig | None = None,
    iteration: int = 1,
    context_provider: Agent1ContextProvider | None = None,
    feedback: dict[str, Any] | None = None,
    intake_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = (config or Agent1CouncilConfig()).normalized()
    provider = context_provider or Agent1ContextProvider()
    context = provider.build_context_package(requirement, project_name, cfg.planning_mode, iteration, "P01-CHARTER", extracted_intents=_extract_intents(requirement))
    prompt = _principal_charter_prompt(requirement, project_name, iteration, context, feedback or {}, intake_report)
    _emit_agent1_event(
        "agent_action",
        phase="planning",
        action="Principal Charter started",
        status="running",
        summary="Creating top-down task charter for middle managers and leaf experts.",
        rollup_stage="Principal",
        iteration=iteration,
    )
    record = _call_codex_record(
        codex_call,
        prompt,
        record_base={
            "record_type": "principal_charter",
            "principal_id": "P01-CHARTER",
            "title": "Principal Charter",
            "domain": "principal",
            "iteration": iteration,
        },
    )
    _emit_council_node(
        layer="principal",
        node_id="P01-CHARTER",
        title="Principal Charter",
        status="conflict" if record["conflicts"] else "pass",
        iteration=iteration,
        summary=str(record.get("output", {}).get("summary", "Principal charter completed.")),
        conflicts=record.get("conflicts", []),
        handoff_digest=record.get("output", {}).get("decisions", []),
        token_usage=record.get("token_usage", {}),
        duration_ms=_duration_ms(record),
        phase_seq=_phase_seq(iteration, "principal", "charter", "P01-CHARTER"),
    )
    return record

def execute_middle_tasking(
    requirement: str,
    project_name: str,
    codex_call: CodexCall,
    charter_record: dict[str, Any],
    *,
    config: Agent1CouncilConfig | None = None,
    iteration: int = 1,
    context_provider: Agent1ContextProvider | None = None,
    intake_report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    cfg = (config or Agent1CouncilConfig()).normalized()
    provider = context_provider or Agent1ContextProvider()
    _emit_batch_event("Middle Tasking", "started", iteration, total=len(MIDDLE_MANAGERS), max_workers=cfg.max_concurrent_middle_calls)
    records = _run_parallel_nodes(
        nodes=MIDDLE_MANAGERS,
        max_workers=cfg.max_concurrent_middle_calls,
        call_builder=lambda manager: _call_middle_tasking(manager, requirement, project_name, codex_call, cfg, iteration, charter_record, provider, intake_report),
    )
    failed = sum(1 for record in records if any(conflict.get("severity") == "critical" for conflict in record.get("conflicts", [])))
    _emit_batch_event("Middle Tasking", "completed", iteration, total=len(MIDDLE_MANAGERS), max_workers=cfg.max_concurrent_middle_calls, completed=len(records), failed=failed)
    return sorted(records, key=lambda item: item["manager_id"])


def execute_group_sessions(
    requirement: str,
    project_name: str,
    codex_call: CodexCall,
    charter_record: dict[str, Any],
    assignment: dict[str, Any],
    *,
    config: Agent1CouncilConfig | None = None,
    iteration: int = 1,
    context_provider: Agent1ContextProvider | None = None,
    feedback: dict[str, Any] | None = None,
    intake_report: dict[str, Any] | None = None,
    parent_span_id: str = "",
    attempt: int = 1,
) -> list[dict[str, Any]]:
    cfg = (config or Agent1CouncilConfig()).normalized()
    provider = context_provider or Agent1ContextProvider()
    groups = tuple(assignment.get("groups") or [])
    _emit_batch_event("Group Sessions", "started", iteration, total=len(groups), max_workers=cfg.max_concurrent_group_calls)
    records: list[dict[str, Any]] = []
    width = max(1, cfg.max_concurrent_group_calls)
    for batch_start in range(0, len(groups), width):
        batch = groups[batch_start : batch_start + width]
        records.extend(
            _run_parallel_nodes(
                nodes=batch,
                max_workers=width,
                call_builder=lambda group: _call_group_session(
                    group,
                    requirement,
                    project_name,
                    codex_call,
                    cfg,
                    iteration,
                    charter_record,
                    provider,
                    feedback or {},
                    intake_report,
                    parent_span_id,
                    attempt,
                ),
            )
        )
        infra_failures = _group_infra_failure_ids(records)
        if len(infra_failures) >= cfg.group_infra_failure_hitl_threshold and batch_start + width < len(groups):
            remaining = groups[batch_start + width :]
            trace_debug_issue(
                severity="error",
                source="agent1",
                code="agent1_group_infra_hard_stop",
                message="Agent 1 group-session council hit infrastructure failure threshold; remaining groups were not sent to the model.",
                details={
                    "iteration": iteration,
                    "failed_group_ids": infra_failures,
                    "threshold": cfg.group_infra_failure_hitl_threshold,
                    "skipped_group_ids": [str(group.get("group_id") or group.get("manager_id") or "") for group in remaining],
                },
                node_id="AGENT1.GROUP_SESSIONS",
            )
            for group in remaining:
                records.append(
                    _group_session_infra_aborted_record(
                        group,
                        requirement,
                        project_name,
                        cfg,
                        iteration,
                        parent_span_id,
                        attempt,
                        failed_group_ids=infra_failures,
                    )
                )
            break
    failed = sum(1 for record in records if _group_session_failed(record))
    _emit_batch_event("Group Sessions", "completed", iteration, total=len(groups), max_workers=cfg.max_concurrent_group_calls, completed=len(records), failed=failed)
    return sorted(records, key=lambda item: item["manager_id"])

def run_agent1_v51_council(
    requirement: str,
    project_name: str,
    codex_call: CodexCall,
    *,
    config: Agent1CouncilConfig | None = None,
    context_provider: Agent1ContextProvider | None = None,
    intake_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = (config or Agent1CouncilConfig()).normalized()
    provider = context_provider or Agent1ContextProvider()
    if cfg.council_mode == "group_session":
        return _run_agent1_group_session_council(
            requirement,
            project_name,
            codex_call,
            config=cfg,
            context_provider=provider,
            intake_report=intake_report,
        )
    iterations = []
    leaf_trace: list[dict[str, Any]] = []
    middle_tasking_trace: list[dict[str, Any]] = []
    middle_trace: list[dict[str, Any]] = []
    principal_charter_trace: list[dict[str, Any]] = []
    principal_trace: list[dict[str, Any]] = []
    guardrail_trace: list[dict[str, Any]] = []
    feedback: dict[str, Any] = {}
    for iteration in range(1, cfg.max_iterations + 1):
        requirement, consumed = consume_live_inputs_for_requirement(requirement, f"agent1.council.iteration.{iteration}.start")
        if consumed:
            trace_event(
                TRACE_FILES["agent1_council"],
                phase="planning",
                agent="agent1",
                node_id="LIVE_INPUT.CONSUME",
                event_type="live_input_checkpoint",
                status="pass",
                payload={"checkpoint": f"agent1.council.iteration.{iteration}.start", "count": len(consumed)},
            )
        _emit_agent1_event(
            "agent_action",
            phase="planning",
            action=f"V5.1 iteration {iteration} started",
            status="running",
            summary=f"Mode={cfg.planning_mode}; leaf={len(LEAF_EXPERTS)} middle={len(MIDDLE_MANAGERS)} principal=1",
            rollup_stage="Iteration",
            iteration=iteration,
        )
        _emit_agent1_event(
            "agent1_council_iteration",
            phase="planning",
            action="iteration started",
            status="running",
            iteration=iteration,
            layer="iteration",
            node_id=f"I{iteration}",
            title=f"Iteration {iteration}",
            phase_seq=_phase_seq(iteration, "iteration", "start"),
            summary=f"Mode={cfg.planning_mode}; leaf={len(LEAF_EXPERTS)} middle={len(MIDDLE_MANAGERS)} principal=1",
        )
        charter_record = execute_principal_charter(
            requirement,
            project_name,
            codex_call,
            config=cfg,
            iteration=iteration,
            context_provider=provider,
            feedback=feedback,
            intake_report=intake_report,
        )
        middle_tasking_records = execute_middle_tasking(
            requirement,
            project_name,
            codex_call,
            charter_record,
            config=cfg,
            iteration=iteration,
            context_provider=provider,
            intake_report=intake_report,
        )
        leaf_records = execute_leaf_experts(
            requirement,
            project_name,
            codex_call,
            config=cfg,
            iteration=iteration,
            feedback={**feedback, "principal_charter": charter_record.get("output", {}), "middle_tasking": _summaries(middle_tasking_records), "intake_router": _compact_intake_report(intake_report)},
            context_provider=provider,
        )
        middle_records = execute_middle_managers(requirement, project_name, codex_call, leaf_records, config=cfg, iteration=iteration, context_provider=provider)
        requirement, consumed = consume_live_inputs_for_requirement(requirement, f"agent1.council.iteration.{iteration}.principal")
        if consumed:
            trace_event(
                TRACE_FILES["agent1_council"],
                phase="planning",
                agent="agent1",
                node_id="LIVE_INPUT.CONSUME",
                event_type="live_input_checkpoint",
                status="pass",
                payload={"checkpoint": f"agent1.council.iteration.{iteration}.principal", "count": len(consumed)},
            )
        principal_record = execute_principal_architect(
            requirement,
            project_name,
            codex_call,
            middle_records,
            config=cfg,
            iteration=iteration,
            context_provider=provider,
            feedback={**feedback, "principal_charter": charter_record.get("output", {}), "middle_tasking": _summaries(middle_tasking_records), "intake_router": _compact_intake_report(intake_report)},
        )
        conflicts = _conflict_matrix(iteration, leaf_records, middle_records, principal_record, extra_records=[charter_record, *middle_tasking_records], requirement=requirement)
        guardrail = _run_deterministic_guardrails(requirement, project_name, principal_record, cfg, iteration)
        guardrail_trace.append(guardrail)
        if not guardrail["pass"]:
            conflicts["critical_conflicts"].append(
                {
                    "source": "deterministic_guardrails",
                    "severity": "critical",
                    "type": "deterministic_guardrail_failed",
                    "failures": guardrail["failures"],
                }
            )
        leaf_trace.extend(leaf_records)
        middle_tasking_trace.extend(middle_tasking_records)
        middle_trace.extend(middle_records)
        principal_charter_trace.append(charter_record)
        principal_trace.append(principal_record)
        iterations.append(
            {
                "iteration": iteration,
                "principal_charter_records": 1,
                "middle_tasking_records": len(middle_tasking_records),
                "leaf_records": len(leaf_records),
                "middle_records": len(middle_records),
                "principal_records": 1,
                "guardrail_pass": guardrail["pass"],
                "guardrail_failures": guardrail["failures"],
                "critical_conflicts": conflicts["critical_conflicts"],
                "noncritical_conflicts": conflicts["noncritical_conflicts"],
                "status": "pass" if not conflicts["critical_conflicts"] else "conflict",
            }
        )
        _emit_agent1_event(
            "agent_discussion",
            speaker="agent1",
            audience="principal_architect",
            message=f"Iteration {iteration} completed with {len(conflicts['critical_conflicts'])} critical and {len(conflicts['noncritical_conflicts'])} noncritical conflicts.",
            severity="warning" if conflicts["critical_conflicts"] else "info",
            iteration=iteration,
        )
        _emit_agent1_event(
            "agent_action",
            phase="planning",
            action=f"V5.1 iteration {iteration} completed",
            status="fail" if conflicts["critical_conflicts"] else "pass",
            summary=f"critical={len(conflicts['critical_conflicts'])}, noncritical={len(conflicts['noncritical_conflicts'])}",
            rollup_stage="Iteration",
            iteration=iteration,
            metric={"critical_conflicts": len(conflicts["critical_conflicts"]), "noncritical_conflicts": len(conflicts["noncritical_conflicts"])},
        )
        _emit_agent1_event(
            "agent1_council_iteration",
            phase="planning",
            action="iteration completed",
            status="conflict" if conflicts["critical_conflicts"] else "pass",
            iteration=iteration,
            layer="iteration",
            node_id=f"I{iteration}",
            title=f"Iteration {iteration}",
            phase_seq=_phase_seq(iteration, "iteration", "complete"),
            summary=f"critical={len(conflicts['critical_conflicts'])}; noncritical={len(conflicts['noncritical_conflicts'])}",
            conflicts=_digest_list(conflicts["critical_conflicts"] + conflicts["noncritical_conflicts"]),
        )
        feedback = {"principal": principal_record.get("output", {}), "conflicts": conflicts, "guardrail": guardrail}
        if cfg.planning_mode == "normal":
            break
        if iteration >= cfg.resolved_min_iterations() and not conflicts["critical_conflicts"] and guardrail["pass"] and principal_record.get("output", {}).get("plan_ready_candidate") is not False:
            break
    guardrail = guardrail_trace[-1]
    status = "HITL_REQUIRED" if iterations[-1]["critical_conflicts"] or not guardrail["pass"] else "READY_FOR_DETERMINISTIC_GUARDRAILS"
    final_conflict_matrix = _conflict_matrix(iterations[-1]["iteration"], leaf_trace, middle_trace, principal_trace[-1], extra_records=[*principal_charter_trace, *middle_tasking_trace], requirement=requirement)
    if not guardrail["pass"]:
        final_conflict_matrix["critical_conflicts"].append(
            {
                "source": "deterministic_guardrails",
                "severity": "critical",
                "type": "deterministic_guardrail_failed",
                "failures": guardrail["failures"],
            }
        )
    _emit_agent1_event(
        "agent_handoff",
        from_agent="agent1",
        to_agent="agent1_guardrails",
        contract="agent1_v51_guardrail_report",
        status="pass" if guardrail["pass"] else "fail",
        summary=f"Deterministic guardrails {'passed' if guardrail['pass'] else 'failed'} with {len(guardrail['failures'])} failures.",
        iteration_count=len(iterations),
    )
    _emit_agent1_event(
        "agent_action",
        phase="planning",
        action="V5.1 deterministic guardrails completed",
        status="pass" if guardrail["pass"] else "fail",
        summary=f"status={status}; failures={len(guardrail['failures'])}",
        rollup_stage="Guardrails",
        metric={"guardrail_failures": len(guardrail["failures"]), "iterations": len(iterations)},
    )
    _emit_council_node(
        layer="guardrail",
        node_id="G01",
        title="Deterministic Guardrails",
        status="pass" if guardrail["pass"] else "fail",
        iteration=iterations[-1]["iteration"],
        summary=f"Guardrails {'passed' if guardrail['pass'] else 'failed'} with {len(guardrail['failures'])} failures.",
        child_ids=[PRINCIPAL_ARCHITECT.expert_id],
        conflicts=[{"severity": "critical", "type": failure} for failure in guardrail["failures"]],
        phase_seq=_phase_seq(iterations[-1]["iteration"], "guardrail", "complete", "G01"),
    )
    for artifact_name in (
        "agent1_leaf_expert_trace.jsonl",
        "agent1_middle_manager_trace.jsonl",
        "agent1_principal_trace.jsonl",
        "agent1_conflict_matrix.json",
        "agent1_v51_guardrail_report.json",
    ):
        _emit_agent1_event(
            "agent1_council_artifact",
            phase="planning",
            status="available",
            iteration=iterations[-1]["iteration"],
            layer="artifact",
            node_id=artifact_name,
            title=artifact_name,
            phase_seq=_phase_seq(iterations[-1]["iteration"], "artifact", "available", artifact_name),
            summary=f"Agent 1 debug artifact available: {artifact_name}",
        )
    return {
        "schema_version": "agent1.deep_council_result.v1",
        "project_name": project_name,
        "raw_requirement": requirement,
        "effective_requirement": requirement,
        "config": topology_manifest(cfg),
        "iterations": iterations,
        "status": status,
        "artifacts": {
            "agent1_deep_council_config.json": json.dumps(topology_manifest(cfg), indent=2, sort_keys=True),
            "agent1_principal_charter_trace.jsonl": _jsonl(sorted(principal_charter_trace, key=lambda item: (item["iteration"], item["principal_id"]))),
            "agent1_middle_tasking_trace.jsonl": _jsonl(sorted(middle_tasking_trace, key=lambda item: (item["iteration"], item["manager_id"]))),
            "agent1_leaf_expert_trace.jsonl": _jsonl(sorted(leaf_trace, key=lambda item: (item["iteration"], item["expert_id"]))),
            "agent1_middle_manager_trace.jsonl": _jsonl(sorted(middle_trace, key=lambda item: (item["iteration"], item["manager_id"]))),
            "agent1_principal_trace.jsonl": _jsonl(sorted(principal_trace, key=lambda item: (item["iteration"], item["principal_id"]))),
            "agent1_conflict_matrix.json": json.dumps(final_conflict_matrix, indent=2, sort_keys=True),
            "agent1_iteration_summary.json": json.dumps(iterations, indent=2, sort_keys=True),
            "agent1_principal_decision.json": json.dumps(principal_trace[-1], indent=2, sort_keys=True),
            "agent1_v51_guardrail_trace.jsonl": _jsonl(guardrail_trace),
            "agent1_rag_context_manifest.json": json.dumps(_context_manifest(provider, requirement, project_name), indent=2, sort_keys=True),
            "agent1_v51_guardrail_report.json": json.dumps(guardrail, indent=2, sort_keys=True),
            "agent1_v51_architecture_spec.json": json.dumps(guardrail.get("spec", {}), indent=2, sort_keys=True),
            "architecture_plan.md": guardrail.get("plan_markdown", ""),
        },
    }


def _run_agent1_group_session_council(
    requirement: str,
    project_name: str,
    codex_call: CodexCall,
    *,
    config: Agent1CouncilConfig,
    context_provider: Agent1ContextProvider,
    intake_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config.normalized()
    provider = context_provider
    iterations = []
    group_trace: list[dict[str, Any]] = []
    principal_charter_trace: list[dict[str, Any]] = []
    principal_trace: list[dict[str, Any]] = []
    guardrail_trace: list[dict[str, Any]] = []
    retry_trace: list[dict[str, Any]] = []
    challenge_matrices: list[dict[str, Any]] = []
    assignment_trace: list[dict[str, Any]] = []
    infra_hard_stop_seen = False
    feedback: dict[str, Any] = {}
    topology = load_topology_manifest()
    topology_hash = topology_manifest_hash(topology)
    root_span = "agent1.cluster_council"
    _emit_agent1_event(
        "agent1_council_mode_selected",
        phase="planning",
        status="pass",
        mode="group_session",
        span_id=root_span,
        summary=f"Agent 1 group-session council selected; planned_calls_per_iteration={planned_calls_per_iteration(cfg)}",
        metric={"planned_calls_per_iteration": planned_calls_per_iteration(cfg), "max_concurrent_group_calls": cfg.max_concurrent_group_calls},
    )
    _emit_agent1_event(
        "agent1_topology_loaded",
        phase="planning",
        status="pass",
        span_id=f"{root_span}.topology",
        parent_span_id=root_span,
        topology_hash=topology_hash,
        topology_version=topology.get("topology_version"),
        summary=f"Topology loaded: groups={len(topology.get('groups', []))}; leaves={len(topology.get('leaf_experts', []))}",
    )
    for iteration in range(1, cfg.max_iterations + 1):
        requirement, consumed = consume_live_inputs_for_requirement(requirement, f"agent1.council.iteration.{iteration}.start")
        if consumed:
            trace_event(
                TRACE_FILES["agent1_council"],
                phase="planning",
                agent="agent1",
                node_id="LIVE_INPUT.CONSUME",
                event_type="live_input_checkpoint",
                status="pass",
                payload={"checkpoint": f"agent1.council.iteration.{iteration}.start", "count": len(consumed)},
            )
        iteration_span = f"{root_span}.iter{iteration}"
        router_span = f"{iteration_span}.router"
        _emit_agent1_event(
            "agent_action",
            phase="planning",
            action=f"V7.1 group-session iteration {iteration} started",
            status="running",
            summary=f"Mode={cfg.planning_mode}; groups={len(MIDDLE_MANAGERS)}; max_group_workers={cfg.max_concurrent_group_calls}",
            rollup_stage="Iteration",
            iteration=iteration,
        )
        _emit_agent1_event(
            "agent1_council_iteration",
            phase="planning",
            action="group-session iteration started",
            status="running",
            iteration=iteration,
            layer="iteration",
            node_id=f"I{iteration}",
            title=f"Iteration {iteration}",
            phase_seq=_phase_seq(iteration, "iteration", "start"),
            summary=f"Group-session mode; groups={len(MIDDLE_MANAGERS)}",
        )
        charter_record = execute_principal_charter(
            requirement,
            project_name,
            codex_call,
            config=cfg,
            iteration=iteration,
            context_provider=provider,
            feedback=feedback,
            intake_report=intake_report,
        )
        principal_charter_trace.append(charter_record)
        assignment = route_agent1_clusters(requirement, config=cfg, manifest=topology, iteration=iteration, intake_report=intake_report)
        assignment_trace.append(assignment)
        _emit_agent1_event(
            "agent1_cluster_assignment",
            phase="planning",
            status="pass",
            span_id=router_span,
            parent_span_id=root_span,
            iteration=iteration,
            topology_hash=assignment["topology_hash"],
            cluster_assignment_hash=assignment["cluster_assignment_hash"],
            group_count=len(assignment.get("groups", [])),
            summary=f"Cluster router assigned {len(assignment.get('groups', []))} group sessions.",
            metric={"group_count": len(assignment.get("groups", []))},
        )
        group_records = execute_group_sessions(
            requirement,
            project_name,
            codex_call,
            charter_record,
            assignment,
            config=cfg,
            iteration=iteration,
            context_provider=provider,
            feedback={**feedback, "principal_charter": charter_record.get("output", {}), "intake_router": _compact_intake_report(intake_report)},
            intake_report=intake_report,
            parent_span_id=router_span,
        )
        infra_failures = _group_infra_failure_ids(group_records)
        infra_hard_stop = len(infra_failures) >= cfg.group_infra_failure_hitl_threshold
        retry_targets = [] if infra_failures else _group_retry_targets(group_records)
        if infra_failures:
            _emit_group_retry_suppressed(infra_failures, iteration, parent_span_id=router_span, reason="codex_infra_failure")
        if retry_targets:
            retry_records = _retry_group_sessions(
                retry_targets,
                group_records,
                requirement,
                project_name,
                codex_call,
                charter_record,
                assignment,
                cfg,
                iteration,
                provider,
                feedback={**feedback, "retry_reason": "group_session_quality_gate"},
                intake_report=intake_report,
                parent_span_id=router_span,
            )
            retry_trace.extend(retry_records)
            group_records = _replace_group_records(group_records, retry_records)
        challenge_matrix = _cross_group_challenge_matrix(iteration, group_records)
        challenge_matrices.append(challenge_matrix)
        _emit_cross_group_challenges(challenge_matrix, iteration, parent_span_id=router_span)
        requirement, consumed = consume_live_inputs_for_requirement(requirement, f"agent1.council.iteration.{iteration}.principal")
        if consumed:
            trace_event(
                TRACE_FILES["agent1_council"],
                phase="planning",
                agent="agent1",
                node_id="LIVE_INPUT.CONSUME",
                event_type="live_input_checkpoint",
                status="pass",
                payload={"checkpoint": f"agent1.council.iteration.{iteration}.principal", "count": len(consumed)},
            )
        review_span = f"{iteration_span}.principal_review"
        _emit_agent1_event(
            "agent1_principal_group_review",
            phase="planning",
            status="running",
            span_id=review_span,
            parent_span_id=router_span,
            iteration=iteration,
            group_count=len(group_records),
            summary="Principal reviewing distilled group-session outputs.",
        )
        principal_record = execute_principal_architect(
            requirement,
            project_name,
            codex_call,
            group_records,
            config=cfg,
            iteration=iteration,
            context_provider=provider,
            feedback={
                **feedback,
                "principal_charter": charter_record.get("output", {}),
                "cross_group_challenge_matrix": _digest_value(challenge_matrix),
                "intake_router": _compact_intake_report(intake_report),
            },
        )
        principal_retry_targets = _principal_retry_targets(principal_record, assignment)
        infra_failures = _group_infra_failure_ids(group_records)
        if principal_retry_targets and infra_failures:
            _emit_group_retry_suppressed(principal_retry_targets, iteration, parent_span_id=review_span, reason="codex_infra_failure_after_principal")
            principal_retry_targets = []
        if principal_retry_targets:
            retry_records = _retry_group_sessions(
                principal_retry_targets,
                group_records,
                requirement,
                project_name,
                codex_call,
                charter_record,
                assignment,
                cfg,
                iteration,
                provider,
                feedback={**feedback, "principal_feedback": principal_record.get("output", {})},
                intake_report=intake_report,
                parent_span_id=review_span,
            )
            retry_trace.extend(retry_records)
            group_records = _replace_group_records(group_records, retry_records)
            challenge_matrix = _cross_group_challenge_matrix(iteration, group_records)
            challenge_matrices[-1] = challenge_matrix
            principal_record = execute_principal_architect(
                requirement,
                project_name,
                codex_call,
                group_records,
                config=cfg,
                iteration=iteration,
                context_provider=provider,
                feedback={
                    **feedback,
                    "principal_retry": True,
                    "principal_feedback": principal_record.get("output", {}),
                    "cross_group_challenge_matrix": _digest_value(challenge_matrix),
                },
            )
        _emit_agent1_event(
            "agent1_principal_group_review",
            phase="planning",
            status="fail" if principal_record["conflicts"] else "pass",
            span_id=f"{review_span}.done",
            parent_span_id=review_span,
            iteration=iteration,
            group_count=len(group_records),
            confidence=principal_record.get("output", {}).get("confidence"),
            summary=str(principal_record.get("output", {}).get("summary", "Principal group review completed."))[:600],
            metric=_token_metrics(principal_record),
        )
        principal_trace.append(principal_record)
        conflicts = _conflict_matrix(iteration, [], group_records, principal_record, extra_records=[charter_record], requirement=requirement)
        unresolved_challenges = [item for item in challenge_matrix.get("challenges", []) if not item.get("resolved")]
        if unresolved_challenges:
            conflicts["critical_conflicts"].append(
                {
                    "source": "agent1_cross_group_challenge_matrix",
                    "severity": "critical",
                    "type": "unresolved_cross_group_challenge",
                    "challenge_ids": [item.get("challenge_id") for item in unresolved_challenges],
                }
            )
        guardrail = _run_deterministic_guardrails(requirement, project_name, principal_record, cfg, iteration)
        guardrail_trace.append(guardrail)
        if not guardrail["pass"]:
            conflicts["critical_conflicts"].append(
                {
                    "source": "deterministic_guardrails",
                    "severity": "critical",
                    "type": "deterministic_guardrail_failed",
                    "failures": guardrail["failures"],
                }
            )
        group_trace.extend(group_records)
        iterations.append(
            {
                "iteration": iteration,
                "principal_charter_records": 1,
                "group_session_records": len(group_records),
                "middle_records": len(group_records),
                "leaf_records": 0,
                "principal_records": 1,
                "retry_records": len([item for item in retry_trace if item.get("iteration") == iteration]),
                "guardrail_pass": guardrail["pass"],
                "guardrail_failures": guardrail["failures"],
                "critical_conflicts": conflicts["critical_conflicts"],
                "noncritical_conflicts": conflicts["noncritical_conflicts"],
                "unresolved_challenges": unresolved_challenges,
                "status": "pass" if not conflicts["critical_conflicts"] else "conflict",
            }
        )
        _emit_agent1_event(
            "agent_discussion",
            speaker="agent1",
            audience="principal_architect",
            message=f"Group-session iteration {iteration} completed with {len(conflicts['critical_conflicts'])} critical and {len(conflicts['noncritical_conflicts'])} noncritical conflicts.",
            severity="warning" if conflicts["critical_conflicts"] else "info",
            iteration=iteration,
        )
        _emit_agent1_event(
            "agent_action",
            phase="planning",
            action=f"V7.1 group-session iteration {iteration} completed",
            status="fail" if conflicts["critical_conflicts"] else "pass",
            summary=f"critical={len(conflicts['critical_conflicts'])}, noncritical={len(conflicts['noncritical_conflicts'])}, retries={iterations[-1]['retry_records']}",
            rollup_stage="Iteration",
            iteration=iteration,
            metric={"critical_conflicts": len(conflicts["critical_conflicts"]), "noncritical_conflicts": len(conflicts["noncritical_conflicts"]), "retries": iterations[-1]["retry_records"]},
        )
        _emit_agent1_event(
            "agent1_council_iteration",
            phase="planning",
            action="group-session iteration completed",
            status="conflict" if conflicts["critical_conflicts"] else "pass",
            iteration=iteration,
            layer="iteration",
            node_id=f"I{iteration}",
            title=f"Iteration {iteration}",
            phase_seq=_phase_seq(iteration, "iteration", "complete"),
            summary=f"critical={len(conflicts['critical_conflicts'])}; noncritical={len(conflicts['noncritical_conflicts'])}; retries={iterations[-1]['retry_records']}",
            conflicts=_digest_list(conflicts["critical_conflicts"] + conflicts["noncritical_conflicts"]),
        )
        feedback = {"principal": principal_record.get("output", {}), "conflicts": conflicts, "guardrail": guardrail}
        if infra_hard_stop:
            infra_hard_stop_seen = True
            trace_debug_issue(
                severity="error",
                source="agent1",
                code="agent1_council_infra_hard_stop",
                message="Agent 1 deep council stopped after one iteration because group-session infrastructure failures reached HITL threshold.",
                details={
                    "iteration": iteration,
                    "failed_group_ids": infra_failures,
                    "threshold": cfg.group_infra_failure_hitl_threshold,
                    "status": "HITL_REQUIRED",
                },
                node_id="AGENT1.V7_1_GROUP_SESSION_ITERATION",
            )
            break
        if cfg.planning_mode == "normal":
            break
        if iteration >= cfg.resolved_min_iterations() and not conflicts["critical_conflicts"] and guardrail["pass"] and principal_record.get("output", {}).get("plan_ready_candidate") is not False:
            break
    guardrail = guardrail_trace[-1]
    status = "HITL_REQUIRED" if iterations[-1]["critical_conflicts"] or not guardrail["pass"] else "READY_FOR_DETERMINISTIC_GUARDRAILS"
    final_conflict_matrix = _conflict_matrix(iterations[-1]["iteration"], [], group_trace, principal_trace[-1], extra_records=principal_charter_trace, requirement=requirement)
    if not guardrail["pass"]:
        final_conflict_matrix["critical_conflicts"].append(
            {
                "source": "deterministic_guardrails",
                "severity": "critical",
                "type": "deterministic_guardrail_failed",
                "failures": guardrail["failures"],
            }
        )
    final_challenge_matrix = challenge_matrices[-1] if challenge_matrices else {"schema_version": "agent1.cross_group_challenge_matrix.v1", "challenges": []}
    _emit_agent1_event(
        "agent_handoff",
        from_agent="agent1",
        to_agent="agent1_guardrails",
        contract="agent1_v71_group_session_guardrail_report",
        status="pass" if guardrail["pass"] else "fail",
        summary=f"Deterministic guardrails {'passed' if guardrail['pass'] else 'failed'} with {len(guardrail['failures'])} failures.",
        iteration_count=len(iterations),
    )
    _emit_agent1_event(
        "agent_action",
        phase="planning",
        action="V7.1 deterministic guardrails completed",
        status="pass" if guardrail["pass"] else "fail",
        summary=f"status={status}; failures={len(guardrail['failures'])}",
        rollup_stage="Guardrails",
        metric={"guardrail_failures": len(guardrail["failures"]), "iterations": len(iterations)},
    )
    _emit_council_node(
        layer="guardrail",
        node_id="G01",
        title="Deterministic Guardrails",
        status="pass" if guardrail["pass"] else "fail",
        iteration=iterations[-1]["iteration"],
        summary=f"Guardrails {'passed' if guardrail['pass'] else 'failed'} with {len(guardrail['failures'])} failures.",
        child_ids=[PRINCIPAL_ARCHITECT.expert_id],
        conflicts=[{"severity": "critical", "type": failure} for failure in guardrail["failures"]],
        phase_seq=_phase_seq(iterations[-1]["iteration"], "guardrail", "complete", "G01"),
    )
    for artifact_name in (
        "agent1_cluster_assignment.json",
        "agent1_group_session_trace.jsonl",
        "agent1_cross_group_challenge_matrix.json",
        "agent1_principal_trace.jsonl",
        "agent1_conflict_matrix.json",
        "agent1_v51_guardrail_report.json",
    ):
        _emit_agent1_event(
            "agent1_council_artifact",
            phase="planning",
            status="available",
            iteration=iterations[-1]["iteration"],
            layer="artifact",
            node_id=artifact_name,
            title=artifact_name,
            phase_seq=_phase_seq(iterations[-1]["iteration"], "artifact", "available", artifact_name),
            summary=f"Agent 1 debug artifact available: {artifact_name}",
        )
    return {
        "schema_version": "agent1.deep_council_result.v1",
        "project_name": project_name,
        "raw_requirement": requirement,
        "effective_requirement": requirement,
        "config": topology_manifest(cfg),
        "iterations": iterations,
        "status": status,
        "hitl_reason": "agent1_council_infra_hard_stop" if infra_hard_stop_seen else "council_conflict",
        "artifacts": {
            "agent1_deep_council_config.json": json.dumps(topology_manifest(cfg), indent=2, sort_keys=True),
            "agent1_cluster_assignment.json": json.dumps(assignment_trace[-1] if assignment_trace else {}, indent=2, sort_keys=True),
            "agent1_group_session_trace.jsonl": _jsonl(sorted(group_trace, key=lambda item: (item["iteration"], item["manager_id"], item.get("attempt", 1)))),
            "agent1_group_retry_trace.jsonl": _jsonl(sorted(retry_trace, key=lambda item: (item["iteration"], item["manager_id"], item.get("attempt", 1)))),
            "agent1_cross_group_challenge_matrix.json": json.dumps(final_challenge_matrix, indent=2, sort_keys=True),
            "agent1_principal_charter_trace.jsonl": _jsonl(sorted(principal_charter_trace, key=lambda item: (item["iteration"], item["principal_id"]))),
            "agent1_middle_tasking_trace.jsonl": "",
            "agent1_leaf_expert_trace.jsonl": "",
            "agent1_middle_manager_trace.jsonl": _jsonl(sorted(group_trace, key=lambda item: (item["iteration"], item["manager_id"], item.get("attempt", 1)))),
            "agent1_principal_trace.jsonl": _jsonl(sorted(principal_trace, key=lambda item: (item["iteration"], item["principal_id"]))),
            "agent1_conflict_matrix.json": json.dumps(final_conflict_matrix, indent=2, sort_keys=True),
            "agent1_iteration_summary.json": json.dumps(iterations, indent=2, sort_keys=True),
            "agent1_principal_decision.json": json.dumps(principal_trace[-1], indent=2, sort_keys=True),
            "agent1_v51_guardrail_trace.jsonl": _jsonl(guardrail_trace),
            "agent1_rag_context_manifest.json": json.dumps(_context_manifest(provider, requirement, project_name), indent=2, sort_keys=True),
            "agent1_v51_guardrail_report.json": json.dumps(guardrail, indent=2, sort_keys=True),
            "agent1_v51_architecture_spec.json": json.dumps(guardrail.get("spec", {}), indent=2, sort_keys=True),
            "architecture_plan.md": guardrail.get("plan_markdown", ""),
        },
    }

def execute_middle_managers(
    requirement: str,
    project_name: str,
    codex_call: CodexCall,
    leaf_records: list[dict[str, Any]],
    *,
    config: Agent1CouncilConfig | None = None,
    iteration: int = 1,
    context_provider: Agent1ContextProvider | None = None,
) -> list[dict[str, Any]]:
    cfg = (config or Agent1CouncilConfig()).normalized()
    provider = context_provider or Agent1ContextProvider()
    leaf_by_id = {record["expert_id"]: record for record in leaf_records}
    _emit_batch_event("Middle Managers", "started", iteration, total=len(MIDDLE_MANAGERS), max_workers=cfg.max_concurrent_middle_calls)
    records = _run_parallel_nodes(
        nodes=MIDDLE_MANAGERS,
        max_workers=cfg.max_concurrent_middle_calls,
        call_builder=lambda manager: _call_middle_manager(manager, requirement, project_name, codex_call, cfg, iteration, leaf_by_id, provider),
    )
    failed = sum(1 for record in records if any(conflict.get("severity") == "critical" for conflict in record.get("conflicts", [])))
    _emit_batch_event("Middle Managers", "completed", iteration, total=len(MIDDLE_MANAGERS), max_workers=cfg.max_concurrent_middle_calls, completed=len(records), failed=failed)
    return sorted(records, key=lambda item: item["manager_id"])


def execute_principal_architect(
    requirement: str,
    project_name: str,
    codex_call: CodexCall,
    middle_records: list[dict[str, Any]],
    *,
    config: Agent1CouncilConfig | None = None,
    iteration: int = 1,
    context_provider: Agent1ContextProvider | None = None,
    feedback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = (config or Agent1CouncilConfig()).normalized()
    provider = context_provider or Agent1ContextProvider()
    context = provider.build_context_package(requirement, project_name, cfg.planning_mode, iteration, PRINCIPAL_ARCHITECT.expert_id, extracted_intents=_extract_intents(requirement))
    prompt = _principal_prompt(PRINCIPAL_ARCHITECT, requirement, project_name, iteration, middle_records, context, feedback or {})
    _emit_agent1_event(
        "agent_action",
        phase="planning",
        action="Principal Architect started",
        status="running",
        summary=f"Reviewing {len(middle_records)} middle manager outputs.",
        rollup_stage="Principal",
        iteration=iteration,
    )
    _emit_council_node(
        layer="principal",
        node_id=PRINCIPAL_ARCHITECT.expert_id,
        title=PRINCIPAL_ARCHITECT.title,
        status="running",
        iteration=iteration,
        summary=f"Reviewing {len(middle_records)} middle manager outputs.",
        child_ids=[record.get("manager_id", "") for record in middle_records],
        phase_seq=_phase_seq(iteration, "principal", "start", PRINCIPAL_ARCHITECT.expert_id),
    )
    record = _call_codex_record(
        codex_call,
        prompt,
        record_base={
            "record_type": "principal",
            "principal_id": PRINCIPAL_ARCHITECT.expert_id,
            "title": PRINCIPAL_ARCHITECT.title,
            "domain": PRINCIPAL_ARCHITECT.domain,
            "iteration": iteration,
        },
    )
    _emit_agent1_event(
        "agent_action",
        phase="planning",
        action="Principal Architect completed",
        status="fail" if record["conflicts"] else "pass",
        summary=str(record.get("output", {}).get("summary", "Principal synthesis completed."))[:600],
        rollup_stage="Principal",
        iteration=iteration,
        metric={"conflicts": len(record["conflicts"])},
    )
    _emit_council_node(
        layer="principal",
        node_id=PRINCIPAL_ARCHITECT.expert_id,
        title=PRINCIPAL_ARCHITECT.title,
        status="conflict" if record["conflicts"] else "pass",
        iteration=iteration,
        summary=str(record.get("output", {}).get("summary", "Principal synthesis completed.")),
        child_ids=[item.get("manager_id", "") for item in middle_records],
        accepted_decisions=record.get("output", {}).get("decisions", []),
        rejected_decisions=record.get("output", {}).get("rejected_alternatives", []),
        conflicts=record.get("conflicts", []),
        feedback_digest=record.get("output", {}).get("feedback_to_middle_managers", {}),
        handoff_digest=record.get("output", {}).get("selected_architecture_candidate", {}),
        token_usage=record.get("token_usage", {}),
        duration_ms=_duration_ms(record),
        phase_seq=_phase_seq(iteration, "principal", "complete", PRINCIPAL_ARCHITECT.expert_id),
    )
    return record


def _run_parallel_nodes(nodes: tuple[Any, ...], max_workers: int, call_builder: Callable[[Any], dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(call_builder, node): node for node in nodes}
        for future in as_completed(futures):
            records.append(future.result())
    return records


def _group_session_infra_aborted_record(
    group: dict[str, Any],
    requirement: str,
    project_name: str,
    config: Agent1CouncilConfig,
    iteration: int,
    parent_span_id: str,
    attempt: int,
    *,
    failed_group_ids: list[str],
) -> dict[str, Any]:
    group_id = str(group.get("group_id") or group.get("manager_id") or "")
    span_id = f"agent1.cluster.iter{iteration}.{group_id}.attempt{attempt}.infra_aborted"
    leaf_ids = [str(item) for item in group.get("leaf_expert_ids") or []]
    guest_ids = [str(item) for item in group.get("guest_expert_ids") or []]
    all_experts = [*leaf_ids, *guest_ids]
    model_call_id = _sha256(f"{span_id}:{project_name}:{_sha256(requirement)}")[:16]
    message = "Group session skipped because prior Codex/API infrastructure failures reached the hard HITL threshold."
    record_base = {
        "record_type": "group_session",
        "group_id": group_id,
        "manager_id": group_id,
        "title": str(group.get("title") or group_id),
        "domain": str(group.get("domain") or ""),
        "covered_experts": all_experts,
        "leaf_expert_ids": leaf_ids,
        "guest_expert_ids": guest_ids,
        "iteration": iteration,
        "attempt": attempt,
        "span_id": span_id,
        "model_call_id": model_call_id,
        "cluster_rationale": group.get("rationale", ""),
    }
    _emit_agent1_event(
        "agent1_group_session_start",
        phase="planning",
        status="skipped",
        span_id=span_id,
        parent_span_id=parent_span_id,
        iteration=iteration,
        group_id=group_id,
        manager_id=group_id,
        leaf_expert_ids=leaf_ids,
        guest_expert_ids=guest_ids,
        model_call_id=model_call_id,
        attempt=attempt,
        summary=message,
    )
    output = _normalize_layer_output(record_base, _fallback_output(record_base, message))
    record = {
        **record_base,
        "output": output,
        "evidence": {"error": message, "prompt_sha256": _sha256(requirement), "response_sha256": _sha256("")},
        "prompt_sha256": _sha256(requirement),
        "response_sha256": _sha256(""),
        "latency_s": 0.0,
        "token_usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None, "estimated_cost_usd": None},
        "parse_status": "infra_aborted",
        "repair_attempted": False,
        "repair_pass": False,
        "retry_attempted": False,
        "retry_count": 0,
        "retry_errors": [],
        "conflicts": [
            {
                "severity": "critical",
                "type": "codex_call_failed",
                "subtype": "agent1_group_infra_hard_stop",
                "message": message,
                "failed_group_ids": failed_group_ids,
                "transient": True,
            }
        ],
    }
    _emit_agent1_event(
        "agent1_group_session_failed",
        phase="planning",
        status="fail",
        span_id=span_id,
        parent_span_id=parent_span_id,
        iteration=iteration,
        group_id=group_id,
        manager_id=group_id,
        leaf_expert_ids=leaf_ids,
        guest_expert_ids=guest_ids,
        model_call_id=model_call_id,
        attempt=attempt,
        confidence=0.0,
        summary=message,
    )
    _emit_council_node(
        layer="group",
        node_id=group_id,
        title=str(group.get("title") or group_id),
        status="fail",
        iteration=iteration,
        child_ids=all_experts,
        conflicts=record["conflicts"],
        summary=message,
        phase_seq=_phase_seq(iteration, "group", "infra_aborted", f"{group_id}:{attempt}"),
    )
    return record

def _call_group_session(
    group: dict[str, Any],
    requirement: str,
    project_name: str,
    codex_call: CodexCall,
    config: Agent1CouncilConfig,
    iteration: int,
    charter_record: dict[str, Any],
    provider: Agent1ContextProvider,
    feedback: dict[str, Any],
    intake_report: dict[str, Any] | None,
    parent_span_id: str,
    attempt: int,
) -> dict[str, Any]:
    group_id = str(group.get("group_id") or group.get("manager_id") or "")
    span_id = f"agent1.cluster.iter{iteration}.{group_id}.attempt{attempt}"
    leaf_ids = [str(item) for item in group.get("leaf_expert_ids") or []]
    guest_ids = [str(item) for item in group.get("guest_expert_ids") or []]
    all_experts = [*leaf_ids, *guest_ids]
    model_call_id = _sha256(f"{span_id}:{project_name}:{_sha256(requirement)}")[:16]
    context = provider.build_context_package(requirement, project_name, config.planning_mode, iteration, group_id, extracted_intents=_extract_intents(requirement))
    prompt = _group_session_prompt(group, requirement, project_name, iteration, charter_record, context, feedback, intake_report)
    _emit_agent1_event(
        "agent1_group_session_start",
        phase="planning",
        status="running",
        span_id=span_id,
        parent_span_id=parent_span_id,
        iteration=iteration,
        group_id=group_id,
        manager_id=group_id,
        leaf_expert_ids=leaf_ids,
        guest_expert_ids=guest_ids,
        model_call_id=model_call_id,
        attempt=attempt,
        summary=f"{group_id} group session started with {len(all_experts)} experts.",
    )
    _emit_council_node(
        layer="group",
        node_id=group_id,
        title=str(group.get("title") or group_id),
        status="running",
        iteration=iteration,
        child_ids=all_experts,
        summary=f"Group-session call attempt {attempt}; default={len(leaf_ids)} guest={len(guest_ids)}.",
        phase_seq=_phase_seq(iteration, "group", "start", f"{group_id}:{attempt}"),
    )
    record = _call_codex_record(
        codex_call,
        prompt,
        record_base={
            "record_type": "group_session",
            "group_id": group_id,
            "manager_id": group_id,
            "title": str(group.get("title") or group_id),
            "domain": str(group.get("domain") or ""),
            "covered_experts": all_experts,
            "leaf_expert_ids": leaf_ids,
            "guest_expert_ids": guest_ids,
            "iteration": iteration,
            "attempt": attempt,
            "span_id": span_id,
            "model_call_id": model_call_id,
            "cluster_rationale": group.get("rationale", ""),
        },
    )
    failed = _group_session_failed(record)
    if failed and _is_group_infra_failure(record):
        trace_debug_issue(
            severity="error",
            source="agent1",
            code="agent1_group_session_infra_failure",
            message=f"{group_id} group session failed because Codex/API call did not return usable evidence.",
            details={
                "iteration": iteration,
                "group_id": group_id,
                "manager_id": group_id,
                "attempt": attempt,
                "span_id": span_id,
                "model_call_id": model_call_id,
                "conflicts": record.get("conflicts", []),
            },
            node_id=f"AGENT1.GROUP_SESSION.{group_id}",
        )
    event_type = "agent1_group_session_failed" if failed else "agent1_group_session_done"
    status = "fail" if failed else "pass"
    _emit_agent1_event(
        event_type,
        phase="planning",
        status=status,
        span_id=span_id,
        parent_span_id=parent_span_id,
        iteration=iteration,
        group_id=group_id,
        manager_id=group_id,
        leaf_expert_ids=leaf_ids,
        guest_expert_ids=guest_ids,
        model_call_id=model_call_id,
        attempt=attempt,
        confidence=record.get("output", {}).get("confidence"),
        summary=str(record.get("output", {}).get("manager_summary") or record.get("output", {}).get("summary", f"{group_id} group completed."))[:600],
        metric=_token_metrics(record),
    )
    _emit_council_node(
        layer="group",
        node_id=group_id,
        title=str(group.get("title") or group_id),
        status="conflict" if record["conflicts"] else "pass",
        iteration=iteration,
        child_ids=all_experts,
        accepted_decisions=record.get("output", {}).get("accepted_decisions", []),
        rejected_decisions=record.get("output", {}).get("rejected_decisions", []),
        conflicts=[*_coerce_conflict_list(record.get("conflicts", [])), *_coerce_conflict_list(record.get("output", {}).get("internal_challenges", []))],
        feedback_digest=record.get("output", {}).get("internal_challenges", []),
        handoff_digest=record.get("output", {}).get("handoff_to_principal", ""),
        token_usage=record.get("token_usage", {}),
        duration_ms=_duration_ms(record),
        summary=str(record.get("output", {}).get("manager_summary") or record.get("output", {}).get("summary", f"{group_id} group completed.")),
        phase_seq=_phase_seq(iteration, "group", "complete", f"{group_id}:{attempt}"),
    )
    return record

def _call_middle_tasking(
    manager: ManagerNode,
    requirement: str,
    project_name: str,
    codex_call: CodexCall,
    config: Agent1CouncilConfig,
    iteration: int,
    charter_record: dict[str, Any],
    provider: Agent1ContextProvider,
    intake_report: dict[str, Any] | None,
) -> dict[str, Any]:
    context = provider.build_context_package(requirement, project_name, config.planning_mode, iteration, f"{manager.manager_id}-TASK", extracted_intents=_extract_intents(requirement))
    prompt = _middle_tasking_prompt(manager, requirement, project_name, iteration, charter_record, context, intake_report)
    _emit_agent1_event(
        "agent_action",
        phase="planning",
        action=f"{manager.manager_id} {manager.title} tasking started",
        status="running",
        summary=f"Deriving top-down tasks for {len(manager.leaf_expert_ids)} leaf experts.",
        rollup_stage="Middle Tasking",
        manager_id=manager.manager_id,
        iteration=iteration,
    )
    record = _call_codex_record(
        codex_call,
        prompt,
        record_base={
            "record_type": "middle_tasking",
            "manager_id": f"{manager.manager_id}-TASK",
            "title": f"{manager.title} Tasking",
            "domain": manager.domain,
            "covered_experts": list(manager.leaf_expert_ids),
            "iteration": iteration,
        },
    )
    _emit_council_node(
        layer="middle",
        node_id=f"{manager.manager_id}-TASK",
        title=f"{manager.title} Tasking",
        status="conflict" if record["conflicts"] else "pass",
        iteration=iteration,
        summary=str(record.get("output", {}).get("summary", f"{manager.title} tasking completed.")),
        parent_id="P01-CHARTER",
        child_ids=list(manager.leaf_expert_ids),
        accepted_decisions=record.get("output", {}).get("decisions", []),
        conflicts=record.get("conflicts", []),
        handoff_digest=record.get("output", {}).get("decisions", []),
        token_usage=record.get("token_usage", {}),
        duration_ms=_duration_ms(record),
        phase_seq=_phase_seq(iteration, "middle", "tasking", f"{manager.manager_id}-TASK"),
    )
    return record

def _call_leaf_expert(
    node: ExpertNode,
    requirement: str,
    project_name: str,
    codex_call: CodexCall,
    config: Agent1CouncilConfig,
    iteration: int,
    intents: dict[str, Any],
    feedback: dict[str, Any],
    provider: Agent1ContextProvider,
) -> dict[str, Any]:
    context = provider.build_context_package(requirement, project_name, config.planning_mode, iteration, node.expert_id, extracted_intents=intents)
    prompt = _leaf_prompt(node, requirement, project_name, iteration, intents, feedback, context)
    span_id = f"agent1.leaf.iter{iteration}.{node.expert_id}"
    model_call_id = _sha256(f"{span_id}:{project_name}:{_sha256(requirement)}")[:16]
    owner_group_id = _leaf_owner_group(node.expert_id)
    _emit_agent1_event(
        "agent_action",
        phase="planning",
        action=f"{node.expert_id} {node.title} started",
        status="running",
        summary=node.mission,
        rollup_stage="Leaf Experts",
        expert_id=node.expert_id,
        iteration=iteration,
    )
    _emit_agent1_event(
        "agent1_leaf_expert_start",
        phase="planning",
        status="running",
        span_id=span_id,
        iteration=iteration,
        expert_id=node.expert_id,
        group_id=owner_group_id,
        model_call_id=model_call_id,
        summary=f"{node.expert_id} leaf expert call started.",
    )
    _emit_council_node(
        layer="leaf",
        node_id=node.expert_id,
        title=node.title,
        status="running",
        iteration=iteration,
        summary=node.mission,
        phase_seq=_phase_seq(iteration, "leaf", "start", node.expert_id),
    )
    record = _call_codex_record(
        codex_call,
        prompt,
        record_base={
            "record_type": "leaf",
            "expert_id": node.expert_id,
            "title": node.title,
            "domain": node.domain,
            "iteration": iteration,
        },
        transient_retries=config.leaf_transient_max_retries,
        retry_backoff_s=config.leaf_retry_backoff_s,
        retry_event=lambda attempt, delay_s, error: _emit_agent1_event(
            "agent1_leaf_expert_retry",
            phase="planning",
            status="running",
            span_id=span_id,
            iteration=iteration,
            expert_id=node.expert_id,
            group_id=owner_group_id,
            model_call_id=model_call_id,
            attempt=attempt,
            retry_count=attempt,
            backoff_s=delay_s,
            error_class=type(error).__name__,
            summary=f"{node.expert_id} transient Codex error; retry {attempt}/{config.leaf_transient_max_retries} after {delay_s:.3f}s.",
        ),
    )
    leaf_failed = any(conflict.get("type") == "codex_call_failed" for conflict in record.get("conflicts", []))
    _emit_agent1_event(
        "agent1_leaf_expert_failed" if leaf_failed else "agent1_leaf_expert_done",
        phase="planning",
        status="fail" if leaf_failed else "pass",
        span_id=span_id,
        iteration=iteration,
        expert_id=node.expert_id,
        group_id=owner_group_id,
        model_call_id=model_call_id,
        retry_count=record.get("retry_count", 0),
        latency_s=record.get("latency_s"),
        error_class=_first_conflict_error_class(record),
        summary=f"{node.expert_id} leaf expert {'failed' if leaf_failed else 'completed'} after {record.get('retry_count', 0)} transient retries.",
        metrics=_token_metrics(record),
    )
    _emit_agent1_event(
        "agent_action",
        phase="planning",
        action=f"{node.expert_id} {node.title} completed",
        status="pass" if not record["conflicts"] else "fail",
        summary=str(record.get("output", {}).get("summary", f"{node.title} completed."))[:600],
        rollup_stage="Leaf Experts",
        expert_id=node.expert_id,
        iteration=iteration,
        metric={"conflicts": len(record["conflicts"]), "total_tokens": record.get("token_usage", {}).get("total_tokens")},
    )
    _emit_council_node(
        layer="leaf",
        node_id=node.expert_id,
        title=node.title,
        status="conflict" if record["conflicts"] else "pass",
        iteration=iteration,
        summary=str(record.get("output", {}).get("summary", f"{node.title} completed.")),
        accepted_decisions=record.get("output", {}).get("decisions", []),
        conflicts=record.get("conflicts", []),
        token_usage=record.get("token_usage", {}),
        duration_ms=_duration_ms(record),
        phase_seq=_phase_seq(iteration, "leaf", "complete", node.expert_id),
    )
    return record


def _call_middle_manager(
    manager: ManagerNode,
    requirement: str,
    project_name: str,
    codex_call: CodexCall,
    config: Agent1CouncilConfig,
    iteration: int,
    leaf_by_id: dict[str, dict[str, Any]],
    provider: Agent1ContextProvider,
) -> dict[str, Any]:
    assigned = [leaf_by_id[leaf_id] for leaf_id in manager.leaf_expert_ids if leaf_id in leaf_by_id]
    context = provider.build_context_package(requirement, project_name, config.planning_mode, iteration, manager.manager_id, extracted_intents=_extract_intents(requirement))
    prompt = _middle_prompt(manager, requirement, project_name, iteration, assigned, context)
    _emit_agent1_event(
        "agent_action",
        phase="planning",
        action=f"{manager.manager_id} {manager.title} started",
        status="running",
        summary=f"Reviewing {len(assigned)}/{len(manager.leaf_expert_ids)} assigned leaf outputs.",
        rollup_stage="Middle Managers",
        manager_id=manager.manager_id,
        iteration=iteration,
    )
    assigned_ids = [item["expert_id"] for item in assigned]
    _emit_council_node(
        layer="middle",
        node_id=manager.manager_id,
        title=manager.title,
        status="running",
        iteration=iteration,
        summary=f"Reviewing {len(assigned)}/{len(manager.leaf_expert_ids)} assigned leaf outputs.",
        child_ids=assigned_ids,
        phase_seq=_phase_seq(iteration, "middle", "start", manager.manager_id),
    )
    record = _call_codex_record(
        codex_call,
        prompt,
        record_base={
            "record_type": "middle",
            "manager_id": manager.manager_id,
            "title": manager.title,
            "domain": manager.domain,
            "covered_experts": list(manager.leaf_expert_ids),
            "iteration": iteration,
        },
    )
    missing = sorted(set(manager.leaf_expert_ids) - {item["expert_id"] for item in assigned})
    if missing:
        record["conflicts"].append({"severity": "critical", "type": "missing_leaf_outputs", "leaf_expert_ids": missing})
    _emit_agent1_event(
        "agent_action",
        phase="planning",
        action=f"{manager.manager_id} {manager.title} completed",
        status="fail" if record["conflicts"] else "pass",
        summary=str(record.get("output", {}).get("domain_summary") or record.get("output", {}).get("summary", f"{manager.title} completed."))[:600],
        rollup_stage="Middle Managers",
        manager_id=manager.manager_id,
        iteration=iteration,
        metric={"conflicts": len(record["conflicts"]), "covered_experts": len(record.get("covered_experts", []))},
    )
    for leaf_id in assigned_ids:
        _emit_agent1_event(
            "agent1_council_edge",
            phase="planning",
            status="linked",
            iteration=iteration,
            layer="edge",
            node_id=f"{leaf_id}->{manager.manager_id}",
            from_node=leaf_id,
            to_node=manager.manager_id,
            parent_id=manager.manager_id,
            child_ids=[leaf_id],
            phase_seq=_phase_seq(iteration, "edge", "linked", f"{leaf_id}-{manager.manager_id}"),
            summary=f"{manager.manager_id} consumed {leaf_id}.",
        )
    _emit_council_node(
        layer="middle",
        node_id=manager.manager_id,
        title=manager.title,
        status="conflict" if record["conflicts"] else "pass",
        iteration=iteration,
        summary=str(record.get("output", {}).get("domain_summary") or record.get("output", {}).get("summary", f"{manager.title} completed.")),
        child_ids=assigned_ids,
        accepted_decisions=record.get("output", {}).get("accepted_decisions", []),
        rejected_decisions=record.get("output", {}).get("rejected_decisions", []),
        conflicts=[
            *_coerce_conflict_list(record.get("conflicts", [])),
            *_coerce_conflict_list(record.get("output", {}).get("domain_conflicts", [])),
        ],
        feedback_digest=record.get("output", {}).get("feedback_to_leaf_experts", {}),
        handoff_digest=record.get("output", {}).get("handoff_to_principal", ""),
        token_usage=record.get("token_usage", {}),
        duration_ms=_duration_ms(record),
        phase_seq=_phase_seq(iteration, "middle", "complete", manager.manager_id),
    )
    return record


def _call_codex_record(
    codex_call: CodexCall,
    prompt: str,
    *,
    record_base: dict[str, Any],
    transient_retries: int = 0,
    retry_backoff_s: float = 0.0,
    retry_event: Callable[[int, float, BaseException], None] | None = None,
) -> dict[str, Any]:
    started = time.time()
    conflicts: list[dict[str, Any]] = []
    repair_attempted = False
    repair_pass = False
    retry_errors: list[dict[str, Any]] = []
    content = ""
    output: dict[str, Any] = {}
    evidence: dict[str, Any] = {}
    parse_status = "exception"
    for attempt in range(max(0, transient_retries) + 1):
        try:
            result = codex_call(prompt)
            content = getattr(result, "content", str(result))
            output = _parse_output(content)
            evidence = _safe_evidence(getattr(result, "evidence", {}), prompt, content)
            parse_status = output.pop("parse_status", "json")
            output, wrapper_key = _unwrap_schema_output(output, record_base)
            if wrapper_key:
                parse_status = f"{parse_status}_unwrapped:{wrapper_key}"
            if not _schema_is_valid(output):
                repair_attempted = True
                repair_prompt = _json_repair_prompt(prompt, content, record_base, parse_status)
                repair_result = codex_call(repair_prompt)
                repair_content = getattr(repair_result, "content", str(repair_result))
                repair_output = _parse_output(repair_content)
                repair_parse_status = repair_output.pop("parse_status", "json")
                repair_output, repair_wrapper_key = _unwrap_schema_output(repair_output, record_base)
                if repair_wrapper_key:
                    repair_parse_status = f"{repair_parse_status}_unwrapped:{repair_wrapper_key}"
                if _schema_is_valid(repair_output):
                    result = repair_result
                    content = repair_content
                    output = repair_output
                    evidence = _safe_evidence(getattr(result, "evidence", {}), prompt, content)
                    parse_status = "json_repaired"
                    repair_pass = True
                else:
                    conflicts.append({"severity": "critical", "type": "invalid_output_schema", "details": f"Strict JSON/schema failed after one repair ({parse_status}->{repair_parse_status})."})
                    output = _fallback_output(record_base, repair_content)
                    parse_status = "repair_failed_invalid_schema"
            output = _normalize_layer_output(record_base, output)
            break
        except Exception as exc:  # noqa: BLE001 - expert failures must become structured conflicts
            if attempt < transient_retries and _is_transient_codex_error(exc):
                delay_s = max(0.0, retry_backoff_s) * (2 ** attempt)
                retry_errors.append({"attempt": attempt + 1, "error_class": type(exc).__name__, "message": str(exc)[:300], "backoff_s": delay_s})
                if retry_event:
                    retry_event(attempt + 1, delay_s, exc)
                if delay_s > 0:
                    time.sleep(delay_s)
                continue
            content = ""
            output = _fallback_output(record_base, str(exc))
            evidence = {"error": str(exc), "prompt_sha256": _sha256(prompt), "response_sha256": _sha256("")}
            parse_status = "exception"
            conflicts.append({"severity": "critical", "type": "codex_call_failed", "message": str(exc), "error_class": type(exc).__name__, "retry_count": len(retry_errors), "transient": _is_transient_codex_error(exc)})
            break
    record = {
        **record_base,
        "output": output,
        "evidence": evidence,
        "prompt_sha256": evidence.get("prompt_sha256", _sha256(prompt)),
        "response_sha256": evidence.get("response_sha256", _sha256(content)),
        "latency_s": round(time.time() - started, 3),
        "token_usage": {
            "prompt_tokens": evidence.get("prompt_tokens"),
            "completion_tokens": evidence.get("completion_tokens"),
            "total_tokens": evidence.get("total_tokens"),
            "estimated_cost_usd": evidence.get("estimated_cost_usd"),
        },
        "parse_status": parse_status,
        "repair_attempted": repair_attempted,
        "repair_pass": repair_pass,
        "retry_attempted": bool(retry_errors),
        "retry_count": len(retry_errors),
        "retry_errors": retry_errors,
        "conflicts": conflicts + _output_conflicts(output),
    }
    return record


def _is_transient_codex_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(token in text for token in ("timeout", "timed out", "502", "bad gateway", "temporarily unavailable", "connection reset"))

def _leaf_owner_group(expert_id: str) -> str:
    for manager in MIDDLE_MANAGERS:
        if expert_id in manager.leaf_expert_ids:
            return manager.manager_id
    return ""

def _first_conflict_error_class(record: dict[str, Any]) -> str:
    for conflict in record.get("conflicts", []):
        if isinstance(conflict, dict) and conflict.get("error_class"):
            return str(conflict.get("error_class"))
    return ""


def _parse_output(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            parsed.setdefault("parse_status", "json")
            return parsed
    except json.JSONDecodeError:
        return {"parse_status": "invalid_json"}
    return {"parse_status": "json_root_not_object"}


def _schema_is_valid(output: dict[str, Any]) -> bool:
    required = {"summary", "decisions", "assumptions", "open_questions", "risks", "conflicts", "citations", "confidence", "needs_revision"}
    return required.issubset(output)


def _unwrap_schema_output(output: dict[str, Any], record_base: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    if _schema_is_valid(output):
        return output, None
    record_type = str(record_base.get("record_type") or "")
    preferred = {
        "principal_charter": ("principal_charter", "charter", "top_down_charter"),
        "middle_tasking": ("middle_tasking", "tasking", "manager_tasking"),
        "group_session": ("group_session", "cluster_group_session", "manager_group_session", "middle_review", "manager_review"),
        "leaf": ("leaf_analysis", "expert_analysis", "leaf"),
        "middle": ("middle_review", "manager_review", "middle"),
        "principal": ("principal_decision", "principal_architecture", "principal"),
    }.get(record_type, ())
    candidate_keys = [*preferred, *[key for key in output.keys() if key not in preferred]]
    for key in candidate_keys:
        nested = output.get(key)
        if isinstance(nested, dict) and _schema_is_valid(nested):
            extras = {extra_key: extra_value for extra_key, extra_value in output.items() if extra_key != key}
            return {**extras, **nested, "unwrapped_from": key}, str(key)
    return output, None


def _normalize_layer_output(record_base: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(output)
    for key in (
        "decisions",
        "assumptions",
        "open_questions",
        "risks",
        "citations",
        "accepted_decisions",
        "rejected_decisions",
        "rejected_alternatives",
        "resolved_conflicts",
    ):
        if key in normalized:
            normalized[key] = _coerce_list(normalized.get(key))
    for key in ("conflicts", "domain_conflicts", "unresolved_conflicts"):
        if key in normalized:
            normalized[key] = _coerce_conflict_list(normalized.get(key))
    if record_base.get("record_type") == "group_session":
        decisions = _coerce_list(normalized.get("decisions", []))
        normalized.setdefault("group_id", record_base.get("group_id"))
        normalized.setdefault("manager_id", record_base.get("manager_id"))
        normalized.setdefault("leaf_expert_ids", record_base.get("leaf_expert_ids", []))
        normalized.setdefault("guest_expert_ids", record_base.get("guest_expert_ids", []))
        normalized.setdefault("leaf_outputs", _default_leaf_outputs(record_base, normalized))
        normalized.setdefault("internal_challenges", _coerce_conflict_list(normalized.get("conflicts", [])))
        normalized.setdefault("accepted_decisions", decisions)
        normalized.setdefault("rejected_decisions", [])
        normalized.setdefault("manager_summary", normalized.get("summary", ""))
        normalized.setdefault("handoff_to_principal", normalized.get("summary", ""))
        normalized.setdefault("needs_retry", bool(normalized.get("needs_revision")))
        normalized.setdefault("covered_experts", record_base.get("covered_experts", []))
        normalized.setdefault("domain_summary", normalized.get("manager_summary", normalized.get("summary", "")))
        normalized.setdefault("domain_conflicts", _coerce_conflict_list(normalized.get("conflicts", [])))
        normalized.setdefault("feedback_to_leaf_experts", {})
    elif record_base.get("record_type") == "middle":
        decisions = _coerce_list(normalized.get("decisions", []))
        normalized.setdefault("accepted_decisions", decisions)
        normalized.setdefault("rejected_decisions", [])
        normalized.setdefault("domain_summary", normalized.get("summary", ""))
        normalized.setdefault("domain_conflicts", _coerce_conflict_list(normalized.get("conflicts", [])))
        normalized.setdefault("feedback_to_leaf_experts", {})
        normalized.setdefault("handoff_to_principal", normalized.get("summary", ""))
        normalized.setdefault("covered_experts", record_base.get("covered_experts", []))
    elif record_base.get("record_type") == "principal":
        normalized.setdefault("selected_architecture_candidate", {"summary": normalized.get("summary", ""), "decisions": normalized.get("decisions", [])})
        normalized.setdefault("rejected_alternatives", [])
        normalized.setdefault("resolved_conflicts", [])
        normalized.setdefault("unresolved_conflicts", normalized.get("conflicts", []))
        normalized.setdefault("feedback_to_middle_managers", {})
        normalized.setdefault("requirements_preserved", True)
        normalized.setdefault("capability_strategy", "deterministic_guardrails_required")
        normalized.setdefault("plan_ready_candidate", not bool(normalized.get("needs_revision")))
    return normalized


def _coerce_list(value: Any) -> list[Any]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, list):
        return value
    return [value]


def _coerce_conflict_list(value: Any) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for item in _coerce_list(value):
        if isinstance(item, dict):
            conflicts.append(item)
        elif item:
            conflicts.append({"severity": "noncritical", "type": "expert_conflict", "message": str(item)})
    return conflicts


def _output_conflicts(output: dict[str, Any]) -> list[dict[str, Any]]:
    conflicts = []
    if output.get("needs_revision"):
        conflicts.append({"severity": "noncritical", "type": "needs_revision"})
    for conflict in _coerce_conflict_list(output.get("conflicts", [])):
        if isinstance(conflict, dict):
            conflicts.append(conflict)
        elif conflict:
            conflicts.append({"severity": "noncritical", "type": "expert_conflict", "message": str(conflict)})
    return conflicts


def _safe_evidence(evidence: dict[str, Any], prompt: str, response: str) -> dict[str, Any]:
    clean = dict(evidence) if isinstance(evidence, dict) else {}
    if "api_key" in clean:
        clean["api_key"] = "<redacted>"
    clean.setdefault("prompt_sha256", _sha256(prompt))
    clean.setdefault("response_sha256", _sha256(response))
    return clean


def _fallback_output(record_base: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "summary": f"{record_base.get('title', record_base.get('record_type'))} produced fallback output.",
        "decisions": [],
        "assumptions": [],
        "open_questions": [],
        "risks": [{"reason": reason[:300]}],
        "conflicts": [{"severity": "noncritical", "type": "fallback_output", "message": reason[:300]}],
        "citations": [],
        "confidence": 0.1,
        "needs_revision": True,
    }


def _conflict_matrix(
    iteration: int,
    leaf_records: list[dict[str, Any]],
    middle_records: list[dict[str, Any]],
    principal_record: dict[str, Any],
    extra_records: list[dict[str, Any]] | None = None,
    requirement: str = "",
) -> dict[str, Any]:
    all_conflicts = []
    for record in [*(extra_records or []), *leaf_records, *middle_records, principal_record]:
        for conflict in record.get("conflicts", []):
            all_conflicts.append(
                _normalize_conflict_for_requirement(
                    {"source": record.get("expert_id") or record.get("manager_id") or record.get("principal_id"), **conflict},
                    requirement,
                )
            )
    leaf_failures = [
        record
        for record in leaf_records
        if record.get("record_type") == "leaf"
        and any(conflict.get("type") == "codex_call_failed" for conflict in record.get("conflicts", []))
    ]
    if len(leaf_records) >= len(LEAF_EXPERTS) and len(leaf_failures) / max(1, len(leaf_records)) > 0.25:
        all_conflicts.append(
            {
                "source": "leaf_layer",
                "severity": "critical",
                "type": "endpoint_unstable",
                "failed_leaf_calls": len(leaf_failures),
                "total_leaf_calls": len(leaf_records),
                "threshold": 0.25,
            }
        )
    critical = [item for item in all_conflicts if item.get("severity") == "critical"]
    noncritical = [item for item in all_conflicts if item.get("severity") != "critical"]
    return {
        "schema_version": "agent1.conflict_matrix.v1",
        "iteration": iteration,
        "critical_conflicts": critical,
        "noncritical_conflicts": noncritical,
    }

def _normalize_conflict_for_requirement(conflict: dict[str, Any], requirement: str) -> dict[str, Any]:
    normalized = dict(conflict)
    if normalized.get("severity") != "critical":
        return normalized
    status_text = " ".join(
        str(normalized.get(key) or "").lower()
        for key in ("status", "resolution_status")
    )
    if any(token in status_text for token in ("resolved", "closed", "mitigated", "accepted")):
        normalized["severity"] = "noncritical"
        normalized["resolved"] = True
        normalized["type"] = normalized.get("type") or "resolved_critical_conflict"
        return normalized
    intents = _extract_intents(requirement)
    requested_peripherals = {str(item).lower() for item in intents.get("external_peripherals") or []}
    conflict_text_fields = (
        "source",
        "type",
        "conflict",
        "description",
        "message",
        "resolution",
        "needed_decision",
        "resolution_status",
        "status",
        "route",
        "domain",
        "item",
        "action",
    )
    text = " ".join(
        str(normalized.get(key) or "")
        for key in conflict_text_fields
    ).lower()
    minimum_design_intent = bool(
        intents.get("cpu_requested")
        or intents.get("requested_bus_protocol")
        or requested_peripherals
    )
    defaultable_item = any(
        token in text
        for token in (
            "reset vector",
            "trap vector",
            "base address",
            "base addresses",
            "address map",
            "address ranges",
            "region sizes",
            "memory size",
            "memory sizes",
            "boot_rom",
            "single_port_sram",
            "default unmapped",
            "interrupt priority",
            "interrupt mask",
            "irq id",
            "register offsets",
            "fifo depth",
        )
    )
    missing_or_open = any(token in text for token in ("missing", "unspecified", "cannot release", "cannot lock", "open", "tbd", "needs"))
    true_contradiction = any(token in text for token in ("contradiction", "violates explicit", "overlap", "overlapping", "illegal overlap"))
    if minimum_design_intent and defaultable_item and missing_or_open and not true_contradiction:
        normalized["severity"] = "noncritical"
        normalized["resolved"] = True
        normalized["type"] = normalized.get("type") or "defaultable_architecture_open_item"
        normalized["resolution_status"] = "deferred_to_agent1_default_or_plan_review"
        normalized["requires_plan_review"] = True
        normalized["resolution"] = normalized.get("resolution") or "Treat as defaultable architecture open item for PLAN_REVIEW; do not block minimum design routing."
        return normalized
    known_peripherals = ("uart", "spi", "i2c", "gpio")
    for peripheral in ("spi", "i2c", "gpio"):
        explicit_out_of_scope = any(
            token in text
            for token in (
                "out of scope",
                "do not add",
                "reject",
                "only external peripheral",
                "not in requirement",
                "not requested",
            )
        )
        requested_other_peripheral = any(other in requested_peripherals and other in text for other in known_peripherals if other != peripheral)
        leaf_task_mismatch = any(
            token in text
            for token in (
                "leaf asks",
                "leaf title asks",
                "leaf targets",
                "l12 targets",
                "retask leaf",
                "retask",
                "project requirement",
                "deterministic intents declare",
                "requirement declares",
            )
        )
        if (
            peripheral not in requested_peripherals
            and peripheral in text
            and (explicit_out_of_scope or (requested_other_peripheral and leaf_task_mismatch))
        ):
            normalized["severity"] = "noncritical"
            normalized["resolved"] = True
            normalized["type"] = normalized.get("type") or f"out_of_scope_{peripheral}_resolved"
            normalized["resolution_status"] = "resolved_for_iteration"
            normalized["resolution"] = normalized.get("resolution") or f"{peripheral.upper()} is out of scope for this requirement; preserve requested peripherals only."
            return normalized
    return normalized


def _run_deterministic_guardrails(
    requirement: str,
    project_name: str,
    principal_record: dict[str, Any],
    config: Agent1CouncilConfig,
    iteration_count: int,
) -> dict[str, Any]:
    principal_output = principal_record.get("output", {}) if isinstance(principal_record.get("output"), dict) else {}
    candidate = principal_output.get("selected_architecture_candidate") if isinstance(principal_output.get("selected_architecture_candidate"), dict) else {}
    ai_analysis = _ai_analysis_from_principal(requirement, project_name, principal_record, config, iteration_count)
    failures: list[str] = []
    reports: dict[str, Any] = {}
    spec: dict[str, Any] = {}
    plan_markdown = ""

    preservation = _validate_candidate_preserves_requirement(requirement, candidate, principal_output)
    if not preservation["pass"]:
        failures.extend(preservation["failures"])
    reports["requirement_preservation"] = preservation

    try:
        spec = generate_architecture_spec(requirement, project_name, ai_analysis=ai_analysis)
        validate_architecture_spec(spec)
        plan_markdown = generate_architecture_plan_markdown(spec)
        plan_quality = validate_plan_quality(spec, plan_markdown)
        requirement_consistency = build_requirement_consistency_report(spec, plan_markdown)
        reports["plan_quality_report"] = plan_quality
        reports["requirement_consistency_report"] = requirement_consistency
        if not plan_quality.get("pass"):
            failures.extend(f"plan_quality:{failure}" for failure in plan_quality.get("failures", []))
        if not requirement_consistency.get("pass"):
            failures.extend(f"requirement_consistency:{failure}" for failure in requirement_consistency.get("failures", []))
    except Exception as exc:  # noqa: BLE001 - guardrail failures must be reported, not raised through UI
        failures.append(f"guardrail_exception:{type(exc).__name__}:{str(exc)}")

    return {
        "schema_version": "agent1.v51_guardrail_report.v1",
        "pass": not failures,
        "failures": failures,
        "planning_mode": config.planning_mode,
        "iteration_count": iteration_count,
        "principal_candidate": candidate,
        "reports": reports,
        "spec": spec,
        "plan_markdown": plan_markdown,
    }


def _ai_analysis_from_principal(
    requirement: str,
    project_name: str,
    principal_record: dict[str, Any],
    config: Agent1CouncilConfig,
    iteration_count: int,
) -> dict[str, Any]:
    output = principal_record.get("output", {}) if isinstance(principal_record.get("output"), dict) else {}
    candidate = output.get("selected_architecture_candidate") if isinstance(output.get("selected_architecture_candidate"), dict) else {}
    intents = _extract_intents(requirement)
    needs_clarification = requirement_needs_clarification(requirement)
    selected = {
        "project_name": project_name,
        "status": "requires_clarification" if needs_clarification else "candidate_ready",
        "summary": candidate.get("summary") or output.get("summary") or "",
        "primary_protocol": None if needs_clarification else candidate.get("primary_protocol") or candidate.get("bus_protocol") or intents.get("requested_bus_protocol") or "APB",
        "peripheral_protocol": candidate.get("peripheral_protocol"),
        "bridges": candidate.get("bridges") or [],
        "external_peripherals": [] if needs_clarification else candidate.get("external_peripherals") or intents.get("external_peripherals") or [],
        "source_experts": ["agent1_v51_deep_council"],
    }
    return {
        "schema_version": "agent1.ai_requirement_analysis.v51",
        "project_name": project_name,
        "raw_requirement": requirement,
        "planning_mode": config.planning_mode,
        "iteration_count": iteration_count,
        "leaf_expert_count": len(LEAF_EXPERTS),
        "middle_manager_count": len(MIDDLE_MANAGERS),
        "principal_call_count": iteration_count,
        "consensus_status": "candidate_ready" if output.get("plan_ready_candidate") else "candidate_needs_guardrails",
        "unresolved_conflicts": output.get("unresolved_conflicts", []),
        "extracted_intents": intents,
        "selected_architecture": selected,
        "rejected_alternatives": output.get("rejected_alternatives", []),
        "assumptions": output.get("assumptions", []),
        "open_questions": output.get("open_questions", []),
        "citations": output.get("citations", []),
        "confidence": output.get("confidence", 0.5),
    }


def _validate_candidate_preserves_requirement(requirement: str, candidate: dict[str, Any], principal_output: dict[str, Any]) -> dict[str, Any]:
    intents = _extract_intents(requirement)
    failures = []
    requested_bus = intents.get("requested_bus_protocol")
    candidate_bus = _upper_or_none(candidate.get("primary_protocol") or candidate.get("bus_protocol"))
    if requested_bus and candidate_bus and candidate_bus != requested_bus:
        failures.append(f"principal_candidate_rewrites_bus:{requested_bus}->{candidate_bus}")
    requested_width = intents.get("cpu_width_bits")
    candidate_width = _int_or_none(candidate.get("cpu_width_bits") or candidate.get("data_width_bits"))
    if requested_width and candidate_width and candidate_width != requested_width:
        failures.append(f"principal_candidate_rewrites_cpu_width:{requested_width}->{candidate_width}")
    requested_peripherals = set(intents.get("external_peripherals") or [])
    candidate_peripherals = {str(item).lower() for item in candidate.get("external_peripherals", [])} if isinstance(candidate.get("external_peripherals"), list) else set()
    if requested_peripherals and candidate_peripherals and not requested_peripherals.issubset(candidate_peripherals):
        failures.append(f"principal_candidate_drops_peripherals:{sorted(requested_peripherals - candidate_peripherals)}")
    if principal_output.get("requirements_preserved") is False:
        failures.append("principal_declared_requirements_not_preserved")
    return {
        "pass": not failures,
        "failures": failures,
        "raw_intents": intents,
        "candidate": candidate,
    }


def _upper_or_none(value: Any) -> str | None:
    return str(value).upper() if value not in (None, "") else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _principal_charter_prompt(requirement: str, project_name: str, iteration: int, context: dict[str, Any], feedback: dict[str, Any], intake_report: dict[str, Any] | None) -> str:
    return "\n".join(
        [
            "# Agent 1 V6.4 Principal Charter",
            "Create a top-down task charter. Do not release final architecture yet.",
            _schema_instruction("principal_charter"),
            "Also include top_down_charter, manager_tasking_goals, protected_user_requirements, and unresolved_questions.",
            f"Project: {project_name}",
            f"Iteration: {iteration}",
            f"Requirement: {requirement}",
            f"Intake router: {json.dumps(_compact_intake_report(intake_report), sort_keys=True)}",
            f"Previous feedback: {json.dumps(_digest_value(feedback), sort_keys=True)[:4000]}",
            f"Context package: {json.dumps(_compact_context(context), sort_keys=True)}",
        ]
    )

def _middle_tasking_prompt(manager: ManagerNode, requirement: str, project_name: str, iteration: int, charter_record: dict[str, Any], context: dict[str, Any], intake_report: dict[str, Any] | None) -> str:
    return "\n".join(
        [
            f"# Agent 1 V6.4 Middle Tasking {manager.manager_id}: {manager.title}",
            "Convert the principal charter into concrete tasks for assigned leaf experts.",
            _schema_instruction("middle_tasking"),
            "Also include leaf_tasking, required_citations, conflict_watchlist, and handoff_expectations.",
            f"Project: {project_name}",
            f"Iteration: {iteration}",
            f"Requirement: {requirement}",
            f"Covered leaf experts: {json.dumps(list(manager.leaf_expert_ids))}",
            f"Principal charter: {json.dumps(_digest_value(charter_record.get('output', {})), sort_keys=True)}",
            f"Intake router: {json.dumps(_compact_intake_report(intake_report), sort_keys=True)}",
            f"Context package: {json.dumps(_compact_context(context), sort_keys=True)}",
        ]
    )

def _group_session_prompt(
    group: dict[str, Any],
    requirement: str,
    project_name: str,
    iteration: int,
    charter_record: dict[str, Any],
    context: dict[str, Any],
    feedback: dict[str, Any],
    intake_report: dict[str, Any] | None,
) -> str:
    return "\n".join(
        [
            f"# Agent 1 V7.1 Group Session {group.get('group_id')}: {group.get('title')}",
            "Simulate one manager and its leaf experts debating in one Codex call.",
            "Manager must challenge weak leaf claims, reject unsafe assumptions, and distill one handoff for Principal.",
            _schema_instruction("group_session"),
            "Also include: group_id, manager_id, leaf_expert_ids, guest_expert_ids, leaf_outputs, internal_challenges, accepted_decisions, rejected_decisions, manager_summary, handoff_to_principal, needs_retry.",
            "Every internal_challenge/conflict should include severity, source_expert_id, target_group_id when cross-domain, reason, proposed_resolution, and resolution_status.",
            f"Project: {project_name}",
            f"Iteration: {iteration}",
            f"Requirement: {requirement}",
            f"Group assignment: {json.dumps(_digest_value(group), sort_keys=True)}",
            f"Principal charter: {json.dumps(_digest_value(charter_record.get('output', {})), sort_keys=True)}",
            f"Intake router: {json.dumps(_compact_intake_report(intake_report), sort_keys=True)}",
            f"Feedback: {json.dumps(_digest_value(feedback), sort_keys=True)[:4000]}",
            f"Context package: {json.dumps(_compact_context(context), sort_keys=True)}",
        ]
    )

def _leaf_prompt(node: ExpertNode, requirement: str, project_name: str, iteration: int, intents: dict[str, Any], feedback: dict[str, Any], context: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# Agent 1 V5.1 Leaf {node.expert_id}: {node.title}",
            node.mission,
            _schema_instruction("leaf"),
            f"Project: {project_name}",
            f"Iteration: {iteration}",
            f"Requirement: {requirement}",
            f"Deterministic intents: {json.dumps(intents, sort_keys=True)}",
            f"Feedback: {json.dumps(feedback, sort_keys=True)[:4000]}",
            f"Context package: {json.dumps(_compact_context(context), sort_keys=True)}",
        ]
    )


def _middle_prompt(manager: ManagerNode, requirement: str, project_name: str, iteration: int, assigned: list[dict[str, Any]], context: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# Agent 1 V5.1 Middle {manager.manager_id}: {manager.title}",
            "Review only assigned leaf outputs. Accept, reject, and route feedback.",
            _schema_instruction("middle"),
            "Also include: accepted_decisions, rejected_decisions, domain_summary, domain_conflicts, feedback_to_leaf_experts, handoff_to_principal.",
            f"Project: {project_name}",
            f"Iteration: {iteration}",
            f"Requirement: {requirement}",
            f"Assigned leaf outputs: {json.dumps(_summaries(assigned), sort_keys=True)}",
            f"Context package: {json.dumps(_compact_context(context), sort_keys=True)}",
        ]
    )


def _principal_prompt(node: ExpertNode, requirement: str, project_name: str, iteration: int, middle_records: list[dict[str, Any]], context: dict[str, Any], feedback: dict[str, Any]) -> str:
    previous_context = {
        "previous_principal_decision": feedback.get("principal", {}),
        "previous_conflict_matrix": feedback.get("conflicts", {}),
        "previous_deterministic_gate_report": _compact_guardrail_feedback(feedback.get("guardrail", {})),
    }
    return "\n".join(
        [
            f"# Agent 1 V5.1 {node.title}",
            node.mission,
            _schema_instruction("principal"),
            "Also include: selected_architecture_candidate, rejected_alternatives, resolved_conflicts, unresolved_conflicts, feedback_to_middle_managers, requirements_preserved, capability_strategy, plan_ready_candidate.",
            f"Project: {project_name}",
            f"Iteration: {iteration}",
            f"Requirement: {requirement}",
            f"Middle outputs: {json.dumps(_summaries(middle_records), sort_keys=True)}",
            f"Previous principal and deterministic gate context: {json.dumps(previous_context, sort_keys=True)[:4000]}",
            f"Context package: {json.dumps(_compact_context(context), sort_keys=True)}",
        ]
    )


def _schema_instruction(layer: str) -> str:
    return (
        f"Return JSON only for {layer} with fields: summary, decisions, assumptions, "
        "open_questions, risks, conflicts, citations, confidence, needs_revision. "
        "Conflicts must include severity critical or noncritical when present. "
        "Do not invent numeric PPA/bandwidth."
    )


def _json_repair_prompt(original_prompt: str, bad_content: str, record_base: dict[str, Any], parse_status: str) -> str:
    return "\n".join(
        [
            "# Agent 1 V6.4 Council JSON Repair",
            "Repair the previous response into strict JSON only.",
            _schema_instruction(str(record_base.get("record_type", "expert"))),
            f"Record base: {json.dumps(_digest_value(record_base), sort_keys=True)}",
            f"Parse status: {parse_status}",
            f"Original prompt sha256: {_sha256(original_prompt)}",
            "Previous response:",
            "```text",
            bad_content[:4000],
            "```",
        ]
    )

def _routing_text(requirement: str, intake_report: dict[str, Any] | None) -> str:
    parts = [requirement]
    if isinstance(intake_report, dict):
        parts.append(json.dumps(_digest_value(intake_report.get("canonical_intent", {})), sort_keys=True))
        parts.append(" ".join(str(item) for item in intake_report.get("missing_fields", [])[:20]))
    return " ".join(parts).lower().replace("_", " ")

def _leaf_keyword_hits(leaf: dict[str, Any], text: str) -> list[str]:
    tags = [str(item).lower().replace("_", " ") for item in leaf.get("tags") or []]
    title_words = [word.lower() for word in str(leaf.get("title") or "").replace("/", " ").split() if len(word) > 2]
    domain = str(leaf.get("domain") or "").lower()
    keywords = [*tags, *title_words, domain]
    return sorted({keyword for keyword in keywords if keyword and keyword in text})

def _guest_candidates_for_group(group_id: str) -> tuple[str, ...]:
    candidates = {
        "M01": ("L09", "L14", "L23", "L24"),
        "M02": ("L09", "L14", "L17", "L18"),
        "M03": ("L14", "L16", "L17", "L18"),
        "M04": ("L09", "L16", "L17", "L18", "L21"),
        "M05": ("L09", "L13", "L14", "L18", "L21", "L23"),
        "M06": ("L09", "L14", "L17", "L21", "L23"),
        "M07": ("L09", "L14", "L16", "L17", "L18", "L21"),
    }
    return candidates.get(group_id, ())

def _cluster_rationale(group_id: str, matched_keywords: list[str], guest_ids: list[str], score: int) -> str:
    if matched_keywords or guest_ids:
        return f"{group_id} score={score}; matched={matched_keywords}; guests={guest_ids}"
    return f"{group_id} uses stable default membership; no extra semantic guest needed."

def _default_leaf_outputs(record_base: dict[str, Any], output: dict[str, Any]) -> list[dict[str, Any]]:
    decisions = _coerce_list(output.get("decisions", []))
    return [
        {
            "expert_id": leaf_id,
            "summary": output.get("summary", ""),
            "decisions": decisions[:3],
            "status": "distilled_by_group_session",
        }
        for leaf_id in record_base.get("covered_experts", [])
    ]

def _group_session_failed(record: dict[str, Any]) -> bool:
    if any(conflict.get("type") == "codex_call_failed" for conflict in record.get("conflicts", [])):
        return True
    if record.get("parse_status") in {"exception", "repair_failed_invalid_schema"}:
        return True
    return False

def _group_retry_targets(records: list[dict[str, Any]]) -> list[str]:
    targets = []
    for record in records:
        if _is_group_infra_failure(record):
            continue
        confidence = _float_or_none(record.get("output", {}).get("confidence"))
        critical = any(conflict.get("severity") == "critical" for conflict in record.get("conflicts", []))
        if record.get("output", {}).get("needs_retry") or critical or (confidence is not None and confidence < 0.35):
            targets.append(str(record.get("group_id") or record.get("manager_id") or ""))
    return sorted({target for target in targets if target})

def _is_group_infra_failure(record: dict[str, Any]) -> bool:
    return any(conflict.get("type") == "codex_call_failed" for conflict in record.get("conflicts", []))

def _group_infra_failure_ids(records: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            str(record.get("group_id") or record.get("manager_id") or "")
            for record in records
            if _is_group_infra_failure(record)
        }
        - {""}
    )

def _emit_group_retry_suppressed(group_ids: list[str], iteration: int, *, parent_span_id: str, reason: str) -> None:
    _emit_agent1_event(
        "agent1_group_retry",
        phase="planning",
        status="skipped",
        span_id=f"agent1.cluster.iter{iteration}.retry_suppressed.{_sha256(','.join(group_ids) + reason)[:10]}",
        parent_span_id=parent_span_id,
        iteration=iteration,
        target_group_ids=group_ids,
        reason=reason,
        summary=f"Group retry suppressed for {len(group_ids)} groups because failures are infrastructure/API timeouts; avoiding retry storm.",
        metric={"suppressed_group_count": len(group_ids)},
    )

def _retry_group_sessions(
    target_group_ids: list[str],
    current_records: list[dict[str, Any]],
    requirement: str,
    project_name: str,
    codex_call: CodexCall,
    charter_record: dict[str, Any],
    assignment: dict[str, Any],
    config: Agent1CouncilConfig,
    iteration: int,
    provider: Agent1ContextProvider,
    *,
    feedback: dict[str, Any],
    intake_report: dict[str, Any] | None,
    parent_span_id: str,
) -> list[dict[str, Any]]:
    groups_by_id = {str(group.get("group_id") or group.get("manager_id") or ""): group for group in assignment.get("groups", [])}
    records_by_id = {str(record.get("group_id") or record.get("manager_id") or ""): record for record in current_records}
    retry_records: list[dict[str, Any]] = []
    for group_id in target_group_ids:
        group = groups_by_id.get(group_id)
        if not group:
            continue
        _emit_agent1_event(
            "agent1_group_retry",
            phase="planning",
            status="running",
            span_id=f"agent1.cluster.iter{iteration}.{group_id}.retry",
            parent_span_id=parent_span_id,
            iteration=iteration,
            target_group_id=group_id,
            group_id=group_id,
            manager_id=group_id,
            attempt=2,
            summary=f"Retrying {group_id} only; Principal/group quality gate requested targeted fix.",
        )
        retry_records.append(
            _call_group_session(
                group,
                requirement,
                project_name,
                codex_call,
                config,
                iteration,
                charter_record,
                provider,
                {**feedback, "previous_group_record": _digest_value(records_by_id.get(group_id, {}))},
                intake_report,
                parent_span_id,
                2,
            )
        )
    return retry_records

def _replace_group_records(records: list[dict[str, Any]], retry_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    replacements = {str(item.get("group_id") or item.get("manager_id") or ""): item for item in retry_records}
    return [replacements.get(str(record.get("group_id") or record.get("manager_id") or ""), record) for record in records]

def _principal_retry_targets(principal_record: dict[str, Any], assignment: dict[str, Any]) -> list[str]:
    if principal_record.get("output", {}).get("plan_ready_candidate") is not False and not any(conflict.get("severity") == "critical" for conflict in principal_record.get("conflicts", [])):
        return []
    known = {str(group.get("group_id") or group.get("manager_id") or "") for group in assignment.get("groups", [])}
    text = json.dumps(_digest_value(principal_record.get("output", {})), sort_keys=True).lower()
    targets = [group_id for group_id in known if group_id.lower() in text]
    feedback = principal_record.get("output", {}).get("feedback_to_middle_managers", {})
    if isinstance(feedback, dict):
        targets.extend(group_id for group_id in known if group_id in feedback)
    for conflict in _coerce_conflict_list(principal_record.get("output", {}).get("unresolved_conflicts", [])):
        target = str(conflict.get("target_group_id") or conflict.get("group_id") or "")
        if target in known:
            targets.append(target)
    return sorted(set(targets))[:2]

def _cross_group_challenge_matrix(iteration: int, group_records: list[dict[str, Any]]) -> dict[str, Any]:
    challenges: list[dict[str, Any]] = []
    known_groups = {str(record.get("group_id") or record.get("manager_id") or "") for record in group_records}
    for record in group_records:
        group_id = str(record.get("group_id") or record.get("manager_id") or "")
        output = record.get("output", {}) if isinstance(record.get("output"), dict) else {}
        for index, item in enumerate([*_coerce_conflict_list(output.get("internal_challenges", [])), *_coerce_conflict_list(output.get("conflicts", []))]):
            target = str(item.get("target_group_id") or item.get("owner_group_id") or item.get("group_id") or "")
            if target and target != group_id and target in known_groups:
                resolution = str(item.get("resolution_status") or item.get("status") or item.get("resolution") or "")
                resolved = any(token in resolution.lower() for token in ("resolved", "accepted", "rejected", "closed", "mitigated", "pass"))
                challenges.append(
                    {
                        "challenge_id": f"I{iteration}-{group_id}-{target}-{index}",
                        "source_group_id": group_id,
                        "target_group_id": target,
                        "severity": item.get("severity", "noncritical"),
                        "reason": item.get("reason") or item.get("message") or item.get("conflict") or item.get("description") or "",
                        "proposed_resolution": item.get("proposed_resolution") or item.get("resolution") or "",
                        "resolution": resolution,
                        "resolved": resolved or item.get("severity") != "critical",
                    }
                )
    return {
        "schema_version": "agent1.cross_group_challenge_matrix.v1",
        "iteration": iteration,
        "challenge_count": len(challenges),
        "unresolved_count": sum(1 for item in challenges if not item.get("resolved")),
        "challenges": challenges,
    }

def _emit_cross_group_challenges(challenge_matrix: dict[str, Any], iteration: int, *, parent_span_id: str) -> None:
    for challenge in challenge_matrix.get("challenges", []):
        _emit_agent1_event(
            "agent1_cross_group_challenge",
            phase="planning",
            status="pass" if challenge.get("resolved") else "fail",
            span_id=f"agent1.cluster.iter{iteration}.{challenge.get('challenge_id')}",
            parent_span_id=parent_span_id,
            iteration=iteration,
            group_id=challenge.get("source_group_id"),
            owner_group_id=challenge.get("target_group_id"),
            challenge_id=challenge.get("challenge_id"),
            resolution=challenge.get("resolution") or challenge.get("proposed_resolution"),
            summary=str(challenge.get("reason") or "cross-group challenge")[:600],
        )

def _token_metrics(record: dict[str, Any]) -> dict[str, Any]:
    usage = record.get("token_usage", {}) if isinstance(record.get("token_usage"), dict) else {}
    return {
        "latency_s": record.get("latency_s"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "estimated_cost_usd": usage.get("estimated_cost_usd"),
    }

def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _compact_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "rag_enabled": context.get("rag_enabled"),
        "rag_provider": context.get("rag_provider"),
        "source_hashes": context.get("source_hashes"),
        "capability_assessment": context.get("capability_assessment"),
        "sources": [{"type": item.get("type"), "path": item.get("path"), "summary": item.get("summary", "")[:600]} for item in context.get("context_sources", [])],
    }


def _compact_intake_report(intake_report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(intake_report, dict):
        return {}
    policy = intake_report.get("policy_matrix", {})
    return {
        "classification": intake_report.get("classification"),
        "normalized_requirement": intake_report.get("normalized_requirement"),
        "canonical_intent": _digest_value(intake_report.get("canonical_intent", {})),
        "missing_fields": intake_report.get("missing_fields", [])[:20],
        "consensus_score": intake_report.get("consensus_score"),
        "calibrated_confidence": intake_report.get("calibrated_confidence"),
        "policy_pass": policy.get("pass") if isinstance(policy, dict) else None,
    }

def _summaries(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": record.get("expert_id") or record.get("manager_id") or record.get("principal_id"),
            "title": record.get("title"),
            "summary": record.get("output", {}).get("summary"),
            "decisions": record.get("output", {}).get("decisions", []),
            "conflicts": record.get("conflicts", []),
        }
        for record in records
    ]


def _context_manifest(provider: Agent1ContextProvider, requirement: str, project_name: str) -> dict[str, Any]:
    package = provider.build_context_package(requirement, project_name, "normal", 1, "manifest")
    return {
        "schema_version": "agent1.rag_context_manifest.v1",
        "rag_enabled": package["rag_enabled"],
        "rag_provider": package["rag_provider"],
        "source_hashes": package["source_hashes"],
        "context_sources": [{"type": item["type"], "path": item["path"], "sha256": item["sha256"]} for item in package["context_sources"]],
    }


def _compact_guardrail_feedback(guardrail: Any) -> dict[str, Any]:
    if not isinstance(guardrail, dict):
        return {}
    return {
        "pass": guardrail.get("pass"),
        "failures": guardrail.get("failures", [])[:20],
        "planning_mode": guardrail.get("planning_mode"),
        "iteration_count": guardrail.get("iteration_count"),
    }


def _jsonl(records: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(record, sort_keys=True) for record in records) + ("\n" if records else "")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _emit_batch_event(
    rollup_stage: str,
    status_word: str,
    iteration: int,
    *,
    total: int,
    max_workers: int,
    completed: int = 0,
    failed: int = 0,
) -> None:
    queued = max(0, total - completed)
    _emit_agent1_event(
        "agent_action",
        phase="planning",
        action=f"V5.1 {rollup_stage} batch {status_word}",
        status="running" if status_word == "started" else ("fail" if failed else "pass"),
        summary=f"iteration={iteration}; total={total}; completed={completed}; queued={queued}; failed={failed}; max_workers={max_workers}",
        rollup_stage=rollup_stage,
        iteration=iteration,
        metric={
            "total": total,
            "completed": completed,
            "queued": queued,
            "failed": failed,
            "max_workers": max_workers,
        },
    )


def _phase_seq(iteration: int, layer: str, step: str, node_id: str = "") -> str:
    suffix = f":{node_id}" if node_id else ""
    return f"{iteration:03d}:{layer}:{step}{suffix}"

def _duration_ms(record: dict[str, Any]) -> int | None:
    value = record.get("latency_s")
    try:
        return int(float(value) * 1000)
    except (TypeError, ValueError):
        return None

def _digest_text(value: Any, limit: int = 512) -> str:
    text = str(value) if value is not None else ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 16)] + "...[truncated]"

def _digest_value(value: Any, *, item_limit: int = 20, text_limit: int = 512) -> Any:
    if isinstance(value, dict):
        return {str(key): _digest_value(child, item_limit=item_limit, text_limit=text_limit) for key, child in list(value.items())[:item_limit]}
    if isinstance(value, list):
        return [_digest_value(item, item_limit=item_limit, text_limit=text_limit) for item in value[:item_limit]]
    if isinstance(value, str):
        return _digest_text(value, text_limit)
    return value

def _digest_list(value: Any, *, item_limit: int = 20) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [_digest_value(item) for item in value[:item_limit]]

def _emit_council_node(
    *,
    layer: str,
    node_id: str,
    title: str,
    status: str,
    iteration: int,
    summary: str,
    parent_id: str | None = None,
    child_ids: list[str] | None = None,
    accepted_decisions: Any = None,
    rejected_decisions: Any = None,
    conflicts: Any = None,
    feedback_digest: Any = None,
    handoff_digest: Any = None,
    token_usage: dict[str, Any] | None = None,
    duration_ms: int | None = None,
    phase_seq: str = "",
) -> None:
    _emit_agent1_event(
        "agent1_council_node",
        agent="agent1",
        phase="planning",
        layer=layer,
        node_id=node_id,
        title=title,
        status=status,
        iteration=iteration,
        parent_id=parent_id,
        child_ids=child_ids or [],
        summary=_digest_text(summary),
        accepted_decisions=_digest_list(accepted_decisions),
        rejected_decisions=_digest_list(rejected_decisions),
        conflicts=_digest_list(conflicts),
        feedback_digest=_digest_value(feedback_digest or {}),
        handoff_digest=_digest_value(handoff_digest or {}),
        token_usage=_digest_value(token_usage or {}),
        duration_ms=duration_ms,
        phase_seq=phase_seq or _phase_seq(iteration, layer, status, node_id),
    )

def _emit_agent1_event(event_type: str, **payload: Any) -> None:
    event = {"type": event_type, **payload}
    if event_type == "agent_action":
        event.setdefault("agent", "agent1")
        event.setdefault("label", "Agent 1 Architect")
    if event_type.startswith("agent1_council_"):
        event.setdefault("agent", "agent1")
        event.setdefault("label", "Agent 1 Deep Council")
        layer = str(event.get("layer") or "council")
        trace_event(
            TRACE_FILES["agent1_guardrail"] if layer == "guardrail" else TRACE_FILES["agent1_council"],
            phase="planning",
            agent="agent1",
            node_id=str(event.get("node_id") or event.get("action") or "AGENT1.COUNCIL"),
            event_type=event_type,
            status=str(event.get("status") or "info"),
            parent_node_id=str(event.get("parent_id") or "AGENT1.COUNCIL_ENTER"),
            payload={key: value for key, value in event.items() if key != "type"},
        )
    elif event_type in {"agent_handoff", "agent_discussion"} or str(event.get("rollup_stage") or "") in {"Guardrails", "Iteration", "Principal"}:
        trace_event(
            TRACE_FILES["agent1_final_decision"],
            phase="planning",
            agent="agent1",
            node_id=str(event.get("node_id") or event.get("action") or event_type),
            event_type=event_type,
            status=str(event.get("status") or event.get("severity") or "info"),
            payload={key: value for key, value in event.items() if key != "type"},
        )
    emit_runtime_event(event)
