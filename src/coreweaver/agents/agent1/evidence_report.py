from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError

from coreweaver.contracts import HandoffValidationError, validate_agent1_to_agent2_handoff
from coreweaver.debug import validate_replay_resume_state, validate_trace_replay_consistency
from coreweaver.framework_types import StrictCoreModel

from .models import ChallengeSeverity, SignoffCertificate

REQUIRED_TRACE_FIELDS = ("event_type", "run_id", "revision_id", "span_id", "timestamp")
REQUIRED_SIGNOFF_GATES = tuple(f"G{i:02d}" for i in range(13))


class EvidenceArtifacts(StrictCoreModel):
    trace_path: str
    replay_path: str
    signoff_path: str
    handoff_path: str
    artifact_index_path: str
    report_path: str
    markdown_report_path: str


class GateEvidence(StrictCoreModel):
    gate_id: str
    status: str


class FindingEvidence(StrictCoreModel):
    gate_id: str
    severity: str
    code: str
    message: str
    evidence_refs: tuple[str, ...] = ()


class TraceSummary(StrictCoreModel):
    event_count: int
    missing_required_fields: tuple[str, ...] = ()
    artifact_ref_count: int = 0
    terminal_events: tuple[str, ...] = ()


class ReplaySummary(StrictCoreModel):
    event_count: int
    checkpoint_count: int
    debug_issue_count: int
    has_blackboard_snapshot: bool
    has_signoff: bool
    has_handoff: bool


class ReplayResumeSummary(StrictCoreModel):
    passed: bool
    latest_stage: str = "unknown"
    latest_checkpoint_ref: str = "unknown"
    action_required: str | None = None
    blackboard_revision: int | None = None
    reconstructable: bool = False
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class TraceValidationSummary(StrictCoreModel):
    passed: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class Agent1EvidenceReport(StrictCoreModel):
    schema_version: str = "coreweaver.agent1.evidence_report.v1"
    run_id: str
    revision_id: str
    profile: str
    benchmark_case_id: str | None = None
    mutation_tags: tuple[str, ...] = ()
    terminal_status: str
    artifacts: EvidenceArtifacts
    gates: tuple[GateEvidence, ...] = ()
    verifier_findings: tuple[FindingEvidence, ...] = ()
    signoff_findings: tuple[FindingEvidence, ...] = ()
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    debug_completeness_score: int
    readiness_score: int
    verdict: str
    trace_summary: TraceSummary
    replay_summary: ReplaySummary
    replay_resume: ReplayResumeSummary
    trace_validation: TraceValidationSummary


