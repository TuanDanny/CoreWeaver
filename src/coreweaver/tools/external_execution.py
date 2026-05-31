from __future__ import annotations

from pydantic import Field

from coreweaver.framework_types import StrictCoreModel


class ExternalExecutionRequest(StrictCoreModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    tool_name: str
    command_preview: str
    placeholder_only: bool = True
