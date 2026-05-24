"""FastAPI entrypoint for SWARM AI STUDIO."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from studio.backend.agent_service import AgentService
from studio.backend.artifacts import preview_artifact
from studio.backend.attachments import delete_staged_attachment, get_staged_attachments, stage_attachments
from studio.backend.config import CredentialError, load_settings, public_settings_payload, resolve_credential_ref, save_settings
from studio.backend.event_hub import EventHub
from studio.backend.job_models import JobCreateRequest
from studio.backend.job_queue import JobNotFound, JobQueueFull
from studio.backend.model_gateway import public_provider_registry
from studio.backend.runner import AGENTS, STAGES, RunnerManager
from studio.backend.run_manifest import OutputPolicyError
from studio.backend.runtime_tracking import (
    build_runtime_debug_summary,
    build_runtime_invariant_report,
    build_runtime_replay_report,
    find_runtime_output_dir,
    latest_runtime_manifest,
    load_runtime_bundle,
    runtime_trace_dir,
    validate_runtime_output_dir,
)

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

    requirement: str = Field(min_length=1, max_length=2000)
    project_name: str = "swarm_soc"
    output_dir: str = ""
    planning_mode: Literal["normal", "deep_planning"] = "normal"
    checkpoint_db: str = ""
    api_key_ref: str = Field(default="owner", alias="apiKeyRef")
    start_policy: Literal["auto", "fresh", "continue"] = Field(default="auto", alias="startPolicy")
    attachment_draft_id: str = Field(default="", alias="attachmentDraftId")
    attachment_ids: list[str] = Field(default_factory=list, alias="attachmentIds")


class RunResumeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    notes: str = Field(default="ok", max_length=2000)
    change: str = Field(default="", max_length=2000)
    resume_action: str = ""
    planning_mode: Literal["normal", "deep_planning"] = "normal"
    api_key_ref: str = Field(default="owner", alias="apiKeyRef")

class LiveInputRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message: str = Field(min_length=1, max_length=2000)
    client_message_id: str = Field(default="", alias="clientMessageId")


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
    watchdog_interval_s: float = 10.0,
    runtime_stale_timeout_s: float = 30 * 60.0,
    runtime_watchdog_enabled: bool = True,
    runtime_watchdog_dry_run: bool = False,
) -> FastAPI:
    hub = event_hub or EventHub()
    runner_manager = manager or RunnerManager()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        watchdog_task: asyncio.Task[Any] | None = None
        if runtime_watchdog_enabled:
            watchdog_task = asyncio.create_task(_runtime_watchdog_loop(app, watchdog_interval_s, runtime_stale_timeout_s, runtime_watchdog_dry_run))
        try:
            yield
        finally:
            if watchdog_task is not None:
                watchdog_task.cancel()
                with suppress(asyncio.CancelledError):
                    await watchdog_task
        service: AgentService = app.state.agent_service
        await service.shutdown()

    app = FastAPI(title="SWARM AI STUDIO V6.8", version="6.8.0", lifespan=lifespan)
    app.state.event_hub = hub
    app.state.heartbeat_interval_s = heartbeat_interval_s
    app.state.runner_manager = runner_manager
    app.state.connection_test_cooldown_s = connection_test_cooldown_s
    app.state.watchdog_interval_s = watchdog_interval_s
    app.state.runtime_stale_timeout_s = runtime_stale_timeout_s
    app.state.runtime_watchdog_enabled = runtime_watchdog_enabled
    app.state.runtime_watchdog_dry_run = runtime_watchdog_dry_run
    app.state.connection_test_last_by_ref = {}
    app.state.credential_health_by_ref = {}
    service = AgentService(
        runner=runner_manager,
        event_hub=hub,
        credential_preflight=lambda ref_id: _preflight_credential(app, ref_id),
    )
    runner_manager.event_sink = service.publish_runner_event
    app.state.agent_service = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(LOCAL_ORIGINS),
        allow_origin_regex=LOCAL_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        runner: RunnerManager = app.state.runner_manager
        service: AgentService = app.state.agent_service
        return {
            "status": "ok",
            "activeRun": runner.state.snapshot() if runner.state.run_id else None,
            "runnerAvailable": True,
            "queueHealth": service.queue_health(),
            "runtime": {
                "watchdogEnabled": app.state.runtime_watchdog_enabled,
                "staleTimeoutS": app.state.runtime_stale_timeout_s,
                "dryRun": app.state.runtime_watchdog_dry_run,
            },
        }

    @app.get("/api/settings")
    async def get_settings() -> dict[str, Any]:
        payload = _settings_payload_with_health(app)
        payload["modelProviders"] = public_provider_registry()
        return payload

    @app.post("/api/settings")
    async def post_settings(payload: SettingsUpdate) -> dict[str, Any]:
        if payload.api_key is not None:
            raise HTTPException(status_code=400, detail="Raw API key is not accepted by web settings")
        try:
            save_settings(payload.endpoint, payload.model, payload.checkpoint_db, payload.output_root, payload.active_key_ref)
        except CredentialError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload = _settings_payload_with_health(app)
        payload["modelProviders"] = public_provider_registry()
        return payload

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
        if runner.state.run_id:
            state = runner.state.snapshot()
            bundle = load_runtime_bundle(runner.state.output_dir) if runner.state.output_dir else {}
            return {**state, "runtime": _compact_runtime_fields(bundle)}
        manifest = latest_runtime_manifest(root=runner.root)
        if manifest:
            return _state_from_runtime_manifest(manifest)
        return runner.state.snapshot()

    @app.post("/api/attachments/stage")
    async def upload_attachments(files: list[UploadFile] = File(...), draft_id: str = Form(default="")) -> dict[str, Any]:
        draft = await stage_attachments(files, draft_id)
        await hub.publish({"type": "attachment_staged", "level": "info", "message": f"{len(draft.attachments)} staged attachments", "draftId": draft.draft_id})
        return {"draftId": draft.draft_id, "attachments": draft.attachments}

    @app.get("/api/attachments/stage/{draft_id}")
    async def staged_attachments(draft_id: str) -> dict[str, Any]:
        draft = get_staged_attachments(draft_id)
        return {"draftId": draft.draft_id, "attachments": draft.attachments}

    @app.delete("/api/attachments/stage/{draft_id}/{attachment_id}")
    async def remove_staged_attachment(draft_id: str, attachment_id: str) -> dict[str, Any]:
        draft = delete_staged_attachment(draft_id, attachment_id)
        await hub.publish({"type": "attachment_staged", "level": "info", "message": f"{len(draft.attachments)} staged attachments", "draftId": draft.draft_id})
        return {"draftId": draft.draft_id, "attachments": draft.attachments}

    @app.get("/api/jobs")
    async def list_jobs() -> dict[str, Any]:
        service: AgentService = app.state.agent_service
        return {"jobs": [job.to_public_dict() for job in await service.list_jobs()], "queueHealth": service.queue_health()}

    @app.post("/api/jobs")
    async def create_job(payload: JobCreateRequest) -> dict[str, Any]:
        service: AgentService = app.state.agent_service
        try:
            job = await service.enqueue_job(payload)
        except OutputPolicyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except CredentialError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except JobQueueFull as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        return job.to_public_dict()

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        service: AgentService = app.state.agent_service
        try:
            return (await service.get_job(job_id)).to_public_dict()
        except JobNotFound as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str) -> dict[str, Any]:
        service: AgentService = app.state.agent_service
        try:
            return (await service.cancel_job(job_id)).to_public_dict()
        except JobNotFound as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc

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

    @app.get("/api/runs/{run_id}/runtime")
    async def get_run_runtime(run_id: str) -> dict[str, Any]:
        runner: RunnerManager = app.state.runner_manager
        output_dir = None
        if runner.state.run_id == run_id and runner.state.output_dir:
            output_dir = runner.state.output_dir
        else:
            found = find_runtime_output_dir(run_id, root=runner.root)
            if found is not None:
                output_dir = str(found)
        if not output_dir:
            raise HTTPException(status_code=404, detail="runtime not found")
        validate_runtime_output_dir(Path(output_dir), active_output_dir=runner.state.output_dir, root=runner.root, run_id=run_id)
        bundle = load_runtime_bundle(output_dir)
        if bundle.get("manifest") is None and bundle.get("errors"):
            tracker = getattr(runner, "runtime_tracker", None)
            if tracker is not None:
                tracker.write_recovery_report({"run_id": run_id, "output_dir": output_dir, "status": "failed"}, reason="manifest_corrupt", action="runtime_api_read")
            raise HTTPException(status_code=409, detail=f"manifest corrupt: {'; '.join(bundle['errors'])}")
        return bundle

    @app.post("/api/runs/start")
    async def start_run(payload: RunStartRequest) -> dict[str, Any]:
        service: AgentService = app.state.agent_service
        try:
            model_payload = payload.model_dump()
            return await service.start_run(model_payload)
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
        service: AgentService = app.state.agent_service
        try:
            return await service.resume_run(payload.model_dump())
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/live-input")
    async def live_input_run(run_id: str, payload: LiveInputRequest) -> dict[str, Any]:
        runner: RunnerManager = app.state.runner_manager
        if runner.state.run_id != run_id:
            raise HTTPException(status_code=404, detail="run not found")
        try:
            return await runner.live_input(payload.model_dump())
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/stop")
    async def stop_run(run_id: str) -> dict[str, Any]:
        runner: RunnerManager = app.state.runner_manager
        if run_id != "current" and runner.state.run_id != run_id:
            raise HTTPException(status_code=404, detail="run not found")
        service: AgentService = app.state.agent_service
        return await service.stop_run()

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
            with suppress(Exception):
                await hub.publish({"type": "websocket_disconnected", "run_id": effective_run_id, "message": "websocket client disconnected"})
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

async def _runtime_watchdog_loop(app: FastAPI, interval_s: float, stale_timeout_s: float, dry_run: bool) -> None:
    while True:
        await asyncio.sleep(interval_s)
        runner: RunnerManager = app.state.runner_manager
        if hasattr(runner, "check_watchdog"):
            await runner.check_watchdog(stale_timeout_s=stale_timeout_s, dry_run=dry_run)

def _compact_runtime_fields(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "manifest": bundle.get("manifest"),
        "recoveryReport": bundle.get("recoveryReport"),
        "debugSummary": bundle.get("debugSummary"),
        "invariantReport": bundle.get("invariantReport"),
        "replayReport": bundle.get("replayReport"),
    }

def _state_from_runtime_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    stages = {stage: "idle" for stage in STAGES}
    phase = str(manifest.get("active_node_id") or "").lower()
    for stage in STAGES:
        if stage in phase:
            stages[stage] = "running"
    agents = {agent: {"status": "idle", "action": "Waiting", "evidence": 0} for agent in AGENTS}
    for agent, payload in (manifest.get("agents") or {}).items():
        if agent in agents and isinstance(payload, dict):
            agents[agent] = {
                "status": str(payload.get("status") or "idle"),
                "action": str(payload.get("message") or payload.get("last_event_type") or "runtime hydrate"),
                "evidence": 0,
            }
    return {
        "run_id": str(manifest.get("run_id") or ""),
        "status": str(manifest.get("status") or "idle"),
        "pid": None,
        "project_name": str(manifest.get("project_name") or ""),
        "requirement": "",
        "output_dir": str(manifest.get("output_dir") or ""),
        "checkpoint_db": "",
        "planning_mode": str(manifest.get("planning_mode") or "normal"),
        "apiKeyRef": str(manifest.get("credential_ref") or "owner"),
        "attachment_manifest_path": "",
        "attachment_context_path": "",
        "job_id": str(manifest.get("job_id") or ""),
        "thread_id": "",
        "start_policy": "",
        "manifest_path": "",
        "stages": stages,
        "agents": agents,
        "metrics": manifest.get("metrics") or {},
        "pause": None,
        "current_plan_path": None,
        "last_event_id": 0,
        "runtime": {"manifest": manifest},
    }


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
