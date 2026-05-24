"""CoreWeaver V6.8 runtime tracking UAT harness.

Runs without a real API key or token spend. Uses FastAPI TestClient plus a fake
runner subprocess to verify runtime artifacts, runtime API, secret scan, and
watchdog behavior.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from studio.backend import config  # noqa: E402
from studio.backend.runner import RunState, RunnerManager  # noqa: E402
from studio.backend.server import create_app  # noqa: E402
import studio.backend.server as server_module  # noqa: E402

EVIDENCE_ROOT = ROOT / "outputs" / "uat" / "v68_runtime_tracking"
FAKE_SECRET = "fake-v68-secret-never-write"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")


def _fake_runner_command(_command_name: str, payload: dict[str, Any]) -> list[str]:
    output_dir = Path(str(payload["output_dir"]))
    plan = output_dir / "reports" / "architecture_plan.md"
    rtl = output_dir / "rtl" / "demo_top.sv"
    code = (
        "import json,pathlib,time;"
        f"plan=pathlib.Path({str(plan)!r});"
        f"rtl=pathlib.Path({str(rtl)!r});"
        "plan.parent.mkdir(parents=True, exist_ok=True);"
        "rtl.parent.mkdir(parents=True, exist_ok=True);"
        "plan.write_text('# Architecture Plan\\nAPB UART CPU', encoding='utf-8');"
        "rtl.write_text('module demo_top; endmodule\\n', encoding='utf-8');"
        "events=["
        "{'type':'stage','stage':'planning','status':'running'},"
        "{'type':'agent_action','agent':'agent1','phase':'planning','status':'running','action':'Codex request started','summary':'Calling fake model for intake'},"
        "{'type':'agent_action','agent':'agent1','phase':'planning','status':'pass','action':'Codex response received','summary':'Model returned architecture evidence','metric':{'latency_s':0.12,'total_tokens':11}},"
        "{'type':'agent_handoff','from_agent':'agent1','to_agent':'agent2','contract':'agent1_to_agent2','status':'pass','summary':'Architecture contract released'},"
        f"{{'type':'artifact','agent':'agent1','phase':'planning','path':{str(plan)!r},'kind':'markdown','bytes':32}},"
        "{'type':'stage','stage':'planning','status':'pass'},"
        "{'type':'stage','stage':'rtl','status':'running'},"
        "{'type':'agent_action','agent':'agent2','phase':'rtl','status':'running','action':'Codex request started','summary':'Calling fake model for rtl_review'},"
        "{'type':'agent_action','agent':'agent2','phase':'rtl','status':'pass','action':'Codex response received','summary':'Model returned rtl_review evidence','metric':{'latency_s':0.2,'total_tokens':13}},"
        "{'type':'metric','agent':'agent2','status':'info','name':'codex_total_tokens','value':13},"
        f"{{'type':'artifact','agent':'agent2','phase':'rtl','path':{str(rtl)!r},'kind':'sv','bytes':25}},"
        "{'type':'stage','stage':'rtl','status':'pass'},"
        "{'type':'done','status':'SIGNOFF_READY'}"
        "];"
        "[print(json.dumps(e), flush=True) or time.sleep(0.02) for e in events]"
    )
    return [sys.executable, "-c", code]


def _slow_runner_command(_command_name: str, _payload: dict[str, Any]) -> list[str]:
    return [sys.executable, "-c", "import json,time; print(json.dumps({'type':'stage','stage':'planning','status':'running'}), flush=True); time.sleep(20)"]


async def _valid_probe(_endpoint: str, _model: str, _api_key: str) -> dict[str, bool | str]:
    return {"ok": True, "message": "Connection OK"}


async def _invalid_probe(_endpoint: str, _model: str, _api_key: str) -> dict[str, bool | str]:
    return {"ok": False, "message": "Access denied: API key is invalid, expired, or unauthorized."}


def _configure_fake_secret(evidence_dir: Path) -> None:
    config.CODEX_CONFIG_PATH = evidence_dir / "codex_api.local.json"
    config.STUDIO_SETTINGS_PATH = evidence_dir / "settings.json"
    config._write_json(config.CODEX_CONFIG_PATH, {"base_url": "http://fake.local/v1", "model": "fake/codex", "api_key": FAKE_SECRET})


def _scan_for_secret(paths: list[Path]) -> list[str]:
    leaks: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if FAKE_SECRET in text or "Bearer " in text or "Authorization" in text:
            leaks.append(str(path))
    return leaks

def _unbalanced_pairs(events: list[dict[str, Any]], kind: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        event_type = str(event.get("event_type") or "")
        corr = str(event.get("correlation_id") or "")
        if event_type == f"{kind}_start":
            counts[corr] = counts.get(corr, 0) + 1
        elif event_type == f"{kind}_done":
            counts[corr] = counts.get(corr, 0) - 1
    return {corr: count for corr, count in counts.items() if count != 0}


def _wait_for_terminal(client: TestClient, timeout_s: float = 5.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    state: dict[str, Any] = {}
    while time.time() < deadline:
        response = client.get("/api/runs/current_state")
        state = response.json()
        if state.get("status") in {"done", "failed", "paused", "stopped"}:
            return state
        time.sleep(0.05)
    return state


def _case_happy_path(evidence_dir: Path, failures: list[str]) -> dict[str, Any]:
    server_module._probe_openai_compatible_endpoint = _valid_probe
    output_dir = evidence_dir / "happy_path_run"
    manager = RunnerManager(root=ROOT, command_builder=_fake_runner_command)
    with TestClient(create_app(manager, connection_test_cooldown_s=0.0, runtime_watchdog_enabled=False)) as client:
        started = client.post(
            "/api/runs/start",
            json={
                "requirement": "Generate a 32-bit APB UART CPU and proceed to Agent2 RTL.",
                "project_name": "v68_happy",
                "output_dir": str(output_dir),
                "startPolicy": "fresh",
            },
        )
        _write_json(evidence_dir / "happy_start_response.json", started.json())
        if started.status_code != 200:
            failures.append(f"happy start failed: {started.status_code} {started.text}")
            return {"ok": False}
        state = _wait_for_terminal(client)
        runtime = client.get(f"/api/runs/{started.json()['run_id']}/runtime")
        _write_json(evidence_dir / "happy_current_state.json", state)
        _write_json(evidence_dir / "happy_runtime_response.json", runtime.json())
        if runtime.status_code != 200:
            failures.append(f"runtime api failed: {runtime.status_code} {runtime.text}")
            return {"ok": False}
    traces = output_dir / "reports" / "traces"
    required_files = [
        traces / "runtime_events.jsonl",
        traces / "runtime_session_manifest.json",
        traces / "runtime_recovery_report.json",
        traces / "runtime_invariant_report.json",
        traces / "runtime_replay_report.json",
        traces / "runtime_debug_summary.json",
    ]
    for path in required_files:
        if not path.is_file():
            failures.append(f"missing runtime file: {path}")
    events = [json.loads(line) for line in (traces / "runtime_events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    event_types = {str(event.get("event_type")) for event in events}
    for required in {"run_init", "job_started", "agent_start", "model_call_start", "model_call_done", "tool_call_start", "tool_call_done", "artifact_written", "job_done"}:
        if required not in event_types:
            failures.append(f"missing runtime event type: {required}")
    invariant = config._read_json(traces / "runtime_invariant_report.json")
    if invariant.get("ok") is not True:
        failures.append(f"invariant failed: {invariant.get('failures')}")
    tool_pairs = _unbalanced_pairs(events, "tool_call")
    model_pairs = _unbalanced_pairs(events, "model_call")
    if tool_pairs or model_pairs:
        failures.append(f"unbalanced runtime pairs: tool={tool_pairs} model={model_pairs}")
    replay = config._read_json(traces / "runtime_replay_report.json")
    if not replay.get("by_source_type"):
        failures.append("runtime replay missing by_source_type source labels")
    recovery = config._read_json(traces / "runtime_recovery_report.json")
    if recovery.get("reason") != "none" or recovery.get("action") != "none":
        failures.append(f"happy path recovery report should be no-op: {recovery}")
    leaks = _scan_for_secret(required_files)
    if leaks:
        failures.append(f"secret leak in runtime files: {leaks}")
    return {"ok": not failures, "run_id": started.json()["run_id"], "event_types": sorted(event_types)}


def _case_invalid_key(evidence_dir: Path, failures: list[str]) -> dict[str, Any]:
    server_module._probe_openai_compatible_endpoint = _invalid_probe
    manager = RunnerManager(root=ROOT, command_builder=_fake_runner_command)
    with TestClient(create_app(manager, connection_test_cooldown_s=0.0, runtime_watchdog_enabled=False)) as client:
        response = client.post("/api/runs/start", json={"requirement": "Generate APB UART", "project_name": "invalid_key", "output_dir": str(evidence_dir / "invalid_key")})
    _write_json(evidence_dir / "invalid_key_response.json", {"status": response.status_code, "body": response.json()})
    if response.status_code != 409 or "Access denied" not in response.text:
        failures.append(f"invalid key did not fail early: {response.status_code} {response.text}")
    if manager.running():
        failures.append("invalid key spawned runner")
    return {"status": response.status_code}


def _case_corrupt_manifest(evidence_dir: Path, failures: list[str]) -> dict[str, Any]:
    output_dir = evidence_dir / "corrupt_manifest"
    traces = output_dir / "reports" / "traces"
    traces.mkdir(parents=True, exist_ok=True)
    (traces / "runtime_session_manifest.json").write_text("{bad json", encoding="utf-8")
    manager = RunnerManager(root=ROOT)
    manager.state = RunState(run_id="v68-corrupt", status="running", project_name="corrupt", output_dir=str(output_dir))
    with TestClient(create_app(manager, runtime_watchdog_enabled=False)) as client:
        response = client.get("/api/runs/v68-corrupt/runtime")
    _write_json(evidence_dir / "corrupt_manifest_response.json", {"status": response.status_code, "body": response.json()})
    if response.status_code != 409:
        failures.append(f"corrupt manifest did not report 409: {response.status_code}")
    if not (traces / "runtime_recovery_report.json").is_file():
        failures.append("corrupt manifest did not write recovery report")
    return {"status": response.status_code}


def _case_watchdog(evidence_dir: Path, failures: list[str]) -> dict[str, Any]:
    async def scenario() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        manager = RunnerManager(root=ROOT, command_builder=_slow_runner_command)
        output_dir = evidence_dir / "watchdog_run"
        await manager.start({"requirement": "Generate APB UART", "project_name": "watchdog", "output_dir": str(output_dir), "start_policy": "fresh"})
        await asyncio.sleep(0.05)
        first = await manager.check_watchdog(stale_timeout_s=0.0)
        second = await manager.check_watchdog(stale_timeout_s=0.0)
        await manager.stop()
        return manager.state.snapshot(), first, second

    state, first, second = asyncio.run(scenario())
    _write_json(evidence_dir / "watchdog_response.json", {"state": state, "first": first, "second": second})
    if not first or first[0].get("event_type") != "watchdog_timeout":
        failures.append("watchdog did not emit timeout")
    if second:
        failures.append("watchdog emitted duplicate timeout")
    if not (Path(state["output_dir"]) / "reports" / "traces" / "runtime_recovery_report.json").is_file():
        failures.append("watchdog did not write recovery report")
    return {"first": len(first), "second": len(second)}


def main() -> int:
    if EVIDENCE_ROOT.exists():
        shutil.rmtree(EVIDENCE_ROOT)
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    _configure_fake_secret(EVIDENCE_ROOT)
    failures: list[str] = []
    summary = {
        "schema_version": "studio.v68_runtime_tracking_uat.v1",
        "evidence_dir": str(EVIDENCE_ROOT),
        "happy_path": _case_happy_path(EVIDENCE_ROOT, failures),
        "invalid_key": _case_invalid_key(EVIDENCE_ROOT, failures),
        "corrupt_manifest": _case_corrupt_manifest(EVIDENCE_ROOT, failures),
        "watchdog": _case_watchdog(EVIDENCE_ROOT, failures),
        "failures": failures,
    }
    _write_json(EVIDENCE_ROOT / "uat_summary.json", summary)
    if failures:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 1
    print(f"V6.8 runtime tracking UAT passed: {EVIDENCE_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
