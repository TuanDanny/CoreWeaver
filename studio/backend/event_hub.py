"""Bounded WebSocket event fanout and replay support."""
from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Any

CRITICAL_EVENT_TYPES = {
    "stage",
    "pause",
    "error",
    "done",
    "process_start",
    "process_exit",
    "metric",
    "agent_action",
    "agent_handoff",
    "agent1_council_iteration",
    "agent1_council_node",
    "agent1_council_edge",
    "agent1_council_artifact",
    "job_queued",
    "job_started",
    "job_progress",
    "job_completed",
    "job_failed",
    "job_cancelled",
    "attachment_staged",
    "attachment_rejected",
    "live_input_ack",
    "live_input_consumed",
    "live_input_error",
    "runtime_event",
    "watchdog_timeout",
}
MAX_EVENT_BYTES = 64 * 1024
FIELD_LIMITS = {
    "message": 4 * 1024,
    "summary": 2 * 1024,
    "traceback_tail": 8 * 1024,
    "preview_tail": 16 * 1024,
    "log_tail": 16 * 1024,
}
DEFAULT_TEXT_LIMIT = 4 * 1024
PATH_TEXT_LIMIT = 2 * 1024


def _truncate_text(value: str, limit: int) -> tuple[str, bool]:
    if len(value.encode("utf-8", errors="replace")) <= limit:
        return value, False
    encoded = value.encode("utf-8", errors="replace")[: max(0, limit - 80)]
    return encoded.decode("utf-8", errors="ignore") + f"\n...[truncated to {limit} bytes]", True


def _sanitize_value(key: str, value: Any) -> tuple[Any, bool]:
    truncated = False
    if isinstance(value, str):
        limit = PATH_TEXT_LIMIT if key in {"path", "full_path", "output_dir", "artifact", "evidence_path"} else FIELD_LIMITS.get(key, DEFAULT_TEXT_LIMIT)
        return _truncate_text(value, limit)
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for child_key, child_value in value.items():
            clean_value, child_truncated = _sanitize_value(str(child_key), child_value)
            clean[str(child_key)] = clean_value
            truncated = truncated or child_truncated
        return clean, truncated
    if isinstance(value, list):
        clean_list: list[Any] = []
        for item in value[:100]:
            clean_value, child_truncated = _sanitize_value(key, item)
            clean_list.append(clean_value)
            truncated = truncated or child_truncated
        if len(value) > 100:
            clean_list.append({"truncated": True, "omitted_items": len(value) - 100})
            truncated = True
        return clean_list, truncated
    return value, False


def sanitize_event(event: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    truncated = bool(event.get("truncated", False))
    for key, value in event.items():
        clean_value, field_truncated = _sanitize_value(str(key), value)
        clean[str(key)] = clean_value
        truncated = truncated or field_truncated
    if truncated:
        clean["truncated"] = True
    serialized = json.dumps(clean, ensure_ascii=False, sort_keys=True)
    if len(serialized.encode("utf-8", errors="replace")) <= MAX_EVENT_BYTES:
        return clean
    compact = {
        "type": clean.get("type", "log"),
        "level": clean.get("level", "warning"),
        "message": f"event payload exceeded {MAX_EVENT_BYTES} bytes and was compacted",
        "original_type": clean.get("type", "unknown"),
        "truncated": True,
    }
    for key in ("agent", "stage", "status", "action_required", "path", "output_dir"):
        if key in clean:
            compact[key] = clean[key]
    return compact


class EventHub:
    def __init__(self, *, replay_limit: int = 2000, client_queue_size: int = 500) -> None:
        self.replay: deque[dict[str, Any]] = deque(maxlen=replay_limit)
        self.client_queue_size = client_queue_size
        self.clients: set[asyncio.Queue[dict[str, Any]]] = set()
        self.dropped_log_events = 0

    async def publish(self, event: dict[str, Any]) -> None:
        event = sanitize_event(event)
        self.replay.append(event)
        stale: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in list(self.clients):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                if event.get("type") in CRITICAL_EVENT_TYPES:
                    try:
                        queue.get_nowait()
                        queue.put_nowait(event)
                    except asyncio.QueueFull:
                        stale.append(queue)
                    except asyncio.QueueEmpty:
                        stale.append(queue)
                else:
                    self.dropped_log_events += 1
        for queue in stale:
            self.clients.discard(queue)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self.client_queue_size)
        self.clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.clients.discard(queue)

    def clear(self) -> None:
        self.replay.clear()
        self.dropped_log_events = 0

    def replay_events(self, run_id: str | None = None) -> list[dict[str, Any]]:
        if not run_id:
            return list(self.replay)
        return [event for event in self.replay if event.get("run_id") in {run_id, None, ""}]
