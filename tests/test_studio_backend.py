import asyncio
import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from studio.backend import config
from studio.backend import attachments as attachment_module
from studio.backend.event_hub import EventHub, MAX_EVENT_BYTES
from studio.backend.runner import RunState, RunnerManager
import studio.backend.runner as runner_module
from studio.backend import secret_admin
import studio.backend.server as server_module
from studio.backend.server import create_app
from studio.backend.run_manifest import MANIFEST_NAME
from studio.backend.runtime_tracking import (
    build_runtime_flow_coverage_report,
    build_runtime_invariant_report,
    load_runtime_bundle,
    read_debug_issues,
    RuntimeTracker,
)
import app.swarm_runner as swarm_runner

def _configure_owner_key(tmp_path, monkeypatch, key: str = "secret-key") -> None:
    local_cfg = tmp_path / "codex_api.local.json"
    local_settings = tmp_path / "settings.json"
    monkeypatch.setattr(config, "CODEX_CONFIG_PATH", local_cfg)
    monkeypatch.setattr(config, "STUDIO_SETTINGS_PATH", local_settings)
    config._write_json(local_cfg, {"base_url": "http://local.test/v1", "model": "model-a", "api_key": key})


def test_health_endpoint_reports_ok():
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_cors_allows_vite_local_origin():
    client = TestClient(create_app())

    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"

