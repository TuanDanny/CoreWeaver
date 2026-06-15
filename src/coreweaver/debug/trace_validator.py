from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any


ROOT_PARENT_ANCHORS = frozenset(
    {
        "agent1",
        "agent1:artifacts",
        "agent1:signoff",
    }
)

TERMINAL_EVENTS = frozenset(
    {
        "hitl_required",
        "handoff_blocked",
        "agent1_handoff_ready",
        "agent1_handoff_blocked",
        "run_end",
    }
)


@dataclass(frozen=True)
class TraceReplayValidationResult:
    passed: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def validate_trace_replay_consistency(
    trace_events: list[dict[str, Any]],
    replay_bundle: dict[str, Any],
) -> TraceReplayValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    replay_events = replay_bundle.get("events") if isinstance(replay_bundle.get("events"), list) else []
    _validate_run_ids(trace_events, replay_bundle, errors)
    _validate_event_order(trace_events, replay_events, errors)
    _validate_spans(trace_events, errors)
    _validate_terminal_event(trace_events, errors)
    _validate_handoff_sequence(trace_events, errors)
    _validate_action_pairs(trace_events, errors, warnings)

    return TraceReplayValidationResult(
        passed=not errors,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _validate_run_ids(
    trace_events: list[dict[str, Any]],
    replay_bundle: dict[str, Any],
    errors: list[str],
) -> None:
    trace_run_ids = {str(event.get("run_id")) for event in trace_events if event.get("run_id")}
    replay_run_id = replay_bundle.get("run_id")
    if len(trace_run_ids) > 1:
        errors.append("trace_run_id_mismatch")
    if replay_run_id and trace_run_ids and str(replay_run_id) not in trace_run_ids:
        errors.append("replay_run_id_mismatch")


def _validate_event_order(
    trace_events: list[dict[str, Any]],
    replay_events: list[Any],
    errors: list[str],
) -> None:
    if len(trace_events) != len(replay_events):
        errors.append("trace_replay_event_count_mismatch")
        return
    for index, (trace_event, replay_event) in enumerate(zip(trace_events, replay_events, strict=True)):
        if not isinstance(replay_event, dict):
            errors.append(f"replay_event_not_object:{index}")
            continue
        trace_key = (trace_event.get("event_type"), trace_event.get("span_id"))
        replay_key = (replay_event.get("event_type"), replay_event.get("span_id"))
        if trace_key != replay_key:
            errors.append(f"trace_replay_event_order_mismatch:{index}")
            return


def _validate_spans(trace_events: list[dict[str, Any]], errors: list[str]) -> None:
    spans = [str(event.get("span_id")) for event in trace_events if event.get("span_id")]
    seen: set[str] = set()
    duplicates: set[str] = set()
    for span in spans:
        if span in seen:
            duplicates.add(span)
        seen.add(span)
    for span in sorted(duplicates):
        errors.append(f"duplicate_span_id:{span}")

    known = set(spans)
    for event in trace_events:
        parent = event.get("parent_span_id")
        if not parent or parent in ROOT_PARENT_ANCHORS or parent in known:
            continue
        errors.append(f"orphan_parent_span:{parent}")


def _validate_terminal_event(trace_events: list[dict[str, Any]], errors: list[str]) -> None:
    if not trace_events:
        errors.append("trace_events_empty")
        return
    if not any(event.get("event_type") in TERMINAL_EVENTS for event in trace_events):
        errors.append("terminal_event_missing")


def _validate_handoff_sequence(trace_events: list[dict[str, Any]], errors: list[str]) -> None:
    handoff_ready_index = _first_event_index(trace_events, "agent1_handoff_ready")
    if handoff_ready_index is None:
        return
    g12_index = None
    for index, event in enumerate(trace_events):
        if event.get("event_type") != "agent1_signoff_gate_done":
            continue
        payload = event.get("payload")
        if isinstance(payload, dict) and payload.get("gate_id") == "G12" and payload.get("status") == "pass":
            g12_index = index
            break
    if g12_index is None:
        errors.append("handoff_ready_without_g12_pass")
    elif handoff_ready_index < g12_index:
        errors.append("handoff_ready_before_g12_pass")


def _validate_action_pairs(
    trace_events: list[dict[str, Any]],
    errors: list[str],
    warnings: list[str],
) -> None:
    _validate_group_pairs(trace_events, errors)
    _validate_tool_pairs(trace_events, errors, warnings)


def _validate_group_pairs(trace_events: list[dict[str, Any]], errors: list[str]) -> None:
    started: Counter[str] = Counter()
    finished: Counter[str] = Counter()
    for event in trace_events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        manager_id = payload.get("manager_id")
        if not manager_id:
            continue
        if event.get("event_type") == "agent1_group_session_start":
            started[str(manager_id)] += 1
        if event.get("event_type") in {"agent1_group_session_done", "agent1_group_session_failed"}:
            finished[str(manager_id)] += 1
    for manager_id in sorted(started):
        missing = started[manager_id] - finished[manager_id]
        if missing > 0:
            errors.append(f"group_session_missing_terminal:{manager_id}:{missing}")


def _validate_tool_pairs(
    trace_events: list[dict[str, Any]],
    errors: list[str],
    warnings: list[str],
) -> None:
    started: Counter[str] = Counter()
    finished: Counter[str] = Counter()
    for event in trace_events:
        tool_call_id = event.get("tool_call_id")
        if not tool_call_id:
            continue
        event_type = event.get("event_type")
        if event_type in {"agent1_tool_call_start", "tool_call_start"}:
            started[str(tool_call_id)] += 1
        if event_type in {"agent1_tool_call_done", "agent1_tool_call_failed", "tool_call_end", "tool_call_failed"}:
            finished[str(tool_call_id)] += 1
    for tool_call_id in sorted(started):
        missing = started[tool_call_id] - finished[tool_call_id]
        if missing > 0:
            errors.append(f"tool_call_missing_terminal:{tool_call_id}:{missing}")
    for tool_call_id in sorted(finished):
        missing_start = finished[tool_call_id] - started[tool_call_id]
        if missing_start > 0:
            warnings.append(f"tool_call_terminal_without_start:{tool_call_id}:{missing_start}")


def _first_event_index(trace_events: list[dict[str, Any]], event_type: str) -> int | None:
    for index, event in enumerate(trace_events):
        if event.get("event_type") == event_type:
            return index
    return None
