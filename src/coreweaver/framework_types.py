from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict

from .harness.secret_scan import scan_text_for_secrets

ID_PATTERN = r"^[A-Za-z0-9_.:-]{1,128}$"
SHA256_PATTERN = r"^[a-fA-F0-9]{64}$"
_ID_RE = re.compile(ID_PATTERN)
_SHA256_RE = re.compile(SHA256_PATTERN)
_SECRET_KEY_PARTS = ("api_key", "authorization", "token", "secret", "password", "bearer")


class StrictCoreModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=False)

    def safe_dump(self) -> dict[str, Any]:
        return redact_value(self.model_dump(mode="json"))


class CoreValidationError(ValueError):
    """Raised when a CoreWeaver framework contract is malformed."""


class JsonBlockKind(str, Enum):
    TEXT = "text"
    JSON = "json"
    MARKDOWN = "markdown"
    ARTIFACT_REF = "artifact_ref"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_id_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise ValueError(f"{field_name} must match {ID_PATTERN}")
    return value


def validate_optional_id(value: str | None, field_name: str) -> str | None:
    if value is None or value == "":
        return value
    return validate_id_text(value, field_name)


def validate_sha256_text(value: str, field_name: str = "sha256") -> str:
    if not isinstance(value, str) or not _SHA256_RE.match(value):
        raise ValueError(f"{field_name} must be 64 hex chars")
    return value.lower()


def validate_iso8601_text(value: str, field_name: str = "timestamp") -> str:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError(f"{field_name} must be ISO8601 datetime")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    datetime.fromisoformat(candidate)
    return value


def ensure_jsonable(value: Any, field_name: str) -> Any:
    try:
        json.dumps(value, sort_keys=True)
    except TypeError as exc:
        raise ValueError(f"{field_name} must be JSON serializable") from exc
    return value


def stable_hash(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def assert_no_secret(value: Any, field_name: str = "payload") -> Any:
    text = json.dumps(value, sort_keys=True, default=str)
    findings = scan_text_for_secrets(text)
    if findings:
        codes = ",".join(sorted({finding.code for finding in findings}))
        raise ValueError(f"{field_name} contains secret-like value: {codes}")
    return value


def redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}
        for key, child in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in _SECRET_KEY_PARTS):
                clean[str(key)] = "<redacted>"
            else:
                clean[str(key)] = redact_value(child)
        return clean
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        redacted = value
        for finding in scan_text_for_secrets(value):
            marker = value[finding.column - 1 :]
            redacted = redacted.replace(marker, "<redacted>")
        return redacted
    return value


def make_idempotency_key(*parts: object) -> str:
    return stable_hash([str(part) for part in parts])
