from __future__ import annotations

from enum import Enum
from typing import Awaitable, Callable

from pydantic import Field

from coreweaver.events import AsyncEventStream, CoreEvent, CoreEventType
from coreweaver.framework_types import StrictCoreModel, make_idempotency_key


class StopReason(str, Enum):
    FINISHED = "finished"
    CLARIFICATION_REQUIRED = "clarification_required"
    HITL_REQUIRED = "hitl_required"
    MAX_ITERS = "max_iters"
    MAX_COST = "max_cost"
    MAX_TOKENS = "max_tokens"
    CIRCUIT_BREAKER = "circuit_breaker"
    SIGNOFF_BLOCKER = "signoff_blocker"
    KILL_SWITCH = "kill_switch"
    FRAMEWORK_PLACEHOLDER_DONE = "framework_placeholder_done"


class AgentLoopConfig(StrictCoreModel):
    max_iters: int = 3
    max_cost_usd: float = 0.0
    max_tokens: int = 0
    run_profile: str = "local_skeleton"


class AgentLoopResult(StrictCoreModel):
    stop_reason: StopReason
    iterations: int
    action_required: str | None = None


StepFn = Callable[[int], Awaitable[StopReason | None]]


class AgentLoop:
    def __init__(self, *, event_stream: AsyncEventStream | None = None, config: AgentLoopConfig | None = None) -> None:
        self.event_stream = event_stream or AsyncEventStream()
        self.config = config or AgentLoopConfig()

    async def run(self, *, run_id: str, revision_id: str, step: StepFn | None = None) -> AgentLoopResult:
        await self.event_stream.emit(CoreEvent(event_type=CoreEventType.AGENT_LOOP_START, run_id=run_id, revision_id=revision_id, span_id="agent_loop", parent_span_id="root"))
        if self.config.run_profile in {"local_skeleton", "ci_no_llm"} and step is None:
            await self.event_stream.emit(CoreEvent(event_type=CoreEventType.HITL_REQUIRED, run_id=run_id, revision_id=revision_id, span_id="agent_loop:pause", parent_span_id="agent_loop", payload={"action_required": "CORE_SKELETON_READY", "message": "core framework skeleton ready"}))
            return AgentLoopResult(stop_reason=StopReason.FRAMEWORK_PLACEHOLDER_DONE, iterations=0, action_required="CORE_SKELETON_READY")
        for iteration in range(1, self.config.max_iters + 1):
            await self.event_stream.emit(CoreEvent(event_type=CoreEventType.AGENT_LOOP_TURN, run_id=run_id, revision_id=revision_id, span_id=f"agent_loop:{iteration}", parent_span_id="agent_loop", payload={"iteration": iteration}))
            if step:
                reason = await step(iteration)
                if reason:
                    return AgentLoopResult(stop_reason=reason, iterations=iteration)
        await self.event_stream.emit(CoreEvent(event_type=CoreEventType.AGENT_LOOP_EXCEED_MAX_ITERS, run_id=run_id, revision_id=revision_id, span_id="agent_loop:max_iters", parent_span_id="agent_loop", payload={"max_iters": self.config.max_iters, "idempotency_key": make_idempotency_key(run_id, revision_id, "max_iters")}))
        return AgentLoopResult(stop_reason=StopReason.MAX_ITERS, iterations=self.config.max_iters, action_required="HITL_REQUIRED")
