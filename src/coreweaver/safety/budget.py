from __future__ import annotations

from enum import Enum

from coreweaver.framework_types import StrictCoreModel


class BudgetDecision(str, Enum):
    ALLOW = "allow"
    WARN = "warn"
    THROTTLE = "throttle"
    HITL = "hitl"
    KILL = "kill"


class CostUsage(StrictCoreModel):
    tokens: int = 0
    cost_usd: float = 0.0


class CostBudget(StrictCoreModel):
    max_tokens: int
    max_cost_usd: float
    warn_ratio: float = 0.8

    def decide(self, usage: CostUsage) -> BudgetDecision:
        if usage.tokens >= self.max_tokens or usage.cost_usd >= self.max_cost_usd:
            return BudgetDecision.KILL
        if usage.tokens >= self.max_tokens * self.warn_ratio or usage.cost_usd >= self.max_cost_usd * self.warn_ratio:
            return BudgetDecision.WARN
        return BudgetDecision.ALLOW
