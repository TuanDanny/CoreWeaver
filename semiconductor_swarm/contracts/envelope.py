"""Common contract envelope model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class ContractEnvelope:
    """Transport wrapper for versioned contract payloads."""

    contract_version: str
    payload: dict[str, Any]
    producer: str
    consumer: str | None = None
    run_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    envelope_id: str = field(default_factory=lambda: uuid4().hex)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "payload": self.payload,
            "producer": self.producer,
            "consumer": self.consumer,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "envelope_id": self.envelope_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContractEnvelope":
        return cls(
            contract_version=data["contract_version"],
            payload=data["payload"],
            producer=data["producer"],
            consumer=data.get("consumer"),
            run_id=data.get("run_id"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            envelope_id=data.get("envelope_id", uuid4().hex),
        )