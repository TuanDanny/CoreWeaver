"""FastAPI entrypoint for SWARM AI STUDIO."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextlib import suppress
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from studio.backend.artifacts import preview_artifact
from studio.backend.config import CredentialError, load_settings, public_settings_payload, resolve_credential_ref, save_settings
from studio.backend.event_hub import EventHub
from studio.backend.runner import RunnerManager
from studio.backend.run_manifest import OutputPolicyError

LOCAL_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}
LOCAL_ORIGIN_REGEX = r"^http://(localhost|127\.0\.0\.1):[0-9]+$"
CREDENTIAL_HEALTH_VALUES = {"missing", "unchecked", "valid", "invalid"}


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    endpoint: str = "http://localhost:20128/v1"
    model: str = "cx/gpt-5.5"
    api_key: str | None = Field(default=None, alias="apiKey")
    active_key_ref: str = Field(default="owner", alias="activeKeyRef")
    checkpoint_db: str = ""
    output_root: str = ""


class ConnectionTestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    endpoint: str = "http://localhost:20128/v1"
    model: str = "cx/gpt-5.5"
    api_key: str | None = Field(default=None, alias="apiKey")
    api_key_ref: str = Field(default="owner", alias="apiKeyRef")


class RunStartRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    requirement: str
    project_name: str = "swarm_soc"
    output_dir: str = ""
    planning_mode: Literal["normal", "deep_planning"] = "normal"
    checkpoint_db: str = ""
    api_key_ref: str = Field(default="owner", alias="apiKeyRef")
    start_policy: Literal["auto", "fresh", "continue"] = Field(default="auto", alias="startPolicy")


class RunResumeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    notes: str = "ok"
    change: str = ""
    resume_action: str = ""
    planning_mode: Literal["normal", "deep_planning"] = "normal"
    api_key_ref: str = Field(default="owner", alias="apiKeyRef")


def _origin_allowed(origin: str | None) -> bool:
    if origin in LOCAL_ORIGINS:
        return True
    parsed = urlparse(origin or "")
    return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"} and parsed.port is not None


def _safe_ref(ref_id: str | None) -> str:
    return (ref_id or "owner").strip() or "owner"

def _settings_payload_with_health(app: FastAPI) -> dict[str, Any]:
    payload = public_settings_payload()
    health: dict[str, str] = {}
    cached: dict[str, dict[str, Any]] = app.state.credential_health_by_ref
    for ref in payload.get("credentialRefs", []):
        ref_id = str(ref.get("id") or "owner")
        if not ref.get("hasSecret"):
            health[ref_id] = "missing"
            continue
        status = str(cached.get(ref_id, {}).get("status") or "unchecked")
        health[ref_id] = status if status in CREDENTIAL_HEALTH_VALUES else "unchecked"
    payload["credentialHealth"] = health
    return payload

def _set_credential_health(app: FastAPI, ref_id: str | None, status: str, message: str) -> None:
    clean_status = status if status in CREDENTIAL_HEALTH_VALUES else "unchecked"
    app.state.credential_health_by_ref[_safe_ref(ref_id)] = {
        "status": clean_status,
        "message": message,
        "timestamp": asyncio.get_running_loop().time(),
    }

def _status_from_probe_result(result: dict[str, bool | str]) -> str:
    if result.get("ok") is True:
        return "valid"
    message = str(result.get("message") or "")
    if "Access denied" in message or "invalid, expired, or unauthorized" in message:
        return "invalid"
    return "unchecked"

def _update_credential_health_from_probe(app: FastAPI, ref_id: str | None, result: dict[str, bool | str]) -> None:
    _set_credential_health(app, ref_id, _status_from_probe_result(result), str(result.get("message") or ""))

async def _preflight_credential(app: FastAPI, ref_id: str | None) -> None:
    requested = _safe_ref(ref_id)
    key, _public_ref, error = resolve_credential_ref(requested)
    if error:
        _set_credential_health(app, requested, "missing", error)
        raise CredentialError(f"Credential {requested} is invalid. Test Connection or update server key before Start. Detail: {error}")

    payload = _settings_payload_with_health(app)
    status = str(payload.get("credentialHealth", {}).get(requested) or "unchecked")
    if status == "invalid":
        raise CredentialError(f"Credential {requested} is invalid. Test Connection or update server key before Start.")
    if status == "missing":
        raise CredentialError(f"Credential {requested} is missing. Update server key before Start.")
    if status == "valid":
        return

    now = asyncio.get_running_loop().time()
    last_by_ref: dict[str, float] = app.state.connection_test_last_by_ref
    last = last_by_ref.get(requested)
    if last is not None and now - last < app.state.connection_test_cooldown_s:
        raise CredentialError(f"Credential {requested} is unchecked. Test Connection cooldown active before Start.")
    last_by_ref[requested] = now
    settings = load_settings()
    result = await _probe_openai_compatible_endpoint(settings.endpoint, settings.model, key or "")
    _update_credential_health_from_probe(app, requested, result)
    if result.get("ok") is not True:
        raise CredentialError(f"Credential {requested} is invalid. Test Connection or update server key before Start. Detail: {result.get('message')}")

def create_app(
    manager: RunnerManager | None = None,
    event_hub: EventHub | None = None,
    heartbeat_interval_s: float = 10.0,
    connection_test_cooldown_s: float = 2.0,
) -> FastAPI:
    hub = event_hub or EventHub()
    runner_manager = manager or RunnerManager(event_sink=hub.publish)
    if manager is not None:
        manager.event_sink = hub.publish

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        runner: RunnerManager = app.state.runner_manager
        await runner.shutdown()

    app = FastAPI(title="SWARM AI STUDIO V6.5", version="6.5.0", lifespan=lifespan)
    app.state.event_hub = hub
    app.state.heartbeat_interval_s = heartbeat_interval_s
    app.state.runner_manager = runner_manager
    app.state.connection_test_cooldown_s = connection_test_cooldown_s
    app.state.connection_test_last_by_ref = {}
    app.state.credential_health_by_ref = {}
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(LOCAL_ORIGINS),
        allow_origin_regex=LOCAL_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        runner: RunnerManager = app.state.runner_manager
        return {"status": "ok", "activeRun": runner.state.snapshot() if runner.state.run_id else None, "runnerAvailable": True}

    @app.get("/api/settings")
    async def get_settings() -> dict[str, Any]:
        return _settings_payload_with_health(app)

    @app.post("/api/settings")
    async def post_settings(payload: SettingsUpdate) -> dict[str, Any]:
        if payload.api_key is not None:
            raise HTTPException(status_code=400, detail="Raw API key is not accepted by web settings")
        try:
            save_settings(payload.endpoint, payload.model, payload.checkpoint_db, payload.output_root, payload.active_key_ref)
        except CredentialError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _settings_payload_with_health(app)

    @app.post("/api/settings/test-connection")
    async def test_connection(payload: ConnectionTestRequest) -> dict[str, bool | str]:
        if payload.api_key is not None:
            raise HTTPException(status_code=400, detail="Raw API key is not accepted by web settings")
        key, _public_ref, error = resolve_credential_ref(payload.api_key_ref)
        if error:
            _set_credential_health(app, payload.api_key_ref, "missing", error)
            raise HTTPException(status_code=400, detail=error)
        now = asyncio.get_running_loop().time()
        last_by_ref: dict[str, float] = app.state.connection_test_last_by_ref
        last = last_by_ref.get(payload.api_key_ref)
        if last is not None and now - last < app.state.connection_test_cooldown_s:
            raise HTTPException(status_code=429, detail="Test connection cooldown active")
        last_by_ref[payload.api_key_ref] = now
        result = await _probe_openai_compatible_endpoint(payload.endpoint, payload.model, key or "")
        _update_credential_health_from_probe(app, payload.api_key_ref, result)
        return result

    @app.get("/api/runs/current_state")
    async def current_state() -> dict[str, Any]:
        runner: RunnerManager = app.state.runner_manager
        return runner.state.snapshot()

    @app.get("/api/artifacts/preview")
    async def artifact_preview(path: str) -> dict[str, object]:
        runner: RunnerManager = app.state.runner_manager
        return preview_artifact(path, runner.state.output_dir)

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        runner: RunnerManager = app.state.runner_manager
        if runner.state.run_id != run_id:
            raise HTTPException(status_code=404, detail="run not found")
        return runner.state.snapshot()

    @app.post("/api/runs/start")
    async def start_run(payload: RunStartRequest) -> dict[str, Any]:
        runner: RunnerManager = app.state.runner_manager
        try:
            model_payload = payload.model_dump()
            conflict = runner.output_conflict(model_payload) if hasattr(runner, "output_conflict") else None
            if conflict:
                raise OutputPolicyError(conflict)
            await _preflight_credential(app, payload.api_key_ref)
            hub.clear()
            return await runner.start(model_payload)
        except OutputPolicyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except CredentialError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/resume")
    async def resume_run(run_id: str, payload: RunResumeRequest) -> dict[str, Any]:
        runner: RunnerManager = app.state.runner_manager
        if runner.state.run_id != run_id:
            raise HTTPException(status_code=404, detail="run not found")
        try:
            return await runner.resume(payload.model_dump())
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/stop")
    async def stop_run(run_id: str) -> dict[str, Any]:
        runner: RunnerManager = app.state.runner_manager
        if run_id != "current" and runner.state.run_id != run_id:
            raise HTTPException(status_code=404, detail="run not found")
        return await runner.stop()

    @app.websocket("/ws/runs/{run_id}")
    async def run_events(websocket: WebSocket, run_id: str) -> None:
        if not _origin_allowed(websocket.headers.get("origin")):
            await websocket.close(code=1008)
            return
        runner: RunnerManager = app.state.runner_manager
        effective_run_id = runner.state.run_id if run_id == "current" else run_id
        if runner.state.run_id and effective_run_id != runner.state.run_id:
            await websocket.close(code=1008)
            return
        hub: EventHub = app.state.event_hub
        await websocket.accept()
        queue = hub.subscribe()
        heartbeat = asyncio.create_task(_heartbeat(websocket, app.state.heartbeat_interval_s, effective_run_id))
        sender = asyncio.create_task(_send_events(websocket, queue, effective_run_id))
        receiver = asyncio.create_task(_receive_until_disconnect(websocket))
        try:
            for event in hub.replay_events(effective_run_id):
                await websocket.send_json(event)
            done, pending = await asyncio.wait({heartbeat, sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                with suppress(Exception):
                    task.result()
            for task in pending:
                task.cancel()
        finally:
            hub.unsubscribe(queue)
            heartbeat.cancel()
            sender.cancel()
            receiver.cancel()

    return app


async def _heartbeat(websocket: WebSocket, interval_s: float, run_id: str | None = None) -> None:
    while True:
        await asyncio.sleep(interval_s)
        payload: dict[str, Any] = {"type": "ping", "ts": asyncio.get_running_loop().time()}
        if run_id:
            payload["run_id"] = run_id
        await websocket.send_json(payload)


async def _send_events(websocket: WebSocket, queue: asyncio.Queue[dict[str, Any]], run_id: str | None = None) -> None:
    while True:
        event = await queue.get()
        if run_id and event.get("run_id") not in {run_id, None, ""}:
            continue
        await websocket.send_json(event)


async def _receive_until_disconnect(websocket: WebSocket) -> None:
    while True:
        await websocket.receive_text()


async def _probe_openai_compatible_endpoint(endpoint: str, model: str, api_key: str) -> dict[str, bool | str]:
    base = endpoint.rstrip("/")
    if not base.startswith(("http://", "https://")):
        return {"ok": False, "message": "Invalid endpoint URL"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Respond with OK only."}],
        "max_tokens": 1,
        "temperature": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
    except httpx.TimeoutException:
        return {"ok": False, "message": "Network timeout: endpoint did not respond within 5s."}
    except httpx.ConnectError:
        return {"ok": False, "message": "Network error: cannot connect to endpoint. Check whether 9Router is running."}
    except httpx.RequestError as exc:
        return {"ok": False, "message": f"Network error: cannot connect to endpoint. Check whether 9Router is running. ({exc.__class__.__name__})"}
    if response.status_code == 200:
        try:
            body = response.json()
        except ValueError:
            return {"ok": False, "message": "Invalid chat/completions response"}
        if isinstance(body, dict) and isinstance(body.get("choices"), list) and body["choices"]:
            return {"ok": True, "message": "Connection OK"}
        return {"ok": False, "message": "Invalid chat/completions response"}
    if response.status_code in {401, 403}:
        return {"ok": False, "message": "Access denied: API key is invalid, expired, or unauthorized."}
    if response.status_code == 429:
        return {"ok": False, "message": "Rate limited: wait before retrying."}
    return {"ok": False, "message": f"Endpoint responded with HTTP {response.status_code}"}


app = create_app()
