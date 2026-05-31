from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from coreweaver.framework_types import JsonBlockKind, StrictCoreModel, ensure_jsonable, validate_id_text, validate_sha256_text

MessageHash = str


class EvidenceRef(StrictCoreModel):
    evidence_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    artifact_ref: str
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")

    @field_validator("evidence_id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        return validate_id_text(value, "evidence_id")

    @field_validator("sha256")
    @classmethod
    def _valid_sha(cls, value: str) -> str:
        return validate_sha256_text(value)


class MessageBlock(StrictCoreModel):
    block_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    kind: JsonBlockKind
    content: Any
    content_type: str = "application/json"

    @field_validator("block_id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        return validate_id_text(value, "block_id")

    @field_validator("content")
    @classmethod
    def _jsonable(cls, value: Any) -> Any:
        return ensure_jsonable(value, "content")
