"""V7.1 Studio UAT: user input -> Agent1 review -> Agent2 RTL with deep tracking audit."""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studio.backend import attachments as attachment_module  # noqa: E402
from studio.backend import config  # noqa: E402
from studio.backend.runner import RunnerManager  # noqa: E402
from studio.backend.server import create_app  # noqa: E402
import studio.backend.server as server_module  # noqa: E402

EVIDENCE_ROOT = ROOT / "outputs" / "uat" / "v71_agent2_flow_tracking"
FAKE_SECRET = "fake-v71-secret-never-write"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _runner_code(events: list[dict[str, Any]], files: dict[str, str]) -> str:
    return (
        "import json,pathlib,time;"
        f"files={files!r};"
        "[pathlib.Path(p).parent.mkdir(parents=True, exist_ok=True) or pathlib.Path(p).write_text(t, encoding='utf-8') for p,t in files.items()];"
        f"events={events!r};"
        "[print(json.dumps(e), flush=True) or time.sleep(0.05) for e in events];"
        "time.sleep(0.15)"
    )


def _fake_flow_command(command_name: str, payload: dict[str, Any]) -> list[str]:
    output_dir = Path(str(payload["output_dir"]))
    plan = output_dir / "reports" / "architecture_plan.md"
    contract = output_dir / "contracts" / "agent1_to_agent2.json"
    rtl = output_dir / "rtl" / "v71_agent2_top.sv"
    rtl_summary = output_dir / "rtl" / "reports" / "agent2_rtl_draft_summary.json"
    if command_name == "start":
        files = {
            str(plan): "# Architecture Plan\n32-bit APB UART CPU\n",
            str(contract): json.dumps({"schema_version": "agent1.to_agent2.v1", "top": "v71_agent2_top", "bus": "APB", "ports_locked": True}, indent=2),
        }
        events = [
            {"type": "stage", "stage": "planning", "status": "running"},
            {"type": "agent_action", "agent": "agent1", "phase": "planning", "status": "running", "action": "Intake started", "summary": "Agent1 intake started from user input"},
            {"type": "agent_action", "agent": "agent1", "phase": "planning", "status": "pass", "action": "Intake complete", "summary": "Agent1 intake complete"},
            {"type": "agent1_council_mode_selected", "mode": "group_session", "iteration": 1, "span_id": "council-mode"},
            {"type": "agent1_topology_loaded", "topology_hash": "uat-topology-v71", "iteration": 1, "span_id": "topology"},
            {"type": "agent1_cluster_assignment", "cluster_assignment_hash": "uat-assign-v71", "iteration": 1, "group_id": "M01", "manager_id": "M01", "leaf_expert_ids": ["L01", "L02", "L03"]},
            {"type": "agent1_group_session_start", "iteration": 1, "span_id": "span-m01", "group_id": "M01", "manager_id": "M01", "leaf_expert_ids": ["L01", "L02", "L03"], "model_call_id": "model-m01"},
            {"type": "agent1_group_session_done", "iteration": 1, "span_id": "span-m01", "group_id": "M01", "manager_id": "M01", "latency_s": 0.31, "total_tokens": 101, "estimated_cost_usd": 0.001},
            {"type": "agent1_cross_group_challenge", "iteration": 1, "span_id": "challenge-1", "owner_group_id": "M01", "challenge_id": "c1", "status": "resolved", "resolution": "accepted"},
            {"type": "agent1_principal_group_review", "iteration": 1, "span_id": "principal-1", "parent_span_id": "span-m01", "status": "pass", "confidence": 0.94},
            {"type": "agent_action", "agent": "agent1", "phase": "planning", "status": "pass", "action": "Guardrail check", "summary": "Agent1 guardrail check passed"},
            {"type": "artifact", "agent": "agent1", "phase": "planning", "path": str(plan), "kind": "markdown", "bytes": 37},
            {"type": "artifact", "agent": "agent1", "phase": "planning", "path": str(contract), "kind": "json", "bytes": 120},
            {"type": "pause", "action_required": "PLAN_REVIEW", "message": "Review Agent1 plan before Agent2.", "plan_path": str(plan)},
        ]
        return [sys.executable, "-c", _runner_code(events, files)]

    files = {
        str(rtl): "module v71_agent2_top(input logic pclk, input logic presetn); endmodule\n",
        str(rtl_summary): json.dumps({"schema_version": "agent2.rtl_summary.v1", "top": "v71_agent2_top", "status": "pass"}, indent=2),
    }
    events = [
        {"type": "live_input_consumed", "agent": "agent1", "status": "pass", "message": "Agent1 consumed queued live follow-up.", "message_id": "uat-live-1"},
        {"type": "trace_event", "event_type": "node_completed", "node_id": "PLAN_REVIEW.APPROVE", "agent": "studio", "phase": "planning", "status": "pass", "summary": "Plan review approved"},
        {"type": "stage", "stage": "planning", "status": "pass"},
        {"type": "agent_handoff", "from_agent": "agent1", "to_agent": "agent2", "contract": "agent1_to_agent2", "status": "pass", "summary": "Architecture contract released to Agent2", "artifact_refs": [str(contract)]},
        {"type": "stage", "stage": "rtl", "status": "running"},
        {"type": "agent_action", "agent": "agent2", "phase": "rtl", "status": "running", "action": "Codex request started", "summary": "Calling fake model for Agent2 RTL implementation"},
        {"type": "agent_action", "agent": "agent2", "phase": "rtl", "status": "pass", "action": "Codex response received", "summary": "Model returned Agent2 RTL evidence", "metric": {"latency_s": 0.22, "total_tokens": 222}},
        {"type": "agent_action", "agent": "agent2", "phase": "rtl", "status": "pass", "action": "A2.01 Spec Normalizer pass", "summary": "Agent2 subagent A2.01 pass", "subagent_id": "A2.01"},
        {"type": "agent_action", "agent": "agent2", "phase": "rtl", "status": "pass", "action": "A2.56 ECO Intent & Surgical Patch Planner pass", "summary": "Agent2 subagent A2.56 pass", "subagent_id": "A2.56"},
        {"type": "metric", "agent": "agent2", "status": "info", "name": "codex_total_tokens", "value": 222},
        {"type": "artifact", "agent": "agent2", "phase": "rtl", "path": str(rtl), "kind": "sv", "bytes": 69},
        {"type": "artifact", "agent": "agent2", "phase": "rtl", "path": str(rtl_summary), "kind": "json", "bytes": 90},
        {"type": "stage", "stage": "rtl", "status": "pass"},
        {"type": "done", "status": "SIGNOFF_READY", "output_dir": str(output_dir)},
    ]
    return [sys.executable, "-c", _runner_code(events, files)]


