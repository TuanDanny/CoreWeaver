"""Shared trace helpers for Studio and Agent flows.

The trace layer is intentionally small and file-backed. It can be used from the
FastAPI process, the subprocess runner, or Agent 1 without importing Studio UI
code. Secrets are redacted before every append.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

TRACE_SCHEMA_VERSION = "swarm.trace_event.v1"
TRACE_MANIFEST_VERSION = "swarm.trace_manifest.v1"
TRACE_HEALTH_VERSION = "swarm.trace_health.v1"
TRACE_INVARIANT_VERSION = "swarm.trace_invariant.v1"
AGENT1_BUDGET_VERSION = "agent1.budget_report.v1"

TRACE_FILES = {
    "studio_flow": "studio_flow_trace.jsonl",
    "runner_process": "runner_process_trace.jsonl",
    "agent1_intake": "agent1_intake_trace.jsonl",
    "agent1_llm": "agent1_llm_trace.jsonl",
    "agent1_canonical": "agent1_canonical_trace.jsonl",
    "agent1_defaults": "agent1_defaults_trace.jsonl",
    "agent1_council": "agent1_council_trace.jsonl",
    "agent1_guardrail": "agent1_guardrail_trace.jsonl",
    "agent1_final_decision": "agent1_final_decision_trace.jsonl",
    "agent1_state_snapshots": "agent1_state_snapshots.jsonl",
    "agent1_artifact_lineage": "agent1_artifact_lineage.jsonl",
    "agent1_completion": "agent1_completion_trace.jsonl",
}

REQUIRED_AGENT1_CORE_NODES = (
    "APP.SWARM_RUNNER_START",
    "GRAPH.AGENT1_ENTER",
    "AGENT1.FAST_ROUTER",
    "AGENT1.INTAKE_COUNCIL",
    "AGENT1.CANONICAL_NORMALIZE",
    "AGENT1.DEFAULTS_APPLY",
    "AGENT1.READY_GATE",
    "AGENT1.HANDOFF_OR_PAUSE",
)

FAILURE_TAXONOMY = {
    "credential": "Credential or provider auth failure.",
    "schema": "LLM JSON/schema validation failure.",
    "canonicalization": "Evidence could not be normalized into canonical intent.",
    "ready_gate": "Requirement failed Agent 1 ready gate.",
    "council": "Agent 1 deep council conflict or unavailable node.",
    "runtime": "Runner/backend runtime failure.",
}

SECRET_KEY_RE = re.compile(r"(api[_-]?key|authorization|bearer|token|access[_-]?token|secret|password)", re.I)
BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.I)
OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")
LONG_SECRETISH_RE = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")

_thread_local = threading.local()
_context_lock = threading.Lock()
_append_lock = threading.Lock()


@dataclass(frozen=True)
class TraceContext:
    run_id: str = ""
    thread_id: str = ""
    flow_id: str = ""
    output_dir: str = ""
    project_name: str = ""

_global_context = TraceContext()


def set_trace_context(
    *,
    run_id: str = "",
    thread_id: str = "",
    flow_id: str = "",
    output_dir: str | Path = "",
    project_name: str = "",
) -> TraceContext:
    context = TraceContext(
        run_id=str(run_id or ""),
        thread_id=str(thread_id or ""),
        flow_id=str(flow_id or run_id or thread_id or "studio_flow"),
        output_dir=str(output_dir or ""),
        project_name=str(project_name or ""),
    )
    _thread_local.context = context
    global _global_context
    with _context_lock:
        _global_context = context
    return context


def clear_trace_context() -> None:
    _thread_local.context = TraceContext()
    global _global_context
    with _context_lock:
        _global_context = TraceContext()


def current_trace_context() -> TraceContext:
    context = getattr(_thread_local, "context", None)
    if isinstance(context, TraceContext) and context.output_dir:
        return context
    with _context_lock:
        return _global_context


def trace_root(output_dir: str | Path | None = None) -> Path | None:
    raw = str(output_dir or current_trace_context().output_dir or "")
    if not raw:
        return None
    return Path(raw) / "reports" / "traces"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def stable_hash(value: Any) -> str:
    return sha256_text(json.dumps(redact(value), sort_keys=True, ensure_ascii=False, default=str))


def redacted_preview(value: Any, limit: int = 600) -> str:
    text = json.dumps(redact(value), sort_keys=True, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 20)] + "...[truncated]"


def redact(value: Any) -> Any:
    redacted, _changed = _redact_value(value, "")
    return redacted


def _redact_value(value: Any, key_path: str) -> tuple[Any, bool]:
    changed = False
    key_leaf = key_path.rsplit(".", 1)[-1]
    if SECRET_KEY_RE.search(key_leaf):
        return "<redacted>", True
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            clean, did = _redact_value(child, f"{key_path}.{key}" if key_path else str(key))
            result[str(key)] = clean
            changed = changed or did
        return result, changed
    if isinstance(value, list):
        result_list = []
        for index, child in enumerate(value):
            clean, did = _redact_value(child, f"{key_path}[{index}]")
            result_list.append(clean)
            changed = changed or did
        return result_list, changed
    if isinstance(value, str):
        clean = BEARER_RE.sub("Bearer <redacted>", value)
        clean = OPENAI_KEY_RE.sub("<redacted>", clean)
        if SECRET_KEY_RE.search(key_path) and value:
            clean = "<redacted>"
        if clean != value:
            changed = True
        return clean, changed
    return value, changed


def secret_leaks(value: Any) -> list[str]:
    text = json.dumps(value, ensure_ascii=False, default=str)
    leaks = []
    if BEARER_RE.search(text):
        leaks.append("bearer_token")
    if OPENAI_KEY_RE.search(text):
        leaks.append("openai_key")
    for match in LONG_SECRETISH_RE.finditer(text):
        token = match.group(0)
        if any(prefix in token.lower() for prefix in ("secret", "token", "key")):
            leaks.append("secretish_token")
            break
    return sorted(set(leaks))


def make_trace_event(
    *,
    phase: str,
    agent: str,
    node_id: str,
    event_type: str,
    status: str = "info",
    parent_node_id: str | None = None,
    flow_id: str | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
    latency_ms: int | float | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = current_trace_context()
    clean_payload, changed = _redact_value(payload or {}, "payload")
    event = {
        "schema_version": TRACE_SCHEMA_VERSION,
        "trace_id": str(uuid.uuid4()),
        "run_id": context.run_id,
        "thread_id": context.thread_id,
        "flow_id": str(flow_id or context.flow_id or "studio_flow"),
        "phase": phase,
        "agent": agent,
        "node_id": node_id,
        "parent_node_id": parent_node_id,
        "event_type": event_type,
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at or now_iso(),
        "latency_ms": latency_ms,
        "redaction_applied": True,
    }
    event.update(clean_payload)
    if changed:
        event["redaction_changed_payload"] = True
    return event


def append_jsonl(path: str | Path, record: dict[str, Any]) -> None:
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    clean = redact(record)
    line = json.dumps(clean, sort_keys=True, ensure_ascii=False, default=str) + "\n"
    with _append_lock:
        with path_obj.open("a", encoding="utf-8") as handle:
            handle.write(line)


def trace_event(
    file_name: str,
    *,
    phase: str,
    agent: str,
    node_id: str,
    event_type: str,
    status: str = "info",
    parent_node_id: str | None = None,
    flow_id: str | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
    latency_ms: int | float | None = None,
    payload: dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
    emit_live: bool = True,
) -> dict[str, Any]:
    event = make_trace_event(
        phase=phase,
        agent=agent,
        node_id=node_id,
        parent_node_id=parent_node_id,
        event_type=event_type,
        status=status,
        flow_id=flow_id,
        started_at=started_at,
        ended_at=ended_at,
        latency_ms=latency_ms,
        payload=payload,
    )
    root = trace_root(output_dir)
    if root is not None:
        append_jsonl(root / file_name, event)
    if emit_live:
        try:
            from semiconductor_swarm.runtime_events import emit_runtime_event

            emit_runtime_event({"type": "trace_event", "trace_file": file_name, **event})
        except Exception:
            pass
    return event


def trace_snapshot(
    name: str,
    state: dict[str, Any],
    *,
    phase: str = "planning",
    agent: str = "agent1",
    node_id: str = "AGENT1.STATE_SNAPSHOT",
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    snapshot = {
        "snapshot_name": name,
        "state_hash": stable_hash(state),
        "state_preview": redacted_preview(state, 1000),
        "classification": state.get("classification") or state.get("intake_classification"),
        "ready_for_council": state.get("ready_for_council"),
        "current_stage": state.get("current_stage") or phase,
    }
    return trace_event(
        TRACE_FILES["agent1_state_snapshots"],
        phase=phase,
        agent=agent,
        node_id=node_id,
        event_type="state_snapshot",
        status="info",
        payload=snapshot,
        output_dir=output_dir,
    )


def trace_artifact_lineage(
    artifact_name: str,
    *,
    source_nodes: Iterable[str] = (),
    artifact_path: str = "",
    kind: str = "",
    phase: str = "planning",
    agent: str = "agent1",
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    return trace_event(
        TRACE_FILES["agent1_artifact_lineage"],
        phase=phase,
        agent=agent,
        node_id="AGENT1.ARTIFACT_WRITE",
        event_type="artifact_write",
        status="pass",
        payload={
            "artifact_name": artifact_name,
            "artifact_path": artifact_path,
            "artifact_kind": kind or Path(artifact_name).suffix.lstrip(".") or "text",
            "source_nodes": list(source_nodes),
        },
        output_dir=output_dir,
    )


def trace_completion(
    *,
    status: str,
    decision: str,
    decision_reason: str,
    blocking_reasons: list[Any] | None = None,
    artifact_refs: list[str] | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    return trace_event(
        TRACE_FILES["agent1_completion"],
        phase="planning",
        agent="agent1",
        node_id="AGENT1.HANDOFF_OR_PAUSE",
        event_type="completion",
        status=status,
        payload={
            "decision": decision,
            "decision_reason": decision_reason,
            "blocking_reasons": blocking_reasons or [],
            "artifact_refs": artifact_refs or [],
        },
        output_dir=output_dir,
    )


def read_trace_events(output_dir: str | Path) -> list[dict[str, Any]]:
    root = trace_root(output_dir)
    if root is None or not root.exists():
        return []
    events: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = {"schema_error": "invalid_jsonl", "source": str(path), "line": line[:200]}
            if isinstance(event, dict):
                event.setdefault("source_trace_file", path.name)
                events.append(event)
    return events


def write_trace_manifest(output_dir: str | Path) -> dict[str, Any]:
    root = trace_root(output_dir)
    manifest = {
        "schema_version": TRACE_MANIFEST_VERSION,
        "generated_at": now_iso(),
        "trace_dir": str(root or ""),
        "files": [],
    }
    if root and root.exists():
        for path in sorted(root.glob("*.jsonl")):
            line_count = sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
            manifest["files"].append({"name": path.name, "bytes": path.stat().st_size, "line_count": line_count})
    if root:
        (root / "trace_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def write_trace_health_report(output_dir: str | Path, required_nodes: Iterable[str] = REQUIRED_AGENT1_CORE_NODES) -> dict[str, Any]:
    events = read_trace_events(output_dir)
    nodes = {str(event.get("node_id")) for event in events if event.get("node_id")}
    required = list(required_nodes)
    missing = [node for node in required if node not in nodes]
    leak_events = [event.get("trace_id") or event.get("node_id") for event in events if secret_leaks(event)]
    score = 100.0
    if required:
        score -= len(missing) / len(required) * 70.0
    if leak_events:
        score -= 30.0
    report = {
        "schema_version": TRACE_HEALTH_VERSION,
        "generated_at": now_iso(),
        "pass": not missing and not leak_events,
        "score": round(max(0.0, score), 3),
        "max_score": 100,
        "required_nodes": required,
        "missing_nodes": missing,
        "event_count": len(events),
        "secret_leak_events": leak_events,
    }
    root = trace_root(output_dir)
    if root:
        root.mkdir(parents=True, exist_ok=True)
        (root / "trace_health_report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def write_trace_invariant_report(output_dir: str | Path) -> dict[str, Any]:
    events = read_trace_events(output_dir)
    failures = []
    seen_trace_ids: set[str] = set()
    for event in events:
        trace_id = str(event.get("trace_id") or "")
        if not trace_id:
            failures.append({"type": "missing_trace_id", "node_id": event.get("node_id")})
        elif trace_id in seen_trace_ids:
            failures.append({"type": "duplicate_trace_id", "trace_id": trace_id})
        seen_trace_ids.add(trace_id)
        for key in ("run_id", "flow_id", "phase", "agent", "node_id", "event_type", "status"):
            if key not in event:
                failures.append({"type": "missing_field", "field": key, "trace_id": trace_id})
    report = {
        "schema_version": TRACE_INVARIANT_VERSION,
        "generated_at": now_iso(),
        "pass": not failures,
        "failures": failures[:200],
        "failure_count": len(failures),
        "event_count": len(events),
    }
    root = trace_root(output_dir)
    if root:
        root.mkdir(parents=True, exist_ok=True)
        (root / "trace_invariant_report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def write_agent1_budget_report(output_dir: str | Path) -> dict[str, Any]:
    events = read_trace_events(output_dir)
    llm_events = [event for event in events if event.get("event_type") in {"llm_call", "llm_call_completed"} or event.get("node_id", "").startswith("A1.")]
    total_tokens = 0
    total_cost = 0.0
    latencies: list[float] = []
    for event in llm_events:
        metrics = event.get("metrics") if isinstance(event.get("metrics"), dict) else {}
        for key in ("total_tokens", "codex_total_tokens"):
            try:
                total_tokens += int(metrics.get(key) or 0)
            except (TypeError, ValueError):
                pass
        try:
            total_cost += float(metrics.get("estimated_cost_usd") or metrics.get("codex_estimated_cost_usd") or 0.0)
        except (TypeError, ValueError):
            pass
        if event.get("latency_ms") is not None:
            try:
                latencies.append(float(event["latency_ms"]))
            except (TypeError, ValueError):
                pass
    report = {
        "schema_version": AGENT1_BUDGET_VERSION,
        "generated_at": now_iso(),
        "codex_call_count": len(llm_events),
        "llm_event_count": len(llm_events),
        "total_tokens": total_tokens,
        "estimated_cost_usd": round(total_cost, 8),
        "latency_ms": {
            "max": round(max(latencies), 3) if latencies else 0,
            "avg": round(sum(latencies) / len(latencies), 3) if latencies else 0,
        },
    }
    root = trace_root(output_dir)
    if root:
        root.mkdir(parents=True, exist_ok=True)
        (root / "agent1_budget_report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def finalize_trace_reports(output_dir: str | Path) -> dict[str, Any]:
    return {
        "manifest": write_trace_manifest(output_dir),
        "health": write_trace_health_report(output_dir),
        "invariants": write_trace_invariant_report(output_dir),
        "budget": write_agent1_budget_report(output_dir),
    }
