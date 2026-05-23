from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


class ForemanConfigError(RuntimeError):
    pass


class ForemanLLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class PytestResult:
    exit_code: int
    output_tail: str


def tail_lines(text: str, limit: int = 50) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-limit:])


def run_pytest() -> PytestResult:
    command = ["pytest", "-q", "--tb=short", "--disable-warnings"]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
    return PytestResult(exit_code=completed.returncode, output_tail=tail_lines(combined, 50))


def extract_json(text: str) -> dict[str, Any]:
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    payload = fence.group(1) if fence else text[text.find("{") : text.rfind("}") + 1]
    if not payload:
        raise ForemanLLMError("missing json")
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ForemanLLMError(str(exc)) from exc
    if not isinstance(parsed, dict):
        raise ForemanLLMError("json root must be object")
    return parsed


def grade_with_llm(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise ForemanLLMError("LLM grader not configured")


def resolve_plan_path(plan_file_path: str) -> Path:
    raw = Path(plan_file_path)
    path = raw if raw.is_absolute() else ROOT / raw
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ForemanConfigError("plan path escapes repository root") from exc
    if not resolved.exists():
        raise ForemanConfigError(f"plan file not found: {resolved}")
    return resolved


def find_active_phase(lines: list[str]) -> tuple[int, int]:
    start = -1
    for index, line in enumerate(lines):
        if re.match(r"^##\s+Phase\s+\d+\b", line):
            start = index
            break
    if start < 0:
        raise ForemanConfigError("No active Phase heading")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return start, end


def tick_tasks_in_active_phase(plan_text: str, tasks_to_tick: list[str]) -> str:
    lines = plan_text.splitlines(keepends=True)
    _start, end = find_active_phase([line.rstrip("\n") for line in lines])
    start = _start + 1
    wanted = set(tasks_to_tick)
    for index in range(start, end):
        line = lines[index]
        match = re.match(r"^(\s*- \[ \] )(.*?)(\r?\n)?$", line)
        if match and match.group(2).strip() in wanted:
            lines[index] = f"{match.group(1).replace('[ ]', '[x]')}{match.group(2)}{match.group(3) or ''}"
    return "".join(lines)


def print_directive(plan_file_path: str) -> None:
    print("FOREMAN DIRECTIVE")
    print(f"plan_file_path: {plan_file_path}")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] != "done":
        print_directive(args[1] if len(args) > 1 else "<missing plan_file_path>")
        print("done requires exactly 2 arguments", file=sys.stderr)
        return 2

    try:
        plan_path = resolve_plan_path(args[1])
        original = plan_path.read_text(encoding="utf-8")
        find_active_phase(original.splitlines())
    except ForemanConfigError as exc:
        print(f"[TIẾN ĐỘ PHASE]: Fail")
        print(str(exc))
        return 1

    pytest_result = run_pytest()
    try:
        grade = grade_with_llm(plan_text=original, pytest_result=pytest_result)
    except ForemanLLMError as exc:
        print("[TIẾN ĐỘ PHASE]: Fail")
        print(f"LLM grading failed: {exc}")
        return 1

    if pytest_result.exit_code != 0:
        print("[TIẾN ĐỘ PHASE]: Fail")
        print("Pytest failed")
        print(pytest_result.output_tail)
        return 1

    if not bool(grade.get("phase_passed")):
        print("[TIẾN ĐỘ PHASE]: Fail")
        print(str(grade.get("feedback_to_worker", "Phase not passed")))
        return 1

    tasks = [str(task) for task in grade.get("tasks_to_tick", [])]
    updated = tick_tasks_in_active_phase(original, tasks)
    plan_path.write_text(updated, encoding="utf-8")
    print("[TIẾN ĐỘ PHASE]: Pass")
    print(str(grade.get("feedback_to_worker", "Continue.")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())