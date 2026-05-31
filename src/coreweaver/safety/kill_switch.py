from __future__ import annotations

from coreweaver.framework_types import StrictCoreModel


class KillSwitchState(StrictCoreModel):
    enabled: bool = False
    reason: str = ""
    controlled_by_agent: bool = False

    def assert_valid(self) -> None:
        if self.controlled_by_agent:
            raise ValueError("kill switch cannot be controlled by agent reasoning")