async def _valid_probe(_endpoint: str, _model: str, _api_key: str) -> dict[str, bool | str]:
    return {"ok": True, "message": "Connection OK"}


def _wait_for_state(client: TestClient, wanted: set[str], timeout_s: float = 10.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    latest: dict[str, Any] = {}
    while time.time() < deadline:
        response = client.get("/api/runs/current_state")
        latest = response.json()
        if str(latest.get("status") or "") in wanted:
            return latest
        time.sleep(0.05)
    return latest


def _scan_for_secret(paths: list[Path]) -> list[str]:
    leaks: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if FAKE_SECRET in text or re.search(r"Bearer\s+[A-Za-z0-9._~+/=-]{8,}", text) or "Authorization" in text:
            leaks.append(str(path))
    return leaks


def _status(segments: dict[str, Any], segment_id: str) -> str:
    raw = segments.get(segment_id)
    return str(raw.get("status") or "missing") if isinstance(raw, dict) else "missing"


def _audit(output_dir: Path, runtime_body: dict[str, Any]) -> dict[str, Any]:
    traces = output_dir / "reports" / "traces"
    files = {
        "events": traces / "runtime_events.jsonl",
        "debug_issues": traces / "debug_issues.jsonl",
        "manifest": traces / "runtime_session_manifest.json",
        "invariant": traces / "runtime_invariant_report.json",
        "replay": traces / "runtime_replay_report.json",
        "flow": traces / "runtime_flow_coverage_report.json",
        "summary": traces / "runtime_debug_summary.json",
        "recovery": traces / "runtime_recovery_report.json",
    }
    events = _read_jsonl(files["events"])
    issues = _read_jsonl(files["debug_issues"])
    manifest = _read_json(files["manifest"])
    invariant = _read_json(files["invariant"])
    replay = _read_json(files["replay"])
    flow = _read_json(files["flow"])
    summary = _read_json(files["summary"])
    coverage = flow.get("coverage") if isinstance(flow.get("coverage"), dict) else {}
    segments = flow.get("segments") if isinstance(flow.get("segments"), dict) else {}
    expected_segments = {
        "frontend_input": "completed",
        "credential_preflight": "completed",
        "attachment_staging": "completed",
        "start_request": "completed",
        "job_queue": "completed",
        "runner_process": "completed",
        "websocket": "completed",
        "live_input": "completed",
        "agent1_intake": "completed",
        "agent1_cluster": "completed",
        "agent1_guardrail": "completed",
        "plan_review": "completed",
        "agent1_artifacts": "completed",
        "agent2_gate": "completed",
        "agent2_rtl": "completed",
    }
    failures: list[str] = []
    for name, path in files.items():
        if name != "debug_issues" and not path.is_file():
            failures.append(f"missing trace file: {name} -> {path}")
    for segment_id, expected in expected_segments.items():
        actual = _status(segments, segment_id)
        if actual != expected:
            failures.append(f"segment {segment_id} expected {expected}, got {actual}")
    event_types = {str(event.get("event_type") or "") for event in events}
    source_types = {str((event.get("source") or {}).get("type") or "") for event in events if isinstance(event.get("source"), dict)}
    for event_type in {"run_init", "job_started", "job_done", "model_call_start", "model_call_done", "tool_call_done", "artifact_written"}:
        if event_type not in event_types:
            failures.append(f"missing runtime event_type: {event_type}")
    for source_type in {"start_preflight", "agent1_group_session_done", "agent_handoff", "websocket_connect", "websocket_replay", "websocket_hydrate", "live_input_consumed"}:
        if source_type not in source_types:
            failures.append(f"missing runtime source type: {source_type}")
    if invariant.get("ok") is not True:
        failures.append(f"invariant not ok: {invariant.get('failures')}")
    if issues:
        failures.append(f"debug issues should be empty for happy path: {[issue.get('code') for issue in issues]}")
    if summary.get("flow_coverage_ok") is not True:
        failures.append(f"debug summary flow_coverage_ok is not true: {summary.get('flow_coverage_ok')}")
    if coverage.get("failed_segment_count") not in {0, None}:
        failures.append(f"coverage has failed segments: {coverage.get('failed_segments')}")
    missing_required = [item for item in coverage.get("missing_segments", []) if item not in {"settings_preflight", "downstream_agents"}]
    if missing_required:
        failures.append(f"coverage missing required segments: {missing_required}")
    span_model = flow.get("canonical_span_model") if isinstance(flow.get("canonical_span_model"), dict) else {}
    for key in ("run_span_id", "backend_request_span_id", "job_span_id", "process_span_id", "agent_span_id", "model_call_id", "artifact_span_id"):
        if not span_model.get(key):
            failures.append(f"missing canonical span: {key}")
    artifacts = [
        output_dir / "inputs" / "attachments_manifest.json",
        output_dir / "inputs" / "attachment_context.md",
        output_dir / "reports" / "architecture_plan.md",
        output_dir / "contracts" / "agent1_to_agent2.json",
        output_dir / "rtl" / "v71_agent2_top.sv",
        output_dir / "rtl" / "reports" / "agent2_rtl_draft_summary.json",
    ]
    for artifact in artifacts:
        if not artifact.is_file():
            failures.append(f"missing output artifact: {artifact}")
    leaks = _scan_for_secret(list(files.values()) + artifacts)
    if leaks:
        failures.append(f"secret leak detected: {leaks}")
    if not runtime_body.get("flowCoverage"):
        failures.append("runtime API did not return flowCoverage")
    return {
        "ok": not failures,
        "failures": failures,
        "output_dir": str(output_dir),
        "event_count": len(events),
        "debug_issue_count": len(issues),
        "event_types": sorted(event_types),
        "source_types": sorted(source_types),
        "segment_status": {segment_id: _status(segments, segment_id) for segment_id in expected_segments},
        "invariant": {"ok": invariant.get("ok"), "failure_count": invariant.get("failure_count"), "warning_count": invariant.get("warning_count")},
        "flow": {"ok": flow.get("ok"), "missing": coverage.get("missing_segments"), "failed": coverage.get("failed_segments")},
        "canonical_span_model": span_model,
    }


def run_uat() -> dict[str, Any]:
    if EVIDENCE_ROOT.exists():
        shutil.rmtree(EVIDENCE_ROOT)
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    config.CODEX_CONFIG_PATH = EVIDENCE_ROOT / "codex_api.local.json"
    config.STUDIO_SETTINGS_PATH = EVIDENCE_ROOT / "settings.json"
    config._write_json(config.CODEX_CONFIG_PATH, {"base_url": "http://fake.local/v1", "model": "fake/codex", "api_key": FAKE_SECRET})
    attachment_module.STAGED_ROOT = EVIDENCE_ROOT / ".swarm" / "staged_inputs"
    server_module._probe_openai_compatible_endpoint = _valid_probe

    events_seen: list[dict[str, Any]] = []

    async def sink(event: dict[str, Any]) -> None:
        events_seen.append(event)

    manager = RunnerManager(root=ROOT, command_builder=_fake_flow_command, event_sink=sink)
    output_dir = EVIDENCE_ROOT / "agent2_flow_output"
    app = create_app(manager, heartbeat_interval_s=0.01, connection_test_cooldown_s=0.0, runtime_watchdog_enabled=False)
    with TestClient(app) as client:
        staged = client.post(
            "/api/attachments/stage",
            files={"files": ("requirements.md", b"# Requirement\n32-bit APB UART CPU with formal-first RTL handoff.\n", "text/markdown")},
        )
        staged_body = staged.json()
        attachment_id = staged_body["attachments"][0]["id"]
        started = client.post(
            "/api/runs/start",
            json={
                "requirement": "Build a 32-bit APB UART CPU and continue through Agent2 RTL.",
                "project_name": "v71_agent2_flow",
                "output_dir": str(output_dir),
                "planning_mode": "normal",
                "startPolicy": "fresh",
                "attachmentDraftId": staged_body["draftId"],
                "attachmentIds": [attachment_id],
            },
        )
        paused = _wait_for_state(client, {"paused"}, timeout_s=10.0)
        live = client.post(f"/api/runs/{paused['run_id']}/live-input", json={"message": "Add APB slave reset safety note before Agent2.", "clientMessageId": "uat-live-1"})
        resumed = client.post(f"/api/runs/{paused['run_id']}/resume", json={"notes": "ok", "resume_action": "PLAN_REVIEW", "planning_mode": "normal"})
        done = _wait_for_state(client, {"done", "failed", "stopped"}, timeout_s=10.0)
        with client.websocket_connect(f"/ws/runs/{paused['run_id']}", headers={"origin": "http://localhost:5173"}) as websocket:
            for _ in range(6):
                try:
                    websocket.receive_json()
                except Exception:
                    break
        runtime = client.get(f"/api/runs/{paused['run_id']}/runtime")
        runtime_body = runtime.json()

    audit = _audit(output_dir, runtime_body)
    report = {
        "schema_version": "studio.v71_agent2_flow_tracking_uat.v1",
        "evidence_root": str(EVIDENCE_ROOT),
        "start_status": started.status_code,
        "resume_status": resumed.status_code,
        "live_input_status": live.status_code,
        "final_state": done,
        "events_seen": len(events_seen),
        "audit": audit,
    }
    _write_json(EVIDENCE_ROOT / "uat_report.json", report)
    return report


def main() -> int:
    report = run_uat()
    if not report["audit"]["ok"]:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1
    print(f"V7.1 Agent2 flow tracking UAT passed: {EVIDENCE_ROOT}")
    print(json.dumps({"event_count": report["audit"]["event_count"], "segments": report["audit"]["segment_status"]}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
