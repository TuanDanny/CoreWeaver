from __future__ import annotations

from pydantic import Field, model_validator

from coreweaver.framework_types import StrictCoreModel, assert_no_secret


class ContextSummary(StrictCoreModel):
    task_overview: str
    decisions: tuple[str, ...] = ()
    open_risks: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    unresolved_challenges: tuple[str, ...] = ()
    signoff_blockers: tuple[str, ...] = ()
    pending_hitl: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    pending_idempotency_keys: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _no_secret_in_compressed_context(self) -> "ContextSummary":
        assert_no_secret(self.model_dump(mode="json"), "ContextSummary")
        return self


def invariant_check_context_summary(summary: ContextSummary) -> tuple[str, ...]:
    issues: list[str] = []
    if summary.unresolved_challenges and not summary.next_actions:
        issues.append("unresolved_challenges_need_next_actions")
    if summary.signoff_blockers and not summary.pending_hitl:
        issues.append("signoff_blockers_need_pending_hitl")
    if "pending replayable work" in summary.open_risks and not summary.pending_idempotency_keys:
        issues.append("pending_replayable_work_needs_idempotency_keys")
    return tuple(issues)
