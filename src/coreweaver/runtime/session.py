from __future__ import annotations

from pathlib import Path

from coreweaver.events import AsyncEventStream, CoreEvent, CoreEventType
from coreweaver.framework_types import make_idempotency_key

from .agent_loop import AgentLoop, AgentLoopResult, StopReason
from .manifest import RuntimeManifest
from .state import RuntimeState


class RuntimeSession:
    def __init__(self, state: RuntimeState, event_stream: AsyncEventStream | None = None) -> None:
        self.state = state
        self.event_stream = event_stream or AsyncEventStream()

    async def start(self) -> AgentLoopResult:
        await self.event_stream.emit(CoreEvent(event_type=CoreEventType.RUN_START, run_id=self.state.run_id, revision_id=self.state.revision_id, span_id="run:start", parent_span_id=None, payload={"profile": self.state.profile}))
        if self.state.profile in {"mock_swarm", "local_llm"}:
            from coreweaver.agents.agent1.runtime import Agent1SwarmRuntime
            from coreweaver.models import ModelRouter, OpenAICompatibleModelClient

            model_router = ModelRouter(OpenAICompatibleModelClient()) if self.state.profile == "local_llm" else ModelRouter()
            swarm_result = await Agent1SwarmRuntime(event_stream=self.event_stream, model_router=model_router).run(
                run_id=self.state.run_id,
                revision_id=self.state.revision_id,
                requirement=self.state.requirement,
                project_name=self.state.project_name,
                planning_mode=self.state.planning_mode,
                output_dir=Path(self.state.output_dir),
                attachment_refs=self.state.attachment_refs,
            )
            stop_reason = StopReason.CLARIFICATION_REQUIRED if swarm_result.action_required == "REQUIREMENT_CLARIFICATION" else StopReason.HITL_REQUIRED
            return AgentLoopResult(stop_reason=stop_reason, iterations=1, action_required=swarm_result.action_required)
        result = await AgentLoop(event_stream=self.event_stream).run(run_id=self.state.run_id, revision_id=self.state.revision_id)
        await self.event_stream.emit(CoreEvent(event_type=CoreEventType.HANDOFF_BLOCKED, run_id=self.state.run_id, revision_id=self.state.revision_id, span_id="handoff:blocked", parent_span_id="agent_loop", idempotency_key=make_idempotency_key(self.state.run_id, "handoff"), payload={"reason": "framework skeleton blocks Agent2 handoff"}))
        return result

    def manifest(self) -> RuntimeManifest:
        return RuntimeManifest(run_id=self.state.run_id, profile=self.state.profile, status=self.state.status)
