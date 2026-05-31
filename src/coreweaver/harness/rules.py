from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import HarnessValidationError, IssueSeverity, ensure_jsonable, validate_id

SUPPORTED_PREDICATES = frozenset(
    {
        "any_debug_issue",
        "missing_required_event_field",
        "architecture_violation_exists",
        "secret_finding_exists",
        "knowledge_inventory_missing",
        "scope_violation_exists",
        "git_ignore_missing",
        "required_text_missing",
        "forbidden_paths_exist",
    }
)

SUPPORTED_ACTIONS = frozenset(
    {
        "block",
        "warn",
        "require_human_review",
        "emit_issue",
    }
)

REQUIRED_RULE_FIELDS = frozenset(
    {
        "id",
        "version",
        "severity",
        "description",
        "applies_to",
        "when",
        "then",
    }
)


@dataclass(frozen=True)
class RuleCondition:
    predicate: str
    params: dict[str, Any]

    def __post_init__(self) -> None:
        validate_id(self.predicate, "predicate")
        if self.predicate not in SUPPORTED_PREDICATES:
            raise HarnessValidationError(f"unsupported rule predicate: {self.predicate}")
        ensure_jsonable(self.params, "condition params")

    def to_dict(self) -> dict[str, Any]:
        return {self.predicate: self.params}


@dataclass(frozen=True)
class RuleAction:
    action: str
    params: dict[str, Any]

    def __post_init__(self) -> None:
        validate_id(self.action, "action")
        if self.action not in SUPPORTED_ACTIONS:
            raise HarnessValidationError(f"unsupported rule action: {self.action}")
        ensure_jsonable(self.params, "action params")

    def to_dict(self) -> dict[str, Any]:
        return {self.action: self.params}


@dataclass(frozen=True)
class Rule:
    id: str
    version: str
    severity: IssueSeverity
    description: str
    applies_to: str
    condition: RuleCondition
    action: RuleAction
    path: str | None = None

    def __post_init__(self) -> None:
        validate_id(self.id, "rule id")
        validate_id(self.version, "rule version")
        if isinstance(self.severity, str):
            object.__setattr__(self, "severity", IssueSeverity(self.severity))
        if not self.description.strip():
            raise HarnessValidationError("rule description is required")
        validate_id(self.applies_to, "applies_to")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "severity": self.severity.value,
            "description": self.description,
            "applies_to": self.applies_to,
            "when": self.condition.to_dict(),
            "then": self.action.to_dict(),
            "path": self.path,
        }


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    passed: bool
    severity: IssueSeverity
    applies_to: str
    action: str
    message: str
    details: dict[str, Any]

    def __post_init__(self) -> None:
        validate_id(self.rule_id, "rule_id")
        if isinstance(self.severity, str):
            object.__setattr__(self, "severity", IssueSeverity(self.severity))
        validate_id(self.applies_to, "applies_to")
        validate_id(self.action, "action")
        if not self.message:
            raise HarnessValidationError("rule result message is required")
        ensure_jsonable(self.details, "rule result details")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["severity"] = self.severity.value
        return data


def load_rules(directory: str | Path) -> tuple[Rule, ...]:
    root = Path(directory)
    if not root.exists():
        raise HarnessValidationError(f"rule directory does not exist: {root}")
    rules = [load_rule(path) for path in sorted(root.glob("*.rule"))]
    seen: set[str] = set()
    for rule in rules:
        if rule.id in seen:
            raise HarnessValidationError(f"duplicate rule id: {rule.id}")
        seen.add(rule.id)
    return tuple(rules)


def load_rule(path: str | Path) -> Rule:
    rule_path = Path(path)
    try:
        raw = json.loads(rule_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HarnessValidationError(f"invalid rule JSON: {rule_path}") from exc
    if not isinstance(raw, dict):
        raise HarnessValidationError("rule root must be an object")
    missing = sorted(REQUIRED_RULE_FIELDS - set(raw))
    if missing:
        raise HarnessValidationError(f"rule missing required fields: {', '.join(missing)}")
    extra = sorted(set(raw) - REQUIRED_RULE_FIELDS)
    if extra:
        raise HarnessValidationError(f"rule has unknown fields: {', '.join(extra)}")
    return Rule(
        id=raw["id"],
        version=raw["version"],
        severity=IssueSeverity(raw["severity"]),
        description=raw["description"],
        applies_to=raw["applies_to"],
        condition=_parse_singleton(raw["when"], RuleCondition, "when"),
        action=_parse_singleton(raw["then"], RuleAction, "then"),
        path=str(rule_path),
    )


def _parse_singleton(
    value: Any,
    cls: type[RuleCondition] | type[RuleAction],
    field_name: str,
) -> RuleCondition | RuleAction:
    if not isinstance(value, dict) or len(value) != 1:
        raise HarnessValidationError(f"{field_name} must contain exactly one entry")
    key, params = next(iter(value.items()))
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise HarnessValidationError(f"{field_name} params must be an object")
    return cls(key, params)
