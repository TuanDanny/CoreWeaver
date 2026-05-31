from __future__ import annotations

from typing import Any

from .core_event import CoreEvent, CoreEventType


def map_core_event_to_studio(event: CoreEvent) -> dict[str, Any]:
    data = event.safe_dump()
    if event.event_type == CoreEventType.DEBUG_ISSUE:
        return {"type": "debug_issue", **data.get("payload", {}), "run_id": event.run_id}
    if event.event_type == CoreEventType.ARTIFACT_WRITTEN:
        return {
            "type": "artifact",
            "run_id": event.run_id,
            "path": str(event.payload.get("path") or ""),
            "kind": str(event.payload.get("kind") or "artifact"),
            "message": str(event.payload.get("message") or "artifact written"),
        }
    if event.event_type == CoreEventType.HITL_REQUIRED:
        return {
            "type": "pause",
            "action_required": str(event.payload.get("action_required") or "HITL_REQUIRED"),
            "message": str(event.payload.get("message") or "human review required"),
            "run_id": event.run_id,
        }
    if event.event_type == CoreEventType.RUN_END:
        return {"type": "done", "run_id": event.run_id, "message": str(event.payload.get("message") or "run ended")}
    if event.event_type.value.startswith("agent1_") or event.event_type in {
        CoreEventType.INTAKE_STARTED,
        CoreEventType.INTAKE_DONE,
        CoreEventType.INTAKE_FAILED,
        CoreEventType.CLASSIFICATION_DONE,
    }:
        return {"type": event.event_type.value, "run_id": event.run_id, **data.get("payload", {})}
    return {
        "type": "agent_action",
        "agent": str(event.payload.get("agent") or "agent1"),
        "status": str(event.payload.get("status") or "info"),
        "action": event.event_type.value,
        "summary": str(event.payload.get("message") or event.event_type.value),
        "run_id": event.run_id,
    }
