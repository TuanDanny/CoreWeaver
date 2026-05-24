import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from studio.backend import config
from studio.backend.agent_service import AgentService
from studio.backend.event_hub import EventHub
from studio.backend.job_models import AgentJob
from studio.backend.job_queue import InProcessJobQueue, JobQueueFull
from studio.backend.runner import RunnerManager
from studio.backend.server import create_app
import studio.backend.server as server_module
from semiconductor_swarm.agents.agent1_planning.architect import generate_architecture_spec
from semiconductor_swarm.contracts.validators import build_agent1_to_agent2_contract


def _configure_owner_key(tmp_path: Path, monkeypatch, key: str = "secret-key") -> None:
    monkeypatch.setattr(config, "CODEX_CONFIG_PATH", tmp_path / "codex_api.local.json")
    monkeypatch.setattr(config, "STUDIO_SETTINGS_PATH", tmp_path / "settings.json")
    config._write_json(config.CODEX_CONFIG_PATH, {"base_url": "http://local.test/v1", "model": "model-a", "api_key": key})


def _quick_runner_command(_command_name, _payload):
    return ["python", "-c", "import json; print(json.dumps({'type':'done','status':'OK'}), flush=True)"]


def test_agent_job_contract_serializes_without_secret():
    job = AgentJob(type="full_swarm_run", requirement="make APB UART", credential_ref="owner")
    payload = job.to_public_dict()

    assert payload["job_id"]
    assert payload["status"] == "queued"
    assert payload["type"] == "full_swarm_run"
    assert payload["credential_ref"] == "owner"
    assert "secret" not in payload


def test_in_process_queue_fifo_cancel_full_and_subscription():
    async def scenario():
        q = InProcessJobQueue(maxsize=2)
        events = q.subscribe_events()
        first = AgentJob(type="debug_bundle", project_name="first")
        second = AgentJob(type="debug_bundle", project_name="second")
        await q.enqueue(first)
        queued_event = await events.get()
        assert queued_event["type"] == "job_queued"
        await q.enqueue(second)
        try:
            await q.enqueue(AgentJob(type="debug_bundle", project_name="third"))
            raise AssertionError("queue should reject beyond maxsize")
        except JobQueueFull:
            pass
        await q.cancel(first.job_id)
        claimed = await q.claim_next()
        assert claimed.job_id == second.job_id
        await q.mark_status(second.job_id, "running")
        await q.mark_status(second.job_id, "completed", artifact_refs=["artifact.json"])
        assert (await q.get(second.job_id)).artifact_refs == ["artifact.json"]

    asyncio.run(scenario())


def test_job_api_lists_health_and_providers(tmp_path, monkeypatch):
    _configure_owner_key(tmp_path, monkeypatch)
    reports = tmp_path / "outputs" / "demo" / "reports"
    reports.mkdir(parents=True)
    (reports / "architecture_plan.md").write_text("# plan", encoding="utf-8")
    client = TestClient(create_app(RunnerManager(root=tmp_path, command_builder=_quick_runner_command)))

    created = client.post(
        "/api/jobs",
        json={"type": "debug_bundle", "project_name": "demo", "output_dir": str(tmp_path / "outputs" / "demo")},
    )
    listed = client.get("/api/jobs")
    health = client.get("/api/health")
    settings = client.get("/api/settings")

    assert created.status_code == 200
    assert created.json()["type"] == "debug_bundle"
    assert listed.status_code == 200
    assert listed.json()["queueHealth"]["backend"] == "in_process"
    assert health.json()["queueHealth"]["jobs"] >= 1
    assert any(provider["id"] == "openai_compatible" and provider["enabled"] for provider in settings.json()["modelProviders"])
    assert all(provider["enabled"] is False for provider in settings.json()["modelProviders"] if provider["id"] in {"openai", "gemini", "grok"})


def test_start_route_creates_job_id_and_never_leaks_secret(tmp_path, monkeypatch):
    _configure_owner_key(tmp_path, monkeypatch)

    async def fake_probe(_endpoint: str, _model: str, _api_key: str):
        return {"ok": True, "message": "Connection OK"}

    monkeypatch.setattr(server_module, "_probe_openai_compatible_endpoint", fake_probe)
    with TestClient(create_app(RunnerManager(root=tmp_path, command_builder=_quick_runner_command))) as client:
        started = client.post(
            "/api/runs/start",
            json={
                "requirement": "Generate APB UART",
                "project_name": "demo",
                "output_dir": str(tmp_path / "outputs" / "demo"),
                "startPolicy": "fresh",
            },
        )
        assert started.status_code == 200
        jobs = client.get("/api/jobs").json()["jobs"]
        stopped = client.post(f"/api/runs/{started.json()['run_id']}/stop")

        assert stopped.status_code == 200
        assert started.json()["job_id"]
        assert "secret-key" not in started.text
        assert any(job["job_id"] == started.json()["job_id"] for job in jobs)


def test_agent_service_process_exit_nonzero_marks_job_failed(tmp_path):
    async def scenario():
        hub = EventHub()
        manager = RunnerManager(root=tmp_path, command_builder=_quick_runner_command)
        service = AgentService(runner=manager, event_hub=hub)
        job = AgentJob(type="debug_bundle", project_name="demo", output_dir=str(tmp_path / "outputs" / "demo"))
        await service.queue.enqueue(job)
        await service.queue.mark_status(job.job_id, "running", run_id="run-1")
        await service.publish_runner_event({"type": "process_exit", "job_id": job.job_id, "run_id": "run-1", "returncode": 2})
        return await service.queue.get(job.job_id)

    job = asyncio.run(scenario())

    assert job.status == "failed"
    assert "process exited 2" in str(job.error)


def test_draft_workers_write_debug_bundle_and_agent2_boundary(tmp_path):
    async def scenario():
        hub = EventHub()
        service = AgentService(runner=RunnerManager(root=tmp_path, command_builder=_quick_runner_command), event_hub=hub)
        output = tmp_path / "outputs" / "demo"
        reports = output / "reports"
        traces = reports / "traces"
        traces.mkdir(parents=True)
        spec = build_agent1_to_agent2_contract(generate_architecture_spec("Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral", "demo"))
        (reports / "architecture_plan.md").write_text("# locked plan", encoding="utf-8")
        (reports / "agent1").mkdir(parents=True)
        (reports / "agent1" / "agent1_to_agent2_contract").write_text(json.dumps(spec, indent=2), encoding="utf-8")
        (traces / "agent1_intake_trace.jsonl").write_text('{"node_id":"AGENT1.READY_GATE"}\n', encoding="utf-8")
        debug = AgentJob(type="debug_bundle", project_name="demo", output_dir=str(output))
        rtl = AgentJob(type="agent2_rtl_draft", project_name="demo", output_dir=str(output))
        await service.queue.enqueue(debug)
        await service.queue.enqueue(rtl)
        await service._run_debug_bundle(debug)
        await service._run_agent2_rtl_draft(rtl)
        return await service.queue.get(debug.job_id), await service.queue.get(rtl.job_id), reports

    debug, rtl, reports = asyncio.run(scenario())

    assert debug.status == "completed"
    assert rtl.status == "completed"
    assert (reports / "debug_bundle_manifest.json").is_file()
    assert (reports.parent / "rtl" / "demo_top.sv").is_file()
    assert (reports.parent / "rtl" / "reports" / "rtl_manifest.json").is_file()
    assert (reports.parent / "rtl" / "reports" / "agent2_rtl_draft_summary.json").is_file()
