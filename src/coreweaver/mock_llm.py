from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MockLlmResponse:
    text: str
    call_id: str


class MockLlmClient:
    """Deterministic test double. No domain behavior is encoded here."""

    def __init__(self, response_text: str = "") -> None:
        self.response_text = response_text
        self.call_count = 0

    def complete(self, prompt: str) -> MockLlmResponse:
        self.call_count += 1
        return MockLlmResponse(text=self.response_text, call_id=f"mock-{self.call_count}")
