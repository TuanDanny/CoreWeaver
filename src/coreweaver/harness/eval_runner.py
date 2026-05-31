from __future__ import annotations

from dataclasses import dataclass

from .evals import BenchmarkCase, BenchmarkResult


@dataclass(frozen=True)
class KeywordTopicEvaluator:
    """Deterministic scaffold evaluator until LLM/domain judges are added."""

    minimum_score: float = 1.0

    def evaluate(self, case: BenchmarkCase, output_text: str) -> BenchmarkResult:
        normalized = output_text.lower()
        missing = tuple(
            topic for topic in case.expected_topics if topic.lower() not in normalized
        )
        covered = len(case.expected_topics) - len(missing)
        score = covered / len(case.expected_topics)
        return BenchmarkResult(
            case_id=case.case_id,
            passed=score >= self.minimum_score,
            score=score,
            findings=tuple(f"missing topic: {topic}" for topic in missing),
        )


def run_benchmark_case(case: BenchmarkCase, output_text: str) -> BenchmarkResult:
    return KeywordTopicEvaluator().evaluate(case, output_text)
