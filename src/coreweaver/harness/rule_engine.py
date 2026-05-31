from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .architecture import ArchitectureViolation
from .knowledge import KnowledgeInventoryResult
from .models import DebugIssue, IssueSeverity, TraceEvent
from .rules import Rule, RuleResult
from .scope import ScopeCheckResult
from .secret_scan import SecretFinding


@dataclass(frozen=True)
class HarnessContext:
    repo_root: str | None = None
    trace_events: tuple[TraceEvent, ...] = ()
    debug_issues: tuple[DebugIssue, ...] = ()
    scope_result: ScopeCheckResult | None = None
    architecture_violations: tuple[ArchitectureViolation, ...] = ()
    knowledge_inventory: KnowledgeInventoryResult | None = None
    secret_findings: tuple[SecretFinding, ...] = ()
    git_ignore_missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleEngine:
    rules: tuple[Rule, ...]

    def run(self, context: HarnessContext) -> tuple[RuleResult, ...]:
        return tuple(_evaluate_rule(rule, context) for rule in self.rules)


def result_to_issue(result: RuleResult, timestamp: str | None = None) -> DebugIssue:
    return DebugIssue(
        severity=result.severity,
        source="harness.rule_engine",
        code=result.rule_id,
        message=result.message,
        timestamp=timestamp or _utc_now(),
        details=result.to_dict(),
    )


def _evaluate_rule(rule: Rule, context: HarnessContext) -> RuleResult:
    matched, details = _evaluate_condition(rule, context)
    passed = not matched
    action_word = rule.action.action
    message = (
        f"rule passed: {rule.id}"
        if passed
        else f"rule failed: {rule.id}; action={action_word}"
    )
    return RuleResult(
        rule_id=rule.id,
        passed=passed,
        severity=rule.severity,
        applies_to=rule.applies_to,
        action=action_word,
        message=message,
        details={
            "description": rule.description,
            "predicate": rule.condition.predicate,
            "predicate_params": rule.condition.params,
            "action_params": rule.action.params,
            "matched": matched,
            **details,
        },
    )


def _evaluate_condition(rule: Rule, context: HarnessContext) -> tuple[bool, dict[str, Any]]:
    predicate = rule.condition.predicate
    params = rule.condition.params
    if predicate == "any_debug_issue":
        return _any_debug_issue(context, params)
    if predicate == "missing_required_event_field":
        return _missing_required_event_field(context, params)
    if predicate == "architecture_violation_exists":
        count = len(context.architecture_violations)
        return count > 0, {"architecture_violation_count": count}
    if predicate == "secret_finding_exists":
        count = len(context.secret_findings)
        return count > 0, {"secret_finding_count": count}
    if predicate == "knowledge_inventory_missing":
        return _knowledge_inventory_missing(context)
    if predicate == "scope_violation_exists":
        count = len(context.scope_result.violations) if context.scope_result else 0
        return count > 0, {"scope_violation_count": count}
    if predicate == "git_ignore_missing":
        path = params.get("path")
        missing = tuple(context.git_ignore_missing)
        if path:
            return path in missing, {"git_ignore_missing": list(missing), "path": path}
        return bool(missing), {"git_ignore_missing": list(missing)}
    if predicate == "required_text_missing":
        return _required_text_missing(context, params)
    if predicate == "forbidden_paths_exist":
        return _forbidden_paths_exist(context, params)
    raise AssertionError(f"unreachable unsupported predicate: {predicate}")


def _any_debug_issue(
    context: HarnessContext,
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    severity = params.get("severity")
    code = params.get("code")
    source = params.get("source")
    matches: list[DebugIssue] = []
    for issue in context.debug_issues:
        if severity and issue.severity.value != severity:
            continue
        if code and issue.code != code:
            continue
        if source and issue.source != source:
            continue
        matches.append(issue)
    return bool(matches), {"debug_issue_count": len(matches)}


def _missing_required_event_field(
    context: HarnessContext,
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    fields = params.get("fields")
    if not isinstance(fields, list) or not all(isinstance(field, str) for field in fields):
        return True, {"invalid_rule_params": "fields must be a string array"}
    missing: list[dict[str, str]] = []
    for event in context.trace_events:
        for field_name in fields:
            value = getattr(event, field_name, None)
            if value is None or value == "":
                missing.append({"span_id": event.span_id, "field": field_name})
    return bool(missing), {"missing_event_fields": missing}


def _knowledge_inventory_missing(context: HarnessContext) -> tuple[bool, dict[str, Any]]:
    inventory = context.knowledge_inventory
    if inventory is None:
        return False, {"knowledge_inventory_present": False}
    missing_paths = list(inventory.missing_paths)
    stale_links = list(inventory.stale_links)
    return bool(missing_paths or stale_links), {
        "missing_paths": missing_paths,
        "stale_links": stale_links,
    }

def _required_text_missing(
    context: HarnessContext,
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    path_value = params.get("path")
    contains = params.get("contains")
    if not isinstance(path_value, str) or not path_value:
        return True, {"invalid_rule_params": "path must be a non-empty string"}
    if not isinstance(contains, list) or not all(isinstance(item, str) for item in contains):
        return True, {"invalid_rule_params": "contains must be a string array"}

    root = Path(context.repo_root or ".").resolve()
    target = (root / path_value).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return True, {"invalid_rule_params": "path must stay inside repo_root", "path": path_value}

    if not target.exists() or not target.is_file():
        return True, {"missing_file": path_value, "missing_text": list(contains)}
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return True, {"unreadable_file": path_value, "missing_text": list(contains)}

    missing_text = [snippet for snippet in contains if snippet not in text]
    return bool(missing_text), {"path": path_value, "missing_text": missing_text}

def _forbidden_paths_exist(
    context: HarnessContext,
    params: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    paths = params.get("paths")
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        return True, {"invalid_rule_params": "paths must be a string array"}
    root = Path(context.repo_root or ".").resolve()
    existing: list[str] = []
    for path_value in paths:
        target = (root / path_value).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return True, {"invalid_rule_params": "path must stay inside repo_root", "path": path_value}
        if target.exists():
            existing.append(path_value)
    return bool(existing), {"forbidden_paths": existing}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
