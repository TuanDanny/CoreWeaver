"""Studio Agent Service boundary over runner, queue, and draft jobs."""
from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from pathlib import Path
from typing import Any, Awaitable, Callable

from studio.backend.config import DEFAULT_CREDENTIAL_REF, ROOT
from studio.backend.event_hub import EventHub
from studio.backend.job_models import AgentJob, JobCreateRequest
from studio.backend.job_queue import InProcessJobQueue, JobNotFound
from studio.backend.run_manifest import OutputPolicyError
from studio.backend.runner import RunnerManager
from semiconductor_swarm.agents.agent2_rtl.rtl_designer import generate_rtl_files, verify_rtl_files

CredentialPreflight = Callable[[str | None], Awaitable[None]]


class AgentService:
    """Owns validation, job creation, cancellation, and runner dispatch."""

    def __init__(
        self,
        *,
        runner: RunnerManager,
        event_hub: EventHub,
        queue: InProcessJobQueue | None = None,
        credential_preflight: CredentialPreflight | None = None,
        root: Path = ROOT,
    ) -> None:
        self.runner = runner
        self.event_hub = event_hub
        self.queue = queue or InProcessJobQueue(event_sink=event_hub.publish)
        if queue is None or getattr(self.queue, "event_sink", None) is None:
            self.queue.event_sink = self.publish_queue_event
        self.credential_preflight = credential_preflight
        self.root = root
        self._worker_task: asyncio.Task[Any] | None = None
        self._active_job_id: str | None = None
        self._started_conditions: dict[str, asyncio.Event] = {}

    async def publish_runner_event(self, event: dict[str, Any]) -> None:
        job_id = str(event.get("job_id") or getattr(self.runner.state, "job_id", "") or "")
        if job_id:
            event = {**event, "job_id": job_id}
            await self._apply_runner_event_to_job(job_id, event)
        await self.event_hub.publish(event)

    async def publish_queue_event(self, event: dict[str, Any]) -> None:
        await self.event_hub.publish(event)
        state = self._state_for_runtime_event(event)
        tracker = getattr(self.runner, "runtime_tracker", None)
        if tracker is None:
            return
        try:
            runtime_events = tracker.record_source_event(event, state)
        except Exception:
            runtime_events = []
        for runtime_event in runtime_events:
            await self.event_hub.publish(runtime_event)

    async def start_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        conflict = self.runner.output_conflict(payload) if hasattr(self.runner, "output_conflict") else None
        if conflict:
            raise OutputPolicyError(conflict)
        await self._preflight(payload.get("api_key_ref") or payload.get("apiKeyRef") or DEFAULT_CREDENTIAL_REF)
        self.event_hub.clear()
        request = JobCreateRequest(
            type="full_swarm_run",
            requirement=str(payload.get("requirement") or ""),
            project_name=str(payload.get("project_name") or "swarm_soc"),
            output_dir=str(payload.get("output_dir") or ""),
            planning_mode=str(payload.get("planning_mode") or "normal"),
            checkpoint_db=str(payload.get("checkpoint_db") or payload.get("checkpointDb") or ""),
            apiKeyRef=str(payload.get("api_key_ref") or payload.get("apiKeyRef") or DEFAULT_CREDENTIAL_REF),
            startPolicy=str(payload.get("start_policy") or payload.get("startPolicy") or "auto"),
            attachmentDraftId=str(payload.get("attachment_draft_id") or payload.get("attachmentDraftId") or ""),
            attachmentIds=list(payload.get("attachment_ids") or payload.get("attachmentIds") or []),
        )
        job = await self.enqueue_job(request, preflight=True)
        await self._wait_for_job_started(job.job_id)
        refreshed = await self.queue.get(job.job_id)
        if refreshed.status == "failed":
            raise RuntimeError(refreshed.error or "job failed")
        snapshot = self.runner.state.snapshot() if getattr(self.runner.state, "run_id", "") else refreshed.to_public_dict()
        return {**snapshot, "job_id": job.job_id}

    async def resume_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = str(getattr(self.runner.state, "job_id", "") or self._active_job_id or "")
        if job_id:
            payload = {**payload, "job_id": job_id}
            await self.queue.mark_status(job_id, "running")
        state = await self.runner.resume(payload)
        return {**state, "job_id": job_id} if job_id else state

    async def stop_run(self) -> dict[str, Any]:
        job_id = str(getattr(self.runner.state, "job_id", "") or self._active_job_id or "")
        state = await self.runner.stop()
        if job_id:
            with suppress(JobNotFound):
                await self.queue.mark_status(job_id, "cancelled", run_id=str(state.get("run_id") or ""))
        return {**state, "job_id": job_id} if job_id else state

    async def enqueue_job(self, request: JobCreateRequest, *, preflight: bool = True) -> AgentJob:
        payload = request.to_runner_payload()
        if request.type in {"full_swarm_run", "agent1_plan_draft", "agent2_rtl_draft"} and preflight:
            conflict = self.runner.output_conflict(payload) if request.type in {"full_swarm_run", "agent1_plan_draft"} and hasattr(self.runner, "output_conflict") else None
            if conflict:
                raise OutputPolicyError(conflict)
            await self._preflight(request.api_key_ref)
        output_dir = str(request.output_dir or self.root / "outputs" / "studio_runs" / request.project_name)
        job = AgentJob(
            type=request.type,
            project_name=request.project_name,
            requirement=request.requirement,
            planning_mode=request.planning_mode,
            output_dir=output_dir,
            checkpoint_db=request.checkpoint_db,
            credential_ref=request.api_key_ref,
            start_policy=request.start_policy,
            attachment_draft_id=request.attachment_draft_id,
            attachment_ids=request.attachment_ids,
        )
        await self.queue.enqueue(job)
        self._ensure_worker()
        return job

    async def cancel_job(self, job_id: str) -> AgentJob:
        if job_id == self._active_job_id and self.runner.running():
            await self.runner.stop()
        return await self.queue.cancel(job_id)

    async def list_jobs(self) -> list[AgentJob]:
        return await self.queue.list()

    async def get_job(self, job_id: str) -> AgentJob:
        return await self.queue.get(job_id)

    def queue_health(self) -> dict[str, Any]:
        return self.queue.health()

    def _state_for_runtime_event(self, event: dict[str, Any]) -> dict[str, Any]:
        state = self.runner.state.snapshot() if getattr(self.runner, "state", None) is not None else {}
        if not state.get("run_id") and event.get("run_id"):
            state["run_id"] = str(event.get("run_id") or "")
        for source_key, state_key in (
            ("job_id", "job_id"),
            ("project_name", "project_name"),
            ("output_dir", "output_dir"),
            ("planning_mode", "planning_mode"),
        ):
            if not state.get(state_key) and event.get(source_key):
                state[state_key] = str(event.get(source_key) or "")
        return state

    async def shutdown(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        await self.runner.shutdown()

    async def _preflight(self, ref_id: str | None) -> None:
        if self.credential_preflight is not None:
            await self.credential_preflight(ref_id)

    def _ensure_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def _worker_loop(self) -> None:
        while True:
            job = await self.queue.claim_next()
            self._active_job_id = job.job_id
            self._started_conditions.setdefault(job.job_id, asyncio.Event())
            try:
                await self._run_job(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self.queue.mark_status(job.job_id, "failed", error=str(exc))
                self._started_conditions[job.job_id].set()
            finally:
                if self._active_job_id == job.job_id:
                    self._active_job_id = None

    async def _run_job(self, job: AgentJob) -> None:
        if job.type == "debug_bundle":
            await self._run_debug_bundle(job)
            return
        if job.type == "agent2_rtl_draft":
            await self._run_agent2_rtl_draft(job)
            return
        await self.queue.mark_status(job.job_id, "running")
        runner_payload = {
            "requirement": job.requirement,
            "project_name": job.project_name,
            "output_dir": job.output_dir,
            "planning_mode": job.planning_mode,
            "checkpoint_db": job.checkpoint_db,
            "api_key_ref": job.credential_ref,
            "start_policy": job.start_policy,
            "attachment_draft_id": job.attachment_draft_id,
            "attachment_ids": job.attachment_ids,
            "job_id": job.job_id,
        }
        state = await self.runner.start(runner_payload)
        await self.queue.mark_status(job.job_id, "running", run_id=str(state.get("run_id") or ""))
        self._started_conditions[job.job_id].set()
        running = getattr(self.runner, "running", lambda: False)
        while running() or getattr(self.runner.state, "status", "") in {"starting", "running", "stopping"}:
            await asyncio.sleep(0.1)
        final = str(getattr(self.runner.state, "status", "completed"))
        if final == "paused":
            await self.queue.mark_status(job.job_id, "paused", run_id=self.runner.state.run_id)
        elif final == "done":
            await self.queue.mark_status(job.job_id, "completed", run_id=self.runner.state.run_id)
        elif final in {"failed"}:
            await self.queue.mark_status(job.job_id, "failed", run_id=self.runner.state.run_id, error="runner failed")
        elif final == "stopped":
            await self.queue.mark_status(job.job_id, "cancelled", run_id=self.runner.state.run_id)

    async def _run_debug_bundle(self, job: AgentJob) -> None:
        await self.queue.mark_status(job.job_id, "running")
        output_dir = Path(job.output_dir)
        reports = output_dir / "reports"
        traces = reports / "traces"
        candidates = [
            reports / "architecture_plan.md",
            reports / "agent1_conflict_matrix.json",
            reports / "agent1_v51_guardrail_report.json",
        ]
        if traces.exists():
            candidates.extend(traces.glob("*.jsonl"))
        artifact_refs = [str(path) for path in candidates if path.exists()]
        manifest = reports / "debug_bundle_manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"job_id": job.job_id, "artifacts": artifact_refs}, indent=2), encoding="utf-8")
        artifact_refs.append(str(manifest))
        await self.publish_runner_event({"type": "artifact", "job_id": job.job_id, "path": str(manifest), "message": "debug bundle manifest"})
        await self.queue.mark_status(job.job_id, "completed", artifact_refs=artifact_refs)
        self._started_conditions.setdefault(job.job_id, asyncio.Event()).set()

    async def _run_agent2_rtl_draft(self, job: AgentJob) -> None:
        await self.queue.mark_status(job.job_id, "running")
        output_dir = Path(job.output_dir)
        spec_path = self._find_agent1_to_agent2_contract(output_dir)
        if spec_path is None:
            await self.queue.mark_status(job.job_id, "failed", error="agent1_to_agent2 contract is required before Agent 2 RTL draft")
            self._started_conditions.setdefault(job.job_id, asyncio.Event()).set()
            return
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        rtl_files = generate_rtl_files(spec, debug=True)
        report = verify_rtl_files(spec, rtl_files)
        artifact_refs = self._write_rtl_draft_artifacts(output_dir, rtl_files, report, spec_path, job.job_id)
        for artifact in artifact_refs[:8]:
            await self.publish_runner_event({"type": "artifact", "job_id": job.job_id, "path": artifact, "message": "agent2 RTL draft artifact"})
        await self.queue.mark_status(job.job_id, "completed", artifact_refs=artifact_refs)
        self._started_conditions.setdefault(job.job_id, asyncio.Event()).set()

    def _find_agent1_to_agent2_contract(self, output_dir: Path) -> Path | None:
        candidates = [
            output_dir / "contracts" / "agent1_to_agent2.json",
            output_dir / "reports" / "agent1" / "agent1_to_agent2_contract",
        ]
        for path in candidates:
            if path.is_file():
                return path
        return None

    def _write_rtl_draft_artifacts(self, output_dir: Path, rtl_files: list[dict[str, Any]], report: dict[str, Any], spec_path: Path, job_id: str) -> list[str]:
        artifact_refs: list[str] = []
        rtl_root = output_dir / "rtl"
        reports_dir = rtl_root / "reports"
        for item in rtl_files:
            filename = str(item.get("filename") or "")
            content = str(item.get("content") or "")
            if not filename:
                continue
            language = str(item.get("language") or "")
            is_report = language in {"json", "markdown"} or filename.endswith((".json", ".md"))
            path = (reports_dir if is_report else rtl_root) / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            artifact_refs.append(str(path))
        summary = {
            "schema_version": "studio.agent2_rtl_draft.v1",
            "job_id": job_id,
            "source_contract": str(spec_path),
            "rtl_file_count": len([item for item in rtl_files if str(item.get("language")) == "systemverilog"]),
            "artifact_count": len(artifact_refs),
            "verification": report,
        }
        summary_path = reports_dir / "agent2_rtl_draft_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        artifact_refs.append(str(summary_path))
        return artifact_refs

    async def _wait_for_job_started(self, job_id: str) -> None:
        event = self._started_conditions.setdefault(job_id, asyncio.Event())
        try:
            await asyncio.wait_for(event.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            job = await self.queue.get(job_id)
            if job.status == "queued":
                raise RuntimeError("job did not start within timeout")

    async def _apply_runner_event_to_job(self, job_id: str, event: dict[str, Any]) -> None:
        try:
            job = await self.queue.get(job_id)
        except JobNotFound:
            return
        event_type = str(event.get("type") or "")
        run_id = str(event.get("run_id") or job.run_id or "")
        if event_type == "process_start":
            await self.queue.mark_status(job_id, "running", run_id=run_id)
            self._started_conditions.setdefault(job_id, asyncio.Event()).set()
        elif event_type == "pause":
            await self.queue.mark_status(job_id, "paused", run_id=run_id)
        elif event_type == "done":
            await self.queue.mark_status(job_id, "completed", run_id=run_id)
        elif event_type == "error":
            await self.queue.mark_status(job_id, "failed", run_id=run_id, error=str(event.get("message") or "runner error"))
        elif event_type == "watchdog_timeout":
            await self.queue.mark_status(job_id, "failed", run_id=run_id, error=str(event.get("message") or "runtime watchdog timeout"))
        elif event_type == "process_exit":
            if job.status == "failed":
                return
            returncode = event.get("returncode")
            if returncode not in (0, None):
                await self.queue.mark_status(job_id, "failed", run_id=run_id, error=f"process exited {returncode}")
