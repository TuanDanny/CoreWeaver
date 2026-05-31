from __future__ import annotations

from coreweaver.framework_types import StrictCoreModel


class CircuitBreakerState(StrictCoreModel):
    failure_count: int = 0
    timeout_count: int = 0
    repeated_call_count: int = 0
    threshold: int = 3

    @property
    def tripped(self) -> bool:
        return max(self.failure_count, self.timeout_count, self.repeated_call_count) >= self.threshold
