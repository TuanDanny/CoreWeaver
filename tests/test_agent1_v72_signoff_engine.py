import json
from pathlib import Path

import pytest

from semiconductor_swarm.agents.agent1_planning.architect import generate_architecture_plan_markdown, generate_architecture_spec
from semiconductor_swarm.agents.agent1_planning.signoff_engine import (
    apply_signoff_waivers,
    build_final_signoff_certificate,
    collect_agent1_signoff_evidence,
    enforce_agent1_to_agent2_handoff,
    run_deterministic_signoff_gates,
    run_agent1_signoff_pipeline,
)
from semiconductor_swarm.agents.agent1_planning.signoff_benchmark import ensure_default_benchmark_report
from semiconductor_swarm.agents.agent1_planning.signoff_models import (
    SIGNOFF_CERTIFICATE_SCHEMA_VERSION,
    SIGNOFF_GATES,
    SIGNOFF_WAIVERS_SCHEMA_VERSION,
)
from semiconductor_swarm.agents.agent1_planning.spec_schema import attach_agent1_contract_manifest, attach_tool_provenance
from semiconductor_swarm.tracing import sha256_text


HASH = "a" * 64
NOW = "2026-05-25T00:00:00+00:00"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _full_spec() -> dict:
    spec = generate_architecture_spec(
        "Generate APB UART peripheral with formal-first register checks",
        "uart_signoff",
    )
    spec.update(
        {
            "power_intent": {"domains": ["core"], "low_power": False},
            "cdc_rdc_plan": {"clock_crossings": [], "reset_crossings": []},
            "interconnect_qos": {"starvation_policy": "round_robin"},
            "memory_hierarchy": {"levels": ["APB register file"]},
            "dft_plan": {"test_modes": ["scan_enable", "test_reset"]},
            "safety_security": {"threat_model": ["APB software access"], "protected_registers": []},
            "ip_reuse_cost": {"reuse_candidates": ["uart"], "buy_vs_build": ["build"]},
            "io_packaging": {"pins": ["pclk", "presetn", "uart_tx", "uart_rx"]},
        }
    )
    spec = attach_tool_provenance(spec)
    spec = attach_agent1_contract_manifest(spec)
    return spec


