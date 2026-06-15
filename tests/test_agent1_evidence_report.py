import asyncio
import json
import subprocess
import sys
from pathlib import Path

from coreweaver.agents.agent1.evidence_report import generate_agent1_evidence_report
from coreweaver.runtime import RuntimeSession, RuntimeState

ROOT = Path(__file__).resolve().parents[1]

SECURE_NPU = (
    "Design a Secure Edge AI Vision NPU with 64-bit AXI4 image DMA, 32-bit APB firmware CSRs, MAC array, "
    "64KB SRAM buffer, AES-256 on-the-fly weight decrypt, software-programmable write-only key locked after "
    "boot with no readback, 500MHz target, and <2W power budget."
)


def _run_agent1(tmp_path: Path, *, requirement: str = SECURE_NPU, run_id: str = "evidence-run") -> Path:
    session = RuntimeSession(
        RuntimeState(
            run_id=run_id,
            profile="mock_swarm",
            requirement=requirement,
            project_name=run_id,
            planning_mode="deep_planning",
            output_dir=str(tmp_path),
        )
    )
    asyncio.run(session.start())
    return tmp_path


def test_agent1_evidence_report_ready_run_proves_debug_and_readiness(tmp_path: Path) -> None:
    run_dir = _run_agent1(tmp_path)
    report = generate_agent1_evidence_report(
        run_dir,
        benchmark_case={"case_id": "case_secure_npu", "mutation_tags": ["secure_key_policy", "ppa_risk"]},
    )
    assert report.verdict == "ready"
    assert report.terminal_status == "PLAN_REVIEW"
    assert report.debug_completeness_score == 100
    assert report.readiness_score == 100
    assert report.benchmark_case_id == "case_secure_npu"
    assert report.mutation_tags == ("secure_key_policy", "ppa_risk")
    assert tuple(gate.gate_id for gate in report.gates) == tuple(f"G{i:02d}" for i in range(13))
    assert Path(report.artifacts.report_path).exists()
    assert Path(report.artifacts.markdown_report_path).exists()
    assert Path(report.artifacts.artifact_index_path).exists()
    markdown = Path(report.artifacts.markdown_report_path).read_text(encoding="utf-8")
    assert "Verdict: `ready`" in markdown
    assert "| `G00` | `pass` |" in markdown
    assert report.artifacts.trace_path in markdown
    assert report.artifacts.replay_path in markdown
    assert report.artifacts.signoff_path in markdown
    assert report.artifacts.handoff_path in markdown
    assert "This run is ready because" in markdown
    assert "## Trace Validation" in markdown
    assert "Passed: `true`" in markdown
    assert "## Replay Resume" in markdown
    assert report.replay_resume.passed is True
    assert report.replay_resume.latest_stage == "handoff_ready"
    assert report.replay_resume.latest_checkpoint_ref == "checkpoints/latest.json"
    assert report.replay_resume.action_required == "PLAN_REVIEW"
    assert report.replay_resume.reconstructable is True


def test_agent1_evidence_report_missing_trace_fails(tmp_path: Path) -> None:
    run_dir = _run_agent1(tmp_path)
    (run_dir / "trace" / "events.jsonl").unlink()
    report = generate_agent1_evidence_report(run_dir)
    assert report.verdict == "not_ready"
    assert "trace_missing" in report.blockers
    assert "trace/events.jsonl" in report.missing_evidence


def test_agent1_evidence_report_missing_replay_fails(tmp_path: Path) -> None:
    run_dir = _run_agent1(tmp_path)
    (run_dir / "replay" / "replay_bundle.json").unlink()
    report = generate_agent1_evidence_report(run_dir)
    assert report.verdict == "not_ready"
    assert "replay_bundle_missing" in report.blockers


def test_agent1_evidence_report_failed_signoff_blocks_readiness(tmp_path: Path) -> None:
    run_dir = _run_agent1(
        tmp_path,
        requirement="Design an APB GPIO peripheral with 32-bit CSRs, interrupt status W1C, 100MHz clock, and NO_RESET_POLICY_MUTATION.",
        run_id="failed-signoff-report",
    )
    report = generate_agent1_evidence_report(run_dir)
    assert report.verdict == "not_ready"
    assert report.readiness_score < 100
    assert "signoff_certificate_failed" in report.blockers
    assert "signoff_gate_failed:G04" in report.blockers
    markdown = Path(report.artifacts.markdown_report_path).read_text(encoding="utf-8")
    assert "Verdict: `not_ready`" in markdown
    assert "signoff_gate_failed:G04" in markdown
    assert "This run is not ready because" in markdown


def test_agent1_evidence_report_ready_handoff_missing_certificate_is_rejected(tmp_path: Path) -> None:
    run_dir = _run_agent1(tmp_path)
    (run_dir / "reports" / "agent1" / "agent1_final_signoff_certificate.json").unlink()
    report = generate_agent1_evidence_report(run_dir)
    assert report.verdict == "not_ready"
    assert "signoff_certificate_missing" in report.blockers
    assert any(blocker.startswith("agent1_to_agent2_handoff_invalid:") for blocker in report.blockers)


