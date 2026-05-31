from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator, model_validator

from coreweaver.framework_types import StrictCoreModel, assert_no_secret, stable_hash, utc_now, validate_id_text, validate_iso8601_text, validate_optional_id, validate_sha256_text

from .blocks import EvidenceRef, MessageBlock

IdempotencyKey = str


class MessageRole(str, Enum):
    USER = "user"
    PRINCIPAL = "principal"
    MIDDLE_MANAGER = "middle_manager"
    LEAF_EXPERT = "leaf_expert"
    TOOL = "tool"
    GATE = "gate"
    SYSTEM = "system"


class MessageKind(str, Enum):
    USER_REQUIREMENT = "user_requirement"
    CLARIFICATION_QUESTION = "clarification_question"
    CLARIFICATION_ANSWER = "clarification_answer"
    EXPERT_TASK = "expert_task"
    EXPERT_RESULT = "expert_result"
    MANAGER_SUMMARY = "manager_summary"
    CHALLENGE = "challenge"
    CHALLENGE_RESPONSE = "challenge_response"
    PRINCIPAL_DECISION = "principal_decision"
    SIGNOFF_FINDING = "signoff_finding"
    HANDOFF_CANDIDATE = "handoff_candidate"
    BLACKBOARD_CONFLICT = "blackboard_conflict"


REPLAYABLE_KINDS = {
    MessageKind.EXPERT_TASK,
    MessageKind.EXPERT_RESULT,
    MessageKind.HANDOFF_CANDIDATE,
    MessageKind.SIGNOFF_FINDING,
}


class CoreMessage(StrictCoreModel):
    message_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    run_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    revision_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    role: MessageRole
    kind: MessageKind
    blocks: tuple[MessageBlock, ...]
    timestamp: str = Field(default_factory=utc_now)
    parent_message_id: str | None = None
    group_id: str | None = None
    blackboard_snapshot_id: str | None = None
    read_revision: int | None = None
    evidence_refs: tuple[EvidenceRef, ...] = ()
    input_hash: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    output_hash: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    replayable: bool = False
    idempotency_key: IdempotencyKey | None = None

    @field_validator("message_id", "run_id", "revision_id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        return validate_id_text(value, "id")

    @field_validator("parent_message_id", "group_id", "blackboard_snapshot_id")
    @classmethod
    def _valid_optional_id(cls, value: str | None) -> str | None:
        return validate_optional_id(value, "optional_id")

    @field_validator("timestamp")
    @classmethod
    def _valid_timestamp(cls, value: str) -> str:
        return validate_iso8601_text(value)

    @field_validator("input_hash", "output_hash")
    @classmethod
    def _valid_hash(cls, value: str) -> str:
        return validate_sha256_text(value)

    @model_validator(mode="after")
    def _message_contract(self) -> "CoreMessage":
        if not self.blocks:
            raise ValueError("CoreMessage requires at least one block")
        if (self.replayable or self.kind in REPLAYABLE_KINDS) and not self.idempotency_key:
            raise ValueError("replayable CoreMessage requires idempotency_key")
        assert_no_secret(self.model_dump(mode="json"), "CoreMessage")
        return self

    @classmethod
    def from_payload(
        cls,
        *,
        message_id: str,
        run_id: str,
        revision_id: str,
        role: MessageRole,
        kind: MessageKind,
        payload: object,
        parent_message_id: str | None = None,
        replayable: bool = False,
        idempotency_key: str | None = None,
    ) -> "CoreMessage":
        content_hash = stable_hash(payload)
        return cls(
            message_id=message_id,
            run_id=run_id,
            revision_id=revision_id,
            role=role,
            kind=kind,
            blocks=(MessageBlock(block_id=f"{message_id}:body", kind="json", content=payload),),
            parent_message_id=parent_message_id,
            input_hash=content_hash,
            output_hash=content_hash,
            replayable=replayable,
            idempotency_key=idempotency_key,
        )
