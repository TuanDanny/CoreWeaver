import json
import subprocess
import sys
from pathlib import Path

import pytest

from coreweaver.harness.eval_runner import KeywordTopicEvaluator
from coreweaver.harness.evals import BenchmarkCase
from coreweaver.harness.knowledge import KnowledgeInventory
from coreweaver.harness.observability import JsonlEventSink, MetricPoint


ROOT = Path(__file__).resolve().parents[1]


def test_knowledge_inventory_passes_current_repo() -> None:
    result = KnowledgeInventory(ROOT).check()
    assert result.passed, result


def test_jsonl_event_sink_rejects_secret(tmp_path: Path) -> None:
    sink = JsonlEventSink(tmp_path / "events.jsonl")
    with pytest.raises(ValueError):
        sink.emit("log", {"token": "sk-" + "A" * 24})


def test_jsonl_event_sink_writes_metric(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    sink = JsonlEventSink(path)
    sink.emit_metric(
        MetricPoint(
            name="latency_ms",
            value=12.5,
            run_id="run1",
            timestamp="2026-05-26T20:00:00Z",
            tags={"stage": "harness"},
        )
    )
    line = json.loads(path.read_text(encoding="utf-8").strip())
    assert line["record_type"] == "metric"
    assert line["payload"]["name"] == "latency_ms"


def test_keyword_topic_evaluator_is_deterministic() -> None:
    case = BenchmarkCase(
        case_id="secure_npu",
        requirement="secure npu",
        expected_topics=("AXI4", "AES-256", "write-only"),
    )
    result = KeywordTopicEvaluator().evaluate(
        case,
        "Plan includes AXI4 DMA and AES-256 key registers.",
    )
    assert not result.passed
    assert result.findings == ("missing topic: write-only",)


def test_harness_check_cli_passes() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/harness_check.py", "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["passed"] is True
