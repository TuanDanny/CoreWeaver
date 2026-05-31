import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_benchmark_runner_cases_pass() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/run_benchmarks.py", "--cases", "benchmarks/cases", "--json"],
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
