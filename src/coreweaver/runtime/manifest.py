from __future__ import annotations

from pydantic import Field

from coreweaver.framework_types import StrictCoreModel, utc_now


class RuntimeManifest(StrictCoreModel):
    run_id: str
    profile: str
    status: str
    policies: dict[str, object] = Field(default_factory=dict)
    budgets: dict[str, object] = Field(default_factory=dict)
    disabled_real_reasoning: bool = True
    active_agent: str = "agent1"
    created_at: str = Field(default_factory=utc_now)