def generate_agent1_evidence_report(
    run_dir: str | Path,
    *,
    profile: str = "mock_swarm",
    benchmark_case: dict[str, Any] | None = None,
    write: bool = True,
) -> Agent1EvidenceReport:
    """Build an Agent1 evidence report from already-written run artifacts."""
    run_path = Path(run_dir)
    trace_path = run_path / "trace" / "events.jsonl"
    replay_path = run_path / "replay" / "replay_bundle.json"
    signoff_path = run_path / "reports" / "agent1" / "agent1_final_signoff_certificate.json"
    handoff_path = run_path / "contracts" / "agent1_to_agent2.json"
    artifact_index_path = run_path / "artifacts" / "agent1_artifact_index.json"
    report_path = run_path / "artifacts" / "agent1_evidence_report.json"
    markdown_report_path = run_path / "artifacts" / "agent1_evidence_report.md"

    blockers: list[str] = []
    warnings: list[str] = []
    missing_evidence: list[str] = []

    events = _load_trace(trace_path, blockers, missing_evidence)
    replay = _load_json_object(replay_path, "replay_bundle", blockers, missing_evidence)
    run_id = _first_text(events, "run_id") or str(replay.get("run_id") or "unknown")
    revision_id = _first_text(events, "revision_id") or "unknown"
    terminal_status = _terminal_status(events)

    artifact_refs = _artifact_refs(events)
    artifact_index = _build_artifact_index(run_path, artifact_refs)
    missing_artifact_refs = tuple(item["path"] for item in artifact_index if not item["exists"])
    for path in missing_artifact_refs:
        blockers.append(f"artifact_ref_missing:{path}")
        missing_evidence.append(f"artifact_ref:{path}")

    trace_missing_fields = _missing_trace_fields(events)
    for field in trace_missing_fields:
        blockers.append(f"trace_missing_required_field:{field}")
        missing_evidence.append(f"trace_field:{field}")

    signoff = _load_signoff(signoff_path, blockers, missing_evidence)
    gates, signoff_findings, verifier_findings = _summarize_signoff(signoff, blockers, warnings, missing_evidence)
    handoff_ready = _validate_handoff(handoff_path, blockers, missing_evidence)

    replay_summary = _summarize_replay(replay, blockers, warnings, missing_evidence)
    replay_resume = _validate_replay_resume(replay, blockers, warnings, missing_evidence)
    trace_validation = _validate_trace_replay(events, replay, blockers, warnings, missing_evidence)
    trace_summary = TraceSummary(
        event_count=len(events),
        missing_required_fields=tuple(sorted(set(trace_missing_fields))),
        artifact_ref_count=len(artifact_refs),
        terminal_events=tuple(_terminal_events(events)),
    )
    debug_score = _debug_score(trace_path, replay_path, trace_missing_fields, replay_summary, replay_resume, missing_artifact_refs, trace_validation)
    readiness_score = _readiness_score(signoff, handoff_ready)
    verdict = "ready" if readiness_score == 100 and debug_score == 100 and not blockers and not missing_evidence else "not_ready"

    if write:
        artifact_index_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_index_path.write_text(json.dumps(artifact_index, indent=2, sort_keys=True), encoding="utf-8")

    report = Agent1EvidenceReport(
        run_id=run_id,
        revision_id=revision_id,
        profile=profile,
        benchmark_case_id=str(benchmark_case.get("case_id")) if benchmark_case and benchmark_case.get("case_id") else None,
        mutation_tags=tuple(str(item) for item in (benchmark_case or {}).get("mutation_tags", ())),
        terminal_status=terminal_status,
        artifacts=EvidenceArtifacts(
            trace_path=_display_path(trace_path),
            replay_path=_display_path(replay_path),
            signoff_path=_display_path(signoff_path),
            handoff_path=_display_path(handoff_path),
            artifact_index_path=_display_path(artifact_index_path),
            report_path=_display_path(report_path),
            markdown_report_path=_display_path(markdown_report_path),
        ),
        gates=gates,
        verifier_findings=verifier_findings,
        signoff_findings=signoff_findings,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
        missing_evidence=tuple(dict.fromkeys(missing_evidence)),
        debug_completeness_score=debug_score,
        readiness_score=readiness_score,
        verdict=verdict,
        trace_summary=trace_summary,
        replay_summary=replay_summary,
        replay_resume=replay_resume,
        trace_validation=trace_validation,
    )
    if write:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8")
        markdown_report_path.write_text(render_agent1_evidence_markdown(report), encoding="utf-8")
    return report


