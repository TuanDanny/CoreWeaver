from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PersistentStateValidationResult:
    passed: bool
    errors: tuple[str, ...]


def validate_feature_list(repo_root: str | Path) -> PersistentStateValidationResult:
    root = Path(repo_root)
    schema_path = root / "feature_list.schema.json"
    data_path = root / "feature_list.json"
    errors: list[str] = []

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return PersistentStateValidationResult(False, (f"feature_list.schema.json: {exc}",))

    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return PersistentStateValidationResult(False, (f"feature_list.json: {exc}",))

    _validate_object(
        data,
        schema,
        path="$",
        errors=errors,
    )
    return PersistentStateValidationResult(passed=not errors, errors=tuple(errors))


def _validate_object(payload: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    if schema.get("type") != "object":
        errors.append(f"{path}: unsupported schema type {schema.get('type')!r}")
        return
    if not isinstance(payload, dict):
        errors.append(f"{path}: expected object")
        return

    required = tuple(schema.get("required", ()))
    for key in required:
        if key not in payload:
            errors.append(f"{path}.{key}: missing required field")

    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        allowed = set(properties)
        for key in payload:
            if key not in allowed:
                errors.append(f"{path}.{key}: additional properties are not allowed")

    for key, value in payload.items():
        subschema = properties.get(key)
        if subschema is None:
            continue
        _validate_value(value, subschema, f"{path}.{key}", errors)


def _validate_value(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    schema_type = schema.get("type")
    if schema_type == "string":
        if not isinstance(value, str):
            errors.append(f"{path}: expected string")
            return
        enum_values = schema.get("enum")
        if enum_values is not None and value not in enum_values:
            allowed = ", ".join(str(item) for item in enum_values)
            errors.append(f"{path}: expected one of {allowed}")
        return

    if schema_type == "array":
        if not isinstance(value, list):
            errors.append(f"{path}: expected array")
            return
        item_schema = schema.get("items")
        if not isinstance(item_schema, dict):
            errors.append(f"{path}: array schema is missing items")
            return
        for index, item in enumerate(value):
            _validate_value(item, item_schema, f"{path}[{index}]", errors)
        return

    if schema_type == "object":
        _validate_object(value, schema, path, errors)
        return

    errors.append(f"{path}: unsupported schema type {schema_type!r}")
