from pathlib import Path

import pytest

from coreweaver.api import CoreWeaverRuntime
from coreweaver.contracts.studio_agent1 import (
    ContractValidationError,
    normalize_agent1_start_payload,
    validate_agent1_studio_event,
)
from coreweaver.run_profiles import load_run_profile

def test_run_profiles_define_credential_policy() -> None:
    assert load_run_profile("local_skeleton").requires_credential is False
    assert load_run_profile("ci_no_llm").requires_credential is False
    assert load_run_profile("local_llm").requires_credential is True
    assert CoreWeaverRuntime("local_llm").capabilities()["requiresCredential"] is True

def test_run_profile_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COREWEAVER_RUN_PROFILE", "ci_no_llm")
    assert CoreWeaverRuntime().capabilities()["profile"] == "ci_no_llm"

def test_unknown_run_profile_fails() -> None:
    with pytest.raises(Exception, match="unknown run profile"):
        load_run_profile("surprise")

def test_agent1_start_payload_normalizes_contract() -> None:
    request = normalize_agent1_start_payload(
        {
            "requirement": "APB GPIO",
            "project_name": "gpio",
            "planning_mode": "normal",
            "run_id": "run1",
            "thread_id": "thread1",
            "output_dir": "runs/gpio",
        }
    )
    assert request.output_dir == Path("runs/gpio")
    assert request.to_payload()["run_id"] == "run1"

def test_agent1_start_payload_requires_run_identity() -> None:
    with pytest.raises(ContractValidationError, match="run_id"):
        normalize_agent1_start_payload({"requirement": "APB GPIO", "thread_id": "thread1", "output_dir": "runs/gpio"})

def test_agent1_start_payload_requires_output_dir_text() -> None:
    with pytest.raises(ContractValidationError, match="output_dir"):
        normalize_agent1_start_payload({"requirement": "APB GPIO", "run_id": "run1", "thread_id": "thread1"})

def test_agent1_start_payload_rejects_unknown_mode() -> None:
    with pytest.raises(ContractValidationError, match="planning_mode"):
        normalize_agent1_start_payload(
            {
                "requirement": "APB GPIO",
                "run_id": "run1",
                "thread_id": "thread1",
                "output_dir": "runs/gpio",
                "planning_mode": "wizard",
            }
        )

def test_agent1_event_validation_allows_pause_contract() -> None:
    validate_agent1_studio_event(
        {
            "type": "pause",
            "run_id": "run1",
            "action_required": "PLAN_REVIEW",
            "message": "architecture plan ready",
        }
    )

def test_agent1_event_validation_rejects_bad_pause() -> None:
    with pytest.raises(ContractValidationError, match="pause type"):
        validate_agent1_studio_event(
            {
                "type": "pause",
                "run_id": "run1",
                "action_required": "RANDOM_GATE",
                "message": "bad",
            }
        )

def test_agent1_debug_issue_requires_core_fields() -> None:
    with pytest.raises(ContractValidationError, match="debug_issue requires code"):
        validate_agent1_studio_event(
            {
                "type": "debug_issue",
                "run_id": "run1",
                "severity": "error",
                "source": "agent1",
                "message": "missing code",
            }
        )

def test_dev_check_script_documents_standard_gate() -> None:
    text = Path("scripts/dev_check.ps1").read_text(encoding="utf-8")
    for token in ("pytest", "harness_check.py", "run_benchmarks.py", "npm"):
        assert token in text
