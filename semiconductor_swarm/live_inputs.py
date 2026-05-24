"""Append-only live input queue consumed at Agent 1 safe checkpoints."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from semiconductor_swarm.tracing import append_jsonl, current_trace_context, now_iso, sha256_text, trace_event

QUEUE_REL = Path("inputs") / "live_input_queue.jsonl"
LEDGER_REL = Path("inputs") / "live_input_ledger.jsonl"
MAX_LIVE_INPUT_CHARS = 2000
MAX_CONSUME_BATCH = 10


def _output_dir(output_dir: str | Path | None = None) -> Path | None:
    raw = str(output_dir or current_trace_context().output_dir or "")
    return Path(raw) if raw else None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def append_live_input(
    output_dir: str | Path,
    *,
    message: str,
    run_id: str = "",
    client_message_id: str = "",
    author: str = "studio-user",
    source: str = "console",
) -> dict[str, Any]:
    clean = message.strip()
    if not clean:
        raise ValueError("live input message is required")
    if len(clean) > MAX_LIVE_INPUT_CHARS:
        raise ValueError(f"live input message exceeds {MAX_LIVE_INPUT_CHARS} characters")
    message_id = client_message_id.strip() or uuid4().hex
    record = {
        "schema_version": "studio.live_input.v1",
        "type": "queued",
        "message_id": message_id,
        "run_id": run_id,
        "author": author,
        "source": source,
        "message": clean,
        "message_hash": sha256_text(clean),
        "created_at": now_iso(),
    }
    root = Path(output_dir)
    append_jsonl(root / QUEUE_REL, record)
    trace_event(
        "live_input_trace.jsonl",
        phase="backend",
        agent="studio",
        node_id="LIVE_INPUT.QUEUE",
        event_type="live_input_queued",
        status="queued",
        payload={"message_id": message_id, "message_hash": record["message_hash"], "chars": len(clean), "source": source},
        output_dir=root,
        emit_live=False,
    )
    return {key: value for key, value in record.items() if key != "message"}


def read_unconsumed_live_inputs(output_dir: str | Path | None = None, *, limit: int = MAX_CONSUME_BATCH) -> list[dict[str, Any]]:
    root = _output_dir(output_dir)
    if root is None:
        return []
    queued = _read_jsonl(root / QUEUE_REL)
    consumed = {str(item.get("message_id")) for item in _read_jsonl(root / LEDGER_REL) if item.get("type") == "consumed"}
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in queued:
        message_id = str(item.get("message_id") or "")
        if not message_id or message_id in consumed or message_id in seen:
            continue
        if item.get("type") != "queued":
            continue
        result.append(item)
        seen.add(message_id)
        if len(result) >= limit:
            break
    return result


def mark_live_inputs_consumed(records: list[dict[str, Any]], checkpoint: str, output_dir: str | Path | None = None) -> None:
    root = _output_dir(output_dir)
    if root is None or not records:
        return
    for item in records:
        append_jsonl(
            root / LEDGER_REL,
            {
                "schema_version": "studio.live_input_ledger.v1",
                "type": "consumed",
                "message_id": item.get("message_id"),
                "message_hash": item.get("message_hash"),
                "checkpoint": checkpoint,
                "consumed_at": now_iso(),
            },
        )
        trace_event(
            "live_input_trace.jsonl",
            phase="planning",
            agent="agent1",
            node_id="LIVE_INPUT.CONSUME",
            event_type="live_input_consumed",
            status="pass",
            payload={"message_id": item.get("message_id"), "message_hash": item.get("message_hash"), "checkpoint": checkpoint},
            output_dir=root,
        )
        try:
            from semiconductor_swarm.runtime_events import emit_runtime_event

            emit_runtime_event(
                {
                    "type": "live_input_consumed",
                    "level": "info",
                    "agent": "agent1",
                    "status": "pass",
                    "message": "live follow-up consumed by Agent1 checkpoint",
                    "message_id": item.get("message_id"),
                    "message_hash": item.get("message_hash"),
                    "checkpoint": checkpoint,
                }
            )
        except Exception:
            pass


def consume_live_inputs_for_requirement(requirement: str, checkpoint: str, output_dir: str | Path | None = None) -> tuple[str, list[dict[str, Any]]]:
    records = read_unconsumed_live_inputs(output_dir)
    if not records:
        return requirement, []
    lines = ["", "Live follow-up update:"]
    for item in records:
        lines.append(f"- [{item.get('created_at', '')}] {item.get('message', '')}")
    mark_live_inputs_consumed(records, checkpoint, output_dir)
    return (requirement.rstrip() + "\n" + "\n".join(lines)).strip(), records
