"""Agent 1 V7.2 evidence collector and deterministic signoff gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
from typing import Any

from semiconductor_swarm.agents.agent1_planning.signoff_models import (
    SIGNOFF_GATES,
    SIGNOFF_PROFILES,
    SIGNOFF_CERTIFICATE_SCHEMA_VERSION,
    Agent1FinalSignoffCertificate,
    SignoffFinding,
    SignoffSchemaError,
    SignoffWaivers,
    validate_no_secret_material,
)
from semiconductor_swarm.agents.agent1_planning.spec_schema import validate_agent1_v4_spec_schema
from semiconductor_swarm.tracing import TRACE_FILES, append_jsonl, now_iso, secret_leaks, sha256_text


REQUIRED_AGENT1_ARTIFACTS = (
    "architecture_plan.md",
    "agent1_final_architecture_spec.json",
    "agent1_artifact_fingerprint_manifest.json",
)

SIGNOFF_REPORT_SCHEMA_VERSION = "agent1_signoff_gate_report/v1"
EVIDENCE_SCHEMA_VERSION = "agent1_signoff_evidence_bundle/v1"
WAIVER_REPORT_SCHEMA_VERSION = "agent1_signoff_waiver_report/v1"
HANDOFF_REPORT_SCHEMA_VERSION = "agent1_to_agent2_signoff_handoff/v1"
BENCHMARK_REPORT_SCHEMA_VERSION = "agent1_signoff_benchmark_report/v1"

SIGNOFF_RUNTIME_ARTIFACTS = {
    "agent1_final_signoff_certificate.json",
    "agent1_signoff_evidence_manifest.json",
    "agent1_signoff_gate_report.json",
    "agent1_signoff_runtime_manifest.json",
    "agent1_to_agent2_signoff_handoff.json",
}

BENCHMARK_ARTIFACTS = {
    "agent1_signoff_benchmark_corpus.jsonl",
    "agent1_signoff_case_results.jsonl",
    "agent1_signoff_benchmark_report.json",
    "agent1_signoff_benchmark_matrix.csv",
    "agent1_signoff_oracle_disagreements.json",
    "agent1_signoff_false_pass_report.json",
    "agent1_signoff_benchmark_manifest_hash.json",
}


@dataclass(frozen=True)
class ArtifactEvidence:
    artifact: str
    path: str
    exists: bool
    sha256: str | None = None
    expected_sha256: str | None = None
    status: str = ""
    revision_id: str = ""
    issue: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "path": self.path,
            "exists": self.exists,
            "sha256": self.sha256,
            "expected_sha256": self.expected_sha256,
            "status": self.status,
            "revision_id": self.revision_id,
            "issue": self.issue,
        }


@dataclass(frozen=True)
class Agent1SignoffEvidence:
    output_dir: Path
    profile: str
    run_manifest: dict[str, Any]
    run_id: str
    revision_id: str
    user_approval_ref: str | None
    artifacts: dict[str, ArtifactEvidence]
    artifact_hashes: dict[str, str]
    fingerprint_manifest: dict[str, Any]
    release_manifest: dict[str, Any]
    spec: dict[str, Any]
    plan_markdown: str
    raw_issues: tuple[dict[str, Any], ...]
    cluster_trace: tuple[dict[str, Any], ...]
    trace_events: tuple[dict[str, Any], ...]
    waivers: SignoffWaivers | None
    waiver_load_error: str
    final_certificate: Agent1FinalSignoffCertificate | None
    certificate_load_error: str
    benchmark_report: dict[str, Any]
    collection_errors: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "output_dir": str(self.output_dir),
            "profile": self.profile,
            "run_id": self.run_id,
            "revision_id": self.revision_id,
            "user_approval_ref": self.user_approval_ref,
            "artifacts": {key: artifact.to_dict() for key, artifact in sorted(self.artifacts.items())},
            "artifact_hashes": dict(sorted(self.artifact_hashes.items())),
            "raw_issue_count": len(self.raw_issues),
            "cluster_trace_count": len(self.cluster_trace),
            "trace_event_count": len(self.trace_events),
            "waiver_count": len(self.waivers.waivers) if self.waivers else 0,
            "waiver_load_error": self.waiver_load_error,
            "certificate_present": self.final_certificate is not None,
            "certificate_load_error": self.certificate_load_error,
            "benchmark_report_present": bool(self.benchmark_report),
            "collection_errors": list(self.collection_errors),
        }


@dataclass(frozen=True)
class SignoffGateReport:
    schema_version: str
    profile: str
    run_id: str
    revision_id: str
    gate_results: dict[str, dict[str, Any]]
    findings: tuple[SignoffFinding, ...]
    blocking_count: int
    warning_count: int
    waiver_summary: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.blocking_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "run_id": self.run_id,
            "revision_id": self.revision_id,
            "passed": self.passed,
            "blocking_count": self.blocking_count,
            "warning_count": self.warning_count,
            "waiver_summary": self.waiver_summary,
            "gate_results": self.gate_results,
            "findings": [finding.to_dict() for finding in self.findings],
        }

    def debug_issues(self) -> list[dict[str, Any]]:
        return [finding_to_debug_issue(finding, profile=self.profile) for finding in self.findings]


@dataclass(frozen=True)
class SignoffPipelineResult:
    evidence: Agent1SignoffEvidence
    gate_report: SignoffGateReport
    certificate: Agent1FinalSignoffCertificate
    handoff_allowed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence": self.evidence.to_manifest(),
            "gate_report": self.gate_report.to_dict(),
            "certificate": self.certificate.to_dict(),
            "handoff_allowed": self.handoff_allowed,
        }


@dataclass(frozen=True)
class Agent1ToAgent2HandoffResult:
    schema_version: str
    allowed: bool
    reason: str
    run_id: str
    revision_id: str
    certificate_ref: str
    blocking_codes: tuple[str, ...]
    debug_issue_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "allowed": self.allowed,
            "reason": self.reason,
            "run_id": self.run_id,
            "revision_id": self.revision_id,
            "certificate_ref": self.certificate_ref,
            "blocking_codes": list(self.blocking_codes),
            "debug_issue_refs": list(self.debug_issue_refs),
        }


def collect_agent1_signoff_evidence(
    output_dir: str | Path,
    *,
    profile: str | None = None,
    expected_run_id: str | None = None,
    expected_revision_id: str | None = None,
    user_approval_ref: str | None = None,
) -> Agent1SignoffEvidence:
    root = Path(output_dir)
    selected_profile = profile or os.getenv("AGENT1_SIGNOFF_PROFILE", "balanced")
    if selected_profile not in SIGNOFF_PROFILES:
        selected_profile = "balanced"
    reports = root / "reports"
    agent1_dir = reports / "agent1"
    errors: list[dict[str, Any]] = []

    run_manifest = _read_json(root / "studio_run_manifest.json", "studio_run_manifest", errors)
    run_id = str(run_manifest.get("run_id") or expected_run_id or "")
    if expected_run_id and run_id and run_id != expected_run_id:
        errors.append({"code": "RUN_ID_MISMATCH", "expected": expected_run_id, "actual": run_id})
    if expected_run_id and not run_id:
        run_id = expected_run_id

    fingerprint_manifest = _read_json(agent1_dir / "agent1_artifact_fingerprint_manifest.json", "fingerprint_manifest", errors)
    release_manifest = _read_json(agent1_dir / "agent1_release_manifest_hash.json", "release_manifest", errors, required=False)
    revision_id = str(
        fingerprint_manifest.get("revision_id")
        or release_manifest.get("revision_id")
        or expected_revision_id
        or ""
    )
    if expected_revision_id and revision_id and revision_id != expected_revision_id:
        errors.append({"code": "REVISION_ID_MISMATCH", "expected": expected_revision_id, "actual": revision_id})
    if expected_revision_id and not revision_id:
        revision_id = expected_revision_id

    plan_path = reports / "architecture_plan.md"
    plan_markdown = _read_text(plan_path, "architecture_plan.md", errors)
    spec = _read_json(agent1_dir / "agent1_final_architecture_spec.json", "agent1_final_architecture_spec", errors)
    artifacts = _collect_artifacts(root, REQUIRED_AGENT1_ARTIFACTS, fingerprint_manifest)
    artifact_hashes = {name: artifact.sha256 for name, artifact in artifacts.items() if artifact.sha256}

    trace_events = tuple(_read_trace_jsonl(reports / "traces"))
    raw_issues = tuple(event for event in trace_events if event.get("type") == "debug_issue" or str(event.get("source_trace_file")) == "debug_issues.jsonl")
    cluster_trace = tuple(
        event for event in trace_events
        if "council" in str(event.get("source_trace_file", "")).lower()
        or str(event.get("node_id", "")).startswith(("M", "L", "P01", "agent1_v51"))
        or str(event.get("event_type", "")).startswith("agent1_")
    )

    waivers, waiver_error = _load_waivers(root)
    final_certificate, certificate_error = _load_certificate(root)
    benchmark_report = _read_json(agent1_dir / "agent1_signoff_benchmark_report.json", "benchmark_report", errors, required=False)

    approval_ref = user_approval_ref or _approval_ref_from_manifest(run_manifest)

    return Agent1SignoffEvidence(
        output_dir=root,
        profile=selected_profile,
        run_manifest=run_manifest,
        run_id=run_id,
        revision_id=revision_id,
        user_approval_ref=approval_ref,
        artifacts=artifacts,
        artifact_hashes=artifact_hashes,
        fingerprint_manifest=fingerprint_manifest,
        release_manifest=release_manifest,
        spec=spec,
        plan_markdown=plan_markdown,
        raw_issues=raw_issues,
        cluster_trace=cluster_trace,
        trace_events=trace_events,
        waivers=waivers,
        waiver_load_error=waiver_error,
        final_certificate=final_certificate,
        certificate_load_error=certificate_error,
        benchmark_report=benchmark_report,
        collection_errors=tuple(errors),
    )


def run_deterministic_signoff_gates(evidence: Agent1SignoffEvidence) -> SignoffGateReport:
    builder = _FindingBuilder(evidence)
    for gate, check in (
        ("G00", _gate_g00_session_integrity),
        ("G01", _gate_g01_requirement_coverage),
        ("G02", _gate_g02_council_convergence),
        ("G03", _gate_g03_artifact_currentness),
        ("G04", _gate_g04_contract_schema),
        ("G05", _gate_g05_memory_register_irq),
        ("G06", _gate_g06_formal_first),
        ("G07", _gate_g07_safety_security_power_clock_reset),
        ("G08", _gate_g08_numeric_provenance),
        ("G09", _gate_g09_independent_critic),
        ("G10", _gate_g10_waiver_governance),
        ("G11", _gate_g11_handoff_readiness),
        ("G12", _gate_g12_benchmark_proof),
    ):
        try:
            check(evidence, builder)
        except Exception as exc:  # pragma: no cover - defensive zero-loss guard
            builder.add(
                gate,
                "SIGNOFF_GATE_EXCEPTION",
                "P0_FATAL",
                f"Deterministic signoff gate {gate} raised an exception.",
                {"exception": type(exc).__name__, "message": str(exc)},
                waivable=False,
            )

    findings = tuple(builder.findings)
    gate_results: dict[str, dict[str, Any]] = {}
    for gate in SIGNOFF_GATES:
        gate_findings = [finding for finding in findings if finding.gate == gate]
        gate_results[gate] = {
            "status": _gate_status(evidence.profile, gate_findings),
            "finding_codes": [finding.code for finding in gate_findings],
            "finding_count": len(gate_findings),
        }
    blocking_count = sum(1 for finding in findings if _finding_blocks_profile(finding, evidence.profile))
    warning_count = len(findings) - blocking_count
    return SignoffGateReport(
        schema_version=SIGNOFF_REPORT_SCHEMA_VERSION,
        profile=evidence.profile,
        run_id=evidence.run_id,
        revision_id=evidence.revision_id,
        gate_results=gate_results,
        findings=findings,
        blocking_count=blocking_count,
        warning_count=warning_count,
        waiver_summary={"schema_version": WAIVER_REPORT_SCHEMA_VERSION, "waiver_count": len(evidence.waivers.waivers) if evidence.waivers else 0, "applied": [], "rejected": []},
    )


def apply_signoff_waivers(report: SignoffGateReport, evidence: Agent1SignoffEvidence) -> SignoffGateReport:
    """Apply exact-match waivers without mutating deterministic findings."""
    if not evidence.waivers:
        return report
    now = datetime.now(timezone.utc)
    applied: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    used_waiver_ids: set[str] = set()
    findings = list(report.findings)

    for index, finding in enumerate(findings):
        matches = [
            waiver for waiver in evidence.waivers.waivers
            if waiver.affected_gate == finding.gate and waiver.matching_finding_code == finding.code
        ]
        for waiver in matches:
            used_waiver_ids.add(waiver.waiver_id)
            expiry = datetime.fromisoformat(waiver.expires_at.replace("Z", "+00:00"))
            if expiry <= now:
                rejected.append({"waiver_id": waiver.waiver_id, "reason": "expired", "gate": finding.gate, "code": finding.code})
                continue
            if not finding.waivable or finding.severity == "P0_FATAL":
                rejected.append({"waiver_id": waiver.waiver_id, "reason": "non_waivable_target", "gate": finding.gate, "code": finding.code})
                continue
            findings[index] = replace(finding, waiver_id=waiver.waiver_id)
            applied.append({"waiver_id": waiver.waiver_id, "gate": finding.gate, "code": finding.code})
            break

    for waiver in evidence.waivers.waivers:
        if waiver.waiver_id not in used_waiver_ids:
            rejected.append({"waiver_id": waiver.waiver_id, "reason": "unused_or_wrong_gate_code", "gate": waiver.affected_gate, "code": waiver.matching_finding_code})

    for rejection in rejected:
        findings.append(
            _make_finding(
                evidence,
                "G10",
                "WAIVER_REJECTED",
                "P1_BLOCKER",
                "A waiver was rejected or did not match any current finding.",
                rejection,
                artifact_ref="signoff_waivers.json",
                waivable=False,
            )
        )

    final_findings = tuple(findings)
    gate_results: dict[str, dict[str, Any]] = {}
    for gate in SIGNOFF_GATES:
        gate_findings = [finding for finding in final_findings if finding.gate == gate]
        gate_results[gate] = {
            "status": _gate_status(evidence.profile, gate_findings),
            "finding_codes": [finding.code for finding in gate_findings],
            "finding_count": len(gate_findings),
        }
    blocking_count = sum(1 for finding in final_findings if _finding_blocks_profile(finding, evidence.profile))
    warning_count = len(final_findings) - blocking_count
    return SignoffGateReport(
        schema_version=report.schema_version,
        profile=report.profile,
        run_id=report.run_id,
        revision_id=report.revision_id,
        gate_results=gate_results,
        findings=final_findings,
        blocking_count=blocking_count,
        warning_count=warning_count,
        waiver_summary={
            "schema_version": WAIVER_REPORT_SCHEMA_VERSION,
            "waiver_count": len(evidence.waivers.waivers),
            "applied": applied,
            "rejected": rejected,
        },
    )


def build_final_signoff_certificate(evidence: Agent1SignoffEvidence, report: SignoffGateReport) -> Agent1FinalSignoffCertificate:
    blocking_codes = [finding.code for finding in report.findings if _finding_blocks_profile(finding, evidence.profile)]
    waived_count = sum(1 for finding in report.findings if finding.waiver_id)
    decision = "PASS" if not blocking_codes and waived_count == 0 else "PASS_WITH_WAIVERS" if not blocking_codes else "BLOCKED"
    benchmark_summary = {
        "case_count": _int_value(evidence.benchmark_report.get("case_count")),
        "false_pass_count": _int_value(evidence.benchmark_report.get("false_pass_count")),
        "must_not_pass_violation_count": _int_value(evidence.benchmark_report.get("must_not_pass_violation_count")),
        "report_present": bool(evidence.benchmark_report),
    }
    handoff_allowed = (
        decision in {"PASS", "PASS_WITH_WAIVERS"}
        and bool(evidence.user_approval_ref)
        and benchmark_summary["false_pass_count"] == 0
        and benchmark_summary["must_not_pass_violation_count"] == 0
    )
    score = max(0.0, 100.0 - report.blocking_count * 20.0 - report.warning_count * 5.0)
    certificate_artifact_hashes = {
        artifact: digest
        for artifact, digest in evidence.artifact_hashes.items()
        if artifact not in SIGNOFF_RUNTIME_ARTIFACTS
    }
    payload = {
        "schema_version": SIGNOFF_CERTIFICATE_SCHEMA_VERSION,
        "run_id": evidence.run_id or "unknown-run",
        "revision_id": evidence.revision_id or "unknown-revision",
        "project": str(evidence.spec.get("project_name") or evidence.run_manifest.get("project_name") or "swarm_soc"),
        "profile": evidence.profile,
        "decision": decision,
        "handoff_allowed": handoff_allowed,
        "score": score,
        "gate_results": report.gate_results,
        "finding_summary": {
            "total": len(report.findings),
            "blocking_count": report.blocking_count,
            "warning_count": report.warning_count,
            "blocking_codes": blocking_codes,
        },
        "waiver_summary": report.waiver_summary,
        "benchmark_summary": benchmark_summary,
        "artifact_hashes": certificate_artifact_hashes,
        "topology_hash": _hash_or_zero(evidence.fingerprint_manifest),
        "config_hash": _hash_or_zero({"profile": evidence.profile, "run_id": evidence.run_id}),
        "prompt_pack_hash": _hash_or_zero(evidence.spec.get("agent1_prompt_pack_manifest", evidence.spec.get("requirements", {}))),
        "model_ref_hash": _hash_or_zero(evidence.run_manifest.get("model", "local")),
        "user_approval_ref": evidence.user_approval_ref,
        "created_at": now_iso(),
    }
    return Agent1FinalSignoffCertificate.from_dict(payload)


def write_signoff_runtime_artifacts(evidence: Agent1SignoffEvidence, report: SignoffGateReport, certificate: Agent1FinalSignoffCertificate) -> dict[str, str]:
    agent1_dir = evidence.output_dir / "reports" / "agent1"
    trace_dir = evidence.output_dir / "reports" / "traces"
    agent1_dir.mkdir(parents=True, exist_ok=True)
    trace_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "evidence_manifest": agent1_dir / "agent1_signoff_evidence_manifest.json",
        "gate_report": agent1_dir / "agent1_signoff_gate_report.json",
        "certificate": agent1_dir / "agent1_final_signoff_certificate.json",
        "runtime_manifest": agent1_dir / "agent1_signoff_runtime_manifest.json",
    }
    outputs["evidence_manifest"].write_text(json.dumps(evidence.to_manifest(), indent=2, sort_keys=True), encoding="utf-8")
    outputs["gate_report"].write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    outputs["certificate"].write_text(json.dumps(certificate.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    runtime_manifest = {
        "schema_version": "agent1_signoff_runtime_manifest/v1",
        "run_id": evidence.run_id,
        "revision_id": evidence.revision_id,
        "profile": evidence.profile,
        "decision": certificate.decision,
        "handoff_allowed": certificate.handoff_allowed,
        "blocking_count": report.blocking_count,
        "warning_count": report.warning_count,
        "debug_issue_count": len(report.findings),
        "artifact_refs": {key: str(path) for key, path in outputs.items() if key != "runtime_manifest"},
        "created_at": now_iso(),
    }
    outputs["runtime_manifest"].write_text(json.dumps(runtime_manifest, indent=2, sort_keys=True), encoding="utf-8")
    for issue in report.debug_issues():
        append_jsonl(trace_dir / TRACE_FILES["debug_issues"], issue)
    return {key: str(path) for key, path in outputs.items()}


def ensure_independent_critic_report(output_dir: str | Path) -> Path:
    """Write deterministic critic fallback when no independent critic artifact exists."""
    root = Path(output_dir)
    agent1_dir = root / "reports" / "agent1"
    critic_path = agent1_dir / "agent1_independent_critic_report.json"
    if critic_path.is_file():
        return critic_path
    agent1_dir.mkdir(parents=True, exist_ok=True)
    errors: list[dict[str, Any]] = []
    plan_quality = _read_json(agent1_dir / "agent1_plan_quality_report.json", "agent1_plan_quality_report", errors, required=False)
    consistency = _read_json(agent1_dir / "agent1_artifact_consistency_report.json", "agent1_artifact_consistency_report", errors, required=False)
    findings: list[dict[str, Any]] = []
    if plan_quality and not bool(plan_quality.get("pass")):
        findings.append(
            {
                "severity": "high",
                "code": "PLAN_QUALITY_FAILED",
                "message": "Deterministic critic found failing Agent1 plan quality checks.",
                "details": {"failures": plan_quality.get("failures") or []},
            }
        )
    if consistency and not bool(consistency.get("pass")):
        findings.append(
            {
                "severity": "high",
                "code": "ARTIFACT_CONSISTENCY_FAILED",
                "message": "Deterministic critic found Agent1 artifact consistency failures.",
                "details": {"issues": (consistency.get("issues") or [])[:10]},
            }
        )
    payload = {
        "schema_version": "agent1_independent_critic_report/v1",
        "critic_type": "deterministic_fallback",
        "created_at": now_iso(),
        "checks": {
            "plan_quality_present": bool(plan_quality),
            "plan_quality_pass": bool(plan_quality.get("pass")) if plan_quality else None,
            "artifact_consistency_present": bool(consistency),
            "artifact_consistency_pass": bool(consistency.get("pass")) if consistency else None,
            "read_errors": errors,
        },
        "findings": findings,
    }
    validate_no_secret_material(payload, "agent1_independent_critic_report")
    critic_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return critic_path

def run_agent1_signoff_pipeline(
    output_dir: str | Path,
    *,
    profile: str | None = None,
    expected_run_id: str | None = None,
    expected_revision_id: str | None = None,
    user_approval_ref: str | None = None,
    write_artifacts: bool = True,
    bootstrap_missing_certificate: bool = True,
) -> SignoffPipelineResult:
    from semiconductor_swarm.agents.agent1_planning.signoff_benchmark import ensure_default_benchmark_report

    ensure_default_benchmark_report(output_dir, profile=profile or os.getenv("AGENT1_SIGNOFF_PROFILE", "balanced"))
    ensure_independent_critic_report(output_dir)
    evidence = collect_agent1_signoff_evidence(
        output_dir,
        profile=profile,
        expected_run_id=expected_run_id,
        expected_revision_id=expected_revision_id,
        user_approval_ref=user_approval_ref,
    )
    gate_report = run_deterministic_signoff_gates(evidence)
    gate_report = apply_signoff_waivers(gate_report, evidence)
    if bootstrap_missing_certificate and evidence.final_certificate is None and not evidence.certificate_load_error:
        gate_report = _without_codes(gate_report, {"CERTIFICATE_MISSING"})
    certificate = build_final_signoff_certificate(evidence, gate_report)
    if write_artifacts:
        write_signoff_runtime_artifacts(evidence, gate_report, certificate)
    return SignoffPipelineResult(
        evidence=evidence,
        gate_report=gate_report,
        certificate=certificate,
        handoff_allowed=certificate.handoff_allowed,
    )


def enforce_agent1_to_agent2_handoff(
    output_dir: str | Path,
    *,
    profile: str | None = None,
    expected_run_id: str | None = None,
    expected_revision_id: str | None = None,
    user_approval_ref: str | None = None,
    write_artifacts: bool = True,
    require_existing_certificate: bool = True,
) -> Agent1ToAgent2HandoffResult:
    if require_existing_certificate and not (Path(output_dir) / "reports" / "agent1" / "agent1_final_signoff_certificate.json").is_file():
        evidence = collect_agent1_signoff_evidence(
            output_dir,
            profile=profile,
            expected_run_id=expected_run_id,
            expected_revision_id=expected_revision_id,
            user_approval_ref=user_approval_ref,
        )
        handoff = Agent1ToAgent2HandoffResult(
            schema_version=HANDOFF_REPORT_SCHEMA_VERSION,
            allowed=False,
            reason="handoff_blocked_missing_certificate",
            run_id=evidence.run_id,
            revision_id=evidence.revision_id,
            certificate_ref=str(Path(output_dir) / "reports" / "agent1" / "agent1_final_signoff_certificate.json"),
            blocking_codes=("CERTIFICATE_MISSING",),
            debug_issue_refs=("AGENT1_AGENT2_HANDOFF_BLOCKED",),
        )
        if write_artifacts:
            _write_handoff_artifact(output_dir, handoff, actual_decision="BLOCKED")
        return handoff
    result = run_agent1_signoff_pipeline(
        output_dir,
        profile=profile,
        expected_run_id=expected_run_id,
        expected_revision_id=expected_revision_id,
        user_approval_ref=user_approval_ref,
        write_artifacts=write_artifacts,
        bootstrap_missing_certificate=False,
    )
    blocking_codes = tuple(finding.code for finding in result.gate_report.findings if _finding_blocks_profile(finding, result.evidence.profile))
    allowed = result.certificate.handoff_allowed and not blocking_codes
    reason = "handoff_allowed" if allowed else "handoff_blocked_by_signoff"
    certificate_ref = str(Path(output_dir) / "reports" / "agent1" / "agent1_final_signoff_certificate.json")
    handoff = Agent1ToAgent2HandoffResult(
        schema_version=HANDOFF_REPORT_SCHEMA_VERSION,
        allowed=allowed,
        reason=reason,
        run_id=result.evidence.run_id,
        revision_id=result.evidence.revision_id,
        certificate_ref=certificate_ref,
        blocking_codes=blocking_codes,
        debug_issue_refs=tuple(issue["code"] for issue in result.gate_report.debug_issues()),
    )
    if write_artifacts:
        _write_handoff_artifact(output_dir, handoff, actual_decision=result.certificate.decision, profile=result.evidence.profile)
    return handoff


def finding_to_debug_issue(finding: SignoffFinding, *, profile: str = "") -> dict[str, Any]:
    severity = {
        "P0_FATAL": "fatal",
        "P1_BLOCKER": "error",
        "P2_MAJOR": "warning",
        "P3_MINOR": "warning",
    }[finding.severity]
    return {
        "type": "debug_issue",
        "schema_version": "swarm.debug_issue.v1",
        "severity": severity,
        "source": finding.source,
        "code": finding.code,
        "message": finding.message,
        "details": finding.details,
        "run_id": finding.run_id,
        "revision_id": finding.revision_id,
        "artifact_ref": finding.artifact_ref or "",
        "node_id": finding.node_id or finding.gate,
        "gate": finding.gate,
        "profile": profile,
        "case_id": finding.case_id,
        "expected_decision": str(finding.details.get("expected_decision") or ""),
        "actual_decision": str(finding.details.get("actual_decision") or ""),
        "false_pass": bool(finding.details.get("false_pass", False)),
        "must_not_pass_violation": bool(finding.details.get("must_not_pass_violation", False)),
        "timestamp": finding.timestamp,
    }

def _without_codes(report: SignoffGateReport, codes: set[str]) -> SignoffGateReport:
    findings = tuple(finding for finding in report.findings if finding.code not in codes)
    gate_results: dict[str, dict[str, Any]] = {}
    for gate in SIGNOFF_GATES:
        gate_findings = [finding for finding in findings if finding.gate == gate]
        gate_results[gate] = {
            "status": _gate_status(report.profile, gate_findings),
            "finding_codes": [finding.code for finding in gate_findings],
            "finding_count": len(gate_findings),
        }
    blocking_count = sum(1 for finding in findings if _finding_blocks_profile(finding, report.profile))
    warning_count = len(findings) - blocking_count
    return SignoffGateReport(
        schema_version=report.schema_version,
        profile=report.profile,
        run_id=report.run_id,
        revision_id=report.revision_id,
        gate_results=gate_results,
        findings=findings,
        blocking_count=blocking_count,
        warning_count=warning_count,
        waiver_summary=report.waiver_summary,
    )

def _write_handoff_artifact(output_dir: str | Path, handoff: Agent1ToAgent2HandoffResult, *, actual_decision: str, profile: str = "") -> None:
    path = Path(output_dir) / "reports" / "agent1" / "agent1_to_agent2_signoff_handoff.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(handoff.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    trace_dir = Path(output_dir) / "reports" / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    if handoff.allowed:
        append_jsonl(
            trace_dir / "agent1_signoff_handoff_trace.jsonl",
            {
                "type": "agent1_signoff_handoff",
                "event_type": "agent1_to_agent2_handoff_allowed",
                "status": "pass",
                "run_id": handoff.run_id,
                "revision_id": handoff.revision_id,
                "certificate_ref": handoff.certificate_ref,
                "timestamp": now_iso(),
            },
        )
        return
    append_jsonl(
        trace_dir / TRACE_FILES["debug_issues"],
        {
            "type": "debug_issue",
            "schema_version": "swarm.debug_issue.v1",
            "severity": "error",
            "source": "agent1.signoff.handoff",
            "code": "AGENT1_AGENT2_HANDOFF_BLOCKED",
            "message": "Agent2 handoff blocked by Agent1 V7.2 signoff.",
            "details": {"blocking_codes": list(handoff.blocking_codes), "reason": handoff.reason},
            "run_id": handoff.run_id,
            "revision_id": handoff.revision_id,
            "artifact_ref": handoff.certificate_ref,
            "node_id": "AGENT1.SIGNOFF.HANDOFF",
            "gate": "G11",
            "profile": profile,
            "case_id": "",
            "expected_decision": "PASS",
            "actual_decision": actual_decision,
            "false_pass": False,
            "must_not_pass_violation": False,
            "timestamp": now_iso(),
        },
    )


class _FindingBuilder:
    def __init__(self, evidence: Agent1SignoffEvidence) -> None:
        self.evidence = evidence
        self.findings: list[SignoffFinding] = []

    def add(
        self,
        gate: str,
        code: str,
        severity: str,
        message: str,
        details: dict[str, Any] | None = None,
        *,
        artifact_ref: str | None = None,
        node_id: str | None = None,
        waivable: bool = True,
    ) -> None:
        clean_details = details or {}
        validate_no_secret_material(clean_details, "finding.details")
        self.findings.append(
            _make_finding(self.evidence, gate, code, severity, message, clean_details, artifact_ref=artifact_ref, node_id=node_id, waivable=waivable)
        )

def _make_finding(
    evidence: Agent1SignoffEvidence,
    gate: str,
    code: str,
    severity: str,
    message: str,
    details: dict[str, Any],
    *,
    artifact_ref: str | None = None,
    node_id: str | None = None,
    waivable: bool = True,
) -> SignoffFinding:
    validate_no_secret_material(details, "finding.details")
    finding_id = f"{gate}-{code}-{sha256_text(json.dumps(details, sort_keys=True, default=str))[:12]}"
    payload = {
        "finding_id": finding_id,
        "gate": gate,
        "code": code,
        "severity": severity,
        "source": "agent1.signoff",
        "message": message,
        "details": details,
        "run_id": evidence.run_id or "unknown-run",
        "revision_id": evidence.revision_id or "unknown-revision",
        "artifact_ref": artifact_ref,
        "node_id": node_id or gate,
        "case_id": details.get("case_id") if isinstance(details.get("case_id"), str) else None,
        "waivable": waivable,
        "waiver_id": None,
        "timestamp": now_iso(),
    }
    return SignoffFinding.from_dict(payload)


def _gate_g00_session_integrity(evidence: Agent1SignoffEvidence, findings: _FindingBuilder) -> None:
    if not evidence.run_manifest:
        findings.add("G00", "RUN_MANIFEST_MISSING", "P1_BLOCKER", "studio_run_manifest.json is missing.", {"output_dir": str(evidence.output_dir)}, artifact_ref="studio_run_manifest.json")
    elif evidence.run_manifest.get("schema_version") != "studio.run_manifest.v1":
        findings.add("G00", "RUN_MANIFEST_INVALID", "P1_BLOCKER", "studio_run_manifest.json schema_version is invalid.", {"schema_version": evidence.run_manifest.get("schema_version")}, artifact_ref="studio_run_manifest.json")
    if not evidence.run_id:
        findings.add("G00", "RUN_ID_MISSING", "P1_BLOCKER", "Run id is missing from signoff evidence.", {}, waivable=False)
    if not evidence.revision_id:
        findings.add("G00", "REVISION_ID_MISSING", "P1_BLOCKER", "Revision id is missing from signoff evidence.", {}, waivable=False)
    for error in evidence.collection_errors:
        code = str(error.get("code") or "")
        if code in {"RUN_ID_MISMATCH", "REVISION_ID_MISMATCH"}:
            findings.add("G00", code, "P0_FATAL", f"{code} detected while collecting signoff evidence.", error, waivable=False)


def _gate_g01_requirement_coverage(evidence: Agent1SignoffEvidence, findings: _FindingBuilder) -> None:
    spec = evidence.spec
    if not spec:
        findings.add("G01", "REQUIREMENT_SPEC_MISSING", "P1_BLOCKER", "Agent1 final architecture spec is missing.", {}, artifact_ref="reports/agent1/agent1_final_architecture_spec.json")
        return
    requirements = spec.get("requirements")
    if not isinstance(requirements, dict) or not requirements:
        findings.add("G01", "REQUIREMENT_COVERAGE_MISSING", "P1_BLOCKER", "Spec lacks requirement coverage object.", {}, artifact_ref="reports/agent1/agent1_final_architecture_spec.json")
    if not spec.get("bus_topology", {}).get("protocol"):
        findings.add("G01", "BUS_REQUIREMENT_MISSING", "P1_BLOCKER", "Spec lacks explicit bus protocol.", {}, artifact_ref="reports/agent1/agent1_final_architecture_spec.json")
    if not spec.get("memory_map"):
        findings.add("G01", "MEMORY_REQUIREMENT_MISSING", "P1_BLOCKER", "Spec lacks memory/register map.", {}, artifact_ref="reports/agent1/agent1_final_architecture_spec.json")


def _gate_g02_council_convergence(evidence: Agent1SignoffEvidence, findings: _FindingBuilder) -> None:
    if not evidence.cluster_trace:
        findings.add("G02", "COUNCIL_TRACE_MISSING", "P2_MAJOR", "Agent1 council trace is missing or empty.", {}, artifact_ref="reports/traces/agent1_council_trace.jsonl")
    for event in evidence.cluster_trace:
        text = json.dumps(event, sort_keys=True, default=str).upper()
        if "HITL_REQUIRED" in text or "UNRESOLVED" in text:
            findings.add("G02", "COUNCIL_UNRESOLVED_CHALLENGE", "P1_BLOCKER", "Council trace contains unresolved challenge or HITL requirement.", {"event": _compact_event(event)}, artifact_ref="reports/traces/agent1_council_trace.jsonl")
            break
        if str(event.get("status", "")).lower() in {"failed", "fail", "error"}:
            findings.add("G02", "COUNCIL_GROUP_FAILED", "P1_BLOCKER", "Council trace contains failed group/session.", {"event": _compact_event(event)}, artifact_ref="reports/traces/agent1_council_trace.jsonl")
            break


def _gate_g03_artifact_currentness(evidence: Agent1SignoffEvidence, findings: _FindingBuilder) -> None:
    for name in REQUIRED_AGENT1_ARTIFACTS:
        artifact = evidence.artifacts.get(name)
        if artifact is None or not artifact.exists:
            findings.add("G03", "MISSING_ARTIFACT", "P1_BLOCKER", f"Required Agent1 artifact missing: {name}.", {"artifact": name}, artifact_ref=name, waivable=False)
            continue
        if artifact.status and artifact.status != "current":
            findings.add("G03", "STALE_ARTIFACT", "P1_BLOCKER", f"Artifact is not marked current: {name}.", artifact.to_dict(), artifact_ref=name)
        if artifact.expected_sha256 and artifact.sha256 != artifact.expected_sha256:
            findings.add("G03", "ARTIFACT_HASH_MISMATCH", "P0_FATAL", f"Artifact hash mismatch: {name}.", artifact.to_dict(), artifact_ref=name, waivable=False)
        if artifact.revision_id and evidence.revision_id and artifact.revision_id != evidence.revision_id:
            findings.add("G03", "ARTIFACT_REVISION_MISMATCH", "P0_FATAL", f"Artifact revision mismatch: {name}.", artifact.to_dict(), artifact_ref=name, waivable=False)


def _gate_g04_contract_schema(evidence: Agent1SignoffEvidence, findings: _FindingBuilder) -> None:
    spec = evidence.spec
    if not spec:
        return
    if not isinstance(spec.get("agent1_contract_manifest"), dict) or not spec["agent1_contract_manifest"]:
        findings.add("G04", "CONTRACT_MANIFEST_MISSING", "P1_BLOCKER", "Agent1 contract manifest is missing.", {}, artifact_ref="reports/agent1/agent1_final_architecture_spec.json")
    try:
        validate_agent1_v4_spec_schema(spec)
    except Exception as exc:
        findings.add("G04", "CONTRACT_SCHEMA_INVALID", "P1_BLOCKER", "Agent1 V4 contract schema validation failed.", {"error": str(exc)}, artifact_ref="reports/agent1/agent1_final_architecture_spec.json")


def _gate_g05_memory_register_irq(evidence: Agent1SignoffEvidence, findings: _FindingBuilder) -> None:
    spec = evidence.spec
    if not spec:
        return
    if not spec.get("memory_map"):
        findings.add("G05", "MEMORY_MAP_MISSING", "P1_BLOCKER", "Memory map is missing.", {}, artifact_ref="reports/agent1/agent1_final_architecture_spec.json")
    for artifact in ("agent1_register_map.rdl", _firmware_header_name(spec), _dv_model_name(spec)):
        item = evidence.artifacts.get(artifact)
        if item is None or not item.exists:
            findings.add("G05", "REGISTER_ARTIFACT_MISSING", "P1_BLOCKER", f"Register collateral missing: {artifact}.", {"artifact": artifact}, artifact_ref=artifact)
    decisions = _read_agent1_json(evidence, "agent1_validation_decisions.json")
    if isinstance(decisions.get("decisions"), list):
        rejected = [entry for entry in decisions["decisions"] if str(entry.get("decision", "")).upper() in {"REJECT", "HITL_REQUIRED"}]
        if rejected:
            findings.add("G05", "REGISTER_VALIDATION_FAILED", "P1_BLOCKER", "Register validation contains REJECT/HITL_REQUIRED decision.", {"rejected": rejected[:5]}, artifact_ref="agent1_validation_decisions.json")
    _gate_g05_lock_register_policy(spec, findings)

def _gate_g05_lock_register_policy(spec: dict[str, Any], findings: _FindingBuilder) -> None:
    for block in _expected_lock_register_blocks(spec):
        registers = spec.get("memory_map", {}).get(block, {}).get("registers", {})
        lock_reg = registers.get("lock") if isinstance(registers, dict) else None
        if not isinstance(lock_reg, dict):
            findings.add("G05", "LOCK_REGISTER_MISSING", "P1_BLOCKER", f"Requirement asks for lock protection but {block}.lock is missing.", {"block": block}, artifact_ref="reports/agent1/agent1_final_architecture_spec.json", waivable=False)
            continue
        if str(lock_reg.get("write_policy") or "").lower() != "set_only":
            findings.add("G05", "LOCK_REGISTER_POLICY_INVALID", "P1_BLOCKER", f"{block}.lock must be set-only for fail-closed protection.", {"block": block, "write_policy": lock_reg.get("write_policy")}, artifact_ref="reports/agent1/agent1_final_architecture_spec.json", waivable=False)

def _expected_lock_register_blocks(spec: dict[str, Any]) -> list[str]:
    raw = str(spec.get("requirements", {}).get("raw") or "").lower()
    if not any(re.search(pattern, raw) for pattern in (
        r"\block(?:able|ed)?\s+(?:register|registers|csr|csrs|security|control)\b",
        r"\b(?:register|registers|csr|csrs)\s+(?:are\s+)?(?:lockable|locked)\b",
        r"\block\s+prevents\b",
        r"\bafter\s+lock\b",
        r"\bprotected\s+register",
    )):
        return []
    memory_map = spec.get("memory_map", {}) if isinstance(spec.get("memory_map"), dict) else {}
    blocks: list[str] = []
    if "gpio" in memory_map and any(token in raw for token in ("gpio", "direction", "pin")):
        blocks.append("gpio")
    if "timer" in memory_map and any(token in raw for token in ("timer", "watchdog", "disable", "kick", "service")):
        blocks.append("timer")
    return blocks

def _gate_g06_formal_first(evidence: Agent1SignoffEvidence, findings: _FindingBuilder) -> None:
    spec = evidence.spec
    if not spec:
        return
    if spec.get("constraints", {}).get("formal_first") is not True:
        findings.add("G06", "FORMAL_FIRST_MISSING", "P1_BLOCKER", "Spec does not assert formal_first=true.", {}, artifact_ref="reports/agent1/agent1_final_architecture_spec.json", waivable=False)
    manifest = spec.get("agent1_contract_manifest", {})
    handoffs = manifest.get("handoffs", {}) if isinstance(manifest, dict) else {}
    if "agent5" not in handoffs:
        findings.add("G06", "FORMAL_HANDOFF_MISSING", "P1_BLOCKER", "Agent5 formal handoff is missing from contract manifest.", {}, artifact_ref="reports/agent1/agent1_contract_manifest.json")


def _gate_g07_safety_security_power_clock_reset(evidence: Agent1SignoffEvidence, findings: _FindingBuilder) -> None:
    leaks = secret_leaks(
        {
            "manifest": evidence.to_manifest(),
            "raw_issues": evidence.raw_issues,
            "trace_events": evidence.trace_events,
        }
    )
    if leaks:
        findings.add("G07", "SECRET_LEAK", "P0_FATAL", "Signoff evidence contains secret-like material.", {"leaks": leaks}, waivable=False)
    for artifact, code in (
        ("agent1_safety_security_plan.json", "SAFETY_SECURITY_PLAN_MISSING"),
        ("agent1_clock_power_plan.json", "CLOCK_POWER_PLAN_MISSING"),
    ):
        item = evidence.artifacts.get(artifact)
        if item is None or not item.exists:
            findings.add("G07", code, "P2_MAJOR", f"{artifact} is missing.", {"artifact": artifact}, artifact_ref=artifact)
    spec = evidence.spec
    if spec and not spec.get("clock_domains"):
        findings.add("G07", "CLOCK_DOMAIN_MISSING", "P2_MAJOR", "Spec lacks clock domain information.", {}, artifact_ref="reports/agent1/agent1_final_architecture_spec.json")


def _gate_g08_numeric_provenance(evidence: Agent1SignoffEvidence, findings: _FindingBuilder) -> None:
    spec = evidence.spec
    if not spec:
        return
    provenance = spec.get("tool_provenance")
    if not isinstance(provenance, dict) or not provenance:
        findings.add("G08", "NUMERIC_PROVENANCE_MISSING", "P1_BLOCKER", "Tool provenance is missing for numeric estimates.", {}, artifact_ref="reports/agent1/agent1_final_architecture_spec.json")
        return
    for field in ("ppa_estimate", "bandwidth_estimate"):
        if field not in provenance:
            findings.add("G08", "NUMERIC_PROVENANCE_INCOMPLETE", "P1_BLOCKER", f"Missing provenance for {field}.", {"field": field}, artifact_ref="reports/agent1/agent1_final_architecture_spec.json")


def _gate_g09_independent_critic(evidence: Agent1SignoffEvidence, findings: _FindingBuilder) -> None:
    report = _read_agent1_json(evidence, "agent1_independent_critic_report.json")
    if not report:
        findings.add("G09", "INDEPENDENT_CRITIC_MISSING", "P2_MAJOR", "Independent critic report is missing.", {}, artifact_ref="agent1_independent_critic_report.json")
        return
    critic_findings = report.get("findings", [])
    if isinstance(critic_findings, list):
        high = [entry for entry in critic_findings if str(entry.get("severity", "")).lower() in {"high", "critical", "p0", "p1"}]
        if high:
            findings.add("G09", "INDEPENDENT_CRITIC_HIGH_FINDING", "P1_BLOCKER", "Independent critic found high-severity issue.", {"findings": high[:5]}, artifact_ref="agent1_independent_critic_report.json")


def _gate_g10_waiver_governance(evidence: Agent1SignoffEvidence, findings: _FindingBuilder) -> None:
    if evidence.waiver_load_error:
        findings.add("G10", "WAIVER_FILE_INVALID", "P1_BLOCKER", "signoff_waivers.json failed schema validation.", {"error": evidence.waiver_load_error}, artifact_ref="signoff_waivers.json")


def _gate_g11_handoff_readiness(evidence: Agent1SignoffEvidence, findings: _FindingBuilder) -> None:
    if not evidence.user_approval_ref:
        findings.add("G11", "USER_APPROVAL_MISSING", "P1_BLOCKER", "User approval reference is missing.", {}, waivable=False)
    if evidence.certificate_load_error:
        findings.add("G11", "CERTIFICATE_INVALID", "P1_BLOCKER", "Final signoff certificate failed schema validation.", {"error": evidence.certificate_load_error}, artifact_ref="agent1_final_signoff_certificate.json", waivable=False)
    elif evidence.final_certificate is None:
        findings.add("G11", "CERTIFICATE_MISSING", "P1_BLOCKER", "Final signoff certificate is missing.", {}, artifact_ref="agent1_final_signoff_certificate.json", waivable=False)
    else:
        cert = evidence.final_certificate
        if cert.run_id != evidence.run_id or cert.revision_id != evidence.revision_id:
            findings.add("G11", "CERTIFICATE_STALE", "P0_FATAL", "Final signoff certificate run/revision does not match evidence.", {"certificate_run_id": cert.run_id, "certificate_revision_id": cert.revision_id}, artifact_ref="agent1_final_signoff_certificate.json", waivable=False)
        if not cert.handoff_allowed or cert.decision not in {"PASS", "PASS_WITH_WAIVERS"}:
            findings.add("G11", "CERTIFICATE_NOT_HANDOFF_ALLOWED", "P1_BLOCKER", "Final signoff certificate does not allow handoff.", {"decision": cert.decision, "handoff_allowed": cert.handoff_allowed}, artifact_ref="agent1_final_signoff_certificate.json", waivable=False)
        for artifact, digest in cert.artifact_hashes.items():
            actual = evidence.artifact_hashes.get(artifact)
            if actual and actual != digest:
                findings.add("G11", "CERTIFICATE_ARTIFACT_HASH_MISMATCH", "P0_FATAL", f"Certificate artifact hash mismatch: {artifact}.", {"expected_sha256": digest, "actual_sha256": actual}, artifact_ref=artifact, waivable=False)


def _gate_g12_benchmark_proof(evidence: Agent1SignoffEvidence, findings: _FindingBuilder) -> None:
    report = evidence.benchmark_report
    if not report:
        findings.add("G12", "BENCHMARK_REPORT_MISSING", "P1_BLOCKER" if evidence.profile in {"strict", "nightly"} else "P2_MAJOR", "Benchmark proof report is missing.", {}, artifact_ref="agent1_signoff_benchmark_report.json")
        return
    if report.get("schema_version") != BENCHMARK_REPORT_SCHEMA_VERSION:
        findings.add("G12", "BENCHMARK_REPORT_SCHEMA_INVALID", "P1_BLOCKER", "Benchmark report schema_version is invalid.", {"schema_version": report.get("schema_version")}, artifact_ref="agent1_signoff_benchmark_report.json")
    false_pass_count = _int_value(report.get("false_pass_count"))
    must_not_pass_violation_count = _int_value(report.get("must_not_pass_violation_count"))
    case_count = _int_value(report.get("case_count"))
    if false_pass_count > 0:
        findings.add("G12", "BENCHMARK_FALSE_PASS", "P0_FATAL", "Benchmark proof found false pass.", {"false_pass_count": false_pass_count}, artifact_ref="agent1_signoff_benchmark_report.json", waivable=False)
    if must_not_pass_violation_count > 0:
        findings.add("G12", "BENCHMARK_MUST_NOT_PASS_VIOLATION", "P0_FATAL", "Benchmark proof found must-not-pass violation.", {"must_not_pass_violation_count": must_not_pass_violation_count}, artifact_ref="agent1_signoff_benchmark_report.json", waivable=False)
    if evidence.profile in {"strict", "nightly"} and case_count < 100:
        findings.add("G12", "BENCHMARK_CORPUS_TOO_SMALL", "P1_BLOCKER", "Strict/nightly signoff requires at least 100 benchmark cases.", {"case_count": case_count}, artifact_ref="agent1_signoff_benchmark_report.json")
    _check_benchmark_artifacts(evidence, findings, report)
    if str(report.get("secret_scan") or "") != "pass":
        findings.add("G12", "BENCHMARK_SECRET_SCAN_FAILED", "P0_FATAL", "Benchmark proof secret scan did not pass.", {"secret_scan": report.get("secret_scan")}, artifact_ref="agent1_signoff_benchmark_report.json", waivable=False)
    for metric, threshold, code in (
        ("waiver_accuracy", 1.0, "BENCHMARK_WAIVER_ACCURACY_FAILED"),
        ("handoff_gate_accuracy", 1.0, "BENCHMARK_HANDOFF_ACCURACY_FAILED"),
        ("stale_artifact_detection_accuracy", 1.0, "BENCHMARK_STALE_ARTIFACT_ACCURACY_FAILED"),
        ("strict_expected_match_rate", 0.98, "BENCHMARK_STRICT_MATCH_RATE_LOW"),
        ("balanced_expected_match_rate", 0.95, "BENCHMARK_BALANCED_MATCH_RATE_LOW"),
    ):
        if _float_value(report.get(metric)) < threshold:
            findings.add("G12", code, "P1_BLOCKER", f"Benchmark metric {metric} is below required threshold.", {"metric": metric, "actual": report.get(metric), "required": threshold}, artifact_ref="agent1_signoff_benchmark_report.json")
    if _int_value(report.get("clean_pass_regression_count")) > 0:
        findings.add("G12", "BENCHMARK_CLEAN_PASS_REGRESSION", "P1_BLOCKER", "Benchmark clean-pass regression count is non-zero.", {"clean_pass_regression_count": report.get("clean_pass_regression_count")}, artifact_ref="agent1_signoff_benchmark_report.json")
    if _int_value(report.get("oracle_disagreement_count")) > 0:
        findings.add("G12", "BENCHMARK_ORACLE_DISAGREEMENT", "P1_BLOCKER", "Benchmark oracle disagreement count is non-zero.", {"oracle_disagreement_count": report.get("oracle_disagreement_count")}, artifact_ref="agent1_signoff_benchmark_report.json")


def _collect_artifacts(root: Path, required: tuple[str, ...], fingerprint_manifest: dict[str, Any]) -> dict[str, ArtifactEvidence]:
    artifact_names = set(required)
    fingerprint_entries = []
    if isinstance(fingerprint_manifest.get("artifacts"), list):
        fingerprint_entries = [entry for entry in fingerprint_manifest["artifacts"] if isinstance(entry, dict)]
        artifact_names.update(str(entry.get("artifact") or "") for entry in fingerprint_entries if entry.get("artifact"))
    for path in (root / "reports").glob("*"):
        if path.is_file():
            artifact_names.add(path.name)
    agent1_dir = root / "reports" / "agent1"
    if agent1_dir.exists():
        for path in agent1_dir.glob("*"):
            if path.is_file():
                artifact_names.add(path.name)

    fingerprint_by_name = {str(entry.get("artifact")): entry for entry in fingerprint_entries if entry.get("artifact")}
    output: dict[str, ArtifactEvidence] = {}
    for name in sorted(artifact_names):
        path = _artifact_path(root, name)
        entry = fingerprint_by_name.get(name, {})
        exists = path.is_file()
        digest = _sha256_file(path) if exists else None
        output[name] = ArtifactEvidence(
            artifact=name,
            path=str(path),
            exists=exists,
            sha256=digest,
            expected_sha256=str(entry.get("sha256") or "") or None,
            status=str(entry.get("status") or ""),
            revision_id=str(entry.get("requirement_revision_id") or entry.get("spec_revision_id") or ""),
        )
    return output


def _artifact_path(root: Path, artifact: str) -> Path:
    artifact_path = Path(artifact)
    if artifact.startswith("reports/") or artifact.startswith("reports\\"):
        return root / artifact_path
    if artifact == "architecture_plan.md":
        return root / "reports" / artifact
    return root / "reports" / "agent1" / artifact


def _sha256_file(path: Path) -> str:
    return sha256_text(path.read_text(encoding="utf-8", errors="replace"))


def _read_json(path: Path, label: str, errors: list[dict[str, Any]], *, required: bool = True) -> dict[str, Any]:
    if not path.is_file():
        if required:
            errors.append({"code": "MISSING_JSON", "label": label, "path": str(path)})
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append({"code": "INVALID_JSON", "label": label, "path": str(path), "error": str(exc)})
        return {}
    if not isinstance(value, dict):
        errors.append({"code": "JSON_NOT_OBJECT", "label": label, "path": str(path)})
        return {}
    return value


def _read_text(path: Path, label: str, errors: list[dict[str, Any]]) -> str:
    if not path.is_file():
        errors.append({"code": "MISSING_TEXT", "label": label, "path": str(path)})
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        errors.append({"code": "UNREADABLE_TEXT", "label": label, "path": str(path), "error": str(exc)})
        return ""


def _read_trace_jsonl(trace_dir: Path) -> list[dict[str, Any]]:
    if not trace_dir.exists():
        return []
    events: list[dict[str, Any]] = []
    for path in sorted(trace_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = {"schema_error": "invalid_jsonl", "source_trace_file": path.name, "line": line[:200]}
            if isinstance(event, dict):
                event.setdefault("source_trace_file", path.name)
                events.append(event)
    return events


def _load_waivers(root: Path) -> tuple[SignoffWaivers | None, str]:
    for path in (root / "reports" / "agent1" / "signoff_waivers.json", root / "reports" / "signoff_waivers.json"):
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return SignoffWaivers.from_dict(payload), ""
        except Exception as exc:
            return None, str(exc)
    return None, ""


def _load_certificate(root: Path) -> tuple[Agent1FinalSignoffCertificate | None, str]:
    for path in (root / "reports" / "agent1" / "agent1_final_signoff_certificate.json", root / "reports" / "agent1_final_signoff_certificate.json"):
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return Agent1FinalSignoffCertificate.from_dict(payload), ""
        except Exception as exc:
            return None, str(exc)
    return None, ""


def _approval_ref_from_manifest(run_manifest: dict[str, Any]) -> str | None:
    for key in ("user_approval_ref", "plan_approval_ref", "approval_ref"):
        if run_manifest.get(key):
            return str(run_manifest[key])
    return None


def _read_agent1_json(evidence: Agent1SignoffEvidence, artifact: str) -> dict[str, Any]:
    path = evidence.output_dir / "reports" / "agent1" / artifact
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _firmware_header_name(spec: dict[str, Any]) -> str:
    project = str(spec.get("project_name") or "project")
    return f"fw_{project}_regs.h"


def _dv_model_name(spec: dict[str, Any]) -> str:
    project = str(spec.get("project_name") or "project")
    return f"tb_{project}_reg_model.py"


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    keys = ("source_trace_file", "node_id", "event_type", "status", "message", "code")
    return {key: event.get(key) for key in keys if key in event}


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

def _float_value(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

def _hash_or_zero(value: Any) -> str:
    if value in (None, "", {}, [], ()):
        return "0" * 64
    return sha256_text(json.dumps(value, sort_keys=True, default=str))


def _finding_blocks_profile(finding: SignoffFinding, profile: str) -> bool:
    if finding.waiver_id:
        return False
    if finding.severity in {"P0_FATAL", "P1_BLOCKER"}:
        return True
    if profile in {"strict", "nightly"} and finding.severity == "P2_MAJOR":
        return True
    return False


def _gate_status(profile: str, findings: list[SignoffFinding]) -> str:
    if not findings:
        return "PASS"
    if all(finding.waiver_id for finding in findings):
        return "WAIVED"
    if any(_finding_blocks_profile(finding, profile) for finding in findings):
        return "FAIL"
    return "WARN"

def _check_benchmark_artifacts(evidence: Agent1SignoffEvidence, findings: _FindingBuilder, report: dict[str, Any]) -> None:
    agent1_dir = evidence.output_dir / "reports" / "agent1"
    for artifact in sorted(BENCHMARK_ARTIFACTS):
        path = agent1_dir / artifact
        if not path.is_file():
            findings.add(
                "G12",
                "BENCHMARK_ARTIFACT_MISSING",
                "P1_BLOCKER",
                f"Benchmark artifact missing: {artifact}.",
                {"artifact": artifact},
                artifact_ref=artifact,
            )
    manifest_path = agent1_dir / "agent1_signoff_benchmark_manifest_hash.json"
    if not manifest_path.is_file():
        return
    manifest = _read_agent1_json(evidence, "agent1_signoff_benchmark_manifest_hash.json")
    manifest_hash = str(manifest.get("manifest_hash") or "")
    if len(manifest_hash) != 64 or any(ch not in "0123456789abcdef" for ch in manifest_hash):
        findings.add(
            "G12",
            "BENCHMARK_MANIFEST_HASH_INVALID",
            "P1_BLOCKER",
            "Benchmark manifest hash is malformed.",
            {"manifest_hash": manifest_hash},
            artifact_ref="agent1_signoff_benchmark_manifest_hash.json",
        )
    if report.get("manifest_hash") and report.get("manifest_hash") != manifest_hash:
        findings.add(
            "G12",
            "BENCHMARK_MANIFEST_HASH_MISMATCH",
            "P1_BLOCKER",
            "Benchmark report manifest hash does not match manifest artifact.",
            {"report_manifest_hash": report.get("manifest_hash"), "manifest_hash": manifest_hash},
            artifact_ref="agent1_signoff_benchmark_manifest_hash.json",
        )
    for artifact_key, filename in (
        ("corpus_hash", "agent1_signoff_benchmark_corpus.jsonl"),
        ("case_results_hash", "agent1_signoff_case_results.jsonl"),
        ("false_pass_report_hash", "agent1_signoff_false_pass_report.json"),
    ):
        expected = str(manifest.get(artifact_key) or "")
        path = agent1_dir / filename
        if expected and path.is_file():
            actual = _sha256_file(path)
            if actual != expected:
                findings.add(
                    "G12",
                    "BENCHMARK_ARTIFACT_HASH_MISMATCH",
                    "P0_FATAL",
                    f"Benchmark artifact hash mismatch: {filename}.",
                    {"artifact": filename, "expected_sha256": expected, "actual_sha256": actual},
                    artifact_ref=filename,
                    waivable=False,
                )