def _build_clean_run(tmp_path: Path, *, approval: bool = True) -> Path:
    root = tmp_path / "run"
    reports = root / "reports"
    agent1 = reports / "agent1"
    traces = reports / "traces"
    agent1.mkdir(parents=True)
    traces.mkdir(parents=True)
    run_manifest = {
        "schema_version": "studio.run_manifest.v1",
        "run_id": "run-001",
        "thread_id": "thread-001",
        "project_name": "uart_signoff",
        "output_dir": str(root),
        "planning_mode": "normal",
        "user_approval_ref": "approval-ok-001" if approval else "",
    }
    _write_json(root / "studio_run_manifest.json", run_manifest)

    spec = _full_spec()
    plan = generate_architecture_plan_markdown(spec)
    (reports / "architecture_plan.md").write_text(plan, encoding="utf-8")
    _write_json(agent1 / "agent1_final_architecture_spec.json", spec)
    _write_json(agent1 / "agent1_contract_manifest.json", spec["agent1_contract_manifest"])
    _write_json(agent1 / "agent1_memory_interface_plan.json", {"memory_map": spec["memory_map"]})
    (agent1 / "agent1_register_map.rdl").write_text("addrmap agent1_register_map { reg ctrl; };", encoding="utf-8")
    (agent1 / "fw_uart_signoff_regs.h").write_text("#define UART_SIGNOFF_UART_CTRL_OFFSET 0x00u\n", encoding="utf-8")
    (agent1 / "tb_uart_signoff_reg_model.py").write_text("class UartSignoffRegModel: pass\n", encoding="utf-8")
    _write_json(agent1 / "agent1_validation_decisions.json", {"decisions": [{"validator": "RDL_vs_CHeader_Validator", "decision": "ACCEPT"}]})
    _write_json(agent1 / "agent1_safety_security_plan.json", {"threat_model": ["APB software access"]})
    _write_json(agent1 / "agent1_clock_power_plan.json", {"clock_domains": spec["clock_domains"]})
    _write_json(agent1 / "agent1_independent_critic_report.json", {"findings": []})
    ensure_default_benchmark_report(root, profile="strict", force=True)
    (traces / "agent1_council_trace.jsonl").write_text(
        json.dumps({"node_id": "agent1_v51_council", "event_type": "agent1_group_session_done", "status": "pass"}) + "\n",
        encoding="utf-8",
    )

    plan_hash = sha256_text((reports / "architecture_plan.md").read_text(encoding="utf-8"))
    spec_hash = sha256_text((agent1 / "agent1_final_architecture_spec.json").read_text(encoding="utf-8"))
    fingerprint = {
        "schema_version": "agent1.artifact_fingerprint_manifest.v1",
        "revision_id": "rev-001",
        "artifact_count": 2,
        "artifacts": [
            {
                "artifact": "architecture_plan.md",
                "sha256": plan_hash,
                "status": "current",
                "requirement_revision_id": "rev-001",
                "spec_revision_id": "rev-001",
            },
            {
                "artifact": "agent1_final_architecture_spec.json",
                "sha256": spec_hash,
                "status": "current",
                "requirement_revision_id": "rev-001",
                "spec_revision_id": "rev-001",
            },
        ],
    }
    _write_json(agent1 / "agent1_artifact_fingerprint_manifest.json", fingerprint)
    _write_json(
        agent1 / "agent1_final_signoff_certificate.json",
        {
            "schema_version": SIGNOFF_CERTIFICATE_SCHEMA_VERSION,
            "run_id": "run-001",
            "revision_id": "rev-001",
            "project": "uart_signoff",
            "profile": "strict",
            "decision": "PASS",
            "handoff_allowed": True,
            "score": 100.0,
            "gate_results": {gate: {"status": "PASS", "finding_codes": []} for gate in SIGNOFF_GATES},
            "finding_summary": {"total": 0},
            "waiver_summary": {"used": 0},
            "benchmark_summary": {"case_count": 110, "false_pass_count": 0, "must_not_pass_violation_count": 0},
            "artifact_hashes": {
                "architecture_plan.md": plan_hash,
                "agent1_final_architecture_spec.json": spec_hash,
            },
            "topology_hash": HASH,
            "config_hash": HASH,
            "prompt_pack_hash": HASH,
            "model_ref_hash": HASH,
            "user_approval_ref": "approval-ok-001" if approval else None,
            "created_at": NOW,
        },
    )
    return root


def _codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def _collect_and_run(root: Path, **kwargs):
    evidence = collect_agent1_signoff_evidence(root, profile="strict", **kwargs)
    return run_deterministic_signoff_gates(evidence)

def _future_waiver(gate: str, code: str, *, waiver_id: str = "waiver-001") -> dict:
    return {
        "waiver_id": waiver_id,
        "owner": "signoff-lead",
        "reason": "Temporary accepted risk for targeted deterministic signoff unit test.",
        "risk_level": "LOW",
        "expires_at": "2099-12-31T00:00:00+00:00",
        "affected_gate": gate,
        "matching_finding_code": code,
        "approval_signature": HASH,
    }


