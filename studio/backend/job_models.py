"""Secret-safe Studio job contracts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal["queued", "running", "paused", "completed", "failed", "cancelled"]
JobType = Literal["agent1_plan_draft", "agent2_rtl_draft", "full_swarm_run", "debug_bundle"]
JobEventType = Literal["job_queued", "job_started", "job_progress", "job_completed", "job_failed", "job_cancelled"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentJob(BaseModel):
    """Canonical job record shared by API, queue, and UI."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    job_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str = ""
    type: JobType
    status: JobStatus = "queued"
    project_name: str = "swarm_soc"
    requirement: str = ""
    planning_mode: str = "normal"
    output_dir: str = ""
    checkpoint_db: str = ""
    credential_ref: str = "owner"
    start_policy: str = "auto"
    attachment_draft_id: str = ""
    attachment_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)
    started_at: str | None = None
    ended_at: str | None = None
    error: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        payload = self.model_dump()
        payload.pop("secret", None)
        return payload


class JobCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    type: JobType = "full_swarm_run"
    requirement: str = ""
    project_name: str = "swarm_soc"
    output_dir: str = ""
    planning_mode: Literal["normal", "deep_planning"] = "normal"
    checkpoint_db: str = ""
    api_key_ref: str = Field(default="owner", alias="apiKeyRef")
    start_policy: Literal["auto", "fresh", "continue"] = Field(default="auto", alias="startPolicy")
    attachment_draft_id: str = Field(default="", alias="attachmentDraftId")
    attachment_ids: list[str] = Field(default_factory=list, alias="attachmentIds")

    def to_runner_payload(self) -> dict[str, Any]:
        return {
            "requirement": self.requirement,
            "project_name": self.project_name,
            "output_dir": self.output_dir,
            "planning_mode": self.planning_mode,
            "checkpoint_db": self.checkpoint_db,
            "api_key_ref": self.api_key_ref,
            "start_policy": self.start_policy,
            "attachment_draft_id": self.attachment_draft_id,
            "attachment_ids": self.attachment_ids,
        }


def job_event(event_type: JobEventType, job: AgentJob, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": event_type,
        "job_id": job.job_id,
        "run_id": job.run_id,
        "job_type": job.type,
        "status": job.status,
        "project_name": job.project_name,
        "output_dir": job.output_dir,
        "planning_mode": job.planning_mode,
        "message": extra.pop("message", f"{job.type} {job.status}"),
    }
    payload.update(extra)
    return payload
