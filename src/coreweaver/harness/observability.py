from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import validate_id
from .secret_scan import scan_text_for_secrets


@dataclass(frozen=True)
class MetricPoint:
    name: str
    value: float
    run_id: str
    timestamp: str
    tags: dict[str, str]

    def __post_init__(self) -> None:
        validate_id(self.name, "metric name")
        validate_id(self.run_id, "run_id")


class JsonlEventSink:
    """Append-only JSONL sink for logs, spans, metrics, and debug artifacts."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, record_type: str, payload: dict[str, Any]) -> None:
        validate_id(record_type, "record_type")
        encoded = json.dumps(payload, sort_keys=True)
        if scan_text_for_secrets(encoded):
            raise ValueError("observability payload contains a possible secret")
        envelope = {
            "record_type": record_type,
            "emitted_at_unix_ms": int(time.time() * 1000),
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(envelope, sort_keys=True) + "\n")

    def emit_metric(self, point: MetricPoint) -> None:
        self.emit("metric", asdict(point))
