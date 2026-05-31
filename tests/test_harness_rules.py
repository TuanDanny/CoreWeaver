import json
import subprocess
import sys
from pathlib import Path

import pytest

from coreweaver.harness.architecture import ArchitectureViolation, DependencyEdge, Layer
from coreweaver.harness.models import DebugIssue, HarnessValidationError, IssueSeverity
from coreweaver.harness.rule_engine import HarnessContext, RuleEngine
from coreweaver.harness.rules import load_rule, load_rules
from coreweaver.harness.secret_scan import SecretFinding


ROOT = Path(__file__).resolve().parents[1]


def _write_rule(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _base_rule() -> dict:
    return {
        "id": "test.rule",
        "version": "1.0.0",
        "severity": "error",
        "description": "test rule",
        "applies_to": "test",
        "when": {"secret_finding_exists": {}},
        "then": {"block": {"action": "test"}},
    }


def test_valid_rule_loads(tmp_path: Path) -> None:
    rule = load_rule(_write_rule(tmp_path / "valid.rule", _base_rule()))
    assert rule.id == "test.rule"
    assert rule.condition.predicate == "secret_finding_exists"


def test_malformed_json_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad.rule"
    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(HarnessValidationError):
        load_rule(path)


def test_missing_required_field_fails(tmp_path: Path) -> None:
    payload = _base_rule()
    del payload["then"]
    with pytest.raises(HarnessValidationError):
        load_rule(_write_rule(tmp_path / "missing.rule", payload))


def test_unknown_predicate_fails(tmp_path: Path) -> None:
    payload = _base_rule()
    payload["when"] = {"run_python": {}}
    with pytest.raises(HarnessValidationError):
        load_rule(_write_rule(tmp_path / "unknown-predicate.rule", payload))


def test_unknown_action_fails(tmp_path: Path) -> None:
    payload = _base_rule()
    payload["then"] = {"execute": {}}
    with pytest.raises(HarnessValidationError):
        load_rule(_write_rule(tmp_path / "unknown-action.rule", payload))


def test_blocker_issue_blocks_agent2_handoff() -> None:
    rules = tuple(rule for rule in load_rules(ROOT / ".rules") if rule.id == "handoff.no_agent2_on_blocker")
    issue = DebugIssue(
        severity=IssueSeverity.BLOCKER,
        source="test",
        code="blocked",
        message="blocked",
        timestamp="2026-05-26T20:00:00Z",
    )
    result = RuleEngine(rules).run(HarnessContext(debug_issues=(issue,)))[0]
    assert not result.passed
    assert result.action == "block"


def test_secret_finding_triggers_security_rule() -> None:
    rules = tuple(rule for rule in load_rules(ROOT / ".rules") if rule.id == "security.no_secret_in_trace")
    finding = SecretFinding(code="openai_key", line=1, column=1, preview="redacted")
    result = RuleEngine(rules).run(HarnessContext(secret_findings=(finding,)))[0]
    assert not result.passed
    assert result.severity == IssueSeverity.BLOCKER


def test_architecture_violation_triggers_layer_rule() -> None:
    rules = tuple(rule for rule in load_rules(ROOT / ".rules") if rule.id == "architecture.layer_order")
    violation = ArchitectureViolation(
        code="backward_layer",
        message="dependency points backward",
        edge=DependencyEdge("agent", Layer.RUNTIME, "agent", Layer.TYPES),
    )
    result = RuleEngine(rules).run(HarnessContext(architecture_violations=(violation,)))[0]
    assert not result.passed
    assert result.severity == IssueSeverity.ERROR


def test_harness_check_cli_includes_rules_and_passes() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/harness_check.py", "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["passed"] is True
    assert report["rules"]["passed"] is True
    assert report["rules"]["results"]


def test_required_text_rule_fails_when_doctrine_text_missing(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "HARNESS_ENGINEERING.md").write_text("missing doctrine", encoding="utf-8")
    rule = load_rule(ROOT / ".rules" / "docs.reference_doctrine_contract.rule")
    result = RuleEngine((rule,)).run(HarnessContext(repo_root=str(tmp_path)))[0]
    assert not result.passed
    assert result.details["missing_text"]


def test_reference_doctrine_rule_passes_repo_doc() -> None:
    rule = load_rule(ROOT / ".rules" / "docs.reference_doctrine_contract.rule")
    result = RuleEngine((rule,)).run(HarnessContext(repo_root=str(ROOT)))[0]
    assert result.passed


def test_src_layout_rule_blocks_root_core_package(tmp_path: Path) -> None:
    (tmp_path / "coreweaver").mkdir()
    rule = load_rule(ROOT / ".rules" / "architecture.src_layout.rule")
    result = RuleEngine((rule,)).run(HarnessContext(repo_root=str(tmp_path)))[0]
    assert not result.passed
    assert result.details["forbidden_paths"] == ["coreweaver"]


def test_src_layout_rule_blocks_legacy_root_internals(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "patterns").mkdir()
    (tmp_path / "main.py").write_text("legacy entrypoint", encoding="utf-8")
    rule = load_rule(ROOT / ".rules" / "architecture.src_layout.rule")
    result = RuleEngine((rule,)).run(HarnessContext(repo_root=str(tmp_path)))[0]
    assert not result.passed
    assert result.details["forbidden_paths"] == ["app", "patterns", "main.py"]


def test_src_layout_rule_passes_current_repo() -> None:
    rule = load_rule(ROOT / ".rules" / "architecture.src_layout.rule")
    result = RuleEngine((rule,)).run(HarnessContext(repo_root=str(ROOT)))[0]
    assert result.passed


def test_harness_check_cli_injected_failure_fails_rules() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/harness_check.py", "--json", "--inject-failing-context"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 1
    report = json.loads(completed.stdout)
    assert report["passed"] is False
    assert report["rules"]["passed"] is False
    failed = [result for result in report["rules"]["results"] if not result["passed"]]
    assert any(result["rule_id"] == "handoff.no_agent2_on_blocker" for result in failed)