def render_agent1_evidence_markdown(report: Agent1EvidenceReport) -> str:
    lines = [
        "# Agent1 Evidence Report",
        "",
        "## Summary",
        f"- Verdict: `{report.verdict}`",
        f"- Run ID: `{report.run_id}`",
        f"- Revision ID: `{report.revision_id}`",
        f"- Profile: `{report.profile}`",
        f"- Benchmark case: `{report.benchmark_case_id or 'none'}`",
        f"- Mutation tags: `{', '.join(report.mutation_tags) if report.mutation_tags else 'none'}`",
        f"- Terminal status: `{report.terminal_status}`",
        f"- Readiness score: `{report.readiness_score}`",
        f"- Debug completeness score: `{report.debug_completeness_score}`",
        "",
        "## Artifacts",
        f"- Trace: [{report.artifacts.trace_path}]({report.artifacts.trace_path})",
        f"- Replay bundle: [{report.artifacts.replay_path}]({report.artifacts.replay_path})",
        f"- Signoff certificate: [{report.artifacts.signoff_path}]({report.artifacts.signoff_path})",
        f"- Handoff: [{report.artifacts.handoff_path}]({report.artifacts.handoff_path})",
        f"- Artifact index: [{report.artifacts.artifact_index_path}]({report.artifacts.artifact_index_path})",
        f"- JSON evidence report: [{report.artifacts.report_path}]({report.artifacts.report_path})",
        "",
        "## G00-G12 Gates",
        "| Gate | Status |",
        "| --- | --- |",
    ]
    if report.gates:
        lines.extend(f"| `{_md_cell(gate.gate_id)}` | `{_md_cell(gate.status)}` |" for gate in report.gates)
    else:
        lines.append("| none | none |")
    lines.extend(
        [
            "",
            "## Verifier Findings",
            *_finding_lines(report.verifier_findings),
            "",
            "## Signoff Findings",
            *_finding_lines(report.signoff_findings),
            "",
            "## Blockers",
            *_list_lines(report.blockers),
            "",
            "## Warnings",
            *_list_lines(report.warnings),
            "",
            "## Missing Evidence",
            *_list_lines(report.missing_evidence),
            "",
            "## Trace Summary",
            f"- Event count: `{report.trace_summary.event_count}`",
            f"- Artifact ref count: `{report.trace_summary.artifact_ref_count}`",
            f"- Missing required fields: `{', '.join(report.trace_summary.missing_required_fields) if report.trace_summary.missing_required_fields else 'none'}`",
            f"- Terminal events: `{', '.join(report.trace_summary.terminal_events) if report.trace_summary.terminal_events else 'none'}`",
            "",
            "## Trace Validation",
            f"- Passed: `{str(report.trace_validation.passed).lower()}`",
            f"- Errors: `{', '.join(report.trace_validation.errors) if report.trace_validation.errors else 'none'}`",
            f"- Warnings: `{', '.join(report.trace_validation.warnings) if report.trace_validation.warnings else 'none'}`",
            "",
            "## Replay Summary",
            f"- Event count: `{report.replay_summary.event_count}`",
            f"- Checkpoint count: `{report.replay_summary.checkpoint_count}`",
            f"- Debug issue count: `{report.replay_summary.debug_issue_count}`",
            f"- Has blackboard snapshot: `{str(report.replay_summary.has_blackboard_snapshot).lower()}`",
            f"- Has signoff: `{str(report.replay_summary.has_signoff).lower()}`",
            f"- Has handoff: `{str(report.replay_summary.has_handoff).lower()}`",
            "",
            "## Replay Resume",
            f"- Passed: `{str(report.replay_resume.passed).lower()}`",
            f"- Latest stage: `{report.replay_resume.latest_stage}`",
            f"- Latest checkpoint: `{report.replay_resume.latest_checkpoint_ref}`",
            f"- Action required: `{report.replay_resume.action_required or 'none'}`",
            f"- Blackboard revision: `{report.replay_resume.blackboard_revision if report.replay_resume.blackboard_revision is not None else 'none'}`",
            f"- Reconstructable: `{str(report.replay_resume.reconstructable).lower()}`",
            f"- Errors: `{', '.join(report.replay_resume.errors) if report.replay_resume.errors else 'none'}`",
            f"- Warnings: `{', '.join(report.replay_resume.warnings) if report.replay_resume.warnings else 'none'}`",
            "",
            "## Reviewer Note",
            _reviewer_note(report),
            "",
        ]
    )
    return "\n".join(lines)


def _load_trace(path: Path, blockers: list[str], missing: list[str]) -> list[dict[str, Any]]:
    if not path.exists():
        blockers.append("trace_missing")
        missing.append("trace/events.jsonl")
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            blockers.append(f"trace_malformed_json:line:{line_number}")
            continue
        if not isinstance(event, dict):
            blockers.append(f"trace_event_not_object:line:{line_number}")
            continue
        events.append(event)
    return events


def _load_json_object(path: Path, label: str, blockers: list[str], missing: list[str]) -> dict[str, Any]:
    if not path.exists():
        blockers.append(f"{label}_missing")
        missing.append(_display_path(path))
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        blockers.append(f"{label}_malformed_json")
        return {}
    if not isinstance(payload, dict):
        blockers.append(f"{label}_not_object")
        return {}
    return payload


def _load_signoff(path: Path, blockers: list[str], missing: list[str]) -> SignoffCertificate | None:
    if not path.exists():
        blockers.append("signoff_certificate_missing")
        missing.append("reports/agent1/agent1_final_signoff_certificate.json")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        blockers.append("signoff_certificate_malformed_json")
        return None
    try:
        return SignoffCertificate.model_validate(payload)
    except ValidationError:
        blockers.append("signoff_certificate_schema_invalid")
        return None


