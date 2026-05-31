from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .runtime import RuntimeSession, RuntimeState
from .run_profiles import RunProfile, load_run_profile


@dataclass(frozen=True)
class CoreRequest:
    requirement: str
    project: str
    mode: str
    run_id: str | None = None
    output_dir: str | None = None


@dataclass(frozen=True)
class CoreResponse:
    status: str
    message: str
    run_id: str | None = None
    action_required: str | None = None
    artifact_paths: tuple[str, ...] = ()


class CoreWeaverRuntime:
    """Public adapter boundary for Studio and direct package callers."""

    def __init__(self, profile: str | RunProfile | None = None) -> None:
        self.profile = profile if isinstance(profile, RunProfile) else load_run_profile(profile)

    def start(self, request: CoreRequest) -> CoreResponse:
        if not request.requirement.strip():
            return CoreResponse(status="paused", message="missing requirement", action_required="REQUIREMENT_CLARIFICATION")
        if self.profile.name in {"mock_swarm", "local_llm"}:
            run_id = request.run_id or f"core:{uuid4().hex[:12]}"
            output_dir = request.output_dir or str(Path("runs") / run_id.replace(":", "_"))
            session = RuntimeSession(
                RuntimeState(
                    run_id=run_id,
                    profile=self.profile.name,
                    status="running",
                    requirement=request.requirement,
                    project_name=request.project,
                    planning_mode=request.mode,
                    output_dir=output_dir,
                )
            )
            result = asyncio.run(session.start())
            artifact_paths = tuple(
                str(event.payload.get("path"))
                for event in session.event_stream.history
                if event.event_type.value == "artifact_written" and event.payload.get("path")
            )
            return CoreResponse(
                status="paused" if result.action_required else "done",
                message=f"core runtime {self.profile.name} stopped at {result.action_required or result.stop_reason.value}",
                run_id=run_id,
                action_required=result.action_required,
                artifact_paths=artifact_paths,
            )
        return CoreResponse(status="ready", message="core runtime skeleton only")

    def capabilities(self) -> dict[str, object]:
        return self.profile.to_capabilities()
