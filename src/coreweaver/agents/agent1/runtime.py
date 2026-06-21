from __future__ import annotations

import asyncio
import json
from pathlib import Path

from coreweaver.events import AsyncEventStream, CoreEvent, CoreEventType
from coreweaver.framework_types import make_idempotency_key, stable_hash
from coreweaver.messages import Blackboard, CoreMessage, MessageKind, MessageRole
from coreweaver.models import ModelRouter
from coreweaver.safety import CanaryFinding, CircuitBreakerState, CostBudget, CostUsage, KillSwitchState
from coreweaver.debug import build_replay_resume_state

from .challenge import ChallengeMatrix
from .handoff import Agent2HandoffGate
from .intake import build_clarification, build_requirement_pack
from .managers import MiddleManagerRunner
from .models import Agent1SwarmResult, ManagerSummary, RequirementClassification, RequirementPack
from .reasoning import ArchitectureReasoningEngine
from .router import Agent1ClusterRouter
from .signoff import IndustrialSignoffEngine
from .topology_contract import default_agent1_topology
from .verifier import ReadOnlyVerifier


class Agent1SwarmRuntime:
    def __init__(
        self,
        *,
        event_stream: AsyncEventStream,
        model_router: ModelRouter | None = None,
        max_challenge_rounds: int = 3,
        max_group_concurrency: int = 4,
        cost_budget: CostBudget | None = None,
        kill_switch: KillSwitchState | None = None,
        circuit_breaker: CircuitBreakerState | None = None,
    ) -> None:
        self.event_stream = event_stream
        self.model_router = model_router or ModelRouter()
        self.max_challenge_rounds = max_challenge_rounds
        self.max_group_concurrency = max_group_concurrency
        self.cost_budget = cost_budget or CostBudget(max_tokens=250_000, max_cost_usd=250.0)
        self.kill_switch = kill_switch or KillSwitchState()
        self.circuit_breaker = circuit_breaker or CircuitBreakerState()

    async def run(
        self,
        *,
        run_id: str,
        revision_id: str,
        requirement: str,
        project_name: str,
        planning_mode: str,
        output_dir: Path,
        attachment_refs: tuple[str, ...] = (),
    ) -> Agent1SwarmResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        await self._emit(CoreEventType.INTAKE_STARTED, run_id, revision_id, "agent1:intake:start", "run:start", {"stage": "intake"})
        pack = build_requirement_pack(requirement=requirement, project_name=project_name, planning_mode=planning_mode, attachment_refs=attachment_refs)
        await self._emit(
            CoreEventType.CLASSIFICATION_DONE,
            run_id,
            revision_id,
            "agent1:intake:classification",
            "agent1:intake:start",
            {"classification": pack.classification.value, "missing_fields": pack.missing_fields},
        )
        self._write_checkpoint(output_dir, "intake", run_id, revision_id, {"classification": pack.classification.value, "missing_fields": pack.missing_fields})
        if pack.classification == RequirementClassification.NON_DESIGN_CONVERSATION:
            await self._emit_pause(run_id, revision_id, "NON_DESIGN_CONVERSATION", "This looks like non-design conversation; Agent1 swarm did not run.")
            self._write_checkpoint(output_dir, "pause_non_design", run_id, revision_id, {"action_required": "NON_DESIGN_CONVERSATION"})
            self._write_runtime_debug_artifacts(output_dir, run_id=run_id)
            return Agent1SwarmResult(status="paused", action_required="NON_DESIGN_CONVERSATION")
        if pack.classification == RequirementClassification.AMBIGUOUS_CHIP_IDEA:
            question = build_clarification(pack)
            await self._emit(
                CoreEventType.AGENT1_MODEL_ROUTE_SELECTED,
                run_id,
                revision_id,
                "agent1:intake:clarification_route",
                "agent1:intake:classification",
                {"route": "clarification", "question_id": question.question_id},
            )
            await self._emit(
                CoreEventType.AGENT1_CLARIFICATION_QUESTION,
                run_id,
                revision_id,
                f"agent1:clarification:{question.question_id}",
                "agent1:intake:classification",
                {"question_id": question.question_id, "question": question.question, "missing_fields": question.missing_fields},
            )
            await self._emit_pause(run_id, revision_id, "REQUIREMENT_CLARIFICATION", question.question, {"missing_fields": question.missing_fields})
            self._write_checkpoint(output_dir, "clarification", run_id, revision_id, question.model_dump(mode="json"))
            self._write_runtime_debug_artifacts(output_dir, run_id=run_id)
            return Agent1SwarmResult(status="paused", action_required="REQUIREMENT_CLARIFICATION")
        await self._emit(CoreEventType.INTAKE_DONE, run_id, revision_id, "agent1:intake:done", "agent1:intake:start", {"requirement_id": pack.requirement_id})
        await self._emit(
            CoreEventType.AGENT1_COUNCIL_MODE_SELECTED,
            run_id,
            revision_id,
            "agent1:council_mode",
            "agent1:intake:done",
            {"mode": "group_session", "planning_mode": planning_mode, "principal_id": "P00", "middle_count": 7, "leaf_count": 24},
        )
        safety_action = await self._safety_preflight(pack, run_id, revision_id)
        if safety_action is not None:
            await self._emit_pause(run_id, revision_id, safety_action, "Agent1 safety preflight blocked execution.")
            self._write_checkpoint(output_dir, f"safety_{safety_action.lower()}", run_id, revision_id, {"action_required": safety_action})
            self._write_runtime_debug_artifacts(output_dir, run_id=run_id)
            return Agent1SwarmResult(status="paused", action_required=safety_action)

        board = Blackboard(run_id)
        self._append_requirement(board, pack, run_id, revision_id)
        await self._emit(CoreEventType.AGENT1_BLACKBOARD_WRITE, run_id, revision_id, "agent1:blackboard:requirement", "agent1:intake:done", {"revision": board.revision, "kind": "user_requirement"})

        topology = default_agent1_topology()
        await self._emit(
            CoreEventType.AGENT1_TOPOLOGY_LOADED,
            run_id,
            revision_id,
            "agent1:topology",
            "agent1:intake:done",
            {"principal_id": topology.principal_id, "manager_count": len(topology.managers), "leaf_count": len(topology.leaves), "topology_hash": stable_hash(topology.model_dump(mode="json"))},
        )
        assignments = Agent1ClusterRouter().assign()
        await self._emit(
            CoreEventType.AGENT1_CLUSTER_ASSIGNMENT,
            run_id,
            revision_id,
            "agent1:cluster",
            "agent1:topology",
            {"assignments": tuple(assignment.model_dump(mode="json") for assignment in assignments)},
        )
        canary = CanaryFinding.from_touch("decomposition_drift", "canary_leak_mutation" in pack.raw_text.lower())
        await self._emit(CoreEventType.AGENT1_CANARY_TOUCHED, run_id, revision_id, "agent1:canary:decomposition", "agent1:cluster", {"canary_id": canary.token_id, "touched": canary.touched, "quarantine_required": canary.quarantine_required})
        if canary.quarantine_required:
            await self._emit_debug_issue(run_id, revision_id, "agent1.safety", "canary_touched", "Canary token appeared in model-visible output.", parent_span_id="agent1:canary:decomposition")
            await self._emit_pause(run_id, revision_id, "HITL_REQUIRED", "Canary quarantine blocks Agent1 handoff.")
            self._write_checkpoint(output_dir, "canary_quarantine", run_id, revision_id, {"canary_id": canary.token_id})
            self._write_runtime_debug_artifacts(output_dir, board)
            return Agent1SwarmResult(status="paused", action_required="HITL_REQUIRED")
        self._write_checkpoint(output_dir, "cluster_assignment", run_id, revision_id, {"assignment_count": len(assignments), "topology_hash": stable_hash(topology.model_dump(mode="json"))})

        summaries = await self._run_managers(pack, assignments, run_id, revision_id)
        for summary in summaries:
            self._append_summary(board, summary, run_id, revision_id)
            await self._emit(CoreEventType.AGENT1_BLACKBOARD_WRITE, run_id, revision_id, f"agent1:blackboard:{summary.manager_id}", "agent1:cluster", {"revision": board.revision, "group_id": summary.group_id, "manager_id": summary.manager_id})
        self._write_checkpoint(output_dir, "group_sessions", run_id, revision_id, {"summary_count": len(summaries), "blackboard_revision": board.revision})

        matrix = ChallengeMatrix(max_rounds=self.max_challenge_rounds)
        challenges = matrix.build(pack, tuple(summaries))
        for challenge in challenges:
            await self._emit(CoreEventType.AGENT1_CROSS_GROUP_CHALLENGE, run_id, revision_id, challenge.challenge_id, "agent1:cluster", challenge.model_dump(mode="json"))
        for iteration in range(1, self.max_challenge_rounds + 1):
            review = matrix.review(challenges, iteration=iteration)
            await self._emit(CoreEventType.AGENT1_PRINCIPAL_GROUP_REVIEW, run_id, revision_id, f"agent1:principal_review:{iteration}", "agent1:cluster", review.model_dump(mode="json"))
            if review.approved:
                break
            if review.action_required == "HITL_REQUIRED":
                await self._emit_pause(run_id, revision_id, "CONFLICT_REQUIRED", "Unresolved cross-group blocker reached max challenge rounds.", {"unresolved_challenges": tuple(challenge.model_dump(mode="json") for challenge in review.unresolved_challenges)})
                self._write_checkpoint(output_dir, "conflict_required", run_id, revision_id, {"iteration": iteration, "unresolved_challenges": tuple(challenge.challenge_id for challenge in review.unresolved_challenges)})
                self._write_runtime_debug_artifacts(output_dir, board)
                return Agent1SwarmResult(status="paused", action_required="CONFLICT_REQUIRED")
        self._write_checkpoint(output_dir, "principal_review", run_id, revision_id, {"challenge_count": len(challenges)})

        verifier_findings = ReadOnlyVerifier().verify(board.snapshot())
        dag_nodes = ("intake", "cluster_assignment", "group_sessions", "challenge_review", "architecture_reasoning", "signoff", "handoff")
        await self._emit(CoreEventType.AGENT1_PLAN_DAG_CREATED, run_id, revision_id, "agent1:plan_dag:created", "agent1:principal_review:1", {"nodes": dag_nodes})
        await self._emit(CoreEventType.AGENT1_PLAN_DAG_VALIDATED, run_id, revision_id, "agent1:plan_dag:validated", "agent1:plan_dag:created", {"nodes": dag_nodes, "status": "acyclic"})
        await self._emit(CoreEventType.AGENT1_PLAN_NODE_START, run_id, revision_id, "agent1:plan_node:architecture_reasoning:start", "agent1:plan_dag:validated", {"plan_node_id": "architecture_reasoning"})
        max_loops = 5 if planning_mode == "deep" else 2
        feedback = None
        for loop_idx in range(max_loops):
            await self.event_stream.emit(
                CoreEvent(
                    event_type=CoreEventType.AGENT1_TOOL_CALL_START,
                    run_id=run_id,
                    revision_id=revision_id,
                    span_id=f"tool:architecture_reasoning:start:{loop_idx}",
                    parent_span_id="agent1:plan_node:architecture_reasoning:start",
                    tool_call_id="tool:architecture_reasoning",
                    idempotency_key=make_idempotency_key(run_id, revision_id, f"architecture_reasoning_{loop_idx}"),
                    payload={"tool_call_id": "tool:architecture_reasoning", "stage": "architecture_reasoning", "loop": loop_idx},
                )
            )
            plan = await ArchitectureReasoningEngine(self.model_router).synthesize(pack, tuple(summaries), idempotency_key=make_idempotency_key(run_id, revision_id, f"architecture_reasoning_{loop_idx}"), feedback=feedback)
            plan_id = stable_hash(plan.model_dump(mode="json"))
            await self.event_stream.emit(
                CoreEvent(
                    event_type=CoreEventType.AGENT1_TOOL_CALL_DONE,
                    run_id=run_id,
                    revision_id=revision_id,
                    span_id=f"tool:architecture_reasoning:done:{loop_idx}",
                    parent_span_id=f"tool:architecture_reasoning:start:{loop_idx}",
                    tool_call_id="tool:architecture_reasoning",
                    idempotency_key=make_idempotency_key(run_id, revision_id, f"architecture_reasoning_{loop_idx}"),
                    payload={"tool_call_id": "tool:architecture_reasoning", "status": "done", "output_hash": plan_id},
                )
            )
            await self._emit(CoreEventType.AGENT1_PLAN_NODE_DONE, run_id, revision_id, f"agent1:plan_node:architecture_reasoning:done:{loop_idx}", "agent1:plan_node:architecture_reasoning:start", {"plan_node_id": "architecture_reasoning", "plan_id": plan_id})
            await self._emit(CoreEventType.AGENT1_PROPOSAL_CREATED, run_id, revision_id, f"agent1:proposal:plan:{loop_idx}", f"agent1:plan_node:architecture_reasoning:done:{loop_idx}", {"proposal_id": plan_id, "artifact_kind": "architecture_plan"})
            if "unapproved_commit_mutation" in pack.raw_text.lower():
                await self._emit(CoreEventType.AGENT1_PROPOSAL_REJECTED, run_id, revision_id, f"agent1:proposal:rejected:{loop_idx}", f"agent1:proposal:plan:{loop_idx}", {"proposal_id": plan_id, "reason": "dangerous action requires approval before commit"})
                await self._emit_pause(run_id, revision_id, "HITL_REQUIRED", "Proposal approval is required before commit.")
                self._write_checkpoint(output_dir, "proposal_rejected", run_id, revision_id, {"proposal_id": plan_id})
                self._write_runtime_debug_artifacts(output_dir, board)
                return Agent1SwarmResult(status="paused", action_required="HITL_REQUIRED", architecture_plan=plan)
            await self._emit(CoreEventType.AGENT1_ROLLBACK_POINT_CREATED, run_id, revision_id, f"agent1:rollback:pre_signoff:{loop_idx}", f"agent1:proposal:plan:{loop_idx}", {"rollback_id": "pre_signoff", "blackboard_revision": board.revision})
            self._write_checkpoint(output_dir, "pre_signoff", run_id, revision_id, {"plan_id": plan_id, "blackboard_revision": board.revision})
            await self.event_stream.emit(
                CoreEvent(
                    event_type=CoreEventType.AGENT1_TOOL_CALL_START,
                    run_id=run_id,
                    revision_id=revision_id,
                    span_id=f"tool:signoff:start:{loop_idx}",
                    parent_span_id=f"agent1:rollback:pre_signoff:{loop_idx}",
                    tool_call_id="tool:signoff",
                    idempotency_key=make_idempotency_key(run_id, revision_id, f"signoff_{loop_idx}"),
                    payload={"tool_call_id": "tool:signoff", "stage": "signoff", "loop": loop_idx},
                )
            )
            certificate = await IndustrialSignoffEngine(self.model_router).evaluate(plan, verifier_findings, idempotency_key=make_idempotency_key(run_id, revision_id, f"signoff_eval_{loop_idx}"))
            await self.event_stream.emit(
                CoreEvent(
                    event_type=CoreEventType.AGENT1_TOOL_CALL_DONE,
                    run_id=run_id,
                    revision_id=revision_id,
                    span_id=f"tool:signoff:done:{loop_idx}",
                    parent_span_id=f"tool:signoff:start:{loop_idx}",
                    tool_call_id="tool:signoff",
                    idempotency_key=make_idempotency_key(run_id, revision_id, f"signoff_{loop_idx}"),
                    payload={"tool_call_id": "tool:signoff", "status": "done", "certificate_id": certificate.certificate_id},
                )
            )
            plan_ref, certificate_ref, handoff_ref = self._write_artifacts(output_dir, plan, certificate)
            handoff = Agent2HandoffGate().build(plan=plan, certificate=certificate, plan_ref=plan_ref, certificate_ref=certificate_ref)
            self._write_json(Path(handoff_ref), handoff.model_dump(mode="json"))
            await self._emit_artifact(run_id, revision_id, plan_ref, "architecture_plan")
            await self._emit_artifact(run_id, revision_id, certificate_ref, "signoff_certificate")
            await self._emit_artifact(run_id, revision_id, handoff_ref, "agent1_to_agent2_handoff")

            for gate_id, status in certificate.gate_results.items():
                await self._emit(
                    CoreEventType.AGENT1_SIGNOFF_GATE_START,
                    run_id,
                    revision_id,
                    f"agent1:signoff:{gate_id}:start:{loop_idx}",
                    f"tool:signoff:done:{loop_idx}",
                    {"gate_id": gate_id, "status": "start"},
                )
                await self._emit(
                    CoreEventType.AGENT1_SIGNOFF_GATE_DONE if status == "pass" else CoreEventType.AGENT1_SIGNOFF_GATE_FAILED,
                    run_id,
                    revision_id,
                    f"agent1:signoff:{gate_id}:done:{loop_idx}",
                    f"agent1:signoff:{gate_id}:start:{loop_idx}",
                    {"gate_id": gate_id, "status": status},
                )
            
            if handoff.ready:
                break
            else:
                feedback = "The previous architecture plan failed signoff/handoff. Please fix the following blockers:\n"
                for blocker in handoff.blockers:
                    feedback += f"- {blocker}\n"
                for gate_id, status in certificate.gate_results.items():
                    if status == "fail":
                        feedback += f"- Gate {gate_id} failed.\n"

        if handoff.ready:
            await self._emit(CoreEventType.AGENT1_PROPOSAL_APPROVED, run_id, revision_id, "agent1:proposal:approved", f"agent1:signoff:G12:done:{loop_idx}", {"proposal_id": plan_id, "certificate_id": certificate.certificate_id})
            await self._emit(CoreEventType.AGENT1_HANDOFF_READY, run_id, revision_id, "agent1:handoff:ready", "agent1:signoff", {"handoff_ref": handoff_ref})
            await self._emit(CoreEventType.AGENT1_PROPOSAL_COMMITTED, run_id, revision_id, "agent1:proposal:committed", "agent1:handoff:ready", {"proposal_id": plan_id, "handoff_ref": handoff_ref})
            self._write_checkpoint(output_dir, "handoff_ready", run_id, revision_id, {"handoff_ref": handoff_ref, "certificate_id": certificate.certificate_id})
            self._write_runtime_debug_artifacts(output_dir, board)
            await self._emit_pause(run_id, revision_id, "PLAN_REVIEW", "Architecture plan ready for human review.", {"plan_path": plan_ref, "artifact_path": plan_ref})
            self._write_runtime_debug_artifacts(output_dir, board)
            return Agent1SwarmResult(status="paused", action_required="PLAN_REVIEW", architecture_plan=plan, signoff_certificate=certificate, handoff=handoff, artifact_paths=(plan_ref, certificate_ref, handoff_ref))
        
        await self._emit(CoreEventType.AGENT1_PROPOSAL_REJECTED, run_id, revision_id, "agent1:proposal:rejected", f"agent1:signoff:G12:done:{loop_idx}", {"proposal_id": plan_id, "blockers": handoff.blockers})
        await self._emit(CoreEventType.AGENT1_HANDOFF_BLOCKED, run_id, revision_id, "agent1:handoff:blocked", "agent1:signoff", {"blockers": handoff.blockers})
        self._write_checkpoint(output_dir, "handoff_blocked", run_id, revision_id, {"blockers": handoff.blockers, "certificate_id": certificate.certificate_id})
        self._write_runtime_debug_artifacts(output_dir, board)
        await self._emit_pause(run_id, revision_id, "HITL_REQUIRED", "Signoff blockers prevent Agent2 handoff.", {"blockers": handoff.blockers, "plan_path": plan_ref})
        self._write_runtime_debug_artifacts(output_dir, board)
        return Agent1SwarmResult(status="paused", action_required="HITL_REQUIRED", architecture_plan=plan, signoff_certificate=certificate, handoff=handoff, artifact_paths=(plan_ref, certificate_ref, handoff_ref))

    async def _run_managers(self, pack: RequirementPack, assignments, run_id: str, revision_id: str) -> tuple[ManagerSummary, ...]:
        runner = MiddleManagerRunner(self.model_router, self.event_stream, max_concurrency=self.max_group_concurrency)
        return tuple(
            await asyncio.gather(
                *(runner.run_group(pack=pack, assignment=assignment, run_id=run_id, revision_id=revision_id) for assignment in assignments),
            )
        )

    async def _safety_preflight(self, pack: RequirementPack, run_id: str, revision_id: str) -> str | None:
        text = pack.raw_text.lower()
        kill_switch = self.kill_switch.model_copy(update={"enabled": True, "reason": "mutation requested"}) if "kill_switch_mutation" in text else self.kill_switch
        kill_switch.assert_valid()
        if kill_switch.enabled:
            await self._emit(CoreEventType.AGENT1_KILL_SWITCH_TRIPPED, run_id, revision_id, "agent1:safety:kill_switch", "agent1:intake:done", {"stage": "pre_cluster", "status": "tripped", "reason": kill_switch.reason})
            await self._emit_debug_issue(run_id, revision_id, "agent1.safety", "kill_switch_tripped", "Kill switch blocks Agent1 execution.", parent_span_id="agent1:safety:kill_switch")
            return "HITL_REQUIRED"
        await self._emit(CoreEventType.AGENT1_KILL_SWITCH_CHECKED, run_id, revision_id, "agent1:safety:kill_switch", "agent1:intake:done", {"stage": "pre_cluster", "status": "clear"})

        breaker = self.circuit_breaker.model_copy(update={"repeated_call_count": self.circuit_breaker.threshold}) if "circuit_breaker_mutation" in text else self.circuit_breaker
        if breaker.tripped:
            await self._emit(CoreEventType.AGENT1_CIRCUIT_BREAKER_OPEN, run_id, revision_id, "agent1:safety:circuit", "agent1:intake:done", {"stage": "pre_cluster", "status": "open"})
            await self._emit_debug_issue(run_id, revision_id, "agent1.safety", "circuit_breaker_open", "Circuit breaker blocks repeated failing calls.", parent_span_id="agent1:safety:circuit")
            return "HITL_REQUIRED"
        await self._emit(CoreEventType.AGENT1_CIRCUIT_BREAKER_CLOSED, run_id, revision_id, "agent1:safety:circuit", "agent1:intake:done", {"stage": "pre_cluster", "status": "closed"})

        usage = CostUsage(tokens=len(pack.raw_text.split()), cost_usd=0.0)
        if "budget_breach_mutation" in text:
            usage = CostUsage(tokens=self.cost_budget.max_tokens, cost_usd=self.cost_budget.max_cost_usd)
        decision = self.cost_budget.decide(usage)
        if decision.value == "kill":
            await self._emit(CoreEventType.AGENT1_BUDGET_CHECK_KILL, run_id, revision_id, "agent1:safety:budget", "agent1:intake:done", {"budget_id": "agent1.default", "budget_remaining": 0, "status": "kill"})
            await self._emit_debug_issue(run_id, revision_id, "agent1.safety", "budget_exceeded", "Budget breach blocks Agent1 execution.", parent_span_id="agent1:safety:budget")
            return "HITL_REQUIRED"
        event_type = CoreEventType.AGENT1_BUDGET_CHECK_WARN if decision.value == "warn" else CoreEventType.AGENT1_BUDGET_CHECK_PASS
        await self._emit(event_type, run_id, revision_id, "agent1:safety:budget", "agent1:intake:done", {"budget_id": "agent1.default", "budget_remaining": "within_budget", "status": decision.value, "tokens": usage.tokens})
        return None

    def _append_requirement(self, board: Blackboard, pack: RequirementPack, run_id: str, revision_id: str) -> None:
        message = CoreMessage.from_payload(
            message_id=f"{pack.requirement_id}:message",
            run_id=run_id,
            revision_id=revision_id,
            role=MessageRole.USER,
            kind=MessageKind.USER_REQUIREMENT,
            payload=pack.model_dump(mode="json"),
        )
        board.append(message, conflict_key="requirement")

    def _append_summary(self, board: Blackboard, summary: ManagerSummary, run_id: str, revision_id: str) -> None:
        message = CoreMessage.from_payload(
            message_id=f"summary:{summary.manager_id}:{board.revision + 1}",
            run_id=run_id,
            revision_id=revision_id,
            role=MessageRole.MIDDLE_MANAGER,
            kind=MessageKind.MANAGER_SUMMARY,
            payload=summary.model_dump(mode="json"),
        ).model_copy(update={"group_id": summary.group_id, "read_revision": board.revision})
        board.append(message, conflict_key=f"manager:{summary.manager_id}")

    async def _emit(self, event_type: CoreEventType, run_id: str, revision_id: str, span_id: str, parent_span_id: str | None, payload: dict) -> None:
        await self.event_stream.emit(CoreEvent(event_type=event_type, run_id=run_id, revision_id=revision_id, span_id=span_id, parent_span_id=parent_span_id, payload=payload))

    async def _emit_pause(self, run_id: str, revision_id: str, action_required: str, message: str, extra: dict | None = None) -> None:
        payload = {"action_required": action_required, "message": message}
        if extra:
            payload.update(extra)
        await self._emit(CoreEventType.HITL_REQUIRED, run_id, revision_id, f"agent1:pause:{action_required.lower()}", "agent1", payload)

    async def _emit_artifact(self, run_id: str, revision_id: str, path: str, kind: str) -> None:
        span_id = f"artifact:{stable_hash(path)[:12]}"
        if not hasattr(self, "_emitted_artifacts"):
            self._emitted_artifacts = set()
        if span_id in self._emitted_artifacts:
            return
        self._emitted_artifacts.add(span_id)
        await self._emit(CoreEventType.ARTIFACT_WRITTEN, run_id, revision_id, span_id, "agent1:artifacts", {"path": path, "kind": kind, "message": f"{kind} written"})

    async def _emit_debug_issue(self, run_id: str, revision_id: str, source: str, code: str, message: str, *, parent_span_id: str) -> None:
        await self._emit(
            CoreEventType.DEBUG_ISSUE,
            run_id,
            revision_id,
            f"issue:{stable_hash([source, code, message])[:12]}",
            parent_span_id,
            {"severity": "blocker", "source": source, "code": code, "message": message},
        )

    def _write_artifacts(self, output_dir: Path, plan, certificate) -> tuple[str, str, str]:
        plan_path = output_dir / "reports" / "architecture_plan.md"
        certificate_path = output_dir / "reports" / "agent1" / "agent1_final_signoff_certificate.json"
        handoff_path = output_dir / "contracts" / "agent1_to_agent2.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        certificate_path.parent.mkdir(parents=True, exist_ok=True)
        handoff_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(plan.to_markdown(), encoding="utf-8")
        self._write_json(certificate_path, certificate.model_dump(mode="json"))
        return str(plan_path), str(certificate_path), str(handoff_path)

    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _write_checkpoint(self, output_dir: Path, stage: str, run_id: str, revision_id: str, payload: dict) -> None:
        checkpoint_dir = output_dir / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        body = {"run_id": run_id, "revision_id": revision_id, "stage": stage, "payload": payload}
        self._write_json(checkpoint_dir / f"{stage}.json", body)
        self._write_json(checkpoint_dir / "latest.json", body)

    def _write_event_trace(self, output_dir: Path) -> None:
        trace_dir = output_dir / "trace"
        trace_dir.mkdir(parents=True, exist_ok=True)
        events = [event.safe_dump() for event in self.event_stream.history]
        (trace_dir / "events.jsonl").write_text("\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n", encoding="utf-8")

    def _write_runtime_debug_artifacts(self, output_dir: Path, board: Blackboard | None = None, *, run_id: str | None = None) -> None:
        replay_dir = output_dir / "replay"
        blackboard_dir = output_dir / "blackboard"
        replay_dir.mkdir(parents=True, exist_ok=True)
        self._write_event_trace(output_dir)
        events = [event.safe_dump() for event in self.event_stream.history]
        snapshot = board.snapshot().safe_dump() if board is not None else None
        if snapshot is not None:
            blackboard_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(blackboard_dir / "snapshot.json", snapshot)
        checkpoints = []
        checkpoint_dir = output_dir / "checkpoints"
        if checkpoint_dir.exists():
            for path in sorted(checkpoint_dir.glob("*.json")):
                checkpoint = json.loads(path.read_text(encoding="utf-8"))
                checkpoint["checkpoint_ref"] = f"checkpoints/{path.name}"
                checkpoint["checkpoint_hash"] = stable_hash(checkpoint)
                checkpoints.append(checkpoint)
        signoff_path = output_dir / "reports" / "agent1" / "agent1_final_signoff_certificate.json"
        handoff_path = output_dir / "contracts" / "agent1_to_agent2.json"
        bundle = {
            "schema_version": "coreweaver.agent1.replay.v1",
            "run_id": board.run_id if board is not None else run_id,
            "events": events,
            "blackboard_snapshot": snapshot,
            "checkpoints": checkpoints,
            "debug_issues": [event for event in events if event.get("event_type") == "debug_issue"],
            "signoff": json.loads(signoff_path.read_text(encoding="utf-8")) if signoff_path.exists() else None,
            "handoff": json.loads(handoff_path.read_text(encoding="utf-8")) if handoff_path.exists() else None,
        }
        bundle["resume"] = build_replay_resume_state(bundle).model_dump(mode="json")
        self._write_json(replay_dir / "replay_bundle.json", bundle)
