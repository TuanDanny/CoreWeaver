from __future__ import annotations

from typing import Any

from pydantic import Field

from coreweaver.framework_types import StrictCoreModel


class ToolSchema(StrictCoreModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    input_schema: dict[str, Any]

    def validate_input(self, payload: dict[str, Any]) -> None:
        required = self.input_schema.get("required", [])
        if not isinstance(required, list):
            raise ValueError("tool schema required must be a list")
        missing = [field for field in required if field not in payload]
        if missing:
            raise ValueError(f"tool input missing required fields: {missing}")
        properties = self.input_schema.get("properties", {})
        if isinstance(properties, dict):
            extra = set(payload) - set(properties)
            if extra and not self.input_schema.get("additionalProperties", True):
                raise ValueError(f"tool input has extra fields: {sorted(extra)}")
