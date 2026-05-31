"""Diff two Studio trace bundles without exposing secrets."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from semiconductor_swarm.tracing import read_trace_events, stable_hash
except ModuleNotFoundError:
    def read_trace_events(output_dir: str | Path) -> list[dict[str, Any]]:
        trace_root = Path(output_dir) / "reports" / "traces"
        events: list[dict[str, Any]] = []
        for trace_file in sorted(trace_root.glob("*.jsonl")):
            for line in trace_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    events.append({**item, "source_trace_file": trace_file.name})
        return events

    def stable_hash(value: Any) -> str:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

DIFF_SCHEMA_VERSION = "studio.trace_diff_report.v1"


def _node_signature(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for event in events:
        key = f"{event.get('node_id')}::{event.get('event_type')}"
        result[key] = {
            "status": event.get("status"),
            "hash": stable_hash({key: value for key, value in event.items() if key not in {"trace_id", "ended_at", "started_at", "latency_ms"}}),
            "trace_file": event.get("source_trace_file"),
        }
    return result


def diff_traces(left_output_dir: str | Path, right_output_dir: str | Path, report_output_dir: str | Path | None = None) -> dict[str, object]:
    left = _node_signature(read_trace_events(left_output_dir))
    right = _node_signature(read_trace_events(right_output_dir))
    left_keys = set(left)
    right_keys = set(right)
    changed = sorted(key for key in left_keys & right_keys if left[key]["hash"] != right[key]["hash"])
    report = {
        "schema_version": DIFF_SCHEMA_VERSION,
        "left": str(left_output_dir),
        "right": str(right_output_dir),
        "added": sorted(right_keys - left_keys),
        "removed": sorted(left_keys - right_keys),
        "changed": changed,
        "pass": not changed and left_keys == right_keys,
    }
    output_base = Path(report_output_dir or right_output_dir) / "reports" / "traces"
    output_base.mkdir(parents=True, exist_ok=True)
    (output_base / "diff_report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diff two Studio trace bundles.")
    parser.add_argument("left_output_dir")
    parser.add_argument("right_output_dir")
    parser.add_argument("--report-output-dir", default="")
    args = parser.parse_args(argv)
    report = diff_traces(args.left_output_dir, args.right_output_dir, args.report_output_dir or None)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
