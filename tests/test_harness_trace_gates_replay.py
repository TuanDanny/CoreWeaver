import json

import pytest

from coreweaver.harness.gates import GateRunner, RequiredEventGate
from coreweaver.harness.models import DebugIssue, IssueSeverity, TraceEvent
from coreweaver.harness.replay import ReplayBundle
from coreweaver.harness.secret_scan import scan_text_for_secrets
from coreweaver.harness.tracing import TraceRecorder


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
