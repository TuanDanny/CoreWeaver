"""Agent 1 V5.1 hierarchical deep expert council primitives."""
from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
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
from semiconductor_swarm.tracing import TRACE_FILES, trace_event

CodexCall = Callable[..., Any]


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
    min_iterations: int | None = None
    max_iterations: int = 7
    max_concurrent_leaf_calls: int = int(os.getenv("AGENT1_MAX_CONCURRENT_LEAF_CALLS", "8"))
    max_concurrent_middle_calls: int = int(os.getenv("AGENT1_MAX_CONCURRENT_MIDDLE_CALLS", "4"))
    expert_call_timeout_s: float | None = None

    def resolved_min_iterations(self) -> int:
        if self.min_iterations is not None:
            return self.min_iterations
        return 3 if self.planning_mode == "deep_planning" else 1

    def normalized(self) -> "Agent1CouncilConfig":
        if self.planning_mode not in {"normal", "deep_planning"}:
            raise ValueError(f"Unsupported Agent1 V5.1 planning mode: {self.planning_mode}")
        return Agent1CouncilConfig(
            planning_mode=self.planning_mode,
            min_iterations=max(1, self.resolved_min_iterations()),
            max_iterations=max(1, self.max_iterations),
            max_concurrent_leaf_calls=_clamp_int(self.max_concurrent_leaf_calls, 1, len(LEAF_EXPERTS)),
            max_concurrent_middle_calls=_clamp_int(self.max_concurrent_middle_calls, 1, len(MIDDLE_MANAGERS)),
            expert_call_timeout_s=self.expert_call_timeout_s,
        )


def topology_manifest(config: Agent1CouncilConfig | None = None) -> dict[str, Any]:
    cfg = (config or Agent1CouncilConfig()).normalized()
    return {
        "schema_version": "agent1.deep_council_config.v1",
        "planning_mode": cfg.planning_mode,
        "min_iterations": cfg.resolved_min_iterations(),
        "max_iterations": cfg.max_iterations,
        "max_concurrent_leaf_calls": cfg.max_concurrent_leaf_calls,
        "max_concurrent_middle_calls": cfg.max_concurrent_middle_calls,
        "leaf_experts": [asdict(item) for item in LEAF_EXPERTS],
        "middle_managers": [asdict(item) for item in MIDDLE_MANAGERS],
        "principal_architect": asdict(PRINCIPAL_ARCHITECT),
        "planned_calls_per_iteration": planned_calls_per_iteration(),
        "minimum_planned_calls": planned_minimum_calls(cfg),
    }


def cluster_map() -> dict[str, tuple[str, ...]]:
    return {manager.manager_id: manager.leaf_expert_ids for manager in MIDDLE_MANAGERS}


def planned_calls_per_iteration() -> int:
    return 1 + len(MIDDLE_MANAGERS) + len(LEAF_EXPERTS) + len(MIDDLE_MANAGERS) + 1


def planned_minimum_calls(config: Agent1CouncilConfig | None = None) -> int:
    cfg = (config or Agent1CouncilConfig()).normalized()
    return planned_calls_per_iteration() * cfg.resolved_min_iterations()


def validate_topology() -> dict[str, Any]:
    leaf_ids = [item.expert_id for item in LEAF_EXPERTS]
    covered = [leaf_id for manager in MIDDLE_MANAGERS for leaf_id in manager.leaf_expert_ids]
    failures = []
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
    return {"pass": not failures, "failures": failures, "leaf_count": len(LEAF_EXPERTS), "middle_count": len(MIDDLE_MANAGERS), "principal_count": 1}


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


def _call_codex_record(codex_call: CodexCall, prompt: str, *, record_base: dict[str, Any]) -> dict[str, Any]:
    started = time.time()
    conflicts: list[dict[str, Any]] = []
    repair_attempted = False
    repair_pass = False
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
    except Exception as exc:  # noqa: BLE001 - expert failures must become structured conflicts
        content = ""
        output = _fallback_output(record_base, str(exc))
        evidence = {"error": str(exc), "prompt_sha256": _sha256(prompt), "response_sha256": _sha256("")}
        parse_status = "exception"
        conflicts.append({"severity": "critical", "type": "codex_call_failed", "message": str(exc)})
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
        "conflicts": conflicts + _output_conflicts(output),
    }
    return record


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
    if record_base.get("record_type") == "middle":
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
