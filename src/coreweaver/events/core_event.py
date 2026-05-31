from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from coreweaver.framework_types import StrictCoreModel, assert_no_secret, ensure_jsonable, utc_now, validate_id_text, validate_iso8601_text, validate_optional_id


class CoreEventType(str, Enum):
    RUN_START = "run_start"
    RUN_END = "run_end"
    AGENT_LOOP_START = "agent_loop_start"
    AGENT_LOOP_TURN = "agent_loop_turn"
    AGENT_LOOP_EXCEED_MAX_ITERS = "agent_loop_exceed_max_iters"
    MESSAGE_PUBLISHED = "message_published"
    BLACKBOARD_APPEND = "blackboard_append"
    BLACKBOARD_CONFLICT_DETECTED = "blackboard_conflict_detected"
    MODEL_CALL_START = "model_call_start"
    MODEL_CALL_END = "model_call_end"
    MODEL_CALL_FAILED = "model_call_failed"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    TOOL_CALL_FAILED = "tool_call_failed"
    GROUP_SESSION_START = "group_session_start"
    GROUP_SESSION_DONE = "group_session_done"
    GROUP_SESSION_FAILED = "group_session_failed"
    HITL_REQUIRED = "hitl_required"
    SIGNOFF_GATE_START = "signoff_gate_start"
    SIGNOFF_GATE_DONE = "signoff_gate_done"
    SIGNOFF_GATE_FAILED = "signoff_gate_failed"
    ARTIFACT_WRITTEN = "artifact_written"
    HANDOFF_BLOCKED = "handoff_blocked"
    DEBUG_ISSUE = "debug_issue"
    INTAKE_STARTED = "intake_started"
    INTAKE_DONE = "intake_done"
    INTAKE_FAILED = "intake_failed"
    CLASSIFICATION_DONE = "classification_done"
    AGENT1_CLARIFICATION_QUESTION = "agent1_clarification_question"
    AGENT1_CLARIFICATION_ANSWER = "agent1_clarification_answer"
    AGENT1_COUNCIL_MODE_SELECTED = "agent1_council_mode_selected"
    AGENT1_TOPOLOGY_LOADED = "agent1_topology_loaded"
    AGENT1_CLUSTER_ASSIGNMENT = "agent1_cluster_assignment"
    AGENT1_GROUP_SESSION_START = "agent1_group_session_start"
    AGENT1_GROUP_SESSION_DONE = "agent1_group_session_done"
    AGENT1_GROUP_SESSION_FAILED = "agent1_group_session_failed"
    AGENT1_GROUP_RETRY = "agent1_group_retry"
    AGENT1_LEAF_EXPERT_START = "agent1_leaf_expert_start"
    AGENT1_LEAF_EXPERT_DONE = "agent1_leaf_expert_done"
    AGENT1_LEAF_EXPERT_FAILED = "agent1_leaf_expert_failed"
    AGENT1_LEAF_EXPERT_RETRY = "agent1_leaf_expert_retry"
    AGENT1_PLAN_DAG_CREATED = "agent1_plan_dag_created"
    AGENT1_PLAN_DAG_VALIDATED = "agent1_plan_dag_validated"
    AGENT1_PLAN_DAG_FAILED = "agent1_plan_dag_failed"
    AGENT1_PLAN_NODE_START = "agent1_plan_node_start"
    AGENT1_PLAN_NODE_DONE = "agent1_plan_node_done"
    AGENT1_PLAN_NODE_FAILED = "agent1_plan_node_failed"
    AGENT1_PLAN_NODE_REPLANNED = "agent1_plan_node_replanned"
    AGENT1_MODEL_ROUTE_SELECTED = "agent1_model_route_selected"
    AGENT1_MODEL_ROUTE_ESCALATED = "agent1_model_route_escalated"
    AGENT1_TOOL_CALL_START = "agent1_tool_call_start"
    AGENT1_TOOL_CALL_DONE = "agent1_tool_call_done"
    AGENT1_TOOL_CALL_FAILED = "agent1_tool_call_failed"
    AGENT1_TOOL_CALL_RETRY = "agent1_tool_call_retry"
    AGENT1_BUDGET_CHECK_PASS = "agent1_budget_check_pass"
    AGENT1_BUDGET_CHECK_WARN = "agent1_budget_check_warn"
    AGENT1_BUDGET_CHECK_THROTTLE = "agent1_budget_check_throttle"
    AGENT1_BUDGET_CHECK_KILL = "agent1_budget_check_kill"
    AGENT1_KILL_SWITCH_CHECKED = "agent1_kill_switch_checked"
    AGENT1_KILL_SWITCH_TRIPPED = "agent1_kill_switch_tripped"
    AGENT1_CIRCUIT_BREAKER_CLOSED = "agent1_circuit_breaker_closed"
    AGENT1_CIRCUIT_BREAKER_OPEN = "agent1_circuit_breaker_open"
    AGENT1_CIRCUIT_BREAKER_HALF_OPEN = "agent1_circuit_breaker_half_open"
    AGENT1_CANARY_TOUCHED = "agent1_canary_touched"
    AGENT1_PROPOSAL_CREATED = "agent1_proposal_created"
    AGENT1_PROPOSAL_APPROVED = "agent1_proposal_approved"
    AGENT1_PROPOSAL_REJECTED = "agent1_proposal_rejected"
    AGENT1_PROPOSAL_COMMITTED = "agent1_proposal_committed"
    AGENT1_ROLLBACK_POINT_CREATED = "agent1_rollback_point_created"
    AGENT1_ROLLBACK_POINT_RESTORED = "agent1_rollback_point_restored"
    AGENT1_BLACKBOARD_WRITE = "agent1_blackboard_write"
    AGENT1_CROSS_GROUP_CHALLENGE = "agent1_cross_group_challenge"
    AGENT1_PRINCIPAL_GROUP_REVIEW = "agent1_principal_group_review"
    AGENT1_SIGNOFF_GATE_START = "agent1_signoff_gate_start"
    AGENT1_SIGNOFF_GATE_DONE = "agent1_signoff_gate_done"
    AGENT1_SIGNOFF_GATE_FAILED = "agent1_signoff_gate_failed"
    AGENT1_HANDOFF_READY = "agent1_handoff_ready"
    AGENT1_HANDOFF_BLOCKED = "agent1_handoff_blocked"


