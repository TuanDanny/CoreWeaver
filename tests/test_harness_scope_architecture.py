from coreweaver.harness.architecture import DependencyEdge, Layer, LayeredArchitectureRule
from coreweaver.harness.models import ScopeContract
from coreweaver.harness.scope import ScopeChecker


def test_scope_checker_flags_forbidden_and_off_scope_paths() -> None:
    contract = ScopeContract(
        task_id="T1",
        goal="build harness",
        allowed_files=("src/coreweaver/**", "tests/**"),
        forbidden_files=("studio/**", "_private/**"),
        acceptance_commands=("python -m pytest -q tests",),
        rollback_plan="remove src/coreweaver and tests",
    )
    result = ScopeChecker(contract).check(
        touched_files=["src/coreweaver/harness/models.py", "studio/backend/server.py", "README.md"],
        commands_run=[],
    )
    assert not result.in_scope
    assert {violation.code for violation in result.violations} == {
        "forbidden_file",
        "off_scope_file",
        "missing_acceptance_command",
    }


def test_layer_rule_blocks_backward_and_cross_domain_edges() -> None:
    rule = LayeredArchitectureRule()
    violations = rule.check_edges(
        [
            DependencyEdge("settings", Layer.RUNTIME, "settings", Layer.TYPES),
            DependencyEdge("settings", Layer.SERVICE, "jobs", Layer.REPO),
            DependencyEdge("providers", Layer.PROVIDERS, "settings", Layer.REPO),
        ]
    )
    assert [violation.code for violation in violations] == ["backward_layer", "cross_domain"]
