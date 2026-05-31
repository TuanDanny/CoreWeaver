from __future__ import annotations

from coreweaver.framework_types import StrictCoreModel, utc_now


class ProposalCommitRecord(StrictCoreModel):
    proposal_id: str
    action: str
    risk: str
    approved: bool = False
    committed_at: str | None = None

    def commit(self) -> "ProposalCommitRecord":
        if not self.approved:
            raise PermissionError("risky action must be approved before commit")
        return self.model_copy(update={"committed_at": utc_now()})