def _summarize_signoff(
    signoff: SignoffCertificate | None,
    blockers: list[str],
    warnings: list[str],
    missing: list[str],
) -> tuple[tuple[GateEvidence, ...], tuple[FindingEvidence, ...], tuple[FindingEvidence, ...]]:
    if signoff is None:
        return (), (), ()
    if signoff.passed is not True:
        blockers.append("signoff_certificate_failed")
    gates = tuple(GateEvidence(gate_id=gate, status=str(status)) for gate, status in sorted(signoff.gate_results.items()))
    if tuple(sorted(signoff.gate_results)) != REQUIRED_SIGNOFF_GATES:
        blockers.append("signoff_gates_incomplete")
        missing.append("signoff:G00-G12")
    failed = tuple(gate for gate, status in signoff.gate_results.items() if status != "pass")
    for gate in failed:
        blockers.append(f"signoff_gate_failed:{gate}")
    findings = tuple(_finding_evidence(finding) for finding in signoff.findings)
    for finding in signoff.findings:
        if finding.severity == ChallengeSeverity.BLOCKER:
            blockers.append(f"signoff_finding_blocker:{finding.code}")
        elif finding.severity == ChallengeSeverity.WARN:
            warnings.append(f"signoff_finding_warn:{finding.code}")
    verifier_findings = tuple(item for item in findings if item.gate_id.startswith("V"))
    return gates, findings, verifier_findings


def _validate_handoff(path: Path, blockers: list[str], missing: list[str]) -> bool:
    if not path.exists():
        blockers.append("agent1_to_agent2_handoff_missing")
        missing.append("contracts/agent1_to_agent2.json")
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        blockers.append("agent1_to_agent2_handoff_malformed_json")
        return False
    if isinstance(payload, dict) and payload.get("ready") is True:
        try:
            validate_agent1_to_agent2_handoff(path)
        except HandoffValidationError as exc:
            blockers.append(f"agent1_to_agent2_handoff_invalid:{exc}")
            missing.append("ready_handoff_valid_certificate")
            return False
        return True
    blockers.append("agent1_to_agent2_handoff_not_ready")
    return False


def _summarize_replay(
    replay: dict[str, Any],
    blockers: list[str],
    warnings: list[str],
    missing: list[str],
) -> ReplaySummary:
    events = replay.get("events") if isinstance(replay.get("events"), list) else []
    checkpoints = replay.get("checkpoints") if isinstance(replay.get("checkpoints"), list) else []
    debug_issues = replay.get("debug_issues") if isinstance(replay.get("debug_issues"), list) else []
    if replay:
        for field in ("schema_version", "run_id", "events", "checkpoints", "debug_issues", "signoff", "handoff", "resume"):
            if field not in replay:
                blockers.append(f"replay_missing_field:{field}")
                missing.append(f"replay:{field}")
        if not events:
            blockers.append("replay_events_empty")
        if not checkpoints:
            warnings.append("replay_checkpoints_empty")
    return ReplaySummary(
        event_count=len(events),
        checkpoint_count=len(checkpoints),
        debug_issue_count=len(debug_issues),
        has_blackboard_snapshot=replay.get("blackboard_snapshot") is not None,
        has_signoff=replay.get("signoff") is not None,
        has_handoff=replay.get("handoff") is not None,
    )


def _validate_replay_resume(
    replay: dict[str, Any],
    blockers: list[str],
    warnings: list[str],
    missing: list[str],
) -> ReplayResumeSummary:
    result = validate_replay_resume_state(replay)
    for error in result.errors:
        blockers.append(f"replay_resume:{error}")
        missing.append(f"replay_resume:{error}")
    for warning in result.warnings:
        warnings.append(f"replay_resume:{warning}")
    state = result.resume_state
    return ReplayResumeSummary(
        passed=result.passed,
        latest_stage=state.latest_stage if state else "unknown",
        latest_checkpoint_ref=state.latest_checkpoint_ref if state else "unknown",
        action_required=state.action_required if state else None,
        blackboard_revision=state.blackboard_revision if state else None,
        reconstructable=state.reconstructable if state else False,
        errors=result.errors,
        warnings=result.warnings,
    )


def _validate_trace_replay(
    events: list[dict[str, Any]],
    replay: dict[str, Any],
    blockers: list[str],
    warnings: list[str],
    missing: list[str],
) -> TraceValidationSummary:
    result = validate_trace_replay_consistency(events, replay)
    for error in result.errors:
        blockers.append(f"trace_validation:{error}")
        missing.append(f"trace_validation:{error}")
    for warning in result.warnings:
        warnings.append(f"trace_validation:{warning}")
    return TraceValidationSummary(
        passed=result.passed,
        errors=result.errors,
        warnings=result.warnings,
    )


def _missing_trace_fields(events: list[dict[str, Any]]) -> tuple[str, ...]:
    missing: set[str] = set()
    for event in events:
        for field in REQUIRED_TRACE_FIELDS:
            if not event.get(field):
                missing.add(field)
    return tuple(sorted(missing))