def test_cors_allows_attachment_delete_from_vite_origin():
    client = TestClient(create_app())

    response = client.options(
        "/api/attachments/stage/draft-id/attachment-id",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "DELETE",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_cors_and_websocket_allow_alternate_local_dev_port():
    client = TestClient(create_app(heartbeat_interval_s=0.01))

    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://127.0.0.1:5174",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5174"
    with client.websocket_connect("/ws/runs/current", headers={"origin": "http://127.0.0.1:5174"}) as websocket:
        assert websocket.receive_json()["type"] == "ping"

def test_cors_rejects_nonlocal_origin():
    client = TestClient(create_app())

    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_missing_api_key_connection_fails_truthfully(tmp_path, monkeypatch):
    local_cfg = tmp_path / "codex_api.local.json"
    monkeypatch.setattr(config, "CODEX_CONFIG_PATH", local_cfg)
    client = TestClient(create_app())

    response = client.post("/api/settings/test-connection", json={"endpoint": "http://localhost:20128/v1", "model": "cx/gpt-5.5", "apiKeyRef": "owner"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing API key for credential ref: owner"


def test_connection_probe_runs_with_redacted_saved_key_ref(tmp_path, monkeypatch):
    local_cfg = tmp_path / "codex_api.local.json"
    local_settings = tmp_path / "settings.json"
    monkeypatch.setattr(config, "CODEX_CONFIG_PATH", local_cfg)
    monkeypatch.setattr(config, "STUDIO_SETTINGS_PATH", local_settings)
    seen: dict[str, str] = {}

    async def fake_probe(endpoint: str, model: str, api_key: str):
        seen["endpoint"] = endpoint
        seen["model"] = model
        seen["api_key"] = api_key
        return {"ok": True, "message": "Connection OK"}

    monkeypatch.setattr(server_module, "_probe_openai_compatible_endpoint", fake_probe)
    config._write_json(local_cfg, {"base_url": "http://local.test/v1", "model": "model-a", "api_key": "secret-key"})
    client = TestClient(create_app(connection_test_cooldown_s=0.0))

    response = client.post(
        "/api/settings/test-connection",
        json={"endpoint": "http://local.test/v1", "model": "model-a", "apiKeyRef": "owner"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "Connection OK"}
    assert seen == {"endpoint": "http://local.test/v1", "model": "model-a", "api_key": "secret-key"}
    assert "Phase 7" not in response.text
    assert "secret-key" not in response.text


def test_connection_probe_rejects_invalid_endpoint_without_key_leak():
    result = asyncio.run(server_module._probe_openai_compatible_endpoint("file:///tmp/socket", "model-a", "secret-key"))

    assert result == {"ok": False, "message": "Invalid endpoint URL"}
    assert "secret-key" not in str(result)


def test_connection_uses_chat_completions_not_models(monkeypatch):
    seen: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "OK"}}]}

    class FakeAsyncClient:
        def __init__(self, timeout):
            seen["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, headers, json):
            seen["url"] = url
            seen["authorization"] = headers.get("Authorization")
            seen["payload"] = json
            return FakeResponse()

        async def get(self, *_args, **_kwargs):
            raise AssertionError("GET /models must not be used for auth proof")

    monkeypatch.setattr(server_module.httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(server_module._probe_openai_compatible_endpoint("http://local.test/v1", "model-a", "secret-key"))

    assert result == {"ok": True, "message": "Connection OK"}
    assert seen["timeout"] == server_module.SETTINGS_PROBE_TIMEOUT_S
    assert seen["url"] == "http://local.test/v1/chat/completions"
    assert seen["authorization"] == "Bearer secret-key"
    assert seen["payload"]["max_tokens"] == 1


def test_connection_uses_httpx_async_client_not_requests():
    source = Path(server_module.__file__).read_text(encoding="utf-8")

    assert "httpx.AsyncClient" in source
    assert "requests." not in source
    assert "import requests" not in source


def test_connection_unauthorized_reports_api_key_error(monkeypatch):
    class FakeResponse:
        status_code = 401

    class FakeAsyncClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(server_module.httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(server_module._probe_openai_compatible_endpoint("http://local.test/v1", "model-a", "secret-key"))

    assert result == {"ok": False, "message": "Access denied: API key is invalid, expired, or unauthorized."}
    assert "secret-key" not in str(result)


def test_connection_refused_reports_network_error(monkeypatch):
    class FakeAsyncClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            raise server_module.httpx.ConnectError("refused")

    monkeypatch.setattr(server_module.httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(server_module._probe_openai_compatible_endpoint("http://local.test/v1", "model-a", "secret-key"))

    assert result == {"ok": False, "message": "Network error: cannot connect to endpoint. Check whether 9Router is running."}
    assert "secret-key" not in str(result)


def test_connection_rate_limit_returns_429_without_provider_call(tmp_path, monkeypatch):
    local_cfg = tmp_path / "codex_api.local.json"
    monkeypatch.setattr(config, "CODEX_CONFIG_PATH", local_cfg)
    config._write_json(local_cfg, {"base_url": "http://local.test/v1", "model": "model-a", "api_key": "secret-key"})
    calls = 0

    async def fake_probe(_endpoint: str, _model: str, _api_key: str):
        nonlocal calls
        calls += 1
        return {"ok": True, "message": "Connection OK"}

    monkeypatch.setattr(server_module, "_probe_openai_compatible_endpoint", fake_probe)
    client = TestClient(create_app(connection_test_cooldown_s=2.0))

    first = client.post("/api/settings/test-connection", json={"endpoint": "http://local.test/v1", "model": "model-a", "apiKeyRef": "owner"})
    second = client.post("/api/settings/test-connection", json={"endpoint": "http://local.test/v1", "model": "model-a", "apiKeyRef": "owner"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"] == "Test connection cooldown active"
    assert calls == 1


def test_settings_response_never_contains_api_key(tmp_path, monkeypatch):
    local_cfg = tmp_path / "codex_api.local.json"
    local_settings = tmp_path / "settings.json"
    monkeypatch.setattr(config, "CODEX_CONFIG_PATH", local_cfg)
    monkeypatch.setattr(config, "STUDIO_SETTINGS_PATH", local_settings)
    config._write_json(local_cfg, {"base_url": "http://one/v1", "model": "model-a", "api_key": "secret-key"})
    client = TestClient(create_app())

    response = client.get("/api/settings")

    assert response.status_code == 200
    text = response.text
    assert "secret-key" not in text
    payload = response.json()
    assert "apiKey" not in payload
    assert "api_key" not in payload
    assert payload["activeKeyRef"] == "owner"
    assert payload["credentialRefs"][0]["hasSecret"] is True


def test_post_settings_rejects_raw_api_key_from_web(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CODEX_CONFIG_PATH", tmp_path / "codex_api.local.json")
    monkeypatch.setattr(config, "STUDIO_SETTINGS_PATH", tmp_path / "settings.json")
    client = TestClient(create_app())

    response = client.post(
        "/api/settings",
        json={
            "endpoint": "http://two/v1",
            "model": "model-b",
            "apiKey": "secret-key",
            "checkpoint_db": str(tmp_path / "b.sqlite"),
            "output_root": str(tmp_path / "outputs2"),
            "activeKeyRef": "owner",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Raw API key is not accepted by web settings"


def test_settings_save_preserves_local_secret_and_stores_active_ref(tmp_path, monkeypatch):
    local_cfg = tmp_path / "codex_api.local.json"
    local_settings = tmp_path / "settings.json"
    monkeypatch.setattr(config, "CODEX_CONFIG_PATH", local_cfg)
    monkeypatch.setattr(config, "STUDIO_SETTINGS_PATH", local_settings)
    config._write_json(local_cfg, {"base_url": "http://old/v1", "model": "old-model", "api_key": "secret-key"})
    client = TestClient(create_app())

    response = client.post(
        "/api/settings",
        json={
            "endpoint": "http://three/v1",
            "model": "model-c",
            "checkpoint_db": str(tmp_path / "c.sqlite"),
            "output_root": str(tmp_path / "outputs3"),
            "activeKeyRef": "owner",
        },
    )

    assert response.status_code == 200
    codex_data = config._read_json(local_cfg)
    ui_data = config._read_json(local_settings)
    assert codex_data["api_key"] == "secret-key"
    assert codex_data["base_url"] == "http://three/v1"
    assert codex_data["model"] == "model-c"
    assert ui_data["active_key_ref"] == "owner"
    assert response.json()["activeKeyRef"] == "owner"

def test_settings_roundtrip_payload_from_frontend_posts_successfully(tmp_path, monkeypatch):
    _configure_owner_key(tmp_path, monkeypatch)
    client = TestClient(create_app())
    current = client.get("/api/settings").json()
    frontend_payload = {
        "endpoint": current["endpoint"],
        "model": current["model"],
        "checkpoint_db": current["checkpoint_db"],
        "output_root": current["output_root"],
        "activeKeyRef": current["activeKeyRef"],
    }

    response = client.post("/api/settings", json=frontend_payload)

    assert response.status_code == 200
    payload = response.json()
    assert payload["activeKeyRef"] == "owner"
    assert payload["credentialHealth"]["owner"] in {"unchecked", "valid", "invalid"}
    assert "secret-key" not in response.text

def test_credential_health_updates_after_auth_failure(tmp_path, monkeypatch):
    _configure_owner_key(tmp_path, monkeypatch)

    async def fake_probe(_endpoint: str, _model: str, _api_key: str):
        return {"ok": False, "message": "Access denied: API key is invalid, expired, or unauthorized."}

    monkeypatch.setattr(server_module, "_probe_openai_compatible_endpoint", fake_probe)
    client = TestClient(create_app(connection_test_cooldown_s=0.0))

    response = client.post("/api/settings/test-connection", json={"endpoint": "http://local.test/v1", "model": "model-a", "apiKeyRef": "owner"})
    settings = client.get("/api/settings")

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert settings.json()["credentialHealth"]["owner"] == "invalid"
    assert "secret-key" not in settings.text

def test_credential_health_response_never_contains_secret(tmp_path, monkeypatch):
    _configure_owner_key(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/settings")

    assert response.status_code == 200
    assert response.json()["credentialHealth"] == {"owner": "unchecked"}
    assert "secret-key" not in response.text

def test_secret_admin_updates_owner_key_without_printing_secret(tmp_path, monkeypatch, capsys):
    local_cfg = tmp_path / "codex_api.local.json"
    monkeypatch.setattr(config, "CODEX_CONFIG_PATH", local_cfg)
    monkeypatch.setattr(secret_admin.getpass, "getpass", lambda _prompt: "new-secret")

    exit_code = secret_admin.main(["set-owner-key"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert config._read_json(local_cfg)["api_key"] == "new-secret"
    assert "new-secret" not in captured.out
    assert "new-secret" not in captured.err


def _fake_runner_command(_command_name, _payload):
    return [
        "python",
        "-c",
        "import json,time; print(json.dumps({'type':'stage','stage':'planning','status':'running'}), flush=True); time.sleep(10)",
    ]


def _fake_quick_runner_command(_command_name, _payload):
    return ["python", "-c", "import json; print(json.dumps({'type':'done','status':'OK'}), flush=True)"]

def _fake_pause_then_exit_command(_command_name, _payload):
    return [
        "python",
        "-c",
        "import json,time; print(json.dumps({'type':'pause','action_required':'REQUIREMENT_CLARIFICATION','message':'pause'}), flush=True); time.sleep(0.25)",
    ]

def _fake_runid_echo_command(_command_name, _payload):
    return [
        "python",
        "-c",
        "import json,os; print(json.dumps({'type':'log','level':'info','message':'hello'}), flush=True)",
    ]

def _fake_slow_intake_command(_command_name, _payload):
    return [
        "python",
        "-c",
        "import json,time; print(json.dumps({'type':'agent_action','agent':'agent1','status':'running','action':'Intake'}), flush=True); time.sleep(30); print(json.dumps({'type':'agent_action','agent':'agent2','status':'running','action':'late RTL'}), flush=True)",
    ]

def _fake_model_call_hang_command(_command_name, _payload):
    return [
        "python",
        "-c",
        "import json,time; print(json.dumps({'type':'agent_action','agent':'agent1','phase':'planning','status':'running','action':'Codex request started','summary':'Calling cx/gpt-5.5 at http://localhost:20128/v1'}), flush=True); time.sleep(30)",
    ]

def _fake_runtime_tracking_command(_command_name, payload):
    artifact = Path(payload["output_dir"]) / "reports" / "architecture_plan.md"
    code = (
        "import json,pathlib;"
        f"p=pathlib.Path({str(artifact)!r});"
        "p.parent.mkdir(parents=True, exist_ok=True);"
        "p.write_text('plan', encoding='utf-8');"
        "events=["
        "{'type':'agent_action','agent':'agent1','phase':'planning','status':'running','action':'Codex request started','summary':'Calling cx/gpt-5.5 at http://localhost:20128/v1'},"
        "{'type':'agent_action','agent':'agent1','phase':'planning','status':'pass','action':'Codex response received','summary':'Model returned architecture evidence','metric':{'latency_s':0.25,'total_tokens':3}},"
        "{'type':'agent_handoff','from_agent':'agent1','to_agent':'agent2','contract':'agent1_to_agent2','status':'pass','summary':'Architecture contract released'},"
        "{'type':'metric','agent':'agent1','status':'info','name':'codex_total_tokens','value':3},"
        f"{{'type':'artifact','agent':'agent1','path':{str(artifact)!r},'kind':'markdown','bytes':4}},"
        "{'type':'done','status':'OK'}"
        "];"
        "[print(json.dumps(e), flush=True) for e in events]"
    )
    return ["python", "-c", code]


def test_start_rejects_second_active_run_and_stop_kills_fake_runner(tmp_path):
    async def scenario():
        manager = RunnerManager(root=tmp_path, command_builder=_fake_runner_command)
        payload = {"requirement": "demo", "project_name": "demo", "output_dir": str(tmp_path / "outputs" / "demo")}
        started = await manager.start(payload)
        assert started["status"] == "running"
        assert manager.running()
        try:
            await manager.start(payload)
            raise AssertionError("second start should fail")
        except RuntimeError as exc:
            assert "already active" in str(exc)
        stopped = await manager.stop()
        assert stopped["status"] == "stopped"

    asyncio.run(scenario())


def test_start_waits_for_paused_process_to_close_before_new_run(tmp_path):
    async def scenario():
        manager = RunnerManager(root=tmp_path, command_builder=_fake_pause_then_exit_command)
        first = await manager.start({"requirement": "chat", "project_name": "chat", "output_dir": str(tmp_path / "outputs" / "chat"), "start_policy": "fresh"})
        assert first["status"] == "running"
        deadline = time.time() + 2
        while manager.state.status != "paused" and time.time() < deadline:
            await asyncio.sleep(0.01)
        assert manager.state.status == "paused"
        second = await manager.start({"requirement": "design", "project_name": "design", "output_dir": str(tmp_path / "outputs" / "design"), "start_policy": "fresh"})
        assert second["project_name"] == "design"
        assert second["status"] == "running"
        await manager.stop()

    asyncio.run(scenario())


def test_runner_injects_key_ref_secret_only_via_env(tmp_path, monkeypatch):
    local_cfg = tmp_path / "codex_api.local.json"
    monkeypatch.setattr(config, "CODEX_CONFIG_PATH", local_cfg)
    config._write_json(local_cfg, {"base_url": "http://local.test/v1", "model": "model-a", "api_key": "secret-key"})
    captured: dict[str, object] = {}

    class EmptyStream:
        async def readline(self):
            return b""

    class FakeProcess:
        pid = 12345
        returncode = None
        stdout = EmptyStream()
        stderr = EmptyStream()

        async def wait(self):
            self.returncode = 0
            return 0

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -9

    async def fake_create_subprocess_exec(*command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return FakeProcess()

    monkeypatch.setattr(runner_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    async def scenario():
        manager = RunnerManager(root=tmp_path)
        state = await manager.start({"requirement": "demo", "project_name": "demo", "apiKeyRef": "owner"})
        await asyncio.sleep(0)
        return state

    state = asyncio.run(scenario())
    command_text = " ".join(str(part) for part in captured["command"])
    env = captured["env"]

    assert env["SWARM_CODEX_API_KEY"] == "secret-key"
    assert env["AGENT1_CODEX_API_KEY"] == "secret-key"
    assert env["AGENT2_CODEX_API_KEY"] == "secret-key"
    assert "secret-key" not in command_text
    assert "secret-key" not in str(state)
    assert state["apiKeyRef"] == "owner"

def test_runtime_tracking_writes_events_manifest_and_secret_safe_summary(tmp_path):
    async def scenario():
        output_dir = tmp_path / "outputs" / "runtime"
        manager = RunnerManager(root=tmp_path, command_builder=_fake_runtime_tracking_command)
        state = await manager.start({"requirement": "Generate APB UART", "project_name": "runtime", "output_dir": str(output_dir), "apiKeyRef": "owner", "start_policy": "fresh"})
        deadline = time.time() + 2
        while (manager.running() or manager.state.status in {"starting", "running"}) and time.time() < deadline:
            await asyncio.sleep(0.02)
        await manager._drain_reader_tasks()
        return state, output_dir

    state, output_dir = asyncio.run(scenario())
    traces = output_dir / "reports" / "traces"
    events = [json.loads(line) for line in (traces / "runtime_events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    manifest = config._read_json(traces / "runtime_session_manifest.json")
    recovery = config._read_json(traces / "runtime_recovery_report.json")
    invariant = config._read_json(traces / "runtime_invariant_report.json")
    replay = config._read_json(traces / "runtime_replay_report.json")
    summary = config._read_json(traces / "runtime_debug_summary.json")
    text = "\n".join(path.read_text(encoding="utf-8") for path in [traces / "runtime_events.jsonl", traces / "runtime_session_manifest.json", traces / "runtime_debug_summary.json"])

    assert state["run_id"]
    assert events[0]["event_type"] == "run_init"
    assert any(event["event_type"] == "model_call_start" for event in events)
    assert any(event["event_type"] == "model_call_done" for event in events)
    assert any(event["event_type"] == "tool_call_start" for event in events)
    assert any(event["event_type"] == "tool_call_done" for event in events)
    assert any(event["event_type"] == "artifact_written" for event in events)
    assert manifest["run_id"] == state["run_id"]
    assert manifest["status"] == "done"
    assert manifest["active_agent"] == ""
    assert manifest["active_node_id"] == ""
    assert manifest["metrics"]["byAgent"]["agent1"]["callCount"] >= 1
    assert recovery["reason"] == "none"
    assert recovery["action"] == "none"
    assert recovery["after_status"] == "done"
    assert invariant["ok"] is True
    assert replay["event_count"] == len(events)
    assert replay["by_source_type"]
    assert summary["event_count"] == len(events)
    assert "secret-key" not in text
    assert "Bearer " not in text

def test_runtime_api_returns_manifest_and_recent_events(tmp_path, monkeypatch):
    _configure_owner_key(tmp_path, monkeypatch)

    async def fake_probe(_endpoint: str, _model: str, _api_key: str):
        return {"ok": True, "message": "Connection OK"}

    monkeypatch.setattr(server_module, "_probe_openai_compatible_endpoint", fake_probe)
    output_dir = tmp_path / "outputs" / "runtime_api"
    manager = RunnerManager(root=tmp_path, command_builder=_fake_runtime_tracking_command)
    with TestClient(create_app(manager, connection_test_cooldown_s=0.0, runtime_watchdog_enabled=False)) as client:
        started = client.post("/api/runs/start", json={"requirement": "Generate APB UART", "project_name": "runtime_api", "output_dir": str(output_dir), "startPolicy": "fresh"})
        assert started.status_code == 200
        run_id = started.json()["run_id"]
        response = client.get(f"/api/runs/{run_id}/runtime")
        stopped = client.post(f"/api/runs/{run_id}/stop")
        assert response.status_code == 200
        assert stopped.status_code == 200
        payload = response.json()
        assert payload["manifest"]["run_id"] == run_id
        assert payload["recentEvents"]
        assert payload["recoveryReport"]["reason"] == "none"
        assert "secret-key" not in response.text

def test_runtime_api_hydrates_custom_indexed_output_after_restart(tmp_path):
    output_dir = tmp_path / "custom_runtime_root" / "custom_run"
    tracker = RuntimeTracker(root=tmp_path)
    state = {
        "run_id": "run-custom",
        "job_id": "job-custom",
        "status": "done",
        "project_name": "custom",
        "output_dir": str(output_dir),
        "planning_mode": "normal",
    }
    tracker.initialize_run(state)
    tracker.record_source_event({"type": "done", "status": "OK"}, state)
    manager = RunnerManager(root=tmp_path)
    client = TestClient(create_app(manager, runtime_watchdog_enabled=False))

    current = client.get("/api/runs/current_state")
    runtime = client.get("/api/runs/run-custom/runtime")

    assert current.status_code == 200
    assert current.json()["run_id"] == "run-custom"
    assert current.json()["output_dir"] == str(output_dir)
    assert runtime.status_code == 200
    assert runtime.json()["manifest"]["run_id"] == "run-custom"
    assert runtime.json()["recoveryReport"]["reason"] == "none"

def test_runtime_api_reports_corrupt_active_manifest(tmp_path):
    output_dir = tmp_path / "outputs" / "corrupt"
    traces = output_dir / "reports" / "traces"
    traces.mkdir(parents=True)
    (traces / "runtime_session_manifest.json").write_text("{bad json", encoding="utf-8")
    manager = RunnerManager(root=tmp_path)
    manager.state = RunState(run_id="run-corrupt", status="running", project_name="corrupt", output_dir=str(output_dir))
    client = TestClient(create_app(manager, runtime_watchdog_enabled=False))

    response = client.get("/api/runs/run-corrupt/runtime")

    assert response.status_code == 409
    assert "manifest corrupt" in response.json()["detail"]
    assert (traces / "runtime_recovery_report.json").is_file()

def test_runtime_watchdog_marks_stale_run_failed_once(tmp_path):
    async def scenario():
        manager = RunnerManager(root=tmp_path, command_builder=_fake_runner_command)
        await manager.start({"requirement": "demo", "project_name": "watchdog", "output_dir": str(tmp_path / "outputs" / "watchdog"), "start_policy": "fresh"})
        await asyncio.sleep(0.05)
        first = await manager.check_watchdog(stale_timeout_s=0.0)
        second = await manager.check_watchdog(stale_timeout_s=0.0)
        await manager.stop()
        return manager, first, second

    manager, first, second = asyncio.run(scenario())

    assert first
    assert first[0]["event_type"] == "watchdog_timeout"
    assert second == []
    assert (Path(manager.state.output_dir) / "reports" / "traces" / "runtime_recovery_report.json").is_file()

def test_runtime_watchdog_classifies_active_model_call_stale(tmp_path):
    async def scenario():
        manager = RunnerManager(root=tmp_path, command_builder=_fake_model_call_hang_command)
        await manager.start({"requirement": "demo", "project_name": "watchdog_model", "output_dir": str(tmp_path / "outputs" / "watchdog_model"), "start_policy": "fresh"})
        deadline = time.time() + 2
        while time.time() < deadline:
            events = (Path(manager.state.output_dir) / "reports" / "traces" / "runtime_events.jsonl").read_text(encoding="utf-8", errors="replace")
            if "model_call_start" in events:
                break
            await asyncio.sleep(0.01)
        first = await manager.check_watchdog(stale_timeout_s=0.0)
        await manager.stop()
        return first

    first = asyncio.run(scenario())

    assert first
    assert first[0]["node_id"] == "WATCHDOG.MODEL_CALL_STALE"
    assert first[0]["error"]["stale_kind"] == "model_call_stale"

def test_runtime_watchdog_recent_backend_progress_is_not_stale(tmp_path):
    async def scenario():
        manager = RunnerManager(root=tmp_path, command_builder=_fake_runner_command)
        await manager.start({"requirement": "demo", "project_name": "watchdog_recent", "output_dir": str(tmp_path / "outputs" / "watchdog_recent"), "start_policy": "fresh"})
        await asyncio.sleep(0.05)
        first = await manager.check_watchdog(stale_timeout_s=3600.0)
        await manager.stop()
        return first

    assert asyncio.run(scenario()) == []

def test_runtime_invariant_fails_strict_tool_pair_left_open(tmp_path):
    output_dir = tmp_path / "outputs" / "strict_tool"
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-strict", "status": "done", "project_name": "strict", "output_dir": str(output_dir)}
    tracker.initialize_run(state)
    tracker._write_events(
        state,
        [
            tracker._build_event(
                state=state,
                event_type="tool_call_start",
                status="running",
                message="tool started",
                agent="agent1",
                phase="planning",
                node_id="TOOL.TEST",
                correlation_id="tool:run-strict:agent1:TOOL.TEST:demo:1",
                source={"type": "test"},
            )
        ],
    )

    report = build_runtime_invariant_report(output_dir)

    assert report["ok"] is False
    assert any(item["code"] == "start_without_done" and item["kind"] == "tool_call" for item in report["failures"])

def test_runtime_invariant_fails_tool_done_without_start(tmp_path):
    output_dir = tmp_path / "outputs" / "strict_tool_done"
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-strict-done", "status": "done", "project_name": "strict", "output_dir": str(output_dir)}
    tracker.initialize_run(state)
    tracker._write_events(
        state,
        [
            tracker._build_event(
                state=state,
                event_type="tool_call_done",
                status="passed",
                message="tool done",
                agent="agent1",
                phase="planning",
                node_id="TOOL.TEST",
                correlation_id="tool:missing",
                source={"type": "test"},
            )
        ],
    )

    report = build_runtime_invariant_report(output_dir)

    assert report["ok"] is False
    assert any(item["code"] == "done_without_start" and item["kind"] == "tool_call" for item in report["failures"])


def test_runtime_invariant_warns_model_done_without_start(tmp_path):
    output_dir = tmp_path / "outputs" / "model_done_no_start"
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-model-no-start", "status": "paused", "project_name": "strict", "output_dir": str(output_dir)}
    tracker.initialize_run(state)
    tracker._write_events(
        state,
        [
            tracker._build_event(
                state=state,
                event_type="model_call_done",
                status="passed",
                message="model done",
                agent="agent1",
                phase="planning",
                node_id="AGENT1.MODEL_CALL",
                correlation_id="model:missing",
                source={"type": "agent_action"},
            )
        ],
    )

    report = build_runtime_invariant_report(output_dir)

    assert report["ok"] is True
    assert not any(item["kind"] == "model_call" for item in report["failures"])
    assert any(item["code"] == "done_without_start" and item["kind"] == "model_call" for item in report["warnings"])


def test_runtime_invariant_findings_are_written_to_debug_issues(tmp_path):
    output_dir = tmp_path / "outputs" / "strict_tool_debug"
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-strict-debug", "status": "done", "project_name": "strict", "output_dir": str(output_dir)}
    tracker.initialize_run(state)
    tracker._write_events(
        state,
        [
            tracker._build_event(
                state=state,
                event_type="tool_call_done",
                status="passed",
                message="tool done",
                agent="agent1",
                phase="planning",
                node_id="TOOL.TEST",
                correlation_id="tool:missing",
                source={"type": "test"},
            )
        ],
    )

    issues = read_debug_issues(output_dir)

    assert any(issue["source"] == "runtime" and issue["code"] == "done_without_start" for issue in issues)
    assert all("secret-key" not in json.dumps(issue) for issue in issues)


def test_runtime_tracker_pairs_concurrent_model_calls_fifo(tmp_path):
    output_dir = tmp_path / "outputs" / "model_fifo"
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-model-fifo", "status": "paused", "project_name": "model", "output_dir": str(output_dir)}
    tracker.initialize_run(state)
    for _ in range(3):
        tracker.record_source_event(
            {"type": "agent_action", "agent": "agent1", "action": "Codex request started", "summary": "Calling cx/gpt-5.5 at http://localhost:20128/v1", "status": "running"},
            state,
        )
    for _ in range(3):
        tracker.record_source_event(
            {"type": "agent_action", "agent": "agent1", "action": "Codex response received", "summary": "Model cx/gpt-5.5 returned architecture evidence in 1.0s", "status": "pass", "metric": {"latency_s": 1.0}},
            state,
        )

    report = build_runtime_invariant_report(output_dir)

    assert not any(item.get("kind") == "model_call" for item in report["failures"])
    assert not any(item.get("kind") == "model_call" for item in report["warnings"])


def test_agent1_cluster_manifest_records_group_session_metrics(tmp_path):
    output_dir = tmp_path / "outputs" / "cluster_manifest"
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-cluster", "status": "running", "project_name": "cluster", "output_dir": str(output_dir)}
    tracker.initialize_run(state)
    tracker.record_source_event({"type": "agent1_council_mode_selected", "mode": "group_session"}, state)
    tracker.record_source_event({"type": "agent1_topology_loaded", "topology_hash": "topo-1"}, state)
    tracker.record_source_event({"type": "agent1_cluster_assignment", "cluster_assignment_hash": "assign-1", "group_id": "M02", "leaf_expert_ids": ["L04", "L05"]}, state)
    tracker.record_source_event({"type": "agent1_group_session_start", "span_id": "span-m02", "group_id": "M02", "manager_id": "M02", "leaf_expert_ids": ["L04", "L05"], "model_call_id": "model-m02"}, state)
    tracker.record_source_event({"type": "agent1_group_session_done", "span_id": "span-m02", "group_id": "M02", "manager_id": "M02", "latency_s": 1.25, "total_tokens": 321, "estimated_cost_usd": 0.0123}, state)

    manifest = json.loads((output_dir / "reports" / "traces" / "runtime_session_manifest.json").read_text(encoding="utf-8"))
    cluster = manifest["agent1_cluster_council"]

    assert cluster["mode"] == "group_session"
    assert cluster["topology_hash"] == "topo-1"
    assert cluster["cluster_assignment_hash"] == "assign-1"
    assert cluster["group_sessions"]["span-m02"]["status"] == "passed"
    assert cluster["group_sessions"]["span-m02"]["metrics"]["total_tokens"] == 321

def test_agent1_cluster_invariant_flags_group_start_without_done(tmp_path):
    output_dir = tmp_path / "outputs" / "cluster_missing_done"
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-cluster-missing", "status": "done", "project_name": "cluster", "output_dir": str(output_dir)}
    tracker.initialize_run(state)
    tracker.record_source_event({"type": "agent1_group_session_start", "span_id": "span-m03", "group_id": "M03"}, state)

    report = build_runtime_invariant_report(output_dir)
    issues = read_debug_issues(output_dir)

    assert any(item["code"] == "agent1_group_start_without_done" for item in report["failures"])
    assert any(issue["code"] == "agent1_group_start_without_done" for issue in issues)

def test_agent1_cluster_invariant_flags_principal_review_before_group_done(tmp_path):
    output_dir = tmp_path / "outputs" / "cluster_review_early"
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-cluster-early", "status": "running", "project_name": "cluster", "output_dir": str(output_dir)}
    tracker.initialize_run(state)
    tracker.record_source_event({"type": "agent1_group_session_start", "span_id": "span-m04", "group_id": "M04"}, state)
    tracker.record_source_event({"type": "agent1_principal_group_review", "span_id": "span-p01", "parent_span_id": "span-m04"}, state)

    report = build_runtime_invariant_report(output_dir)

    assert any(item["code"] == "agent1_principal_review_before_groups_done" for item in report["failures"])

def test_agent1_cluster_invariant_flags_bad_retry_group(tmp_path):
    output_dir = tmp_path / "outputs" / "cluster_bad_retry"
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-cluster-retry", "status": "running", "project_name": "cluster", "output_dir": str(output_dir)}
    tracker.initialize_run(state)
    tracker.record_source_event({"type": "agent1_cluster_assignment", "group_id": "M02"}, state)
    tracker.record_source_event({"type": "agent1_group_retry", "target_group_id": "M99"}, state)

    report = build_runtime_invariant_report(output_dir)

    assert any(item["code"] == "agent1_retry_target_group_unknown" for item in report["failures"])

def test_agent1_cluster_invariant_accepts_skipped_retry_group_list(tmp_path):
    output_dir = tmp_path / "outputs" / "cluster_skipped_retry_list"
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-cluster-retry-skip", "status": "paused", "project_name": "cluster", "output_dir": str(output_dir)}
    tracker.initialize_run(state)
    tracker.record_source_event({"type": "agent1_cluster_assignment", "group_id": "M02"}, state)
    tracker.record_source_event({"type": "agent1_cluster_assignment", "group_id": "M03"}, state)
    tracker.record_source_event({"type": "agent1_group_retry", "status": "skipped", "target_group_ids": ["M02", "M03"]}, state)

    report = build_runtime_invariant_report(output_dir)

    assert not any(item["code"] == "agent1_retry_target_group_unknown" for item in report["failures"])

def test_agent1_cluster_invariant_blocks_agent2_with_unresolved_challenge(tmp_path):
    output_dir = tmp_path / "outputs" / "cluster_unresolved_challenge"
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-cluster-challenge", "status": "running", "project_name": "cluster", "output_dir": str(output_dir)}
    tracker.initialize_run(state)
    tracker.record_source_event({"type": "agent1_cross_group_challenge", "challenge_id": "c1", "owner_group_id": "M04", "status": "open"}, state)
    tracker.record_source_event({"type": "agent_handoff", "from_agent": "agent1", "to_agent": "agent2", "contract": "agent1_to_agent2", "status": "pass"}, state)

    report = build_runtime_invariant_report(output_dir)

    assert any(item["code"] == "agent2_handoff_with_unresolved_agent1_challenge" for item in report["failures"])

def test_agent1_cluster_invariant_flags_clarification_answer_unknown_question(tmp_path):
    output_dir = tmp_path / "outputs" / "cluster_bad_clarification"
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-cluster-clarify", "status": "paused", "project_name": "cluster", "output_dir": str(output_dir)}
    tracker.initialize_run(state)
    tracker.record_source_event({"type": "agent1_clarification_answer", "question_id": "missing-q", "answer_id": "a1"}, state)

    report = build_runtime_invariant_report(output_dir)

    assert any(item["code"] == "agent1_clarification_answer_unknown_question" for item in report["failures"])

def test_runtime_flow_coverage_tracks_start_preflight_process_agent1_agent2(tmp_path):
    output_dir = tmp_path / "outputs" / "flow_ok"
    plan_path = output_dir / "reports" / "architecture_plan.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text("# Plan\n", encoding="utf-8")
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-flow-ok", "status": "running", "project_name": "flow", "output_dir": str(output_dir)}
    tracker.initialize_run(state)
    tracker.record_source_event({"type": "start_preflight", "status": "pass", "attachment_ids": []}, state)
    tracker.record_source_event({"type": "process_start", "pid": 1234}, state)
    tracker.record_source_event({"type": "agent_action", "agent": "agent1", "action": "Extract explicit requirements", "summary": "Agent1 intake started", "status": "running"}, state)
    tracker.record_source_event({"type": "agent1_council_mode_selected", "mode": "group_session"}, state)
    tracker.record_source_event({"type": "agent1_topology_loaded", "topology_hash": "topo-flow"}, state)
    tracker.record_source_event({"type": "agent1_cluster_assignment", "cluster_assignment_hash": "assign-flow", "group_id": "M01"}, state)
    tracker.record_source_event({"type": "agent1_group_session_start", "span_id": "span-m01", "group_id": "M01"}, state)
    tracker.record_source_event({"type": "agent1_group_session_done", "span_id": "span-m01", "group_id": "M01"}, state)
    tracker.record_source_event({"type": "artifact", "agent": "agent1", "path": str(plan_path), "message": "architecture_plan.md"}, state)
    tracker.record_source_event({"type": "agent_handoff", "from_agent": "agent1", "to_agent": "agent2", "contract": "agent1_to_agent2", "status": "pass", "artifact_refs": [str(plan_path)]}, state)
    tracker.record_source_event({"type": "agent_action", "agent": "agent2", "action": "Generating APB/RTL collateral", "summary": "Agent2 RTL started", "status": "running"}, state)

    report = build_runtime_flow_coverage_report(output_dir)
    segments = report["segments"]

    assert segments["credential_preflight"]["status"] == "completed"
    assert segments["runner_process"]["status"] == "started"
    assert segments["agent1_cluster"]["status"] == "completed"
    assert segments["agent1_artifacts"]["status"] == "completed"
    assert segments["agent2_gate"]["status"] == "completed"
    assert segments["agent2_rtl"]["status"] == "started"
    assert report["canonical_span_model"]["run_span_id"] == "run:run-flow-ok"
    assert report["canonical_span_model"]["process_span_id"].startswith("job:")

def test_runtime_flow_coverage_skips_cluster_segments_for_agent1_simple_fast_path(tmp_path):
    output_dir = tmp_path / "outputs" / "flow_fast_path"
    plan_path = output_dir / "reports" / "architecture_plan.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text("# Plan\n", encoding="utf-8")
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-flow-fast", "status": "done", "project_name": "flow", "output_dir": str(output_dir)}
    tracker.initialize_run(state)
    tracker.record_source_event({"type": "start_preflight", "status": "pass", "attachment_ids": []}, state)
    tracker.record_source_event({"type": "process_start", "pid": 1234}, state)
    tracker.record_source_event(
        {
            "type": "trace_event",
            "event_type": "node_completed",
            "status": "pass",
            "agent": "agent1",
            "node_id": "AGENT1.A1_00_SIMPLE_DESIGN_FAST_PATH",
            "summary": "classification=DESIGN_READY; peripherals=uart,spi,i2c,gpio,timer",
        },
        state,
    )
    tracker.record_source_event({"type": "artifact", "agent": "agent1", "path": str(plan_path), "message": "architecture_plan.md"}, state)
    tracker.record_source_event({"type": "agent_handoff", "from_agent": "agent1", "to_agent": "agent2", "contract": "agent1_to_agent2", "status": "pass", "artifact_refs": [str(plan_path)]}, state)
    tracker.record_source_event({"type": "agent_action", "agent": "agent2", "action": "Generating APB/RTL collateral", "summary": "Agent2 RTL started", "status": "pass"}, state)
    tracker.record_source_event({"type": "process_exit", "returncode": 0}, state)
    trace_dir = output_dir / "reports" / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    (trace_dir / "debug_issues.jsonl").write_text(
        json.dumps({"code": "flow_missing_required_span", "flow_segment": "agent1_cluster", "severity": "warning"}) + "\n",
        encoding="utf-8",
    )

    report = build_runtime_flow_coverage_report(output_dir)
    invariant = build_runtime_invariant_report(output_dir)

    assert report["segments"]["agent1_cluster"]["status"] == "skipped"
    assert report["segments"]["agent1_guardrail"]["status"] == "skipped"
    assert report["segments"]["agent1_cluster"]["last_issue_code"] == ""
    assert not any(item.get("flow_segment") in {"agent1_cluster", "agent1_guardrail"} for item in invariant["warnings"])

def test_runtime_flow_coverage_flags_missing_span(tmp_path):
    output_dir = tmp_path / "outputs" / "flow_missing"
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-flow-missing", "status": "done", "project_name": "flow", "output_dir": str(output_dir)}
    tracker.initialize_run(state)

    report = build_runtime_invariant_report(output_dir)
    issues = read_debug_issues(output_dir)

    assert any(item["code"] == "flow_missing_required_span" and item["flow_segment"] == "runner_process" for item in report["failures"])
    assert any(issue["code"] == "flow_missing_required_span" and issue.get("flow_segment") == "runner_process" for issue in issues)

def test_runtime_flow_coverage_blocks_agent2_when_agent1_artifact_stale(tmp_path):
    output_dir = tmp_path / "outputs" / "flow_stale_agent1"
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-flow-stale", "status": "running", "project_name": "flow", "output_dir": str(output_dir)}
    tracker.initialize_run(state)
    tracker.record_source_event({"type": "start_preflight", "status": "pass"}, state)
    tracker.record_source_event({"type": "process_start", "pid": 44}, state)
    tracker.record_source_event({"type": "agent_handoff", "from_agent": "agent1", "to_agent": "agent2", "contract": "agent1_to_agent2", "status": "pass"}, state)

    report = build_runtime_invariant_report(output_dir)

    assert any(item["code"] == "flow_agent2_handoff_with_stale_agent1_artifact" for item in report["failures"])

def test_runtime_flow_coverage_detects_attachment_payload_mismatch(tmp_path):
    output_dir = tmp_path / "outputs" / "flow_attachment_mismatch"
    inputs_dir = output_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = inputs_dir / "attachments_manifest.json"
    manifest_path.write_text(json.dumps({"attachments": [{"id": "committed-b"}]}), encoding="utf-8")
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-flow-attach", "status": "running", "project_name": "flow", "output_dir": str(output_dir), "attachment_manifest_path": str(manifest_path)}
    tracker.initialize_run(state)
    tracker.record_source_event({"type": "start_preflight", "status": "pass", "attachment_ids": ["requested-a"]}, state)

    report = build_runtime_invariant_report(output_dir)

    assert any(item["code"] == "flow_attachment_payload_mismatch" for item in report["failures"])

def test_runtime_flow_coverage_detects_non_monotonic_websocket_replay(tmp_path):
    output_dir = tmp_path / "outputs" / "flow_ws"
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-flow-ws", "status": "running", "project_name": "flow", "output_dir": str(output_dir)}
    tracker.initialize_run(state)
    tracker.record_source_event({"type": "websocket_replay", "status": "pass", "event_id": 10, "message": "replay 10"}, state)
    tracker.record_source_event({"type": "websocket_replay", "status": "pass", "event_id": 7, "message": "replay 7"}, state)

    report = build_runtime_invariant_report(output_dir)

    assert any(item["code"] == "flow_non_monotonic_websocket_replay" for item in report["failures"])

def test_runtime_flow_coverage_report_never_contains_secret(tmp_path):
    output_dir = tmp_path / "outputs" / "flow_secret"
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-flow-secret", "status": "running", "project_name": "flow", "output_dir": str(output_dir), "apiKeyRef": "sk-secret123456789"}
    tracker.initialize_run(state)
    tracker.record_source_event({"type": "start_preflight", "status": "pass", "message": "Authorization: Bearer sk-secret123456789"}, state)

    report = build_runtime_flow_coverage_report(output_dir)
    text = json.dumps(report)

    assert "sk-secret123456789" not in text
    assert "Authorization" not in text

def test_runtime_flow_coverage_detects_missing_artifact_file(tmp_path):
    output_dir = tmp_path / "outputs" / "flow_missing_artifact"
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-flow-artifact", "status": "running", "project_name": "flow", "output_dir": str(output_dir)}
    tracker.initialize_run(state)
    tracker.record_source_event({"type": "artifact", "agent": "agent1", "path": str(output_dir / "reports" / "missing_plan.md"), "message": "missing artifact"}, state)

    report = build_runtime_invariant_report(output_dir)

    assert any(item["code"] == "flow_missing_artifact_file" for item in report["failures"])

def test_runtime_bundle_hydrates_agent1_signoff_artifacts(tmp_path):
    output_dir = tmp_path / "outputs" / "signoff_bundle"
    agent1 = output_dir / "reports" / "agent1"
    agent1.mkdir(parents=True)
    certificate = {
        "schema_version": "agent1_final_signoff_certificate/v1",
        "decision": "PASS",
        "handoff_allowed": True,
        "profile": "strict",
        "score": 100.0,
        "finding_summary": {"blocking_count": 0, "warning_count": 0, "blocking_codes": []},
        "waiver_summary": {"applied": [], "rejected": []},
        "benchmark_summary": {"case_count": 110, "false_pass_count": 0, "must_not_pass_violation_count": 0},
    }
    gate_report = {
        "schema_version": "agent1_signoff_gate_report/v1",
        "passed": True,
        "gate_results": {"G00": {"status": "PASS", "finding_codes": []}},
        "findings": [],
    }
    benchmark = {"schema_version": "agent1_signoff_benchmark_report/v1", "case_count": 110, "false_pass_count": 0}
    (agent1 / "agent1_final_signoff_certificate.json").write_text(json.dumps(certificate), encoding="utf-8")
    (agent1 / "agent1_signoff_gate_report.json").write_text(json.dumps(gate_report), encoding="utf-8")
    (agent1 / "agent1_signoff_benchmark_report.json").write_text(json.dumps(benchmark), encoding="utf-8")
    (agent1 / "agent1_signoff_false_pass_report.json").write_text(json.dumps({"items": []}), encoding="utf-8")

    bundle = load_runtime_bundle(output_dir)

    assert bundle["signoff"]["certificate"]["decision"] == "PASS"
    assert bundle["signoff"]["gateReport"]["gate_results"]["G00"]["status"] == "PASS"
    assert bundle["signoff"]["benchmarkReport"]["case_count"] == 110
    assert bundle["signoff"]["artifactStatus"]["certificate"]["exists"] is True
    assert bundle["signoff"]["state"] == "PASSED"
    assert "api_key" not in json.dumps(bundle["signoff"]).lower()

def test_runtime_bundle_marks_signoff_not_reached_without_certificate(tmp_path):
    output_dir = tmp_path / "outputs" / "not_reached"
    (output_dir / "reports" / "agent1").mkdir(parents=True)

    bundle = load_runtime_bundle(output_dir)

    assert bundle["signoff"]["state"] == "NOT_REACHED"
    assert bundle["signoff"]["certificate"] is None

def test_runtime_bundle_marks_partial_before_signoff(tmp_path):
    output_dir = tmp_path / "outputs" / "partial"
    agent1 = output_dir / "reports" / "agent1"
    agent1.mkdir(parents=True)
    (agent1 / "agent1_partial_evidence.json").write_text(json.dumps({"schema_version": "agent1.partial_evidence.v1"}), encoding="utf-8")

    bundle = load_runtime_bundle(output_dir)

    assert bundle["signoff"]["state"] == "PARTIAL"

def test_failed_agent_action_is_not_recorded_as_model_call(tmp_path):
    output_dir = tmp_path / "outputs" / "failed_agent_action"
    tracker = RuntimeTracker(root=tmp_path)
    state = {"run_id": "run-agent-action", "status": "paused", "project_name": "agent", "output_dir": str(output_dir)}
    tracker.initialize_run(state)

    tracker.record_source_event(
        {
            "type": "agent_action",
            "agent": "agent1",
            "action": "L04 CPU/ISA Expert completed",
            "summary": "No CPU ISA selected. DV register model fields remain in the peripheral contract.",
            "status": "fail",
        },
        state,
    )

    events = (output_dir / "reports" / "traces" / "runtime_events.jsonl").read_text(encoding="utf-8")

    assert "model_call_done" not in events
    assert "AGENT1.L04_CPU_ISA_EXPERT" in events


def test_stop_during_intake_kills_process_tree_without_late_agent2_events(tmp_path):
    events = []

    async def scenario():
        async def sink(event):
            events.append(event)

        manager = RunnerManager(root=tmp_path, command_builder=_fake_slow_intake_command, event_sink=sink)
        await manager.start({"requirement": "demo", "project_name": "demo", "output_dir": str(tmp_path / "outputs" / "demo"), "start_policy": "fresh"})
        await asyncio.sleep(0.2)
        stopped = await manager.stop()
        assert stopped["status"] == "stopped"

    asyncio.run(scenario())

    assert any(event.get("agent") == "agent1" for event in events)
    assert not any(event.get("agent") == "agent2" for event in events)
    assert sum(1 for event in events if event.get("type") == "process_exit") == 1


class _FakeStartManager:
    def __init__(self):
        self.start_count = 0
        self.state = type("State", (), {"run_id": "", "snapshot": lambda _self: {"run_id": "fake", "status": "running"}})()

    async def start(self, _payload):
        self.start_count += 1
        self.state.run_id = "fake"
        return {"run_id": "fake", "status": "running"}

    async def stop(self):
        return {"run_id": "fake", "status": "stopped"}

    async def shutdown(self):
        return None

def test_start_preflight_blocks_missing_credential(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CODEX_CONFIG_PATH", tmp_path / "codex_api.local.json")
    monkeypatch.setattr(config, "STUDIO_SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.delenv("SWARM_CODEX_API_KEY", raising=False)
    monkeypatch.delenv("AGENT1_CODEX_API_KEY", raising=False)
    manager = _FakeStartManager()
    client = TestClient(create_app(manager))

    response = client.post("/api/runs/start", json={"requirement": "demo", "project_name": "demo"})

    assert response.status_code == 409
    assert "Credential owner is invalid" in response.json()["detail"]
    assert manager.start_count == 0
    assert client.get("/api/settings").json()["credentialHealth"]["owner"] == "missing"

def test_start_preflight_blocks_invalid_credential(tmp_path, monkeypatch):
    _configure_owner_key(tmp_path, monkeypatch)

    async def fake_probe(_endpoint: str, _model: str, _api_key: str):
        return {"ok": False, "message": "Access denied: API key is invalid, expired, or unauthorized."}

    monkeypatch.setattr(server_module, "_probe_openai_compatible_endpoint", fake_probe)
    manager = _FakeStartManager()
    client = TestClient(create_app(manager, connection_test_cooldown_s=0.0))

    response = client.post("/api/runs/start", json={"requirement": "demo", "project_name": "demo"})

    assert response.status_code == 409
    assert "Access denied" in response.json()["detail"]
    assert manager.start_count == 0
    assert client.get("/api/settings").json()["credentialHealth"]["owner"] == "invalid"

def test_start_does_not_spawn_runner_when_credential_invalid(tmp_path, monkeypatch):
    _configure_owner_key(tmp_path, monkeypatch)

    async def fake_probe(_endpoint: str, _model: str, _api_key: str):
        return {"ok": False, "message": "Access denied: API key is invalid, expired, or unauthorized."}

    monkeypatch.setattr(server_module, "_probe_openai_compatible_endpoint", fake_probe)
    manager = _FakeStartManager()
    client = TestClient(create_app(manager, connection_test_cooldown_s=0.0))
    test = client.post("/api/settings/test-connection", json={"endpoint": "http://local.test/v1", "model": "model-a", "apiKeyRef": "owner"})
    assert test.status_code == 200

    response = client.post("/api/runs/start", json={"requirement": "demo", "project_name": "demo"})

    assert response.status_code == 409
    assert manager.start_count == 0

def test_process_exit_nonzero_preserves_failed_state():
    manager = RunnerManager(command_builder=_fake_quick_runner_command)
    manager.state.status = "failed"

    manager.state.apply_event({"type": "process_exit", "returncode": 1})

    assert manager.state.status == "failed"

def test_process_exit_nonzero_clears_stale_plan_review_pause():
    manager = RunnerManager(command_builder=_fake_quick_runner_command)
    manager.state.status = "paused"
    manager.state.pause = {"action_required": "PLAN_REVIEW"}
    manager.state.current_plan_path = "reports/architecture_plan.md"

    manager.state.apply_event({"type": "process_exit", "returncode": 1})

    assert manager.state.status == "failed"
    assert manager.state.pause is None
    assert manager.state.current_plan_path is None

def test_snapshot_sanitizes_failed_stale_plan_review_pause():
    manager = RunnerManager(command_builder=_fake_quick_runner_command)
    manager.state.status = "failed"
    manager.state.pause = {"action_required": "PLAN_REVIEW"}
    manager.state.current_plan_path = "reports/architecture_plan.md"

    snapshot = manager.state.snapshot()

    assert snapshot["pause"] is None
    assert snapshot["current_plan_path"] is None

def test_snapshot_sanitizes_running_stale_plan_review_pause():
    manager = RunnerManager(command_builder=_fake_quick_runner_command)
    manager.state.status = "running"
    manager.state.pause = {"action_required": "PLAN_REVIEW"}
    manager.state.current_plan_path = "reports/architecture_plan.md"

    snapshot = manager.state.snapshot()

    assert snapshot["pause"] is None
    assert snapshot["current_plan_path"] is None

def test_snapshot_sanitizes_stopped_paused_nodes():
    manager = RunnerManager(command_builder=_fake_quick_runner_command)
    manager.state.status = "stopped"
    manager.state.pause = {"action_required": "PLAN_REVIEW"}
    manager.state.current_plan_path = "reports/architecture_plan.md"
    manager.state.stages["planning"] = "paused"
    manager.state.agents["agent1"]["status"] = "paused"

    snapshot = manager.state.snapshot()

    assert snapshot["pause"] is None
    assert snapshot["current_plan_path"] is None
    assert snapshot["stages"]["planning"] == "stopped"
    assert snapshot["agents"]["agent1"]["status"] == "stopped"

def test_process_start_clears_stale_plan_review_pause():
    manager = RunnerManager(command_builder=_fake_quick_runner_command)
    manager.state.status = "paused"
    manager.state.pause = {"action_required": "PLAN_REVIEW"}
    manager.state.current_plan_path = "reports/architecture_plan.md"

    manager.state.apply_event({"type": "process_start", "pid": 1234})

    assert manager.state.status == "running"
    assert manager.state.pause is None
    assert manager.state.current_plan_path is None

def test_non_plan_pause_clears_current_plan_path():
    manager = RunnerManager(command_builder=_fake_quick_runner_command)
    manager.state.current_plan_path = "reports/architecture_plan.md"

    manager.state.apply_event({"type": "pause", "action_required": "CONFLICT_REQUIRED", "message": "conflict"})

    assert manager.state.status == "paused"
    assert manager.state.current_plan_path is None

def test_process_exit_zero_preserves_paused_state():
    manager = RunnerManager(command_builder=_fake_quick_runner_command)
    manager.state.status = "paused"
    manager.state.pause = {"action_required": "PLAN_REVIEW"}
    manager.state.stages["planning"] = "paused"

    manager.state.apply_event({"type": "process_exit", "returncode": 0})

    assert manager.state.status == "paused"
    assert manager.state.pause == {"action_required": "PLAN_REVIEW"}
    assert manager.state.stages["planning"] == "paused"

def test_state_from_runtime_manifest_restores_latest_pause_payload(tmp_path):
    output_dir = tmp_path / "hydrate_run"
    trace_dir = output_dir / "reports" / "traces"
    trace_dir.mkdir(parents=True)
    plan_path = output_dir / "reports" / "architecture_plan.md"
    (trace_dir / "runtime_events.jsonl").write_text(
        json.dumps(
            {
                "type": "runtime_event",
                "event_type": "node_done",
                "status": "paused",
                "run_id": "run-hydrate",
                "job_id": "job-hydrate",
                "node_id": "PAUSE.PLAN_REVIEW",
                "message": "Architecture plan is ready.",
                "artifact_refs": [str(plan_path)],
                "source": {"type": "pause", "action_required": "PLAN_REVIEW"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "run_id": "run-hydrate",
        "job_id": "job-hydrate",
        "status": "paused",
        "project_name": "hydrate",
        "output_dir": str(output_dir),
        "active_node_id": "RUNNER.PROCESS_EXIT",
        "agents": {},
    }

    snapshot = server_module._state_from_runtime_manifest(manifest)

    assert snapshot["status"] == "paused"
    assert snapshot["pause"]["action_required"] == "PLAN_REVIEW"
    assert snapshot["pause"]["plan_path"] == str(plan_path)
    assert snapshot["current_plan_path"] == str(plan_path)
    assert snapshot["stages"]["planning"] == "paused"
    assert snapshot["agents"]["agent1"]["status"] == "paused"

def test_state_from_runtime_manifest_restores_hitl_required_pause(tmp_path):
    output_dir = tmp_path / "hitl_run"
    trace_dir = output_dir / "reports" / "traces"
    trace_dir.mkdir(parents=True)
    checklist = output_dir / "reports" / "agent1_requirement_clarification.md"
    (trace_dir / "runtime_events.jsonl").write_text(
        json.dumps(
            {
                "type": "runtime_event",
                "event_type": "node_done",
                "status": "paused",
                "run_id": "run-hitl",
                "job_id": "job-hitl",
                "node_id": "PAUSE.HITL_REQUIRED",
                "message": "Agent 1 infra hard stop.",
                "artifact_refs": [str(checklist)],
                "source": {"type": "pause", "action_required": "HITL_REQUIRED"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "run_id": "run-hitl",
        "job_id": "job-hitl",
        "status": "paused",
        "project_name": "hitl",
        "output_dir": str(output_dir),
        "active_node_id": "RUNNER.PROCESS_EXIT",
        "agents": {},
    }

    snapshot = server_module._state_from_runtime_manifest(manifest)

    assert snapshot["pause"]["action_required"] == "HITL_REQUIRED"
    assert snapshot["current_plan_path"] is None
    assert snapshot["stages"]["planning"] == "paused"
    assert snapshot["stages"]["hitl"] == "paused"
    assert snapshot["agents"]["agent1"]["status"] == "paused"

def test_state_from_runtime_manifest_infers_hitl_required_from_partial_plan_event(tmp_path):
    output_dir = tmp_path / "partial_run"
    trace_dir = output_dir / "reports" / "traces"
    trace_dir.mkdir(parents=True)
    checklist = output_dir / "reports" / "agent1_requirement_clarification.md"
    (trace_dir / "runtime_events.jsonl").write_text(
        json.dumps(
            {
                "type": "runtime_event",
                "event_type": "node_done",
                "status": "paused",
                "run_id": "run-partial",
                "job_id": "job-partial",
                "node_id": "AGENT1.PARTIAL_PLAN_GENERATED",
                "message": "Agent 1 stopped before release; partial plan and recovery checklist are available.",
                "artifact_refs": [str(checklist)],
                "source": {"type": "agent_action", "status": "paused", "action": "Partial plan generated"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "run_id": "run-partial",
        "job_id": "job-partial",
        "status": "paused",
        "project_name": "partial",
        "output_dir": str(output_dir),
        "active_node_id": "RUNNER.PROCESS_EXIT",
        "agents": {},
    }

    snapshot = server_module._state_from_runtime_manifest(manifest)

    assert snapshot["pause"]["action_required"] == "HITL_REQUIRED"
    assert snapshot["pause"]["artifact_path"] == str(checklist)
    assert snapshot["current_plan_path"] is None
    assert snapshot["stages"]["planning"] == "paused"
    assert snapshot["stages"]["hitl"] == "paused"

def test_paused_agent_action_synthesizes_requirement_clarification_pause():
    manager = RunnerManager(command_builder=_fake_quick_runner_command)
    manager.state.run_id = "run-clarify"
    manager.state.job_id = "job-clarify"

    manager.state.apply_event(
        {
            "type": "agent_action",
            "agent": "agent1",
            "status": "paused",
            "action": "Requirement clarification needed",
            "summary": "Need workload and power budget.",
            "artifact": "reports/agent1_requirement_clarification.md",
        }
    )
    manager.state.apply_event({"type": "process_exit", "returncode": 0})

    snapshot = manager.state.snapshot()
    assert snapshot["status"] == "paused"
    assert snapshot["pause"]["action_required"] == "REQUIREMENT_CLARIFICATION"
    assert snapshot["pause"]["plan_path"] == "reports/agent1_requirement_clarification.md"
    assert snapshot["current_plan_path"] is None

def test_generic_paused_agent_action_waits_for_specific_pause_artifact():
    manager = RunnerManager(command_builder=_fake_quick_runner_command)
    manager.state.run_id = "run-clarify"
    manager.state.job_id = "job-clarify"

    manager.state.apply_event(
        {
            "type": "agent_action",
            "agent": "agent1",
            "status": "paused",
            "action": "A1.00 Intake Council",
            "summary": "classification=DESIGN_NEEDS_CLARIFICATION; consensus=0.7",
        }
    )
    assert manager.state.pause is None

    manager.state.apply_event(
        {
            "type": "agent_action",
            "agent": "agent1",
            "status": "paused",
            "action": "Requirement clarification needed",
            "summary": "Need reset polarity.",
            "artifact": "reports/agent1_requirement_clarification.md",
        }
    )

    snapshot = manager.state.snapshot()
    assert snapshot["pause"]["action_required"] == "REQUIREMENT_CLARIFICATION"
    assert snapshot["pause"]["artifact_path"] == "reports/agent1_requirement_clarification.md"

def test_paused_agent_action_synthesizes_conflict_pause_with_artifact():
    manager = RunnerManager(command_builder=_fake_quick_runner_command)
    manager.state.run_id = "run-conflict"
    manager.state.job_id = "job-conflict"

    manager.state.apply_event(
        {
            "type": "agent_action",
            "agent": "agent1",
            "status": "paused",
            "action": "Conflict resolution needed",
            "summary": "Reset polarity conflict.",
            "artifact": "reports/agent1_requirement_clarification.md",
        }
    )
    manager.state.apply_event({"type": "process_exit", "returncode": 0})

    snapshot = manager.state.snapshot()
    assert snapshot["status"] == "paused"
    assert snapshot["pause"]["action_required"] == "CONFLICT_REQUIRED"
    assert snapshot["pause"]["artifact_path"] == "reports/agent1_requirement_clarification.md"
    assert snapshot["current_plan_path"] is None

def test_paused_agent_action_synthesizes_non_design_pause_with_artifact():
    manager = RunnerManager(command_builder=_fake_quick_runner_command)
    manager.state.run_id = "run-non-design"

    manager.state.apply_event(
        {
            "type": "agent_action",
            "agent": "agent1",
            "status": "paused",
            "action": "Non-design conversation answered",
            "summary": "I am an AI assistant.",
            "artifact": "reports/agent1_requirement_clarification.md",
        }
    )

    snapshot = manager.state.snapshot()
    assert snapshot["status"] == "paused"
    assert snapshot["pause"]["action_required"] == "NON_DESIGN_CONVERSATION"
    assert snapshot["pause"]["artifact_path"] == "reports/agent1_requirement_clarification.md"

def test_paused_agent_action_synthesizes_hitl_required_for_partial_plan():
    manager = RunnerManager(command_builder=_fake_quick_runner_command)
    manager.state.run_id = "run-partial"
    manager.state.job_id = "job-partial"

    manager.state.apply_event(
        {
            "type": "agent_action",
            "agent": "agent1",
            "status": "paused",
            "action": "Partial plan generated",
            "summary": "Agent 1 stopped before release; partial plan and recovery checklist are available.",
            "artifact": "reports/agent1_requirement_clarification.md",
        }
    )
    manager.state.apply_event({"type": "process_exit", "returncode": 0})

    snapshot = manager.state.snapshot()
    assert snapshot["status"] == "paused"
    assert snapshot["pause"]["action_required"] == "HITL_REQUIRED"
    assert snapshot["pause"]["artifact_path"] == "reports/agent1_requirement_clarification.md"
    assert snapshot["current_plan_path"] is None

def test_process_exit_stop_marks_running_stage_and_agent_stopped():
    manager = RunnerManager(command_builder=_fake_quick_runner_command)
    manager.state.status = "stopped"
    manager.state.stages["planning"] = "running"
    manager.state.agents["agent1"] = {"status": "running", "action": "Codex request started", "evidence": 0}

    manager.state.apply_event({"type": "process_exit", "returncode": 1})

    assert manager.state.status == "stopped"
    assert manager.state.stages["planning"] == "stopped"
    assert manager.state.agents["agent1"]["status"] == "stopped"

def test_stale_process_exit_from_previous_launch_does_not_corrupt_active_state():
    events = []

    class OldProcess:
        returncode = 1

        async def wait(self):
            return self.returncode

    async def scenario():
        async def sink(event):
            events.append(event)

        manager = RunnerManager(event_sink=sink, command_builder=_fake_quick_runner_command)
        manager.state.run_id = "same-run"
        manager.state.status = "running"
        manager._launch_seq = 2
        await manager._watch(OldProcess(), "same-run", 1)
        return manager.state.status

    status = asyncio.run(scenario())

    assert status == "running"
    assert not any(event.get("type") == "process_exit" for event in events)

def test_resume_command_reuses_start_checkpoint_db(tmp_path):
    manager = RunnerManager(root=tmp_path)
    checkpoint_db = tmp_path / "custom.sqlite"
    manager.state = RunState(
        run_id="run-1",
        project_name="demo",
        output_dir=str(tmp_path / "outputs" / "demo"),
        checkpoint_db=str(checkpoint_db),
        thread_id="thread-1",
        pause={"action_required": "PLAN_REVIEW"},
    )

    command = manager._default_command("resume", {"notes": "ok", "resume_action": "PLAN_REVIEW"})

    assert command[command.index("--checkpoint-db") + 1] == str(checkpoint_db)

def test_resume_normalizes_generic_approve_to_current_pause_action(tmp_path):
    manager = RunnerManager(root=tmp_path)
    output_dir = tmp_path / "outputs" / "demo"
    manager.state = RunState(
        run_id="run-1",
        status="paused",
        project_name="demo",
        output_dir=str(output_dir),
        thread_id="thread-1",
        pause={"action_required": "HUMAN_REVIEW"},
    )
    captured: dict[str, object] = {}

    async def fake_launch(command_name: str, payload: dict[str, object]) -> None:
        captured.update(payload)

    manager._launch = fake_launch  # type: ignore[method-assign]

    asyncio.run(manager.resume({"notes": "ok", "resume_action": "approve"}))

    assert captured["resume_action"] == "HUMAN_REVIEW"

def test_start_endpoint_reports_active_run(tmp_path, monkeypatch):
    _configure_owner_key(tmp_path, monkeypatch)

    async def fake_probe(_endpoint: str, _model: str, _api_key: str):
        return {"ok": True, "message": "Connection OK"}

    monkeypatch.setattr(server_module, "_probe_openai_compatible_endpoint", fake_probe)
    class FakeManager:
        def __init__(self):
            self.state = type("State", (), {"run_id": "", "snapshot": lambda _self: {"run_id": "fake", "status": "running"}})()

        async def start(self, _payload):
            self.state.run_id = "fake"
            return {"run_id": "fake", "status": "running"}

        async def shutdown(self):
            return None

    manager = FakeManager()
    client = TestClient(create_app(manager))

    started = client.post("/api/runs/start", json={"requirement": "demo", "project_name": "demo"})
    assert started.status_code == 200
    assert started.json()["status"] == "running"

def test_start_same_nonempty_output_requires_policy_before_credential_probe(tmp_path, monkeypatch):
    _configure_owner_key(tmp_path, monkeypatch)
    output_dir = tmp_path / "outputs" / "demo"
    output_dir.mkdir(parents=True)
    (output_dir / "old.log").write_text("old SIGNOFF_READY", encoding="utf-8")
    calls = 0

    async def fake_probe(_endpoint: str, _model: str, _api_key: str):
        nonlocal calls
        calls += 1
        return {"ok": True, "message": "Connection OK"}

    monkeypatch.setattr(server_module, "_probe_openai_compatible_endpoint", fake_probe)
    manager = RunnerManager(root=tmp_path, command_builder=_fake_quick_runner_command)
    client = TestClient(create_app(manager))

    response = client.post("/api/runs/start", json={"requirement": "demo", "project_name": "demo", "output_dir": str(output_dir)})

    assert response.status_code == 409
    assert "OUTPUT_EXISTS" in response.json()["detail"]
    assert calls == 0

def test_fresh_run_archives_existing_output_and_writes_manifest_with_unique_thread(tmp_path):
    output_dir = tmp_path / "outputs" / "demo"
    output_dir.mkdir(parents=True)
    (output_dir / "status.log").write_text("old resume ok\nold SIGNOFF_READY\n", encoding="utf-8")

    async def scenario():
        manager = RunnerManager(root=tmp_path, command_builder=_fake_quick_runner_command)
        first = await manager.start({"requirement": "demo", "project_name": "demo", "output_dir": str(output_dir), "start_policy": "fresh"})
        await manager.stop()
        second = await manager.start({"requirement": "demo", "project_name": "demo", "output_dir": str(output_dir), "start_policy": "fresh"})
        await manager.stop()
        return first, second

    first, second = asyncio.run(scenario())
    manifest = config._read_json(output_dir / MANIFEST_NAME)
    archives = list((tmp_path / "outputs" / "_archives").glob("demo_*"))

    assert archives
    assert first["thread_id"] != second["thread_id"]
    assert manifest["run_id"] == second["run_id"]
    assert manifest["thread_id"] == second["thread_id"]
    assert (output_dir / "run_lineage.json").is_file()

def test_continue_existing_requires_valid_manifest_and_reuses_thread(tmp_path):
    output_dir = tmp_path / "outputs" / "demo"
    output_dir.mkdir(parents=True)

    async def scenario():
        manager = RunnerManager(root=tmp_path, command_builder=_fake_quick_runner_command)
        try:
            await manager.start({"requirement": "demo", "project_name": "demo", "output_dir": str(output_dir), "start_policy": "continue"})
            raise AssertionError("continue should require manifest")
        except RuntimeError as exc:
            assert MANIFEST_NAME in str(exc)
        fresh = await manager.start({"requirement": "demo", "project_name": "demo", "output_dir": str(output_dir), "start_policy": "fresh"})
        await manager.stop()
        continued = await manager.start({"requirement": "demo", "project_name": "demo", "output_dir": str(output_dir), "start_policy": "continue"})
        await manager.stop()
        return fresh, continued

    fresh, continued = asyncio.run(scenario())

    assert continued["run_id"] == fresh["run_id"]
    assert continued["thread_id"] == fresh["thread_id"]

def test_websocket_replay_filters_by_run_id():
    hub = EventHub()

    async def publish():
        await hub.publish({"type": "log", "message": "old SIGNOFF_READY", "run_id": "old"})
        await hub.publish({"type": "log", "message": "new planning", "run_id": "new"})

    asyncio.run(publish())

    replay = hub.replay_events("new")

    assert [event["message"] for event in replay] == ["new planning"]

def test_status_tailer_starts_at_end_to_prevent_stale_logs(tmp_path, monkeypatch):
    status = tmp_path / "status.log"
    status.write_text("old resume ok\nold SIGNOFF_READY\n", encoding="utf-8")
    stream = io.StringIO()
    monkeypatch.setattr(swarm_runner, "_EVENT_STDOUT", stream)
    monkeypatch.setattr(swarm_runner, "_RUN_ID", "run-new")
    tailer = swarm_runner.StatusTailer(status, start_at_end=True)

    tailer.start()
    status.write_text(status.read_text(encoding="utf-8") + "new planning\n", encoding="utf-8")
    time_limit = time.monotonic() + 2
    while "new planning" not in stream.getvalue() and time.monotonic() < time_limit:
        time.sleep(0.05)
    tailer.stop()

    text = stream.getvalue()
    assert "new planning" in text
    assert "old SIGNOFF_READY" not in text
    assert "old resume ok" not in text


def test_human_review_pause_reports_missing_disk_artifacts(tmp_path, monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(swarm_runner, "_EVENT_STDOUT", stream)
    monkeypatch.setattr(swarm_runner, "_RUN_ID", "run-missing-artifact")

    swarm_runner._emit_pause(
        {
            "action_required": "HUMAN_REVIEW",
            "message": "review",
            "rtl_files": ["missing_top.sv"],
            "formal_files": ["fv_missing_top.sv"],
        },
        tmp_path,
    )

    events = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    assert {"type": "stage", "stage": "rtl", "status": "failed", "run_id": "run-missing-artifact"} in events
    assert {"type": "stage", "stage": "formal", "status": "failed", "run_id": "run-missing-artifact"} in events
    issues = read_debug_issues(tmp_path)
    assert [issue["code"] for issue in issues] == ["human_review_missing_artifact", "human_review_missing_artifact"]
    assert all("missing" in issue["artifact_ref"] for issue in issues)


def test_signoff_ready_done_marks_all_active_pipeline_stages_pass(tmp_path, monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(swarm_runner, "_EVENT_STDOUT", stream)
    monkeypatch.setattr(swarm_runner, "_RUN_ID", "run-signoff-ready")

    swarm_runner._emit_done({"status": "SIGNOFF_READY"}, tmp_path)

    events = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    stages = {(event.get("stage"), event.get("status")) for event in events if event.get("type") == "stage"}
    assert {
        ("rtl", "pass"),
        ("formal", "pass"),
        ("hitl", "pass"),
        ("dv", "pass"),
        ("physical", "pass"),
        ("signoff", "pass"),
    }.issubset(stages)

def test_conflict_pause_emits_reviewable_artifact_path(tmp_path, monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(swarm_runner, "_EVENT_STDOUT", stream)
    monkeypatch.setattr(swarm_runner, "_RUN_ID", "run-conflict-artifact")
    clarification = tmp_path / "reports" / "agent1_requirement_clarification.md"
    clarification.parent.mkdir(parents=True)
    clarification.write_text("# Conflict\n", encoding="utf-8")

    swarm_runner._emit_pause(
        {
            "action_required": "CONFLICT_REQUIRED",
            "message": "reset conflict",
            "plan_path": str(clarification),
            "artifact_path": str(clarification),
        },
        tmp_path,
    )

    events = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    paused_actions = [event for event in events if event.get("type") == "agent_action" and event.get("status") == "paused"]
    pauses = [event for event in events if event.get("type") == "pause"]
    assert paused_actions and paused_actions[0]["artifact"] == str(clarification)
    assert pauses and pauses[0]["action_required"] == "CONFLICT_REQUIRED"
    assert pauses[0]["plan_path"] == str(clarification)
    assert pauses[0]["artifact_path"] == str(clarification)


def test_websocket_replays_events_and_rejects_bad_origin():
    hub = EventHub()
    client = TestClient(create_app(event_hub=hub))

    async def publish():
        await hub.publish({"type": "stage", "stage": "planning", "status": "running"})

    asyncio.run(publish())

    with client.websocket_connect("/ws/runs/current", headers={"origin": "http://localhost:5173"}) as websocket:
        assert websocket.receive_json()["type"] == "stage"

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/runs/current", headers={"origin": "http://evil.example"}):
            pass


def test_websocket_heartbeat_emits_ping_during_idle():
    client = TestClient(create_app(heartbeat_interval_s=0.01))

    with client.websocket_connect("/ws/runs/current", headers={"origin": "http://localhost:5173"}) as websocket:
        assert websocket.receive_json()["type"] == "ping"


def test_event_hub_backpressure_drops_logs_but_keeps_critical():
    async def scenario():
        hub = EventHub(client_queue_size=1)
        queue = hub.subscribe()
        await hub.publish({"type": "log", "message": "first"})
        await hub.publish({"type": "log", "message": "drop-me"})
        await hub.publish({"type": "stage", "stage": "planning", "status": "pass"})
        assert queue.qsize() == 1
        assert (await queue.get())["type"] == "stage"
        assert hub.dropped_log_events >= 1

    asyncio.run(scenario())


def test_event_hub_keeps_agent1_council_events_when_queue_is_full():
    async def scenario():
        hub = EventHub(client_queue_size=1)
        queue = hub.subscribe()
        await hub.publish({"type": "log", "message": "first"})
        await hub.publish({"type": "agent1_council_node", "layer": "middle", "node_id": "M03", "status": "pass"})
        assert queue.qsize() == 1
        event = await queue.get()
        assert event["type"] == "agent1_council_node"
        assert event["node_id"] == "M03"

    asyncio.run(scenario())


def test_event_hub_caps_oversized_events():
    async def scenario():
        hub = EventHub()
        await hub.publish({"type": "log", "level": "info", "message": "x" * (MAX_EVENT_BYTES * 2)})
        event = hub.replay_events()[0]
        assert event["truncated"] is True
        assert len(str(event).encode("utf-8")) < MAX_EVENT_BYTES

    asyncio.run(scenario())


def test_health_endpoint_responsive_while_long_runner_active(tmp_path, monkeypatch):
    _configure_owner_key(tmp_path, monkeypatch)

    async def fake_probe(_endpoint: str, _model: str, _api_key: str):
        return {"ok": True, "message": "Connection OK"}

    monkeypatch.setattr(server_module, "_probe_openai_compatible_endpoint", fake_probe)

    class FakeActiveManager:
        def __init__(self):
            self.state = type(
                "State",
                (),
                {"run_id": "", "snapshot": lambda _self: {"run_id": "fake", "status": "running"}},
            )()

        async def start(self, _payload):
            self.state.run_id = "fake"
            return {"run_id": "fake", "status": "running"}

        async def stop(self):
            return {"run_id": "fake", "status": "stopped"}

        async def shutdown(self):
            return None

    manager = FakeActiveManager()
    client = TestClient(create_app(manager))
    started = client.post("/api/runs/start", json={"requirement": "demo", "project_name": "demo"})
    assert started.status_code == 200
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    run_id = started.json()["run_id"]
    stopped = client.post(f"/api/runs/{run_id}/stop")
    assert stopped.status_code == 200


def test_stop_current_alias_stops_active_run_without_frontend_run_id(tmp_path, monkeypatch):
    _configure_owner_key(tmp_path, monkeypatch)

    async def fake_probe(_endpoint: str, _model: str, _api_key: str):
        return {"ok": True, "message": "Connection OK"}

    monkeypatch.setattr(server_module, "_probe_openai_compatible_endpoint", fake_probe)
    manager = _FakeStartManager()
    client = TestClient(create_app(manager))

    started = client.post("/api/runs/start", json={"requirement": "demo", "project_name": "demo"})
    stopped = client.post("/api/runs/current/stop")

    assert started.status_code == 200
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"

def test_attachment_stage_rejects_unsupported_type_and_never_returns_path(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module, "STAGED_ROOT", tmp_path / ".swarm" / "staged_inputs")
    client = TestClient(create_app())

    ok = client.post(
        "/api/attachments/stage",
        files=[("files", ("spec.md", b"# Spec\nUse APB and UART.", "text/markdown"))],
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["draftId"]
    assert body["attachments"][0]["kind"] == "markdown"
    assert "path" not in body["attachments"][0]

    blocked = client.post(
        "/api/attachments/stage",
        files=[("files", ("tool.exe", b"MZ", "application/octet-stream"))],
    )
    assert blocked.status_code == 415


def test_start_with_attachment_writes_manifest_and_context(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module, "STAGED_ROOT", tmp_path / ".swarm" / "staged_inputs")
    _configure_owner_key(tmp_path, monkeypatch)

    async def fake_probe(_endpoint: str, _model: str, _api_key: str):
        return {"ok": True, "message": "Connection OK"}

    monkeypatch.setattr(server_module, "_probe_openai_compatible_endpoint", fake_probe)
    manager = RunnerManager(root=tmp_path, command_builder=_fake_quick_runner_command)
    with TestClient(create_app(manager, connection_test_cooldown_s=0.0)) as client:
        upload = client.post(
            "/api/attachments/stage",
            files=[("files", ("req.md", b"# Requirement\nUse APB and UART.", "text/markdown"))],
        )
        draft = upload.json()
        output_dir = tmp_path / "outputs" / "attached"
        started = client.post(
            "/api/runs/start",
            json={
                "requirement": "Build attached IP",
                "project_name": "attached",
                "output_dir": str(output_dir),
                "startPolicy": "fresh",
                "attachmentDraftId": draft["draftId"],
                "attachmentIds": [draft["attachments"][0]["id"]],
            },
        )
        assert started.status_code == 200
        stopped = client.post(f"/api/runs/{started.json()['run_id']}/stop")
        assert stopped.status_code == 200
    assert (output_dir / "inputs" / "attachments_manifest.json").exists()
    context = (output_dir / "inputs" / "attachment_context.md").read_text(encoding="utf-8")
    assert "Use APB and UART" in context


def test_live_input_running_run_queues_without_resume(tmp_path, monkeypatch):
    manager = RunnerManager(root=tmp_path, command_builder=_fake_runner_command)
    output_dir = tmp_path / "outputs" / "live"
    output_dir.mkdir(parents=True)
    manager.state = RunState(run_id="run-live", status="running", project_name="live", output_dir=str(output_dir))
    client = TestClient(create_app(manager, connection_test_cooldown_s=0.0))

    queued = client.post("/api/runs/run-live/live-input", json={"message": "Add I2C follow-up now", "clientMessageId": "msg-1"})
    assert queued.status_code == 200
    assert queued.json()["status"] == "queued"
    queue_text = (output_dir / "inputs" / "live_input_queue.jsonl").read_text(encoding="utf-8")
    assert "Add I2C follow-up now" in queue_text


def test_artifact_preview_sandbox_and_extension_allowlist(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    safe = outputs / "run" / "architecture_plan.md"
    safe.parent.mkdir(parents=True)
    safe.write_text("# plan", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    binary = outputs / "run" / "wave.bin"
    binary.write_bytes(b"\x00\x01")
    monkeypatch.setattr("studio.backend.artifacts.ROOT", tmp_path)
    client = TestClient(create_app())

    ok = client.get("/api/artifacts/preview", params={"path": str(safe)})
    assert ok.status_code == 200
    assert ok.json()["text"] == "# plan"

    trace = outputs / "run" / "reports" / "traces" / "agent1_intake_trace.jsonl"
    trace.parent.mkdir(parents=True)
    trace.write_text('{"node_id":"AGENT1.READY_GATE"}\n', encoding="utf-8")
    trace_ok = client.get("/api/artifacts/preview", params={"path": str(trace)})
    assert trace_ok.status_code == 200
    assert "AGENT1.READY_GATE" in trace_ok.json()["text"]

    outside = client.get("/api/artifacts/preview", params={"path": str(secret)})
    assert outside.status_code == 403

    blocked = client.get("/api/artifacts/preview", params={"path": str(binary)})
    assert blocked.status_code == 415

    missing = client.get("/api/artifacts/preview", params={"path": str(outputs / "run" / "missing.jsonl")})
    assert missing.status_code == 404
