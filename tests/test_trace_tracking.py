import json
from concurrent.futures import ThreadPoolExecutor

from semiconductor_swarm.tracing import (
    TRACE_FILES,
    append_jsonl,
    clear_trace_context,
    finalize_trace_reports,
    read_trace_events,
    redact,
    secret_leaks,
    set_trace_context,
    trace_debug_issue,
    trace_event,
    write_trace_health_report,
)


def test_trace_redaction_removes_secrets_from_nested_payload(tmp_path):
    set_trace_context(run_id="run-1", thread_id="thread-1", output_dir=tmp_path)

    event = trace_event(
        TRACE_FILES["studio_flow"],
        phase="settings",
        agent="studio",
        node_id="API.TEST_CONNECTION",
        event_type="credential_probe",
        payload={
            "api_key": "fake-api-key",
            "headers": {"Authorization": "Bearer fake"},
            "message": "safe",
        },
    )

    clear_trace_context()
    text = (tmp_path / "reports" / "traces" / TRACE_FILES["studio_flow"]).read_text(encoding="utf-8")
    assert "fake-api-key" not in text
    assert "Bearer fake" not in text
    assert event["api_key"] == "<redacted>"
    assert event["headers"]["Authorization"] == "<redacted>"
    assert event["message"] == "safe"


def test_trace_redaction_and_leak_scan_catch_inline_secret_assignment():
    payload = {"message": "debug issue carried api_key=TESTSECRET12345 in free text"}

    clean = redact(payload)

    assert "TESTSECRET12345" not in json.dumps(clean)
    assert clean["message"] == "debug issue carried api_key=<redacted> in free text"
    assert secret_leaks(payload) == ["secret_assignment"]


def test_trace_jsonl_schema_and_reader(tmp_path):
    set_trace_context(run_id="run-2", thread_id="thread-2", flow_id="flow-a", output_dir=tmp_path)

    trace_event(
        TRACE_FILES["agent1_intake"],
        phase="planning",
        agent="agent1",
        node_id="AGENT1.FAST_ROUTER",
        event_type="node_completed",
        status="pass",
        payload={"decision": "DESIGN_READY"},
    )

    events = read_trace_events(tmp_path)
    clear_trace_context()

    assert len(events) == 1
    event = events[0]
    assert event["run_id"] == "run-2"
    assert event["thread_id"] == "thread-2"
    assert event["flow_id"] == "flow-a"
    assert event["node_id"] == "AGENT1.FAST_ROUTER"
    assert event["trace_id"]


def test_trace_debug_issue_promotes_group_session_context(tmp_path):
    set_trace_context(run_id="run-group", thread_id="thread-group", output_dir=tmp_path)

    trace_debug_issue(
        severity="error",
        source="agent1",
        code="agent1_group_session_infra_failure",
        message="M02 failed",
        details={"iteration": 2, "group_id": "M02", "span_id": "span-m02", "model_call_id": "call-m02"},
        node_id="AGENT1.GROUP_SESSION.M02",
    )

    clear_trace_context()
    issue = json.loads((tmp_path / "reports" / "traces" / TRACE_FILES["debug_issues"]).read_text(encoding="utf-8"))
    assert issue["group_id"] == "M02"
    assert issue["span_id"] == "span-m02"
    assert issue["model_call_id"] == "call-m02"
    assert issue["iteration"] == 2

def test_trace_jsonl_concurrent_appends_do_not_corrupt_lines(tmp_path):
    set_trace_context(run_id="run-concurrent", thread_id="thread-concurrent", flow_id="flow-concurrent", output_dir=tmp_path)

    def write_event(index: int) -> None:
        trace_event(
            TRACE_FILES["agent1_council"],
            phase="planning",
            agent="agent1",
            node_id=f"L{index:02d}",
            event_type="agent1_council_node",
            status="pass",
            payload={"summary": "x" * 2000},
        )

    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(write_event, range(80)))

    path = tmp_path / "reports" / "traces" / TRACE_FILES["agent1_council"]
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    clear_trace_context()

    assert len(events) == 80
    assert all(event["trace_id"] for event in events)


def test_trace_health_fails_when_required_nodes_missing(tmp_path):
    append_jsonl(tmp_path / "reports" / "traces" / TRACE_FILES["agent1_intake"], {"trace_id": "1", "node_id": "AGENT1.FAST_ROUTER"})

    report = write_trace_health_report(tmp_path, required_nodes=["AGENT1.FAST_ROUTER", "AGENT1.READY_GATE"])

    assert report["pass"] is False
    assert report["max_score"] == 100
    assert report["score"] == 65.0
    assert report["missing_nodes"] == ["AGENT1.READY_GATE"]


def test_trace_finalize_writes_manifest_health_invariants_and_budget(tmp_path):
    set_trace_context(run_id="run-3", thread_id="thread-3", output_dir=tmp_path)
    for node in ("APP.SWARM_RUNNER_START", "GRAPH.AGENT1_ENTER", "AGENT1.FAST_ROUTER", "AGENT1.INTAKE_COUNCIL", "AGENT1.CANONICAL_NORMALIZE", "AGENT1.DEFAULTS_APPLY", "AGENT1.READY_GATE", "AGENT1.HANDOFF_OR_PAUSE"):
        trace_event(
            TRACE_FILES["agent1_intake"],
            phase="planning",
            agent="agent1",
            node_id=node,
            event_type="node_completed",
            status="pass",
        )

    reports = finalize_trace_reports(tmp_path)
    clear_trace_context()

    root = tmp_path / "reports" / "traces"
    assert (root / "trace_manifest.json").is_file()
    assert (root / "trace_health_report.json").is_file()
    assert (root / "trace_invariant_report.json").is_file()
    assert (root / "agent1_budget_report.json").is_file()
    assert reports["health"]["pass"] is True
    assert reports["health"]["score"] == 100.0
    assert reports["budget"]["codex_call_count"] == reports["budget"]["llm_event_count"]
    assert json.loads((root / "trace_health_report.json").read_text(encoding="utf-8"))["pass"] is True
