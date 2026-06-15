from __future__ import annotations

import json
from pathlib import Path

from coreweaver.events import AsyncEventStream, CoreEvent, CoreEventType
from coreweaver.framework_types import make_idempotency_key
from coreweaver.debug import validate_replay_resume_state

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
            swarm_result = await self._run_agent1(self.state.requirement, revision_id=self.state.revision_id)
            stop_reason = StopReason.CLARIFICATION_REQUIRED if swarm_result.action_required == "REQUIREMENT_CLARIFICATION" else StopReason.HITL_REQUIRED
            return AgentLoopResult(stop_reason=stop_reason, iterations=1, action_required=swarm_result.action_required)
        result = await AgentLoop(event_stream=self.event_stream).run(run_id=self.state.run_id, revision_id=self.state.revision_id)
        await self.event_stream.emit(CoreEvent(event_type=CoreEventType.HANDOFF_BLOCKED, run_id=self.state.run_id, revision_id=self.state.revision_id, span_id="handoff:blocked", parent_span_id="agent_loop", idempotency_key=make_idempotency_key(self.state.run_id, "handoff"), payload={"reason": "framework skeleton blocks Agent2 handoff"}))
        return result

    async def resume(self, *, resume_action: str = "", notes: str = "", change: str = "") -> AgentLoopResult:
        await self.event_stream.emit(
            CoreEvent(
                event_type=CoreEventType.RUN_START,
                run_id=self.state.run_id,
                revision_id="rev:resume",
                span_id="run:start",
                parent_span_id=None,
                payload={"profile": self.state.profile, "command": "resume"},
            )
        )
        replay = self._load_replay_bundle()
        validation = validate_replay_resume_state(replay)
        if not validation.passed or validation.resume_state is None:
            await self._emit_resume_blocked("replay_resume_invalid", {"errors": validation.errors})
            self._write_resume_result("blocked", "HITL_REQUIRED", {"errors": validation.errors})
            return AgentLoopResult(stop_reason=StopReason.HITL_REQUIRED, iterations=1, action_required="HITL_REQUIRED")

        resume_state = validation.resume_state
        await self.event_stream.emit(
            CoreEvent(
                event_type=CoreEventType.AGENT1_ROLLBACK_POINT_RESTORED,
                run_id=self.state.run_id,
                revision_id="rev:resume",
                span_id="agent1:resume:restored",
                parent_span_id="run:start",
                payload={
                    "latest_stage": resume_state.latest_stage,
                    "checkpoint_ref": resume_state.latest_checkpoint_ref,
                    "checkpoint_hash": resume_state.latest_checkpoint_hash,
                    "action_required": resume_state.action_required,
                },
            )
        )

        requested = (resume_action or resume_state.action_required or "").upper()
        note_text = (change or notes).strip()
        if resume_state.action_required == "REQUIREMENT_CLARIFICATION" and note_text:
            requirement = self._resumed_requirement(note_text)
            swarm_result = await self._run_agent1(requirement, revision_id="rev:resume")
            stop_reason = StopReason.CLARIFICATION_REQUIRED if swarm_result.action_required == "REQUIREMENT_CLARIFICATION" else StopReason.HITL_REQUIRED
            return AgentLoopResult(stop_reason=stop_reason, iterations=1, action_required=swarm_result.action_required)

        if resume_state.action_required == "PLAN_REVIEW" and requested in {"", "OK", "APPROVE", "APPROVED", "PLAN_REVIEW"}:
            await self.event_stream.emit(
                CoreEvent(
                    event_type=CoreEventType.RUN_END,
                    run_id=self.state.run_id,
                    revision_id="rev:resume",
                    span_id="run:end",
                    parent_span_id="agent1:resume:restored",
                    payload={"message": "PLAN_REVIEW approved from replay resume checkpoint.", "action_required": "DONE"},
                )
            )
            self._write_resume_result("done", "DONE", {"approved_from": resume_state.latest_checkpoint_ref})
            return AgentLoopResult(stop_reason=StopReason.FINISHED, iterations=1, action_required=None)

        await self._emit_resume_blocked(
            "resume_requires_human_action",
            {
                "resume_action": requested,
                "checkpoint_action_required": resume_state.action_required,
                "latest_stage": resume_state.latest_stage,
            },
        )
        self._write_resume_result("blocked", "HITL_REQUIRED", {"checkpoint_action_required": resume_state.action_required})
        return AgentLoopResult(stop_reason=StopReason.HITL_REQUIRED, iterations=1, action_required="HITL_REQUIRED")

    def manifest(self) -> RuntimeManifest:
        return RuntimeManifest(run_id=self.state.run_id, profile=self.state.profile, status=self.state.status)

    async def _run_agent1(self, requirement: str, *, revision_id: str):
        from coreweaver.agents.agent1.runtime import Agent1SwarmRuntime
        from coreweaver.models import ModelRouter, OpenAICompatibleModelClient

        model_router = ModelRouter(OpenAICompatibleModelClient()) if self.state.profile == "local_llm" else ModelRouter()
        return await Agent1SwarmRuntime(event_stream=self.event_stream, model_router=model_router).run(
            run_id=self.state.run_id,
            revision_id=revision_id,
            requirement=requirement,
            project_name=self.state.project_name,
            planning_mode=self.state.planning_mode,
            output_dir=Path(self.state.output_dir),
            attachment_refs=self.state.attachment_refs,
        )

    def _load_replay_bundle(self) -> dict:
        replay_path = Path(self.state.output_dir) / "replay" / "replay_bundle.json"
        if not replay_path.exists():
            return {}
        try:
            payload = json.loads(replay_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _resumed_requirement(self, note_text: str) -> str:
        base = self.state.requirement.strip()
        if not base:
            return note_text
        return f"{base}\n\nClarification response:\n{note_text}"

    async def _emit_resume_blocked(self, code: str, details: dict) -> None:
        await self.event_stream.emit(
            CoreEvent(
                event_type=CoreEventType.DEBUG_ISSUE,
                run_id=self.state.run_id,
                revision_id="rev:resume",
                span_id=f"issue:{code}",
                parent_span_id="run:start",
                payload={"severity": "blocker", "source": "agent1.resume", "code": code, "message": "Agent1 resume blocked by checkpoint gate.", "details": details},
            )
        )
        await self.event_stream.emit(
            CoreEvent(
                event_type=CoreEventType.HITL_REQUIRED,
                run_id=self.state.run_id,
                revision_id="rev:resume",
                span_id="agent1:pause:resume_blocked",
                parent_span_id=f"issue:{code}",
                payload={"action_required": "HITL_REQUIRED", "message": "Resume requires human review before Agent1 can continue."},
            )
        )

    def _write_resume_result(self, status: str, action_required: str, details: dict) -> None:
        output_dir = Path(self.state.output_dir)
        replay_dir = output_dir / "replay"
        trace_dir = output_dir / "trace"
        replay_dir.mkdir(parents=True, exist_ok=True)
        trace_dir.mkdir(parents=True, exist_ok=True)
        events = [event.safe_dump() for event in self.event_stream.history]
        (trace_dir / "resume_events.jsonl").write_text("\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n", encoding="utf-8")
        (replay_dir / "resume_result.json").write_text(
            json.dumps(
                {
                    "schema_version": "coreweaver.agent1.resume_result.v1",
                    "run_id": self.state.run_id,
                    "status": status,
                    "action_required": action_required,
                    "events": events,
                    "details": details,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
