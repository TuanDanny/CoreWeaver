import json

import pytest

from coreweaver.harness.gates import GateRunner, RequiredEventGate
from coreweaver.harness.models import DebugIssue, IssueSeverity, TraceEvent
from coreweaver.harness.replay import ReplayBundle
from coreweaver.harness.secret_scan import scan_text_for_secrets
from coreweaver.harness.tracing import TraceRecorder
from coreweaver.debug.trace_validator import validate_trace_replay_consistency


def test_trace_recorder_rejects_secret_payload() -> None:
    recorder = TraceRecorder()
    with pytest.raises(ValueError):
        recorder.record_event(
            TraceEvent(
                event_type="model_call",
                run_id="run1",
                revision_id="rev1",
                span_id="span1",
                parent_span_id=None,
                timestamp="2026-05-26T20:00:00Z",
                payload={"authorization": "Bearer " + "abcdefghijklmnopqrstuvwxyz"},
            )
        )


def test_required_event_gate_reports_missing_event() -> None:
    gate_results = GateRunner((RequiredEventGate(("intake_done",)),)).run([], [])
    assert not gate_results[0].passed
    assert gate_results[0].findings[0].code == "missing_event"


def test_replay_bundle_writes_json(tmp_path) -> None:
    event = TraceEvent(
        event_type="intake_done",
        run_id="run1",
        revision_id="rev1",
        span_id="span1",
        parent_span_id=None,
        timestamp="2026-05-26T20:00:00Z",
        payload={"ok": True},
    )
    issue = DebugIssue(
        severity=IssueSeverity.INFO,
        source="test",
        code="ok",
        message="ok",
        timestamp="2026-05-26T20:00:00Z",
    )
    path = ReplayBundle(
        run_id="run1",
        events=(event,),
        issues=(issue,),
        gate_results=GateRunner().run([event], [issue]),
        manifest={"mode": "harness"},
    ).write(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["run_id"] == "run1"
    assert data["events"][0]["event_type"] == "intake_done"


def test_secret_scanner_redacts_preview() -> None:
    findings = scan_text_for_secrets("api_" + "key='1234567890abcdef'")
    assert findings
    assert "***" in findings[0].preview


def test_trace_replay_validator_rejects_event_count_mismatch() -> None:
    trace_events = [
        {"event_type": "run_start", "run_id": "run1", "revision_id": "rev1", "span_id": "run:start", "timestamp": "2026-05-26T20:00:00Z"},
        {"event_type": "hitl_required", "run_id": "run1", "revision_id": "rev1", "span_id": "pause", "parent_span_id": "run:start", "timestamp": "2026-05-26T20:00:01Z"},
    ]

    result = validate_trace_replay_consistency(trace_events, {"run_id": "run1", "events": trace_events[:1]})

    assert not result.passed
    assert "trace_replay_event_count_mismatch" in result.errors


def test_trace_replay_validator_rejects_duplicate_and_orphan_spans() -> None:
    trace_events = [
        {"event_type": "run_start", "run_id": "run1", "revision_id": "rev1", "span_id": "run:start", "timestamp": "2026-05-26T20:00:00Z"},
        {"event_type": "debug_issue", "run_id": "run1", "revision_id": "rev1", "span_id": "run:start", "parent_span_id": "missing", "timestamp": "2026-05-26T20:00:01Z"},
        {"event_type": "hitl_required", "run_id": "run1", "revision_id": "rev1", "span_id": "pause", "parent_span_id": "run:start", "timestamp": "2026-05-26T20:00:02Z"},
    ]

    result = validate_trace_replay_consistency(trace_events, {"run_id": "run1", "events": trace_events})

    assert not result.passed
    assert "duplicate_span_id:run:start" in result.errors
    assert "orphan_parent_span:missing" in result.errors


def test_trace_replay_validator_counts_unpaired_group_and_tool_lifecycles() -> None:
    trace_events = [
        {"event_type": "run_start", "run_id": "run1", "revision_id": "rev1", "span_id": "run:start", "timestamp": "2026-05-26T20:00:00Z"},
        {
            "event_type": "agent1_group_session_start",
            "run_id": "run1",
            "revision_id": "rev1",
            "span_id": "group:m01:start:1",
            "parent_span_id": "run:start",
            "timestamp": "2026-05-26T20:00:01Z",
            "payload": {"manager_id": "M01"},
        },
        {
            "event_type": "agent1_group_session_start",
            "run_id": "run1",
            "revision_id": "rev1",
            "span_id": "group:m01:start:2",
            "parent_span_id": "run:start",
            "timestamp": "2026-05-26T20:00:02Z",
            "payload": {"manager_id": "M01"},
        },
        {
            "event_type": "agent1_group_session_done",
            "run_id": "run1",
            "revision_id": "rev1",
            "span_id": "group:m01:done:1",
            "parent_span_id": "group:m01:start:1",
            "timestamp": "2026-05-26T20:00:03Z",
            "payload": {"manager_id": "M01"},
        },
        {
            "event_type": "agent1_tool_call_start",
            "run_id": "run1",
            "revision_id": "rev1",
            "span_id": "tool:start:1",
            "parent_span_id": "run:start",
            "tool_call_id": "tool-1",
            "timestamp": "2026-05-26T20:00:04Z",
        },
        {
            "event_type": "agent1_tool_call_start",
            "run_id": "run1",
            "revision_id": "rev1",
            "span_id": "tool:start:2",
            "parent_span_id": "run:start",
            "tool_call_id": "tool-1",
            "timestamp": "2026-05-26T20:00:05Z",
        },
        {
            "event_type": "agent1_tool_call_done",
            "run_id": "run1",
            "revision_id": "rev1",
            "span_id": "tool:done:1",
            "parent_span_id": "tool:start:1",
            "tool_call_id": "tool-1",
            "timestamp": "2026-05-26T20:00:06Z",
        },
        {
            "event_type": "agent1_tool_call_done",
            "run_id": "run1",
            "revision_id": "rev1",
            "span_id": "tool:done:without-start",
            "parent_span_id": "run:start",
            "tool_call_id": "tool-2",
            "timestamp": "2026-05-26T20:00:07Z",
        },
        {"event_type": "hitl_required", "run_id": "run1", "revision_id": "rev1", "span_id": "pause", "parent_span_id": "run:start", "timestamp": "2026-05-26T20:00:08Z"},
    ]

    result = validate_trace_replay_consistency(trace_events, {"run_id": "run1", "events": trace_events})

    assert not result.passed
    assert "group_session_missing_terminal:M01:1" in result.errors
    assert "tool_call_missing_terminal:tool-1:1" in result.errors
    assert "tool_call_terminal_without_start:tool-2:1" in result.warnings
