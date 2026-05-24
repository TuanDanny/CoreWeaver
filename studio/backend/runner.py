"""Async subprocess runner manager for Studio V6."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from semiconductor_swarm.live_inputs import append_live_input
from studio.backend.attachments import commit_staged_attachments
from studio.backend.config import DEFAULT_CREDENTIAL_REF, ROOT, redact_secret_text, resolve_credential_ref
from studio.backend.run_manifest import (
    OutputPolicyError,
    append_lineage,
    archive_output_dir,
    load_manifest,
    output_conflict_message,
    write_manifest,
)
from studio.backend.runtime_tracking import RuntimeTracker
from semiconductor_swarm.tracing import TRACE_FILES, trace_event

EventSink = Callable[[dict[str, Any]], Awaitable[None]]
CommandBuilder = Callable[[str, dict[str, Any]], list[str]]

STAGES = ("planning", "rtl", "formal", "hitl", "dv", "physical", "signoff")
AGENTS = ("agent1", "agent2", "agent3", "agent4", "agent5", "agent6")
CRITICAL_EVENT_TYPES = {
    "stage",
    "pause",
    "error",
    "done",
    "process_start",
    "process_exit",
    "metric",
    "agent_action",
    "agent_handoff",
    "agent1_council_iteration",
    "agent1_council_node",
    "agent1_council_edge",
    "agent1_council_artifact",
}


@dataclass
class RunState:
    run_id: str = ""
    status: str = "idle"
    pid: int | None = None
    project_name: str = ""
    requirement: str = ""
    output_dir: str = ""
    checkpoint_db: str = ""
    planning_mode: str = "normal"
    api_key_ref: str = DEFAULT_CREDENTIAL_REF
    attachment_manifest_path: str = ""
    attachment_context_path: str = ""
    job_id: str = ""
    thread_id: str = ""
    start_policy: str = "auto"
    manifest_path: str = ""
    stages: dict[str, str] = field(default_factory=lambda: {stage: "idle" for stage in STAGES})
    agents: dict[str, dict[str, Any]] = field(default_factory=lambda: {agent: {"status": "idle", "action": "Waiting", "evidence": 0} for agent in AGENTS})
    metrics: dict[str, Any] = field(default_factory=dict)
    pause: dict[str, Any] | None = None
    current_plan_path: str | None = None
    last_event_id: int = 0

    def apply_event(self, event: dict[str, Any]) -> None:
        kind = str(event.get("type", "log"))
        if kind == "process_start":
            self.pid = int(event.get("pid")) if str(event.get("pid", "")).isdigit() else self.pid
            self.status = "running"
        elif kind == "process_exit":
            if self.status == "paused" and event.get("returncode") in (0, None):
                self.pid = None
                return
            if self.status not in {"done", "failed", "stopped"}:
                self.status = "stopped" if event.get("returncode") in (0, None) else "failed"
            if self.status in {"failed", "stopped"}:
                self._mark_running_nodes_terminal(self.status)
            self.pid = None
        elif kind == "stage":
            stage = str(event.get("stage", ""))
            if stage in self.stages:
                self.stages[stage] = str(event.get("status", "idle"))
        elif kind == "agent_action":
            agent = str(event.get("agent", ""))
            if agent in self.agents:
                self.agents[agent]["status"] = str(event.get("status", "info"))
                self.agents[agent]["action"] = str(event.get("action", "activity"))
        elif kind == "metric":
            self.metrics[str(event.get("name", "metric"))] = event.get("value")
        elif kind == "pause":
            self.status = "paused"
            self.pause = event
            if event.get("plan_path"):
                self.current_plan_path = str(event.get("plan_path"))
        elif kind == "done":
            self.status = "done"
            self.pause = None
        elif kind == "error":
            self.status = "failed"
            self._mark_running_nodes_terminal("failed")
        elif kind == "watchdog_timeout":
            self.status = "stopped" if self.status == "stopping" else "failed"
            self._mark_running_nodes_terminal(self.status)

    def _mark_running_nodes_terminal(self, status: str) -> None:
        for stage, stage_status in list(self.stages.items()):
            if stage_status in {"running", "starting"}:
                self.stages[stage] = status
        for agent, agent_state in self.agents.items():
            if str(agent_state.get("status")) in {"running", "starting"}:
                self.agents[agent] = {**agent_state, "status": status, "action": status}

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "pid": self.pid,
            "project_name": self.project_name,
            "requirement": self.requirement,
            "output_dir": self.output_dir,
            "checkpoint_db": self.checkpoint_db,
            "planning_mode": self.planning_mode,
            "apiKeyRef": self.api_key_ref,
            "attachment_manifest_path": self.attachment_manifest_path,
            "attachment_context_path": self.attachment_context_path,
            "job_id": self.job_id,
            "thread_id": self.thread_id,
            "start_policy": self.start_policy,
            "manifest_path": self.manifest_path,
            "stages": self.stages,
            "agents": self.agents,
            "metrics": self.metrics,
            "pause": self.pause,
            "current_plan_path": self.current_plan_path,
            "last_event_id": self.last_event_id,
        }


class RunnerManager:
    def __init__(self, *, root: Path = ROOT, event_sink: EventSink | None = None, command_builder: CommandBuilder | None = None) -> None:
        self.root = root
        self.event_sink = event_sink
        self.command_builder = command_builder or self._default_command
        self._uses_default_command = command_builder is None
        self.process: asyncio.subprocess.Process | None = None
        self.state = RunState()
        self.runtime_tracker = RuntimeTracker(root=root)
        self._lock = asyncio.Lock()
        self._reader_tasks: list[asyncio.Task[Any]] = []
        self._launch_seq = 0

    def running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    def output_conflict(self, payload: dict[str, Any]) -> str | None:
        output_dir = Path(str(payload.get("output_dir") or self.root / "outputs" / "studio_runs" / str(payload.get("project_name") or "swarm_soc")))
        policy = str(payload.get("start_policy") or payload.get("startPolicy") or "auto")
        if policy != "auto":
            return None
        return output_conflict_message(output_dir)

    async def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            await self._settle_paused_process()
            if self.running():
                raise RuntimeError("run already active")
            project_name = str(payload.get("project_name") or "swarm_soc")
            output_dir = Path(str(payload.get("output_dir") or self.root / "outputs" / "studio_runs" / project_name))
            checkpoint_db = str(payload.get("checkpoint_db") or payload.get("checkpointDb") or self.root / ".swarm" / "studio_web_checkpoints.sqlite")
            planning_mode = str(payload.get("planning_mode") or "normal")
            start_policy = str(payload.get("start_policy") or payload.get("startPolicy") or "auto")
            archived_from: str | None = None
            if start_policy == "auto":
                conflict = output_conflict_message(output_dir)
                if conflict:
                    raise OutputPolicyError(conflict)
            if start_policy == "continue":
                manifest = load_manifest(output_dir)
                run_id = str(manifest["run_id"])
                thread_id = str(manifest["thread_id"])
            else:
                if start_policy == "fresh":
                    archived = archive_output_dir(output_dir)
                    archived_from = str(archived) if archived else None
                run_id = str(uuid.uuid4())
                thread_id = f"studio-web-{project_name}-{run_id[:8]}"
                manifest = write_manifest(
                    output_dir,
                    run_id=run_id,
                    thread_id=thread_id,
                    project_name=project_name,
                    planning_mode=planning_mode,
                    start_policy=start_policy,
                    archived_from=archived_from,
                )
                append_lineage(output_dir, {"event": "start", **manifest})
            self.state = RunState(
                run_id=run_id,
                status="starting",
                project_name=project_name,
                requirement=str(payload.get("requirement") or ""),
                output_dir=str(output_dir),
                checkpoint_db=checkpoint_db,
                planning_mode=planning_mode,
                api_key_ref=str(payload.get("api_key_ref") or payload.get("apiKeyRef") or DEFAULT_CREDENTIAL_REF),
                job_id=str(payload.get("job_id") or ""),
                thread_id=thread_id,
                start_policy=start_policy,
                manifest_path=str(output_dir / "studio_run_manifest.json"),
            )
            attachment_paths = commit_staged_attachments(
                str(payload.get("attachment_draft_id") or payload.get("attachmentDraftId") or ""),
                list(payload.get("attachment_ids") or payload.get("attachmentIds") or []),
                output_dir,
            )
            if attachment_paths:
                self.state.attachment_manifest_path = str(attachment_paths.get("attachment_manifest") or "")
                self.state.attachment_context_path = str(attachment_paths.get("attachment_context") or "")
            await self._publish_runtime_events(self.runtime_tracker.initialize_run(self.state.snapshot()))
            trace_event(
                TRACE_FILES["studio_flow"],
                phase="backend",
                agent="studio",
                node_id="API.POST_RUNS_START",
                event_type="route_enter",
                status="running",
                payload={
                    "run_id": run_id,
                    "job_id": self.state.job_id,
                    "project_name": project_name,
                    "planning_mode": planning_mode,
                    "start_policy": start_policy,
                    "output_dir": str(output_dir),
                    "requirement_preview": str(payload.get("requirement") or "")[:600],
                    "attachment_manifest": self.state.attachment_manifest_path,
                },
                output_dir=output_dir,
                emit_live=False,
            )
            payload = {
                **payload,
                "run_id": run_id,
                "thread_id": thread_id,
                "output_dir": str(output_dir),
                "planning_mode": planning_mode,
                **attachment_paths,
            }
            await self._launch("start", payload)
            return self.state.snapshot()

    async def resume(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            await self._settle_paused_process()
            if self.running():
                raise RuntimeError("run already active")
            if not self.state.run_id:
                raise RuntimeError("no run to resume")
            self.state.status = "starting"
            self.state.api_key_ref = str(payload.get("api_key_ref") or payload.get("apiKeyRef") or self.state.api_key_ref or DEFAULT_CREDENTIAL_REF)
            self.state.job_id = str(payload.get("job_id") or self.state.job_id or "")
            self.state.checkpoint_db = str(payload.get("checkpoint_db") or payload.get("checkpointDb") or self.state.checkpoint_db)
            payload = {**payload, "run_id": self.state.run_id, "thread_id": self.state.thread_id, "output_dir": self.state.output_dir}
            await self._launch("resume", payload)
            return self.state.snapshot()

    async def live_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            if not self.state.run_id:
                raise RuntimeError("no run is active")
            if self.state.status in {"idle", "stopped", "done", "failed"}:
                raise RuntimeError(f"run is {self.state.status}; live input is closed")
            if not self.state.output_dir:
                raise RuntimeError("run output directory is unavailable")
            record = append_live_input(
                self.state.output_dir,
                message=str(payload.get("message") or ""),
                run_id=self.state.run_id,
                client_message_id=str(payload.get("client_message_id") or payload.get("clientMessageId") or ""),
            )
            await self._emit(
                {
                    "type": "live_input_ack",
                    "level": "info",
                    "agent": "console",
                    "status": "queued",
                    "message": "queued to Agent1 checkpoint",
                    "message_id": record["message_id"],
                    "message_hash": record["message_hash"],
                },
                run_id=self.state.run_id,
            )
            return {"ok": True, "status": "queued", "message_id": record["message_id"], "run_id": self.state.run_id}

    async def stop(self) -> dict[str, Any]:
        async with self._lock:
            proc = self.process
            if proc is None or proc.returncode is not None:
                if proc is not None:
                    await self._drain_reader_tasks()
                    if self.process is proc:
                        self.process = None
                self.state.status = "stopped" if self.state.run_id else "idle"
                return self.state.snapshot()
            self.state.status = "stopping"
            self._launch_seq += 1
            trace_event(
                TRACE_FILES["studio_flow"],
                phase="backend",
                agent="studio",
                node_id="API.POST_RUNS_STOP",
                event_type="route_enter",
                status="running",
                payload={"run_id": self.state.run_id, "job_id": self.state.job_id, "pid": proc.pid},
                output_dir=self.state.output_dir,
                emit_live=False,
            )
            await self._emit({"type": "log", "level": "warning", "message": f"stopping pid={proc.pid}"}, run_id=self.state.run_id)
            if os.name == "nt":
                taskkill = await asyncio.create_subprocess_exec("taskkill", "/T", "/F", "/PID", str(proc.pid), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                try:
                    await asyncio.wait_for(taskkill.wait(), timeout=5)
                except asyncio.TimeoutError:
                    taskkill.kill()
                    await taskkill.wait()
            elif proc.pid:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if proc.returncode is None:
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2)
                except asyncio.TimeoutError:
                    try:
                        proc.terminate()
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=2)
                    except asyncio.TimeoutError:
                        try:
                            proc.kill()
                        except ProcessLookupError:
                            pass
                        await proc.wait()
            await self._drain_reader_tasks()
            self.state.status = "stopped"
            await self._emit({"type": "process_exit", "returncode": proc.returncode}, run_id=self.state.run_id)
            self.process = None
            return self.state.snapshot()

    async def shutdown(self) -> None:
        if self.running():
            await self.stop()

    async def check_watchdog(self, *, stale_timeout_s: float, dry_run: bool = False) -> list[dict[str, Any]]:
        if not self.state.run_id or not self.state.output_dir:
            return []
        if self.state.status not in {"starting", "running", "stopping"}:
            return []
        stale = self.runtime_tracker.stale_snapshot(self.state.output_dir)
        raw_age = stale.get("age_s")
        age = float(raw_age) if isinstance(raw_age, (int, float)) else None
        if age is None or age < stale_timeout_s:
            return []
        stale_kind = str(stale.get("stale_kind") or "")
        if stale_kind != "model_call_stale":
            stale_kind = "subprocess" if self.running() else "queue"
        if self.state.status == "stopping":
            stale_kind = "stopping"
        reason = f"{stale_kind} runtime stale for {age:.1f}s (limit {stale_timeout_s:.1f}s)"
        before = self.state.status
        if not dry_run:
            self.state.status = "stopped" if self.state.status == "stopping" else "failed"
            self.state._mark_running_nodes_terminal(self.state.status)
        events = self.runtime_tracker.watchdog_timeout(self.state.snapshot(), reason=reason, stale_kind=stale_kind)
        self.runtime_tracker.write_recovery_report(self.state.snapshot(), reason=reason, action="watchdog_timeout", before_status=before)
        await self._publish_runtime_events(events)
        if events and self.event_sink is not None:
            await self.event_sink({"type": "watchdog_timeout", "run_id": self.state.run_id, "job_id": self.state.job_id, "message": reason, "status": self.state.status})
        return events

    async def _settle_paused_process(self) -> None:
        proc = self.process
        if proc is None:
            return
        if proc.returncode is not None:
            await self._drain_reader_tasks()
            if self.process is proc:
                self.process = None
            return
        if self.state.status != "paused":
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=3)
        except asyncio.TimeoutError:
            return
        await self._drain_reader_tasks()
        if self.process is proc:
            self.process = None

    async def _launch(self, command_name: str, payload: dict[str, Any]) -> None:
        command = self.command_builder(command_name, payload)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        key_ref = str(payload.get("api_key_ref") or payload.get("apiKeyRef") or self.state.api_key_ref or DEFAULT_CREDENTIAL_REF)
        if self._uses_default_command:
            secret, _public_ref, error = resolve_credential_ref(key_ref)
            if error:
                await self._emit({"type": "error", "message": "Missing credential ref secret", "credential_ref": key_ref}, run_id=self.state.run_id)
                raise RuntimeError(error)
            if secret:
                env["SWARM_CODEX_API_KEY"] = secret
                env["AGENT1_CODEX_API_KEY"] = secret
                env["AGENT2_CODEX_API_KEY"] = secret
        kwargs: dict[str, Any] = {
            "cwd": str(self.root),
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "env": env,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(asyncio.subprocess, "CREATE_NO_WINDOW", 0) or 0x08000000
        else:
            kwargs["preexec_fn"] = os.setsid
        self._launch_seq += 1
        launch_seq = self._launch_seq
        self.process = await asyncio.create_subprocess_exec(*command, **kwargs)
        trace_event(
            TRACE_FILES["runner_process"],
            phase="backend",
            agent="studio",
            node_id="RUNNER.PROCESS_LAUNCH",
            event_type="process_launch",
            status="running",
            payload={"run_id": self.state.run_id, "pid": self.process.pid, "command": command_name},
            output_dir=self.state.output_dir,
            emit_live=False,
        )
        await self._emit({"type": "process_start", "pid": self.process.pid}, run_id=self.state.run_id)
        run_id = self.state.run_id
        self._reader_tasks = [
            asyncio.create_task(self._read_stdout(self.process, run_id, launch_seq)),
            asyncio.create_task(self._read_stderr(self.process, run_id, launch_seq)),
            asyncio.create_task(self._watch(self.process, run_id, launch_seq)),
        ]

    def _default_command(self, command_name: str, payload: dict[str, Any]) -> list[str]:
        runner = self.root / "app" / "swarm_runner.py"
        project = str(payload.get("project_name") or self.state.project_name or "swarm_soc")
        output_dir = str(payload.get("output_dir") or self.state.output_dir or self.root / "outputs" / "studio_runs" / project)
        checkpoint_db = str(
            payload.get("checkpoint_db")
            or payload.get("checkpointDb")
            or self.state.checkpoint_db
            or self.root / ".swarm" / "studio_web_checkpoints.sqlite"
        )
        planning_mode = str(payload.get("planning_mode") or self.state.planning_mode or "normal")
        api_key_ref = str(payload.get("api_key_ref") or payload.get("apiKeyRef") or self.state.api_key_ref or DEFAULT_CREDENTIAL_REF)
        thread_id = str(payload.get("thread_id") or self.state.thread_id or f"studio-web-{project}-{self.state.run_id[:8]}")
        self.state.api_key_ref = api_key_ref
        self.state.thread_id = thread_id
        args = [
            sys.executable,
            str(runner),
            command_name,
            "--project-name",
            project,
            "--thread-id",
            thread_id,
            "--run-id",
            str(payload.get("run_id") or self.state.run_id),
            "--output-dir",
            output_dir,
            "--checkpoint-db",
            checkpoint_db,
            "--planning-mode",
            planning_mode,
        ]
        attachment_manifest = str(payload.get("attachment_manifest") or self.state.attachment_manifest_path or "")
        if attachment_manifest:
            args.extend(["--attachment-manifest", attachment_manifest])
        if command_name == "start":
            args.extend(["--requirement", str(payload.get("requirement") or self.state.requirement)])
        else:
            args.extend(["--notes", str(payload.get("notes") or "ok"), "--resume-action", str(payload.get("resume_action") or self.state.pause.get("action_required", "") if self.state.pause else "")])
            if payload.get("change"):
                args.extend(["--change", str(payload["change"])])
        return args

    async def _read_stdout(self, proc: asyncio.subprocess.Process, run_id: str, launch_seq: int) -> None:
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            if launch_seq != self._launch_seq:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                event = json.loads(text)
                if not isinstance(event, dict):
                    event = {"type": "log", "level": "info", "message": text}
            except json.JSONDecodeError:
                event = {"type": "log", "level": "info", "message": text}
            await self._emit(event, run_id=run_id)

    async def _read_stderr(self, proc: asyncio.subprocess.Process, run_id: str, launch_seq: int) -> None:
        assert proc.stderr is not None
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            if launch_seq != self._launch_seq:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                await self._emit({"type": "log", "level": "error", "message": text}, run_id=run_id)

    async def _watch(self, proc: asyncio.subprocess.Process, run_id: str, launch_seq: int) -> None:
        code = await proc.wait()
        if launch_seq != self._launch_seq:
            return
        await self._drain_reader_tasks()
        await self._emit({"type": "process_exit", "returncode": code}, run_id=run_id)
        if self.process is proc:
            self.process = None

    async def _drain_reader_tasks(self) -> None:
        current = asyncio.current_task()
        tasks = [task for task in self._reader_tasks if task is not current and not task.done()]
        if not tasks:
            return
        try:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=1)
        except asyncio.TimeoutError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _emit(self, event: dict[str, Any], *, run_id: str | None = None) -> None:
        event_run_id = str(event.get("run_id") or run_id or self.state.run_id)
        if run_id and self.state.run_id and event_run_id != self.state.run_id:
            return
        if event_run_id:
            event = {**event, "run_id": event_run_id}
        if self.state.job_id and not event.get("job_id"):
            event = {**event, "job_id": self.state.job_id}
        clean = redact_secret_text(event)
        self.state.last_event_id += 1
        clean["event_id"] = self.state.last_event_id
        self.state.apply_event(clean)
        runtime_events: list[dict[str, Any]] = []
        try:
            runtime_events = self.runtime_tracker.record_source_event(clean, self.state.snapshot())
        except Exception as exc:
            runtime_events = []
            clean = {**clean, "runtime_tracking_error": str(exc)}
        if self.event_sink is not None:
            await self.event_sink(clean)
            await self._publish_runtime_events(runtime_events)

    async def _publish_runtime_events(self, events: list[dict[str, Any]]) -> None:
        if self.event_sink is None:
            return
        for event in events:
            await self.event_sink(event)
