from __future__ import annotations

from coreweaver.framework_types import StrictCoreModel


class CanaryFinding(StrictCoreModel):
    token_id: str
    touched: bool
    quarantine_required: bool

    @classmethod
    def from_touch(cls, token_id: str, touched: bool) -> "CanaryFinding":
        return cls(token_id=token_id, touched=touched, quarantine_required=touched)