def test_phase2_collector_loads_current_artifacts_hashes_traces_and_approval(tmp_path):
    root = _build_clean_run(tmp_path)
    (root / "reports" / "traces" / "debug_issues.jsonl").write_text(
        json.dumps(
            {
                "type": "debug_issue",
                "severity": "warning",
                "source": "unit",
                "code": "PREEXISTING_WARNING",
                "message": "existing raw warning",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    evidence = collect_agent1_signoff_evidence(root, profile="strict")

    assert evidence.run_id == "run-001"
    assert evidence.revision_id == "rev-001"
    assert evidence.user_approval_ref == "approval-ok-001"
    assert evidence.artifacts["architecture_plan.md"].exists
    assert evidence.artifacts["architecture_plan.md"].sha256 == evidence.artifacts["architecture_plan.md"].expected_sha256
    assert evidence.cluster_trace
    assert len(evidence.raw_issues) == 1
    assert evidence.to_manifest()["raw_issue_count"] == 1
    assert evidence.benchmark_report["case_count"] == 110
    assert evidence.final_certificate is not None


def test_phase3_clean_evidence_has_all_gates_pass_and_no_blocking_findings(tmp_path):
    root = _build_clean_run(tmp_path)
    report = _collect_and_run(root)

    assert report.passed, report.to_dict()
    assert report.blocking_count == 0
    assert set(report.gate_results) == set(SIGNOFF_GATES)
    assert all(result["status"] == "PASS" for result in report.gate_results.values())


def test_phase2_collector_detects_wrong_run_id_for_g00(tmp_path):
    root = _build_clean_run(tmp_path)
    report = _collect_and_run(root, expected_run_id="run-other")
    assert "RUN_ID_MISMATCH" in _codes(report)
    assert report.gate_results["G00"]["status"] == "FAIL"


def test_phase3_debug_issue_tracking_is_zero_loss_and_profiled(tmp_path):
    root = _build_clean_run(tmp_path)
    (root / "reports" / "architecture_plan.md").write_text("# stale mutation\n", encoding="utf-8")

    report = _collect_and_run(root)
    issues = report.debug_issues()

    assert len(issues) == len(report.findings)
    assert issues
    for issue in issues:
        for key in (
            "severity",
            "source",
            "code",
            "message",
            "details",
            "run_id",
            "revision_id",
            "artifact_ref",
            "node_id",
            "gate",
            "profile",
            "case_id",
            "timestamp",
        ):
            assert key in issue
        assert issue["profile"] == "strict"
        assert issue["gate"] in SIGNOFF_GATES


def test_phase3_tracking_secret_leak_in_raw_issue_becomes_g07_fatal(tmp_path):
    root = _build_clean_run(tmp_path)
    (root / "reports" / "traces" / "debug_issues.jsonl").write_text(
        json.dumps(
            {
                "type": "debug_issue",
                "severity": "warning",
                "source": "unit",
                "code": "RAW_SECRET",
                "message": "sk-" + "testsecret1234567890",
                "details": {"note": "inline " + "api_key=TESTSECRET12345" + " must block release"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = _collect_and_run(root)

    assert "SECRET_LEAK" in _codes(report)
    secret_finding = next(finding for finding in report.findings if finding.code == "SECRET_LEAK")
    assert secret_finding.gate == "G07"
    assert secret_finding.severity == "P0_FATAL"


@pytest.mark.parametrize(
    ("gate", "expected_code", "mutate"),
    [
        ("G00", "RUN_MANIFEST_MISSING", lambda root: (root / "studio_run_manifest.json").unlink()),
        (
            "G01",
            "MEMORY_REQUIREMENT_MISSING",
            lambda root: _rewrite_spec(root, lambda spec: spec.__setitem__("memory_map", {})),
        ),
        (
            "G02",
            "COUNCIL_UNRESOLVED_CHALLENGE",
            lambda root: (root / "reports" / "traces" / "agent1_council_trace.jsonl").write_text(
                json.dumps({"node_id": "M02", "status": "fail", "message": "HITL_REQUIRED unresolved"}) + "\n",
                encoding="utf-8",
            ),
        ),
        (
            "G03",
            "ARTIFACT_HASH_MISMATCH",
            lambda root: (root / "reports" / "architecture_plan.md").write_text("# stale mutation\n", encoding="utf-8"),
        ),
        (
            "G04",
            "CONTRACT_MANIFEST_MISSING",
            lambda root: _rewrite_spec(root, lambda spec: spec.pop("agent1_contract_manifest", None)),
        ),
        ("G05", "REGISTER_ARTIFACT_MISSING", lambda root: (root / "reports" / "agent1" / "agent1_register_map.rdl").unlink()),
        (
            "G06",
            "FORMAL_FIRST_MISSING",
            lambda root: _rewrite_spec(root, lambda spec: spec["constraints"].__setitem__("formal_first", False)),
        ),
        ("G07", "SAFETY_SECURITY_PLAN_MISSING", lambda root: (root / "reports" / "agent1" / "agent1_safety_security_plan.json").unlink()),
        (
            "G08",
            "NUMERIC_PROVENANCE_MISSING",
            lambda root: _rewrite_spec(root, lambda spec: spec.pop("tool_provenance", None)),
        ),
        (
            "G09",
            "INDEPENDENT_CRITIC_HIGH_FINDING",
            lambda root: _write_json(
                root / "reports" / "agent1" / "agent1_independent_critic_report.json",
                {"findings": [{"severity": "high", "message": "bad semantic issue"}]},
            ),
        ),
        (
            "G10",
            "WAIVER_FILE_INVALID",
            lambda root: _write_json(root / "reports" / "agent1" / "signoff_waivers.json", {"schema_version": "bad", "waivers": []}),
        ),
        ("G11", "USER_APPROVAL_MISSING", lambda root: _remove_approval(root)),
        (
            "G12",
            "BENCHMARK_FALSE_PASS",
            lambda root: _write_json(
                root / "reports" / "agent1" / "agent1_signoff_benchmark_report.json",
                {"case_count": 110, "false_pass_count": 1, "must_not_pass_violation_count": 0},
            ),
        ),
    ],
)
def test_phase3_each_gate_has_forced_negative_finding(tmp_path, gate, expected_code, mutate):
    root = _build_clean_run(tmp_path)
    mutate(root)

    report = _collect_and_run(root)

    assert expected_code in _codes(report), report.to_dict()
    assert report.gate_results[gate]["status"] == "FAIL"
    assert any(issue["code"] == expected_code for issue in report.debug_issues())

def test_phase3_lock_requirement_missing_lock_register_is_blocking(tmp_path):
    root = _build_clean_run(tmp_path)
    spec = generate_architecture_spec(
        "Design an APB4 GPIO watchdog subsystem. No CPU. "
        "Watchdog lock prevents disable after lock and protects GPIO direction. "
        "Formal-first SVA plus cocotb.",
        "uart_signoff",
    )
    spec.update(
        {
            "power_intent": {"domains": ["core"], "low_power": False},
            "cdc_rdc_plan": {"clock_crossings": [], "reset_crossings": []},
            "interconnect_qos": {"starvation_policy": "round_robin"},
            "memory_hierarchy": {"levels": ["APB register file"]},
            "dft_plan": {"test_modes": ["scan_enable", "test_reset"]},
            "safety_security": {"threat_model": ["APB software access"], "protected_registers": []},
            "ip_reuse_cost": {"reuse_candidates": ["gpio", "timer"], "buy_vs_build": ["build"]},
            "io_packaging": {"pins": ["pclk", "presetn", "gpio"]},
        }
    )
    spec = attach_tool_provenance(spec)
    spec = attach_agent1_contract_manifest(spec)
    spec["memory_map"]["gpio"]["registers"].pop("lock")
    spec["memory_map"]["timer"]["registers"].pop("lock")
    _write_json(root / "reports" / "agent1" / "agent1_final_architecture_spec.json", spec)

    report = _collect_and_run(root)

    codes = _codes(report)
    assert "LOCK_REGISTER_MISSING" in codes, report.to_dict()
    assert report.gate_results["G05"]["status"] == "FAIL"
    assert any(issue["code"] == "LOCK_REGISTER_MISSING" for issue in report.debug_issues())

def test_phase4_valid_exact_waiver_produces_pass_with_waivers(tmp_path):
    root = _build_clean_run(tmp_path)
    (root / "reports" / "agent1" / "agent1_safety_security_plan.json").unlink()
    _write_json(
        root / "reports" / "agent1" / "signoff_waivers.json",
        {"schema_version": SIGNOFF_WAIVERS_SCHEMA_VERSION, "waivers": [_future_waiver("G07", "SAFETY_SECURITY_PLAN_MISSING")]},
    )
    evidence = collect_agent1_signoff_evidence(root, profile="strict")
    report = apply_signoff_waivers(run_deterministic_signoff_gates(evidence), evidence)
    certificate = build_final_signoff_certificate(evidence, report)

    assert report.passed, report.to_dict()
    assert report.gate_results["G07"]["status"] == "WAIVED"
    assert report.waiver_summary["applied"][0]["waiver_id"] == "waiver-001"
    assert certificate.decision == "PASS_WITH_WAIVERS"
    assert certificate.handoff_allowed is True

def test_phase4_expired_wrong_and_non_waivable_waivers_block(tmp_path):
    root = _build_clean_run(tmp_path)
    _rewrite_spec(root, lambda spec: spec["constraints"].__setitem__("formal_first", False))
    expired = _future_waiver("G06", "FORMAL_FIRST_MISSING", waiver_id="waiver-expired")
    expired["expires_at"] = "2000-01-01T00:00:00+00:00"
    wrong = _future_waiver("G06", "BUS_REQUIREMENT_MISSING", waiver_id="waiver-wrong")
    non_waivable = _future_waiver("G06", "FORMAL_FIRST_MISSING", waiver_id="waiver-non-waivable")
    _write_json(
        root / "reports" / "agent1" / "signoff_waivers.json",
        {"schema_version": SIGNOFF_WAIVERS_SCHEMA_VERSION, "waivers": [expired, wrong, non_waivable]},
    )
    evidence = collect_agent1_signoff_evidence(root, profile="strict")
    report = apply_signoff_waivers(run_deterministic_signoff_gates(evidence), evidence)

    assert "FORMAL_FIRST_MISSING" in _codes(report)
    assert "WAIVER_REJECTED" in _codes(report)
    assert report.gate_results["G10"]["status"] == "FAIL"
    assert report.passed is False
    reasons = {item["reason"] for item in report.waiver_summary["rejected"]}
    assert {"expired", "unused_or_wrong_gate_code", "non_waivable_target"} <= reasons

def test_phase5_benchmark_harness_writes_110_case_safety_zero_artifacts(tmp_path):
    root = tmp_path / "bench"
    report = ensure_default_benchmark_report(root, profile="strict", force=True)
    agent1 = root / "reports" / "agent1"

    assert report["schema_version"] == "agent1_signoff_benchmark_report/v1"
    assert report["case_count"] == 110
    assert report["false_pass_count"] == 0
    assert report["must_not_pass_violation_count"] == 0
    assert report["waiver_accuracy"] == 1.0
    assert report["handoff_gate_accuracy"] == 1.0
    for filename in (
        "agent1_signoff_benchmark_corpus.jsonl",
        "agent1_signoff_case_results.jsonl",
        "agent1_signoff_benchmark_matrix.csv",
        "agent1_signoff_oracle_disagreements.json",
        "agent1_signoff_false_pass_report.json",
        "agent1_signoff_benchmark_manifest_hash.json",
    ):
        assert (agent1 / filename).is_file(), filename
    manifest = _read_json(agent1 / "agent1_signoff_benchmark_manifest_hash.json")
    assert len(manifest["manifest_hash"]) == 64
    assert _read_json(agent1 / "agent1_signoff_false_pass_report.json")["items"] == []

def test_phase5_fake_or_stale_benchmark_artifacts_fail_g12(tmp_path):
    root = _build_clean_run(tmp_path)
    corpus = root / "reports" / "agent1" / "agent1_signoff_benchmark_corpus.jsonl"
    corpus.write_text(corpus.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    report = _collect_and_run(root)

    assert "BENCHMARK_ARTIFACT_HASH_MISMATCH" in _codes(report)
    assert report.gate_results["G12"]["status"] == "FAIL"

def test_phase6_pipeline_writes_runtime_artifacts_and_debug_issues(tmp_path):
    root = _build_clean_run(tmp_path)
    (root / "reports" / "agent1" / "agent1_safety_security_plan.json").unlink()
    result = run_agent1_signoff_pipeline(root, profile="balanced", user_approval_ref="approval-ok-001")
    agent1 = root / "reports" / "agent1"
    debug_text = (root / "reports" / "traces" / "debug_issues.jsonl").read_text(encoding="utf-8")

    assert result.handoff_allowed is True
    assert (agent1 / "agent1_signoff_evidence_manifest.json").is_file()
    assert (agent1 / "agent1_signoff_gate_report.json").is_file()
    assert (agent1 / "agent1_final_signoff_certificate.json").is_file()
    assert (agent1 / "agent1_signoff_runtime_manifest.json").is_file()
    assert "SAFETY_SECURITY_PLAN_MISSING" in debug_text

def test_phase6_pipeline_bootstraps_deterministic_independent_critic(tmp_path):
    root = _build_clean_run(tmp_path)
    critic = root / "reports" / "agent1" / "agent1_independent_critic_report.json"
    critic.unlink()

    result = run_agent1_signoff_pipeline(root, profile="balanced", user_approval_ref="approval-ok-001")
    gate_report = _read_json(root / "reports" / "agent1" / "agent1_signoff_gate_report.json")
    critic_payload = _read_json(critic)

    assert result.handoff_allowed is True
    assert critic_payload["critic_type"] == "deterministic_fallback"
    assert critic_payload["findings"] == []
    assert "INDEPENDENT_CRITIC_MISSING" not in _codes(result.gate_report)
    assert gate_report["gate_results"]["G09"]["status"] == "PASS"

def test_phase7_handoff_allows_clean_certificate_and_blocks_missing_or_stale(tmp_path):
    root = _build_clean_run(tmp_path)

    allowed = enforce_agent1_to_agent2_handoff(root, profile="strict", user_approval_ref="approval-ok-001")
    assert allowed.allowed is True

    missing_root = _build_clean_run(tmp_path / "missing")
    (missing_root / "reports" / "agent1" / "agent1_final_signoff_certificate.json").unlink()
    blocked_missing = enforce_agent1_to_agent2_handoff(missing_root, profile="strict", user_approval_ref="approval-ok-001")
    assert blocked_missing.allowed is False
    assert blocked_missing.blocking_codes == ("CERTIFICATE_MISSING",)

    stale_root = _build_clean_run(tmp_path / "stale")
    cert_path = stale_root / "reports" / "agent1" / "agent1_final_signoff_certificate.json"
    cert = _read_json(cert_path)
    cert["revision_id"] = "rev-other"
    _write_json(cert_path, cert)
    blocked_stale = enforce_agent1_to_agent2_handoff(stale_root, profile="strict", user_approval_ref="approval-ok-001")
    assert blocked_stale.allowed is False
    assert "CERTIFICATE_STALE" in blocked_stale.blocking_codes


def _rewrite_spec(root: Path, mutator) -> None:
    path = root / "reports" / "agent1" / "agent1_final_architecture_spec.json"
    spec = _read_json(path)
    mutator(spec)
    _write_json(path, spec)


def _remove_approval(root: Path) -> None:
    manifest_path = root / "studio_run_manifest.json"
    manifest = _read_json(manifest_path)
    manifest["user_approval_ref"] = ""
    _write_json(manifest_path, manifest)
    cert_path = root / "reports" / "agent1" / "agent1_final_signoff_certificate.json"
    cert = _read_json(cert_path)
    cert["handoff_allowed"] = False
    cert["user_approval_ref"] = None
    _write_json(cert_path, cert)
