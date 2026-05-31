from __future__ import annotations

from pydantic import Field

from coreweaver.framework_types import StrictCoreModel, utc_now


class GroupSession(StrictCoreModel):
    group_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    manager_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    leaf_ids: tuple[str, ...]
    iteration: int = 0
    started_at: str = Field(default_factory=utc_now)


class GroupSessionResult(StrictCoreModel):
    group_id: str
    status: str
    accepted_message_ids: tuple[str, ...] = ()
    rejected_message_ids: tuple[str, ...] = ()
    challenge_ids: tuple[str, ...] = ()
