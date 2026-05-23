"""Schema registry and lightweight validation for versioned contracts."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .constants import PLANNED_V1_CONTRACTS


class ContractValidationError(ValueError):
    """Raised when contract payload fails registry validation."""


SCHEMA_DIR = Path(__file__).with_name("schemas")
SCHEMA_FILES = {
    name: SCHEMA_DIR / f"{name.replace('/', '__')}.schema.json"
    for name in PLANNED_V1_CONTRACTS
}


def list_contracts() -> tuple[str, ...]:
    return PLANNED_V1_CONTRACTS


@lru_cache(maxsize=None)
def get_contract_schema(contract_version: str) -> dict[str, Any]:
    if contract_version not in SCHEMA_FILES:
        raise KeyError(f"unknown contract: {contract_version}")
    path = SCHEMA_FILES[contract_version]
    if not path.exists():
        raise FileNotFoundError(f"missing schema for {contract_version}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_contract(contract_version: str, payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        raise ContractValidationError("payload must be dict")
    schema = get_contract_schema(contract_version)
    expected = schema.get("properties", {}).get("contract_version", {}).get("const")
    if expected and expected != contract_version:
        raise ContractValidationError(f"schema const mismatch: {expected} != {contract_version}")
    _validate_schema("$", payload, schema)
    return True


def _validate_schema(path: str, value: Any, schema: dict[str, Any]) -> None:
    _validate_type(path, value, schema.get("type"))

    if "enum" in schema and value not in schema["enum"]:
        raise ContractValidationError(f"invalid enum for {path}: {value}")
    if "const" in schema and value != schema["const"]:
        raise ContractValidationError(f"invalid const for {path}: {value}")

    schema_type = schema.get("type")
    if schema_type == "object" and isinstance(value, dict):
        properties = schema.get("properties", {})
        for field in schema.get("required", []):
            if field not in value:
                raise ContractValidationError(f"missing required field: {path}.{field}")
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise ContractValidationError(f"unexpected field at {path}: {extras[0]}")
        additional_schema = schema.get("additionalProperties")
        for field, item in value.items():
            child_path = f"{path}.{field}"
            if field in properties:
                _validate_schema(child_path, item, properties[field])
            elif isinstance(additional_schema, dict):
                _validate_schema(child_path, item, additional_schema)

    if schema_type == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_schema(f"{path}[{index}]", item, item_schema)


def _validate_type(field: str, value: Any, schema_type: str | list[str] | None) -> None:
    if schema_type is None:
        return
    allowed = schema_type if isinstance(schema_type, list) else [schema_type]
    checks = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "null": lambda v: v is None,
    }
    if not any(checks[t](value) for t in allowed if t in checks):
        raise ContractValidationError(f"invalid type for {field}: expected {allowed}")