ACTION_EVENTS = {
    CoreEventType.MODEL_CALL_START,
    CoreEventType.MODEL_CALL_END,
    CoreEventType.MODEL_CALL_FAILED,
    CoreEventType.TOOL_CALL_START,
    CoreEventType.TOOL_CALL_END,
    CoreEventType.TOOL_CALL_FAILED,
}


class CoreEvent(StrictCoreModel):
    event_type: CoreEventType
    run_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    revision_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    span_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    parent_span_id: str | None = None
    timestamp: str = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)
    model_call_id: str | None = None
    tool_call_id: str | None = None
    idempotency_key: str | None = None
    retry_count: int = 0
    timeout_ms: int | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None

    @field_validator("run_id", "revision_id", "span_id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        return validate_id_text(value, "id")

    @field_validator("parent_span_id", "model_call_id", "tool_call_id")
    @classmethod
    def _valid_optional_id(cls, value: str | None) -> str | None:
        return validate_optional_id(value, "optional_id")

    @field_validator("timestamp")
    @classmethod
    def _valid_timestamp(cls, value: str) -> str:
        return validate_iso8601_text(value)

    @field_validator("payload")
    @classmethod
    def _json_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        ensure_jsonable(value, "payload")
        assert_no_secret(value, "CoreEvent.payload")
        return value

    @model_validator(mode="after")
    def _event_contract(self) -> "CoreEvent":
        if self.event_type in ACTION_EVENTS and not self.idempotency_key:
            raise ValueError("model/tool action event requires idempotency_key")
        if self.retry_count < 0:
            raise ValueError("retry_count must be non-negative")
        return self
