from __future__ import annotations

from pydantic import Field

from coreweaver.framework_types import StrictCoreModel, utc_now


class RuntimeState(StrictCoreModel):
    run_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    revision_id: str = "rev:0"
    status: str = "initialized"
    profile: str = "local_skeleton"
    requirement: str = ""
    project_name: str = "swarm_soc"
    planning_mode: str = "normal"
    output_dir: str = "runs"
    attachment_refs: tuple[str, ...] = ()
    active_span_id: str = "root"
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
