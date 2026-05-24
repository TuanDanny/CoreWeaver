"""In-process async queue for Studio jobs."""
from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
from typing import Any

from studio.backend.job_models import AgentJob, JobStatus, job_event, utc_now_iso


class JobQueueFull(RuntimeError):
    """Raised when the bounded queue cannot accept more work."""


class JobNotFound(KeyError):
    """Raised when a job ID is unknown."""


class InProcessJobQueue:
    """Small async queue with a future Redis/BullMQ-shaped API boundary."""

    def __init__(self, *, maxsize: int = 32, event_queue_size: int = 500, event_sink: Any | None = None) -> None:
        self.maxsize = maxsize
        self.event_sink = event_sink
        self._ready: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)
        self._jobs: dict[str, AgentJob] = {}
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._events: deque[dict[str, Any]] = deque(maxlen=2000)
        self._event_queue_size = event_queue_size
        self._lock = asyncio.Lock()

    async def enqueue(self, job: AgentJob) -> str:
        async with self._lock:
            if self._ready.full():
                raise JobQueueFull("Job queue is full")
            if job.job_id in self._jobs:
                raise ValueError(f"Duplicate job_id: {job.job_id}")
            job.status = "queued"
            self._jobs[job.job_id] = job
            self._ready.put_nowait(job.job_id)
        await self._publish(job_event("job_queued", job, message=f"queued {job.type}"))
        return job.job_id

    async def claim_next(self) -> AgentJob:
        while True:
            job_id = await self._ready.get()
            job = self._jobs.get(job_id)
            if job is None:
                continue
            if job.status == "cancelled":
                continue
            return job

    async def mark_status(self, job_id: str, status: JobStatus, *, error: str | None = None, artifact_refs: list[str] | None = None, run_id: str | None = None) -> AgentJob:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFound(job_id)
            job.status = status
            if run_id:
                job.run_id = run_id
            if status == "running" and not job.started_at:
                job.started_at = utc_now_iso()
            if status in {"completed", "failed", "cancelled"}:
                job.ended_at = utc_now_iso()
            if error:
                job.error = error
            if artifact_refs:
                job.artifact_refs = list(dict.fromkeys([*job.artifact_refs, *artifact_refs]))
        event_type = {
            "queued": "job_queued",
            "running": "job_started",
            "paused": "job_progress",
            "completed": "job_completed",
            "failed": "job_failed",
            "cancelled": "job_cancelled",
        }[status]
        await self._publish(job_event(event_type, job, message=error or f"{job.type} {status}", artifact_refs=job.artifact_refs))
        return job

    async def cancel(self, job_id: str) -> AgentJob:
        job = await self.get(job_id)
        if job.status in {"completed", "failed", "cancelled"}:
            return job
        return await self.mark_status(job_id, "cancelled")

    async def get(self, job_id: str) -> AgentJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        return job

    async def list(self) -> list[AgentJob]:
        return sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)

    def subscribe_events(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._event_queue_size)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def replay_events(self) -> list[dict[str, Any]]:
        return list(self._events)

    async def _publish(self, event: dict[str, Any]) -> None:
        self._events.append(event)
        if self.event_sink is not None:
            await self.event_sink(event)
        stale: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            self._subscribers.discard(queue)

    def health(self) -> dict[str, Any]:
        statuses: dict[str, int] = {}
        waits: list[float] = []
        durations: list[float] = []
        active_job_id = ""
        last_failure: dict[str, Any] | None = None
        for job in self._jobs.values():
            statuses[job.status] = statuses.get(job.status, 0) + 1
            if job.status == "running" and not active_job_id:
                active_job_id = job.job_id
            wait = _duration_ms(job.created_at, job.started_at)
            duration = _duration_ms(job.started_at, job.ended_at)
            if wait is not None:
                waits.append(wait)
            if duration is not None:
                durations.append(duration)
            if job.status == "failed" and job.error:
                last_failure = {"job_id": job.job_id, "error": job.error, "ended_at": job.ended_at}
        return {
            "backend": "in_process",
            "maxsize": self.maxsize,
            "queued": self._ready.qsize(),
            "running": statuses.get("running", 0),
            "completed": statuses.get("completed", 0),
            "failed": statuses.get("failed", 0),
            "cancelled": statuses.get("cancelled", 0),
            "jobs": len(self._jobs),
            "statuses": statuses,
            "averageWaitMs": round(sum(waits) / len(waits), 2) if waits else None,
            "averageDurationMs": round(sum(durations) / len(durations), 2) if durations else None,
            "activeJobId": active_job_id,
            "lastFailure": last_failure,
            "redisCompatibleAdapter": False,
        }


def _duration_ms(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError:
        return None
    return max(0.0, (end_dt - start_dt).total_seconds() * 1000)
