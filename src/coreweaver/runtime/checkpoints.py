from __future__ import annotations

from typing import Any


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._completed: dict[str, Any] = {}

    def has_completed(self, idempotency_key: str) -> bool:
        return idempotency_key in self._completed

    def record_completed(self, idempotency_key: str, result: Any) -> None:
        self._completed[idempotency_key] = result

    def get_completed(self, idempotency_key: str) -> Any:
        return self._completed[idempotency_key]
