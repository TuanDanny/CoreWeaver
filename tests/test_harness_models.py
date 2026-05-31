import pytest

from coreweaver.harness.models import (
    ArtifactRef,
    DebugIssue,
    HarnessValidationError,
    IssueSeverity,
    ScopeContract,
)


def test_artifact_ref_rejects_bad_sha256() -> None:
    with pytest.raises(HarnessValidationError):
        ArtifactRef(path="out.json", sha256="bad-hash", kind="json")


def test_debug_issue_rejects_bad_timestamp() -> None:
    with pytest.raises(HarnessValidationError):
        DebugIssue(
            severity=IssueSeverity.ERROR,
            source="test",
            code="bad_time",
            message="bad timestamp",
            timestamp="not-a-date",
        )


def test_scope_contract_requires_forbidden_files() -> None:
    with pytest.raises(HarnessValidationError):
        ScopeContract(
            task_id="T1",
            goal="build harness",
            allowed_files=("src/coreweaver/**",),
            forbidden_files=(),
            acceptance_commands=("python -m pytest -q tests",),
            rollback_plan="delete harness files",
        )
