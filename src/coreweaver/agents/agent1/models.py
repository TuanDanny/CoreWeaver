from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from coreweaver.framework_types import StrictCoreModel, assert_no_secret, stable_hash, utc_now, validate_iso8601_text


class RequirementClassification(str, Enum):
    NON_DESIGN_CONVERSATION = "non_design_conversation"
    AMBIGUOUS_CHIP_IDEA = "ambiguous_chip_idea"
    DESIGN_READY_REQUIREMENT = "design_ready_requirement"


class RequirementPack(StrictCoreModel):
    requirement_id: str
    raw_text: str
    project_name: str
    planning_mode: str
    classification: RequirementClassification
    extracted: dict[str, Any] = Field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    attachment_refs: tuple[str, ...] = ()
    created_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _no_secret(self) -> "RequirementPack":
        assert_no_secret(self.model_dump(mode="json"), "RequirementPack")
        return self


class ClarificationQuestion(StrictCoreModel):
    question_id: str
    missing_fields: tuple[str, ...]
    question: str
    reason: str


class ExpertTask(StrictCoreModel):
    task_id: str
    group_id: str
    manager_id: str
    expert_id: str
    specialty: str
    prompt: str
    input_hash: str
    idempotency_key: str


class ExpertResult(StrictCoreModel):
    task_id: str
    group_id: str
    manager_id: str
    expert_id: str
    specialty: str
    status: str
    findings: tuple[str, ...]
    risks: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    model_call_id: str | None = None
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    output_hash: str


class ManagerSummary(StrictCoreModel):
    group_id: str
    manager_id: str
    accepted_results: tuple[ExpertResult, ...]
    failed_expert_ids: tuple[str, ...] = ()
    summary: str
    output_hash: str


class ChallengeSeverity(str, Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    BLOCKER = "blocker"


class Challenge(StrictCoreModel):
    challenge_id: str
    source_group_id: str
    target_group_id: str
    severity: ChallengeSeverity
    message: str
    resolved: bool = False


class PrincipalReview(StrictCoreModel):
    approved: bool
    iteration: int
    unresolved_challenges: tuple[Challenge, ...] = ()
    action_required: str | None = None


class RegisterEntry(StrictCoreModel):
    name: str
    offset: str
    access: str
    reset: str
    description: str


class ArchitecturePlan(StrictCoreModel):
    title: str
    requirement_summary: str
    assumptions: tuple[str, ...]
    open_questions: tuple[str, ...]
    top_level_blocks: tuple[str, ...]
    interfaces: tuple[str, ...]
    memory_map: tuple[str, ...]
    registers: tuple[RegisterEntry, ...]
    security_model: tuple[str, ...]
    datapath_control: tuple[str, ...]
    reset_clock_cdc: tuple[str, ...]
    interrupt_error_policy: tuple[str, ...]
    formal_intent: tuple[str, ...]
    dv_intent: tuple[str, ...]
    ppa_risks: tuple[str, ...]
    agent2_handoff_contract: tuple[str, ...]
    provenance_refs: tuple[str, ...]

    def to_markdown(self) -> str:
        lines = [f"# {self.title}", "", "## Requirement Summary", self.requirement_summary, ""]
        sections: tuple[tuple[str, tuple[str, ...]], ...] = (
            ("Assumptions", self.assumptions),
            ("Open Questions", self.open_questions),
            ("Top-Level Block Diagram", self.top_level_blocks),
            ("Interface Architecture", self.interfaces),
            ("Memory Map", self.memory_map),
            ("Register Policy", tuple(f"{r.offset} | {r.name} | {r.access} | reset {r.reset} | {r.description}" for r in self.registers)),
            ("Security Model", self.security_model),
            ("Datapath / Control Plan", self.datapath_control),
            ("Reset / Clock / CDC / RDC", self.reset_clock_cdc),
            ("Interrupt / Error Policy", self.interrupt_error_policy),
            ("Formal-First Verification Intent", self.formal_intent),
            ("DV / cocotb Intent", self.dv_intent),
            ("PPA Risks", self.ppa_risks),
            ("Agent2 Handoff Contract", self.agent2_handoff_contract),
            ("Provenance", self.provenance_refs),
        )
        for title, items in sections:
            lines.extend([f"## {title}"])
            lines.extend(f"- {item}" for item in (items or ("TBD",)))
            lines.append("")
        return "\n".join(lines)


class SignoffFinding(StrictCoreModel):
    gate_id: str
    severity: ChallengeSeverity
    code: str
    message: str
    evidence_refs: tuple[str, ...] = ()
    waiver_allowed: bool = False


class SignoffCertificate(StrictCoreModel):
    certificate_id: str
    passed: bool
    findings: tuple[SignoffFinding, ...]
    gate_results: dict[str, str]
    created_at: str = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def _valid_created_at(cls, value: str) -> str:
        return validate_iso8601_text(value)


class Agent1ToAgent2Handoff(StrictCoreModel):
    handoff_id: str
    ready: bool
    architecture_plan_ref: str
    signoff_certificate_ref: str
    locked_interfaces: tuple[str, ...]
    locked_registers: tuple[RegisterEntry, ...]
    blockers: tuple[str, ...] = ()
    trace_refs: tuple[str, ...] = ()


class Agent1SwarmResult(StrictCoreModel):
    status: str
    action_required: str | None = None
    architecture_plan: ArchitecturePlan | None = None
    signoff_certificate: SignoffCertificate | None = None
    handoff: Agent1ToAgent2Handoff | None = None
    artifact_paths: tuple[str, ...] = ()


def content_id(prefix: str, value: object) -> str:
    return f"{prefix}:{stable_hash(value)[:16]}"
