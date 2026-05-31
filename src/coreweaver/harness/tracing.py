from __future__ import annotations

import json
from pathlib import Path

from .models import DebugIssue, TraceEvent
from .secret_scan import scan_text_for_secrets


class TraceRecorder:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
        self.issues: list[DebugIssue] = []

    def record_event(self, event: TraceEvent) -> None:
        payload_text = json.dumps(event.payload, sort_keys=True)
        if scan_text_for_secrets(payload_text):
            raise ValueError("trace payload contains a possible secret")
        self.events.append(event)

    def record_issue(self, issue: DebugIssue) -> None:
        details_text = json.dumps(issue.details, sort_keys=True)
        if scan_text_for_secrets(details_text) or scan_text_for_secrets(issue.message):
            raise ValueError("debug issue contains a possible secret")
        self.issues.append(issue)

    def write_jsonl(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for event in self.events:
                handle.write(json.dumps({"type": "event", **event.to_dict()}, sort_keys=True) + "\n")
            for issue in self.issues:
                handle.write(json.dumps({"type": "issue", **issue.to_dict()}, sort_keys=True) + "\n")
