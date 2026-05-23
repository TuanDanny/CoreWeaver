from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import swarm_foreman


def write_plan(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_plan_file_path_fails_without_auto_detect(capsys: pytest.CaptureFixture[str]) -> None:
    code = swarm_foreman.main(["done"])

    captured = capsys.readouterr()
    assert code == 2
    assert "requires exactly 2 arguments" in captured.err
    assert "FOREMAN DIRECTIVE" in captured.out
    assert "<missing plan_file_path>" in captured.out


def test_run_pytest_uses_exact_smart_command_and_last_50_lines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = []
    stdout = "\n".join(f"out-{index}" for index in range(10))
    stderr = "\n".join(f"err-{index}" for index in range(60))

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], 7, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(swarm_foreman, "ROOT", tmp_path)
    monkeypatch.setattr(swarm_foreman.subprocess, "run", fake_run)

    result = swarm_foreman.run_pytest()

    assert calls[0][0][0] == ["pytest", "-q", "--tb=short", "--disable-warnings"]
    assert calls[0][1]["cwd"] == tmp_path
    assert calls[0][1]["capture_output"] is True
    assert calls[0][1]["text"] is True
    assert calls[0][1]["check"] is False
    assert result.exit_code == 7
    assert len(result.output_tail.splitlines()) == 50
    assert "err-10" in result.output_tail
    assert "err-9" not in result.output_tail


def test_extract_json_handles_markdown_fence() -> None:
    parsed = swarm_foreman.extract_json(
        'noise\n```json\n{"phase_passed": true, "tasks_to_tick": ["A"]}\n```\n'
    )

    assert parsed["phase_passed"] is True
    assert parsed["tasks_to_tick"] == ["A"]


def test_ticks_only_matching_task_inside_active_phase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(swarm_foreman, "ROOT", tmp_path)
    plan = write_plan(
        tmp_path / "docs" / "exec-plans" / "active" / "plan.md",
        """# Plan

## Phase 1
- [ ] Same task
- [ ] Phase one only

## Phase 2
- [ ] Same task
""",
    )
    monkeypatch.setattr(
        swarm_foreman,
        "run_pytest",
        lambda: swarm_foreman.PytestResult(exit_code=0, output_tail="passed"),
    )
    monkeypatch.setattr(
        swarm_foreman,
        "grade_with_llm",
        lambda *args, **kwargs: {
            "score": 100,
            "phase_passed": True,
            "tasks_to_tick": ["Same task"],
            "feedback_to_worker": "Continue.",
        },
    )

    code = swarm_foreman.main(["done", str(plan)])

    assert code == 0
    assert plan.read_text(encoding="utf-8") == """# Plan

## Phase 1
- [x] Same task
- [ ] Phase one only

## Phase 2
- [ ] Same task
"""


def test_no_phase_heading_fails_closed_without_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(swarm_foreman, "ROOT", tmp_path)
    plan = write_plan(
        tmp_path / "docs" / "exec-plans" / "active" / "plan.md",
        """# Plan

## Milestone 1
- [ ] Task
""",
    )
    original = plan.read_text(encoding="utf-8")

    code = swarm_foreman.main(["done", str(plan)])

    captured = capsys.readouterr()
    assert code == 1
    assert "No active Phase heading" in captured.out
    assert plan.read_text(encoding="utf-8") == original


def test_failed_pytest_does_not_tick_and_prints_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(swarm_foreman, "ROOT", tmp_path)
    plan = write_plan(
        tmp_path / "docs" / "exec-plans" / "active" / "plan.md",
        """# Plan

## Phase 1
- [ ] Task
""",
    )
    monkeypatch.setattr(
        swarm_foreman,
        "run_pytest",
        lambda: swarm_foreman.PytestResult(exit_code=1, output_tail="traceback"),
    )
    monkeypatch.setattr(
        swarm_foreman,
        "grade_with_llm",
        lambda *args, **kwargs: {
            "score": 30,
            "phase_passed": False,
            "tasks_to_tick": ["Task"],
            "feedback_to_worker": "Fix tests.",
        },
    )

    code = swarm_foreman.main(["done", str(plan)])

    captured = capsys.readouterr()
    assert code == 1
    assert "[TIẾN ĐỘ PHASE]: Fail" in captured.out
    assert "Pytest failed" in captured.out
    assert "- [ ] Task" in plan.read_text(encoding="utf-8")


def test_llm_parse_failure_does_not_tick_and_prints_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(swarm_foreman, "ROOT", tmp_path)
    plan = write_plan(
        tmp_path / "docs" / "exec-plans" / "active" / "plan.md",
        """# Plan

## Phase 1
- [ ] Task
""",
    )
    monkeypatch.setattr(
        swarm_foreman,
        "run_pytest",
        lambda: swarm_foreman.PytestResult(exit_code=0, output_tail="passed"),
    )

    def bad_grade(*args, **kwargs):
        raise swarm_foreman.ForemanLLMError("bad json")

    monkeypatch.setattr(swarm_foreman, "grade_with_llm", bad_grade)

    code = swarm_foreman.main(["done", str(plan)])

    captured = capsys.readouterr()
    assert code == 1
    assert "LLM grading failed" in captured.out
    assert "- [ ] Task" in plan.read_text(encoding="utf-8")


def test_resolve_relative_plan_path_stays_under_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(swarm_foreman, "ROOT", tmp_path)
    plan = write_plan(tmp_path / "docs" / "exec-plans" / "active" / "plan.md", "# Plan\n")

    assert swarm_foreman.resolve_plan_path("docs/exec-plans/active/plan.md") == plan.resolve()

    with pytest.raises(swarm_foreman.ForemanConfigError):
        swarm_foreman.resolve_plan_path("../outside.md")
