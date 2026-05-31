from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from coreweaver.runtime import RuntimeSession, RuntimeState
from coreweaver.agents.agent1.evidence_report import generate_agent1_evidence_report


async def _run_case(case: dict[str, object], output_root: Path) -> dict[str, object]:
    case_id = str(case["case_id"])
    requirement = str(case["requirement"])
    expected_status = str(case.get("expected_status") or "PLAN_REVIEW")
    expected_topics = tuple(str(item) for item in case.get("expected_topics", []))
    output_dir = output_root / case_id
    session = RuntimeSession(
        RuntimeState(
            run_id=f"bench-{case_id}",
            profile="mock_swarm",
            status="running",
            requirement=requirement,
            project_name=case_id,
            planning_mode="deep_planning",
            output_dir=str(output_dir),
        )
    )
    result = await session.start()
    event_payload = "\n".join(json.dumps(event.safe_dump(), sort_keys=True) for event in session.event_stream.history)
    plan_path = output_dir / "reports" / "architecture_plan.md"
    plan_text = plan_path.read_text(encoding="utf-8") if plan_path.exists() else ""
    combined = f"{event_payload}\n{plan_text}".lower()
    missing_topics = tuple(topic for topic in expected_topics if topic.lower() not in combined)
    status_ok = result.action_required == expected_status or expected_status.lower() in combined
    passed = status_ok and not missing_topics
    evidence_report = generate_agent1_evidence_report(output_dir, profile="mock_swarm", benchmark_case=case)
    return {
        "case_id": case_id,
        "passed": passed,
        "expected_status": expected_status,
        "status_ok": status_ok,
        "missing_topics": missing_topics,
        "artifact": str(plan_path).replace("\\", "/") if plan_path.exists() else "",
        "evidence_report": evidence_report.artifacts.report_path,
        "evidence_markdown_report": evidence_report.artifacts.markdown_report_path,
        "evidence_verdict": evidence_report.verdict,
        "debug_completeness_score": evidence_report.debug_completeness_score,
        "readiness_score": evidence_report.readiness_score,
    }


async def _run_all(cases: list[dict[str, object]], output_root: Path) -> list[dict[str, object]]:
    results = []
    for case in cases:
        results.append(await _run_case(case, output_root))
    return results


def _load_cases(cases_dir: Path) -> list[dict[str, object]]:
    cases = []
    schema_path = ROOT / "benchmarks" / "schemas" / "benchmark_case.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    for path in sorted(cases_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        _validate_case_schema(path, data, schema)
        cases.append(data)
    return cases


def _validate_case_schema(path: Path, data: dict[str, object], schema: dict[str, object]) -> None:
    required = tuple(str(item) for item in schema.get("required", ()))
    allowed = set((schema.get("properties") or {}).keys())
    for field in required:
        if field not in data:
            raise ValueError(f"{path} missing {field}")
    extra = sorted(set(data) - allowed)
    if extra:
        raise ValueError(f"{path} has unsupported fields: {', '.join(extra)}")
    if not isinstance(data.get("case_id"), str) or not data["case_id"]:
        raise ValueError(f"{path} case_id must be a non-empty string")
    if not isinstance(data.get("requirement"), str) or not data["requirement"]:
        raise ValueError(f"{path} requirement must be a non-empty string")
    for field in ("expected_topics", "mutation_tags"):
        if field in data and not _is_string_list(data[field]):
            raise ValueError(f"{path} {field} must be an array of strings")
    if "expected_status" in data and not isinstance(data["expected_status"], str):
        raise ValueError(f"{path} expected_status must be a string")


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="benchmarks/cases")
    parser.add_argument("--results", default="benchmarks/results")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cases_dir = Path(args.cases)
    output_root = Path(args.results)
    output_root.mkdir(parents=True, exist_ok=True)
    cases = _load_cases(cases_dir)
    if cases:
        results = asyncio.run(_run_all(cases, output_root))
        pass_rate = sum(1 for result in results if bool(result["passed"])) / len(results)
        passed = pass_rate >= 0.9
        message = "benchmark cases executed"
    else:
        results = []
        passed = True
        pass_rate = 1.0
        message = "benchmark framework ready"
    report = {
        "passed": passed,
        "case_count": len(cases),
        "message": message,
        "pass_rate": pass_rate,
        "cases": [case["case_id"] for case in cases],
        "results": results,
    }
    (output_root / "latest_report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{report['case_count']} cases")
        print(message)
        print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
