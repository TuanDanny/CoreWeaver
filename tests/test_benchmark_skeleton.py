import asyncio
import json
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from scripts import run_benchmarks
from scripts.run_benchmarks import _benchmark_evidence_policy, _benchmark_gate_passed, _run_case


ROOT = Path(__file__).resolve().parents[1]


def test_benchmark_runner_cases_pass(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_benchmarks.py",
            "--cases",
            "benchmarks/cases",
            "--results",
            str(tmp_path / "benchmark-results"),
            "--json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    report = json.loads(completed.stdout)
    assert report["passed"] is True
    assert report["case_count"] >= 10
    assert report["message"] == "benchmark cases executed"
    first_result = report["results"][0]
    assert first_result["evidence_markdown_report"].endswith("artifacts/agent1_evidence_report.md")
    assert first_result["evidence_policy_passed"] is True
    assert first_result["evidence_policy_errors"] == []
    assert report["evidence_gate_passed"] is True


def test_benchmark_overall_fails_on_any_evidence_policy_failure() -> None:
    results = [
        {"passed": True, "evidence_policy_passed": True},
        {"passed": True, "evidence_policy_passed": True},
        {"passed": False, "evidence_policy_passed": False},
        {"passed": True, "evidence_policy_passed": True},
        {"passed": True, "evidence_policy_passed": True},
        {"passed": True, "evidence_policy_passed": True},
        {"passed": True, "evidence_policy_passed": True},
        {"passed": True, "evidence_policy_passed": True},
        {"passed": True, "evidence_policy_passed": True},
        {"passed": True, "evidence_policy_passed": True},
    ]

    pass_rate = sum(1 for result in results if bool(result["passed"])) / len(results)
    evidence_gate_passed = all(bool(result["evidence_policy_passed"]) for result in results)

    assert pass_rate == 0.9
    assert evidence_gate_passed is False
    assert _benchmark_gate_passed(results, pass_rate) is False


def test_benchmark_case_status_uses_runtime_action_not_text_leak(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeEvent:
        def safe_dump(self) -> dict[str, object]:
            return {"payload": "PLAN_REVIEW leaked into trace text"}

    class FakeSession:
        def __init__(self, state: object) -> None:
            self.event_stream = SimpleNamespace(history=[FakeEvent()])

        async def start(self) -> SimpleNamespace:
            return SimpleNamespace(action_required="NON_DESIGN_CONVERSATION")

    def fake_report(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            verdict="not_ready",
            readiness_score=0,
            debug_completeness_score=100,
            artifacts=SimpleNamespace(report_path="", markdown_report_path=""),
        )

    monkeypatch.setattr(run_benchmarks, "RuntimeSession", FakeSession)
    monkeypatch.setattr(run_benchmarks, "generate_agent1_evidence_report", fake_report)

    result = asyncio.run(
        _run_case(
            {
                "case_id": "status_leak",
                "requirement": "demo",
                "expected_status": "PLAN_REVIEW",
            },
            tmp_path,
        )
    )

    assert result["status_ok"] is False
    assert result["passed"] is False


def test_benchmark_case_cleans_stale_output_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stale_plan = tmp_path / "stale_case" / "reports" / "architecture_plan.md"
    stale_plan.parent.mkdir(parents=True)
    stale_plan.write_text("stale PLAN_REVIEW artifact", encoding="utf-8")

    class FakeSession:
        def __init__(self, state: object) -> None:
            self.event_stream = SimpleNamespace(history=[])

        async def start(self) -> SimpleNamespace:
            return SimpleNamespace(action_required="NON_DESIGN_CONVERSATION")

    def fake_report(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            verdict="not_ready",
            readiness_score=0,
            debug_completeness_score=100,
            artifacts=SimpleNamespace(report_path="", markdown_report_path=""),
        )

    monkeypatch.setattr(run_benchmarks, "RuntimeSession", FakeSession)
    monkeypatch.setattr(run_benchmarks, "generate_agent1_evidence_report", fake_report)

    result = asyncio.run(
        _run_case(
            {
                "case_id": "stale_case",
                "requirement": "demo",
                "expected_status": "NON_DESIGN_CONVERSATION",
            },
            tmp_path,
        )
    )

    assert result["artifact"] == ""
    assert not stale_plan.exists()


def test_benchmark_evidence_policy_requires_ready_evidence_for_plan_review() -> None:
    result = _benchmark_evidence_policy(
        expected_status="PLAN_REVIEW",
        evidence_verdict="not_ready",
        readiness_score=100,
        debug_completeness_score=100,
    )

    assert result["passed"] is False
    assert "evidence_verdict:not_ready" in result["errors"]


def test_benchmark_evidence_policy_rejects_ready_evidence_for_blocked_case() -> None:
    result = _benchmark_evidence_policy(
        expected_status="HITL_REQUIRED",
        evidence_verdict="ready",
        readiness_score=100,
        debug_completeness_score=100,
    )

    assert result["passed"] is False
    assert "non_ready_case_evidence_verdict:ready" in result["errors"]
    assert "non_ready_case_readiness_score:100" in result["errors"]


def test_benchmark_evidence_policy_requires_complete_debug_evidence() -> None:
    result = _benchmark_evidence_policy(
        expected_status="PLAN_REVIEW",
        evidence_verdict="ready",
        readiness_score=100,
        debug_completeness_score=83,
    )

    assert result["passed"] is False
    assert "debug_completeness_score:83" in result["errors"]
