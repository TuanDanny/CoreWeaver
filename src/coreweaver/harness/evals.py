from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    requirement: str
    expected_topics: tuple[str, ...]
    mutation_tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.case_id or not self.requirement or not self.expected_topics:
            raise ValueError("benchmark case requires id, requirement, and expected topics")


@dataclass(frozen=True)
class BenchmarkResult:
    case_id: str
    passed: bool
    score: float
    findings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.score < 0.0 or self.score > 1.0:
            raise ValueError("score must be in [0, 1]")