def _artifact_refs(events: list[dict[str, Any]]) -> tuple[str, ...]:
    refs: list[str] = []
    for event in events:
        if event.get("event_type") != "artifact_written":
            continue
        payload = event.get("payload")
        if isinstance(payload, dict) and payload.get("path"):
            refs.append(str(payload["path"]))
    return tuple(refs)


def _build_artifact_index(run_path: Path, refs: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {
            "path": ref,
            "exists": _resolve_ref(run_path, ref).exists(),
            "kind": "trace_artifact_ref",
        }
        for ref in refs
    ]


def _resolve_ref(run_path: Path, ref: str) -> Path:
    candidate = Path(ref)
    if candidate.is_absolute() or candidate.exists():
        return candidate
    return run_path / candidate


def _terminal_status(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        payload = event.get("payload")
        if isinstance(payload, dict) and payload.get("action_required"):
            return str(payload["action_required"])
        if event.get("event_type") == "agent1_handoff_ready":
            return "PLAN_REVIEW"
        if event.get("event_type") == "agent1_handoff_blocked":
            return "HITL_REQUIRED"
    return "UNKNOWN"


def _terminal_events(events: list[dict[str, Any]]) -> tuple[str, ...]:
    names = []
    for event in events:
        event_type = str(event.get("event_type") or "")
        if event_type in {"hitl_required", "agent1_handoff_ready", "agent1_handoff_blocked"}:
            names.append(event_type)
    return tuple(names)


def _first_text(events: list[dict[str, Any]], field: str) -> str | None:
    for event in events:
        value = event.get(field)
        if value:
            return str(value)
    return None


def _finding_evidence(finding: Any) -> FindingEvidence:
    return FindingEvidence(
        gate_id=str(finding.gate_id),
        severity=str(finding.severity.value if hasattr(finding.severity, "value") else finding.severity),
        code=str(finding.code),
        message=str(finding.message),
        evidence_refs=tuple(str(item) for item in finding.evidence_refs),
    )


def _debug_score(
    trace_path: Path,
    replay_path: Path,
    trace_missing_fields: tuple[str, ...],
    replay_summary: ReplaySummary,
    replay_resume: ReplayResumeSummary,
    missing_artifact_refs: tuple[str, ...],
    trace_validation: TraceValidationSummary,
) -> int:
    checks = (
        trace_path.exists(),
        replay_path.exists(),
        trace_path.exists() and not trace_missing_fields,
        replay_summary.event_count > 0,
        replay_summary.checkpoint_count > 0,
        replay_resume.passed,
        trace_path.exists() and not missing_artifact_refs,
        trace_validation.passed,
    )
    return round(100 * sum(1 for item in checks if item) / len(checks))


def _readiness_score(signoff: SignoffCertificate | None, handoff_ready: bool) -> int:
    if signoff is None:
        return 0
    gates_complete = tuple(sorted(signoff.gate_results)) == REQUIRED_SIGNOFF_GATES
    gates_pass = gates_complete and all(status == "pass" for status in signoff.gate_results.values())
    if signoff.passed and gates_pass and handoff_ready:
        return 100
    if signoff.passed and gates_pass:
        return 60
    return 20


def _finding_lines(findings: tuple[FindingEvidence, ...]) -> list[str]:
    if not findings:
        return ["- None"]
    return [
        f"- `{finding.gate_id}` `{finding.severity}` `{finding.code}`: {finding.message}"
        + (f" Evidence: `{', '.join(finding.evidence_refs)}`" if finding.evidence_refs else "")
        for finding in findings
    ]


def _list_lines(items: tuple[str, ...]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- `{item}`" for item in items]


def _reviewer_note(report: Agent1EvidenceReport) -> str:
    if report.verdict == "ready":
        return (
            "This run is ready because debug evidence is complete, G00-G12 signoff gates pass, "
            "and the Agent1-to-Agent2 handoff is backed by a valid passing signoff certificate."
        )
    reasons = []
    if report.blockers:
        reasons.append(f"blockers exist ({', '.join(report.blockers[:5])})")
    if report.missing_evidence:
        reasons.append(f"missing evidence exists ({', '.join(report.missing_evidence[:5])})")
    if report.readiness_score < 100:
        reasons.append(f"readiness score is {report.readiness_score}")
    if report.debug_completeness_score < 100:
        reasons.append(f"debug completeness score is {report.debug_completeness_score}")
    detail = "; ".join(reasons) if reasons else "the evidence verdict is not ready"
    return f"This run is not ready because {detail}."


def _md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _display_path(path: Path) -> str:
    return str(path).replace("\\", "/")
