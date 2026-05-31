from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

AGENT1_PAUSE_TYPES = (
    "CORE_SKELETON_READY",
    "REQUIREMENT_CLARIFICATION",
    "PLAN_REVIEW",
    "HITL_REQUIRED",
    "CONFLICT_REQUIRED",
    "NON_DESIGN_CONVERSATION",
    "HUMAN_REVIEW",
)

ALLOWED_AGENT1_EVENT_TYPES = (
    "agent_action",
    "agent_handoff",
    "artifact",
    "debug_issue",
    "done",
    "error",
    "metric",
    "pause",
    "stage",
    "agent1_topology_loaded",
    "agent1_cluster_assignment",
    "agent1_group_session_start",
    "agent1_group_session_done",
    "agent1_group_session_failed",
    "agent1_group_retry",
    "agent1_cross_group_challenge",
    "agent1_principal_group_review",
    "agent1_clarification_question",
    "agent1_clarification_answer",
    "agent1_council_mode_selected",
    "intake_started",
    "intake_done",
    "intake_failed",
    "classification_done",
    "agent1_leaf_expert_start",
    "agent1_leaf_expert_done",
    "agent1_leaf_expert_failed",
    "agent1_leaf_expert_retry",
    "agent1_plan_dag_created",
    "agent1_plan_dag_validated",
    "agent1_plan_dag_failed",
    "agent1_plan_node_start",
    "agent1_plan_node_done",
    "agent1_plan_node_failed",
    "agent1_plan_node_replanned",
    "agent1_model_route_selected",
    "agent1_model_route_escalated",
    "agent1_tool_call_start",
    "agent1_tool_call_done",
    "agent1_tool_call_failed",
    "agent1_tool_call_retry",
    "agent1_budget_check_pass",
    "agent1_budget_check_warn",
    "agent1_budget_check_throttle",
    "agent1_budget_check_kill",
    "agent1_kill_switch_checked",
    "agent1_kill_switch_tripped",
    "agent1_circuit_breaker_closed",
    "agent1_circuit_breaker_open",
    "agent1_circuit_breaker_half_open",
    "agent1_canary_touched",
    "agent1_proposal_created",
    "agent1_proposal_approved",
    "agent1_proposal_rejected",
    "agent1_proposal_committed",
    "agent1_rollback_point_created",
    "agent1_rollback_point_restored",
    "agent1_blackboard_write",
    "agent1_signoff_gate_start",
    "agent1_signoff_gate_done",
    "agent1_signoff_gate_failed",
    "agent1_handoff_ready",
    "agent1_handoff_blocked",
)

REQUIRED_AGENT1_ARTIFACTS = (
    "reports/architecture_plan.md",
    "contracts/agent1_to_agent2.json",
    "reports/agent1/agent1_final_signoff_certificate.json",
)

class ContractValidationError(ValueError):
    """Raised when Studio/CoreWeaver contract data is malformed."""

@dataclass(frozen=True)
class Agent1StartRequest:
    requirement: str
    project_name: str
    planning_mode: str
    run_id: str
    thread_id: str
    output_dir: Path
    checkpoint_db: str = ""
    attachment_manifest: str = ""
    attachment_context: str = ""

    def to_payload(self) -> dict[str, str]:
        return {
            "requirement": self.requirement,
            "project_name": self.project_name,
            "planning_mode": self.planning_mode,
            "run_id": self.run_id,
            "thread_id": self.thread_id,
            "output_dir": str(self.output_dir),
            "checkpoint_db": self.checkpoint_db,
            "attachment_manifest": self.attachment_manifest,
            "attachment_context": self.attachment_context,
        }

def normalize_agent1_start_payload(payload: dict[str, Any]) -> Agent1StartRequest:
    requirement = str(payload.get("requirement") or "").strip()
    project_name = str(payload.get("project_name") or "swarm_soc").strip() or "swarm_soc"
    planning_mode = str(payload.get("planning_mode") or "normal").strip() or "normal"
    run_id = str(payload.get("run_id") or "").strip()
    thread_id = str(payload.get("thread_id") or "").strip()
    output_dir_text = str(payload.get("output_dir") or "").strip()
    output_dir = Path(output_dir_text).expanduser()
    if not requirement:
        raise ContractValidationError("Agent1 start payload requires requirement")
    if planning_mode not in {"normal", "deep_planning"}:
        raise ContractValidationError("Agent1 start payload requires planning_mode normal or deep_planning")
    if not run_id:
        raise ContractValidationError("Agent1 start payload requires run_id")
    if not thread_id:
        raise ContractValidationError("Agent1 start payload requires thread_id")
    if not output_dir_text:
        raise ContractValidationError("Agent1 start payload requires output_dir")
    return Agent1StartRequest(
        requirement=requirement,
        project_name=project_name,
        planning_mode=planning_mode,
        run_id=run_id,
        thread_id=thread_id,
        output_dir=output_dir,
        checkpoint_db=str(payload.get("checkpoint_db") or payload.get("checkpointDb") or ""),
        attachment_manifest=str(payload.get("attachment_manifest") or ""),
        attachment_context=str(payload.get("attachment_context") or ""),
    )

def validate_agent1_studio_event(event: dict[str, Any]) -> None:
    event_type = str(event.get("type") or "")
    if event_type not in ALLOWED_AGENT1_EVENT_TYPES:
        raise ContractValidationError(f"Agent1 event type is not allowed: {event_type}")
    if event_type not in {"metric"} and not str(event.get("run_id") or ""):
        raise ContractValidationError("Agent1 event requires run_id")
    if event_type == "agent_action" and str(event.get("agent") or "") != "agent1":
        raise ContractValidationError("agent_action from Agent1 must set agent=agent1")
    if event_type == "pause":
        action_required = str(event.get("action_required") or "")
        if action_required not in AGENT1_PAUSE_TYPES:
            raise ContractValidationError(f"Agent1 pause type is not allowed: {action_required}")
        if not str(event.get("message") or ""):
            raise ContractValidationError("Agent1 pause requires message")
    if event_type == "artifact" and not str(event.get("path") or ""):
        raise ContractValidationError("Agent1 artifact event requires path")
    if event_type == "debug_issue":
        for field in ("severity", "source", "code", "message"):
            if not str(event.get(field) or ""):
                raise ContractValidationError(f"debug_issue requires {field}")
