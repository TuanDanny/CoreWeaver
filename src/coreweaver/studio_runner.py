from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "coreweaver"

from .contracts.studio_agent1 import Agent1StartRequest, normalize_agent1_start_payload, validate_agent1_studio_event
from .events import map_core_event_to_studio
from .runtime import RuntimeSession, RuntimeState


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "resume"])
    parser.add_argument("--project-name", default="swarm_soc")
    parser.add_argument("--thread-id", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--checkpoint-db", default="")
    parser.add_argument("--planning-mode", default="normal")
    parser.add_argument("--attachment-manifest", default="")
    parser.add_argument("--attachment-context", default="")
    parser.add_argument("--requirement", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--resume-action", default="")
    parser.add_argument("--change", default="")
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir) if args.output_dir else Path("runs") / Path(args.run_id or "skeleton")
    output_dir.mkdir(parents=True, exist_ok=True)
    request = normalize_agent1_start_payload(
        {
            "requirement": args.requirement or args.notes or args.change or args.resume_action,
            "project_name": args.project_name,
            "planning_mode": args.planning_mode,
            "run_id": args.run_id,
            "thread_id": args.thread_id,
            "output_dir": str(output_dir),
            "checkpoint_db": args.checkpoint_db,
            "attachment_manifest": args.attachment_manifest,
            "attachment_context": args.attachment_context,
        }
    )
    profile = os.environ.get("COREWEAVER_RUN_PROFILE", "mock_swarm").strip() or "mock_swarm"
    asyncio.run(
        _run_coreweaver(
            request,
            profile,
            command=args.command,
            resume_action=args.resume_action,
            notes=args.notes,
            change=args.change,
        )
    )
    return 0


async def _run_coreweaver(
    request: Agent1StartRequest,
    profile: str,
    *,
    command: str = "start",
    resume_action: str = "",
    notes: str = "",
    change: str = "",
) -> None:
    session = RuntimeSession(
        RuntimeState(
            run_id=request.run_id,
            profile=profile,
            status="running",
            requirement=request.requirement,
            project_name=request.project_name,
            planning_mode=request.planning_mode,
            output_dir=str(request.output_dir),
            attachment_refs=tuple(ref for ref in (request.attachment_manifest, request.attachment_context) if ref),
        )
    )
    if command == "resume":
        await session.resume(resume_action=resume_action, notes=notes, change=change)
    else:
        await session.start()
    for event in session.event_stream.history:
        studio_event = map_core_event_to_studio(event)
        if studio_event.get("type") == "pause":
            studio_event["message"] = str(studio_event.get("message") or "core runtime paused")
        elif studio_event.get("type") == "agent_action":
            studio_event["summary"] = str(studio_event.get("summary") or "framework event")
            studio_event["planning_mode"] = request.planning_mode
        _emit(studio_event)


def _emit(event: dict[str, object]) -> None:
    validate_agent1_studio_event(event)
    print(json.dumps(event, sort_keys=True), flush=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
