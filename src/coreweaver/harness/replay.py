from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .gates import GateResult
from .models import DebugIssue, TraceEvent


@dataclass(frozen=True)
class ReplayBundle:
    run_id: str
    events: tuple[TraceEvent, ...]
    issues: tuple[DebugIssue, ...]
    gate_results: tuple[GateResult, ...]
    manifest: dict[str, Any]

    def write(self, directory: str | Path) -> Path:
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{self.run_id}.replay.json"
        data = {
            "run_id": self.run_id,
            "events": [event.to_dict() for event in self.events],
            "issues": [issue.to_dict() for issue in self.issues],
            "gate_results": [asdict(result) for result in self.gate_results],
            "manifest": self.manifest,
        }
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        return path
