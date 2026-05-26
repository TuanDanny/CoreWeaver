import pytest

from semiconductor_swarm.agents.agent1_planning.signoff_models import (
    BENCHMARK_CASE_SCHEMA_VERSION,
    BENCHMARK_RESULT_SCHEMA_VERSION,
    SIGNOFF_CERTIFICATE_SCHEMA_VERSION,
    SIGNOFF_GATES,
    SIGNOFF_JSON_SCHEMAS,
    SIGNOFF_WAIVERS_SCHEMA_VERSION,
    Agent1FinalSignoffCertificate,
    BenchmarkCase,
    BenchmarkResult,
    SignoffFinding,
    SignoffSchemaError,
    SignoffWaiver,
    SignoffWaivers,
    validate_sha256,
)


HASH = "a" * 64
OTHER_HASH = "b" * 64
NOW = "2026-05-25T00:00:00+00:00"


def _waiver_payload() -> dict:
    return {
        "waiver_id": "WVR-001",
        "owner": "chief.engineer",
        "reason": "Known non-critical benchmark warning accepted for smoke only.",
        "risk_level": "LOW",
        "expires_at": "2026-06-25T00:00:00+00:00",
        "affected_gate": "G09",
        "matching_finding_code": "CRITIC_LOW_CONFIDENCE",
        "approval_signature": HASH,
    }


def _finding_payload() -> dict:
    return {
        "finding_id": "FND-001",
        "gate": "G03",
        "code": "STALE_ARTIFACT",
        "severity": "P1_BLOCKER",
        "source": "agent1.signoff",
        "message": "Artifact hash does not match current revision.",
        "details": {"expected_sha256": HASH, "actual_sha256": OTHER_HASH},
        "run_id": "run-001",
        "revision_id": "rev-001",
        "artifact_ref": "reports/architecture_plan.md",
        "node_id": "G03",
        "case_id": None,
        "waivable": True,
        "waiver_id": None,
        "timestamp": NOW,
    }


def _gate_results(status: str = "PASS") -> dict:
    return {gate: {"status": status, "finding_codes": []} for gate in SIGNOFF_GATES}


def _certificate_payload() -> dict:
    return {
        "schema_version": SIGNOFF_CERTIFICATE_SCHEMA_VERSION,
        "run_id": "run-001",
        "revision_id": "rev-001",
        "project": "cpu32bit_web",
        "profile": "strict",
        "decision": "PASS",
        "handoff_allowed": True,
        "score": 99.5,
        "gate_results": _gate_results(),
        "finding_summary": {"total": 0, "by_severity": {"P0_FATAL": 0}},
        "waiver_summary": {"used": 0, "rejected": 0},
        "benchmark_summary": {
            "case_count": 110,
            "false_pass_count": 0,
            "must_not_pass_violation_count": 0,
        },
        "artifact_hashes": {"reports/architecture_plan.md": HASH},
        "topology_hash": HASH,
        "config_hash": HASH,
        "prompt_pack_hash": HASH,
        "model_ref_hash": HASH,
        "user_approval_ref": "approval-ok-001",
        "created_at": NOW,
    }


def _benchmark_case_payload() -> dict:
    return {
        "schema_version": BENCHMARK_CASE_SCHEMA_VERSION,
        "case_id": "TC-001",
        "category": "stale_missing_hash_artifact",
        "profile": "strict",
        "requirement": "Generate APB UART peripheral with formal-first register checks.",
        "attachments": [],
        "mutations": [{"type": "replace_artifact_hash", "artifact_ref": "reports/architecture_plan.md"}],
        "waivers": [],
        "expected_decision": "BLOCKED",
        "expected_handoff_allowed": False,
        "expected_finding_codes": ["STALE_ARTIFACT"],
        "must_not_pass": True,
        "oracle_notes": "Stale artifact must block strict handoff.",
        "expected_debug_issue_codes": ["STALE_ARTIFACT"],
    }


def _benchmark_result_payload() -> dict:
    return {
        "schema_version": BENCHMARK_RESULT_SCHEMA_VERSION,
        "case_id": "TC-001",
        "profile": "strict",
        "actual_decision": "BLOCKED",
        "actual_handoff_allowed": False,
        "actual_finding_codes": ["STALE_ARTIFACT"],
        "expected_match": True,
        "false_pass": False,
        "false_block": False,
        "must_not_pass_violation": False,
        "oracle_disagreement": False,
        "latency_s": 0.25,
        "token_cost_estimate": 0.0,
        "artifact_refs": ["agent1_signoff_benchmark_report.json"],
        "debug_issue_refs": ["issue-001"],
    }