def test_agent1_evidence_report_incomplete_gates_are_detected(tmp_path: Path) -> None:
    run_dir = _run_agent1(tmp_path)
    signoff_path = run_dir / "reports" / "agent1" / "agent1_final_signoff_certificate.json"
    signoff = json.loads(signoff_path.read_text(encoding="utf-8"))
    signoff["gate_results"].pop("G12")
    signoff_path.write_text(json.dumps(signoff), encoding="utf-8")
    handoff_path = run_dir / "contracts" / "agent1_to_agent2.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    handoff["signoff_gate_results"].pop("G12")
    handoff_path.write_text(json.dumps(handoff), encoding="utf-8")

    report = generate_agent1_evidence_report(run_dir)
    assert report.verdict == "not_ready"
    assert "signoff_gates_incomplete" in report.blockers
    assert any(blocker.startswith("agent1_to_agent2_handoff_invalid:") for blocker in report.blockers)


def test_agent1_evidence_report_missing_trace_required_field_fails(tmp_path: Path) -> None:
    run_dir = _run_agent1(tmp_path)
    trace_path = run_dir / "trace" / "events.jsonl"
    lines = trace_path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first.pop("span_id")
    lines[0] = json.dumps(first)
    trace_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = generate_agent1_evidence_report(run_dir)
    assert report.verdict == "not_ready"
    assert "trace_missing_required_field:span_id" in report.blockers


def test_agent1_evidence_report_trace_replay_count_mismatch_fails(tmp_path: Path) -> None:
    run_dir = _run_agent1(tmp_path)
    replay_path = run_dir / "replay" / "replay_bundle.json"
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    replay["events"] = replay["events"][:-1]
    replay_path.write_text(json.dumps(replay), encoding="utf-8")

    report = generate_agent1_evidence_report(run_dir)

    assert report.verdict == "not_ready"
    assert report.trace_validation.passed is False
    assert "trace_replay_event_count_mismatch" in report.trace_validation.errors
    assert "trace_validation:trace_replay_event_count_mismatch" in report.blockers


def test_agent1_evidence_report_duplicate_span_fails(tmp_path: Path) -> None:
    run_dir = _run_agent1(tmp_path)
    trace_path = run_dir / "trace" / "events.jsonl"
    lines = trace_path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    second["span_id"] = first["span_id"]
    lines[1] = json.dumps(second)
    trace_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = generate_agent1_evidence_report(run_dir)

    assert report.verdict == "not_ready"
    assert any(error.startswith("duplicate_span_id:") for error in report.trace_validation.errors)
    assert any(blocker.startswith("trace_validation:duplicate_span_id:") for blocker in report.blockers)


def test_agent1_evidence_report_handoff_ready_without_g12_trace_fails(tmp_path: Path) -> None:
    run_dir = _run_agent1(tmp_path)
    trace_path = run_dir / "trace" / "events.jsonl"
    lines = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        payload = event.get("payload")
        if (
            event.get("event_type") == "agent1_signoff_gate_done"
            and isinstance(payload, dict)
            and payload.get("gate_id") == "G12"
        ):
            payload["status"] = "fail"
        lines.append(json.dumps(event))
    trace_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    replay_path = run_dir / "replay" / "replay_bundle.json"
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    replay["events"] = [json.loads(line) for line in lines]
    replay_path.write_text(json.dumps(replay), encoding="utf-8")

    report = generate_agent1_evidence_report(run_dir)

    assert report.verdict == "not_ready"
    assert "handoff_ready_without_g12_pass" in report.trace_validation.errors
    assert "trace_validation:handoff_ready_without_g12_pass" in report.blockers


def test_agent1_evidence_report_resume_mismatch_blocks_ready(tmp_path: Path) -> None:
    run_dir = _run_agent1(tmp_path)
    replay_path = run_dir / "replay" / "replay_bundle.json"
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    replay["resume"]["latest_stage"] = "stale_stage"
    replay_path.write_text(json.dumps(replay), encoding="utf-8")

    report = generate_agent1_evidence_report(run_dir)

    assert report.verdict == "not_ready"
    assert report.replay_resume.passed is False
    assert "replay_resume_mismatch:latest_stage" in report.replay_resume.errors
    assert "replay_resume:replay_resume_mismatch:latest_stage" in report.blockers


def test_agent1_evidence_report_missing_artifact_ref_fails(tmp_path: Path) -> None:
    run_dir = _run_agent1(tmp_path)
    (run_dir / "reports" / "architecture_plan.md").unlink()
    report = generate_agent1_evidence_report(run_dir)
    assert report.verdict == "not_ready"
    assert any(blocker.startswith("artifact_ref_missing:") for blocker in report.blockers)
    assert any(blocker.startswith("agent1_to_agent2_handoff_invalid:") for blocker in report.blockers)


def test_agent1_evidence_report_cli_prints_json_and_markdown_paths(tmp_path: Path) -> None:
    run_dir = _run_agent1(tmp_path)
    completed = subprocess.run(
        [sys.executable, "scripts/generate_agent1_evidence_report.py", "--run-dir", str(run_dir)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    lines = completed.stdout.splitlines()
    assert lines[0] == "ready"
    assert lines[1].endswith("artifacts/agent1_evidence_report.json")
    assert lines[2].endswith("artifacts/agent1_evidence_report.md")