def test_phase1_signoff_finding_accepts_valid_payload():
    finding = SignoffFinding.from_dict(_finding_payload())
    assert finding.gate == "G03"
    assert finding.to_dict()["details"]["expected_sha256"] == HASH


def test_phase1_waivers_bundle_accepts_valid_payload():
    bundle = SignoffWaivers.from_dict(
        {"schema_version": SIGNOFF_WAIVERS_SCHEMA_VERSION, "waivers": [_waiver_payload()]}
    )
    assert bundle.waivers[0].matching_finding_code == "CRITIC_LOW_CONFIDENCE"


def test_phase1_final_certificate_accepts_valid_payload():
    cert = Agent1FinalSignoffCertificate.from_dict(_certificate_payload())
    assert cert.handoff_allowed is True
    assert cert.benchmark_summary["false_pass_count"] == 0


def test_phase1_benchmark_case_and_result_accept_valid_payloads():
    case = BenchmarkCase.from_dict(_benchmark_case_payload())
    result = BenchmarkResult.from_dict(_benchmark_result_payload())
    assert case.must_not_pass is True
    assert result.expected_match is True


def test_phase1_json_schema_bundle_exposes_required_contracts():
    assert set(SIGNOFF_JSON_SCHEMAS) == {
        "signoff_finding",
        "agent1_final_signoff_certificate",
        "signoff_waivers",
        "benchmark_case",
        "benchmark_result",
    }
    assert "G12" in SIGNOFF_JSON_SCHEMAS["signoff_finding"]["properties"]["gate"]["enum"]


def test_phase1_rejects_invalid_waiver_expiry_datetime():
    payload = _waiver_payload()
    payload["expires_at"] = "tomorrow"
    with pytest.raises(SignoffSchemaError, match="expires_at"):
        SignoffWaiver.from_dict(payload)


def test_phase1_rejects_hash_not_sha256_lowercase():
    with pytest.raises(SignoffSchemaError, match="SHA256"):
        validate_sha256("A" * 64, "topology_hash")
    payload = _certificate_payload()
    payload["topology_hash"] = "abc"
    with pytest.raises(SignoffSchemaError, match="topology_hash"):
        Agent1FinalSignoffCertificate.from_dict(payload)


def test_phase1_rejects_datetime_without_timezone():
    payload = _finding_payload()
    payload["timestamp"] = "2026-05-25T00:00:00"
    with pytest.raises(SignoffSchemaError, match="timezone"):
        SignoffFinding.from_dict(payload)


def test_phase1_rejects_invalid_gate_and_unknown_key():
    payload = _finding_payload()
    payload["gate"] = "G99"
    with pytest.raises(SignoffSchemaError, match="gate"):
        SignoffFinding.from_dict(payload)

    payload = _finding_payload()
    payload["extra"] = "not allowed"
    with pytest.raises(SignoffSchemaError, match="unknown keys"):
        SignoffFinding.from_dict(payload)


def test_phase1_rejects_secret_like_debug_details():
    payload = _finding_payload()
    payload["details"] = {"api_key": "should-never-enter-debug"}
    with pytest.raises(SignoffSchemaError, match="secret-like key"):
        SignoffFinding.from_dict(payload)


def test_phase1_rejects_certificate_missing_gate_result():
    payload = _certificate_payload()
    payload["gate_results"].pop("G12")
    with pytest.raises(SignoffSchemaError, match="missing gates"):
        Agent1FinalSignoffCertificate.from_dict(payload)


def test_phase1_rejects_failed_certificate_with_handoff_allowed():
    payload = _certificate_payload()
    payload["decision"] = "FAILED"
    with pytest.raises(SignoffSchemaError, match="handoff_allowed"):
        Agent1FinalSignoffCertificate.from_dict(payload)


def test_phase1_rejects_handoff_when_benchmark_safety_zero_fails():
    payload = _certificate_payload()
    payload["benchmark_summary"]["false_pass_count"] = 1
    with pytest.raises(SignoffSchemaError, match="safety-zero"):
        Agent1FinalSignoffCertificate.from_dict(payload)


def test_phase1_rejects_must_not_pass_case_that_expects_pass():
    payload = _benchmark_case_payload()
    payload["expected_decision"] = "PASS"
    payload["expected_handoff_allowed"] = True
    with pytest.raises(SignoffSchemaError, match="must_not_pass"):
        BenchmarkCase.from_dict(payload)


def test_phase1_rejects_false_pass_without_handoff():
    payload = _benchmark_result_payload()
    payload["expected_match"] = False
    payload["false_pass"] = True
    with pytest.raises(SignoffSchemaError, match="false_pass"):
        BenchmarkResult.from_dict(payload)
