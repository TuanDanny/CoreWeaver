"""Structured runtime tracking artifacts for Studio runs."""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from studio.backend.config import DEFAULT_CREDENTIAL_REF, ROOT

RUNTIME_SCHEMA_VERSION = "studio.runtime_event.v1"
MANIFEST_SCHEMA_VERSION = "studio.runtime_session_manifest.v1"
TRACE_DIR = Path("reports") / "traces"
EVENTS_NAME = "runtime_events.jsonl"
MANIFEST_NAME = "runtime_session_manifest.json"
RECOVERY_NAME = "runtime_recovery_report.json"
INVARIANT_NAME = "runtime_invariant_report.json"
REPLAY_NAME = "runtime_replay_report.json"
DEBUG_SUMMARY_NAME = "runtime_debug_summary.json"
RUNTIME_INDEX_NAME = "runtime_index.json"

AGENTS = {"system", "agent1", "agent2", "agent3", "agent4", "agent5", "agent6", "studio", "runner", "console"}
PHASES = {"planning", "rtl", "formal", "hitl", "dv", "physical", "signoff", "studio", "backend", "runner"}
TERMINAL_EVENT_TYPES = {"job_done", "runtime_error", "watchdog_timeout", "runtime_recovered"}
PROGRESS_EVENT_TYPES = {"node_start", "node_done", "model_call_done", "artifact_written", "job_started", "job_done"}
STRICT_PAIR_KINDS = {"tool_call", "model_call"}
SECRET_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"Authorization\s*[:=]\s*[A-Za-z0-9._\- ]+", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _parse_runtime_timestamp(value: Any) -> datetime | None:
    try:
        timestamp = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def runtime_trace_dir(output_dir: str | Path) -> Path:
    return Path(output_dir) / TRACE_DIR


def runtime_file(output_dir: str | Path, name: str) -> Path:
    return runtime_trace_dir(output_dir) / name

def runtime_index_file(root: Path = ROOT) -> Path:
    return root / ".swarm" / RUNTIME_INDEX_NAME


def redact_runtime_payload(value: Any) -> Any:
    clean = _redact_sensitive_keys(value)
    return _redact_secret_patterns(clean)


def _redact_sensitive_keys(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered in {"api_key", "authorization", "token", "access_token"} or (("secret" in lowered) and lowered not in {"secret_scan", "secretscan"}):
                clean[str(key)] = "<redacted>"
            else:
                clean[str(key)] = _redact_sensitive_keys(child)
        return clean
    if isinstance(value, list):
        return [_redact_sensitive_keys(item) for item in value]
    return value


def _redact_secret_patterns(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_secret_patterns(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_redact_secret_patterns(item) for item in value]
    if isinstance(value, str):
        text = value
        for pattern in SECRET_PATTERNS:
            text = pattern.sub("<redacted>", text)
        return text
    return value


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(redact_runtime_payload(payload), indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def read_runtime_events(output_dir: str | Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    path = runtime_file(output_dir, EVENTS_NAME)
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events[-limit:] if limit else events


def load_runtime_bundle(output_dir: str | Path, *, recent_limit: int = 400) -> dict[str, Any]:
    trace_dir = runtime_trace_dir(output_dir)
    manifest = _safe_read_json(trace_dir / MANIFEST_NAME)
    return {
        "manifest": manifest.get("payload"),
        "recentEvents": read_runtime_events(output_dir, limit=recent_limit),
        "recoveryReport": _safe_read_json(trace_dir / RECOVERY_NAME).get("payload"),
        "invariantReport": _safe_read_json(trace_dir / INVARIANT_NAME).get("payload"),
        "replayReport": _safe_read_json(trace_dir / REPLAY_NAME).get("payload"),
        "debugSummary": _safe_read_json(trace_dir / DEBUG_SUMMARY_NAME).get("payload"),
        "errors": [item for item in (
            manifest.get("error"),
            _safe_read_json(trace_dir / RECOVERY_NAME).get("error"),
            _safe_read_json(trace_dir / INVARIANT_NAME).get("error"),
            _safe_read_json(trace_dir / REPLAY_NAME).get("error"),
            _safe_read_json(trace_dir / DEBUG_SUMMARY_NAME).get("error"),
        ) if item],
    }


def _safe_read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"payload": None}
    try:
        return {"payload": _read_json(path)}
    except (OSError, json.JSONDecodeError) as exc:
        return {"payload": None, "error": f"{path.name}: {exc}"}


def _read_runtime_index(root: Path = ROOT) -> dict[str, Any]:
    path = runtime_index_file(root)
    try:
        payload = _read_json(path)
    except (OSError, json.JSONDecodeError):
        return {"schema_version": "studio.runtime_index.v1", "runs": {}}
    if not isinstance(payload.get("runs"), dict):
        payload["runs"] = {}
    return payload

def _write_runtime_index(root: Path, manifest: dict[str, Any]) -> None:
    run_id = str(manifest.get("run_id") or "")
    output_dir = str(manifest.get("output_dir") or "")
    if not run_id or not output_dir:
        return
    index = _read_runtime_index(root)
    runs = index.setdefault("runs", {})
    runs[run_id] = {
        "run_id": run_id,
        "job_id": str(manifest.get("job_id") or ""),
        "project_name": str(manifest.get("project_name") or ""),
        "output_dir": output_dir,
        "status": str(manifest.get("status") or ""),
        "updated_at": str(manifest.get("last_runtime_event_at") or utc_now_iso()),
        "manifest_path": str(runtime_file(output_dir, MANIFEST_NAME)),
    }
    index.update({"schema_version": "studio.runtime_index.v1", "latest_run_id": run_id, "updated_at": utc_now_iso()})
    _write_json_atomic(runtime_index_file(root), index)

def _indexed_runtime_output_dir(run_id: str, *, root: Path = ROOT) -> Path | None:
    item = (_read_runtime_index(root).get("runs") or {}).get(run_id)
    if not isinstance(item, dict):
        return None
    output_text = str(item.get("output_dir") or "")
    if not output_text:
        return None
    output_dir = Path(output_text)
    try:
        manifest = _read_json(runtime_file(output_dir, MANIFEST_NAME))
    except (OSError, json.JSONDecodeError):
        return output_dir if runtime_file(output_dir, MANIFEST_NAME).exists() else None
    return output_dir if str(manifest.get("run_id") or "") == run_id else None

def _runtime_manifest_candidates(root: Path = ROOT) -> list[Path]:
    outputs_root = root / "outputs"
    if not outputs_root.exists():
        return []
    return sorted(outputs_root.glob(f"**/{TRACE_DIR.as_posix()}/{MANIFEST_NAME}"), key=lambda p: p.stat().st_mtime, reverse=True)

def find_runtime_output_dir(run_id: str, *, root: Path = ROOT) -> Path | None:
    indexed = _indexed_runtime_output_dir(run_id, root=root)
    if indexed is not None:
        return indexed
    candidates = _runtime_manifest_candidates(root)
    for manifest_path in candidates:
        try:
            manifest = _read_json(manifest_path)
        except (OSError, json.JSONDecodeError):
            continue
        if str(manifest.get("run_id") or "") == run_id:
            output_dir = str(manifest.get("output_dir") or "")
            return Path(output_dir) if output_dir else manifest_path.parents[2]
    return None


def latest_runtime_manifest(*, root: Path = ROOT) -> dict[str, Any] | None:
    index = _read_runtime_index(root)
    indexed = sorted(
        [item for item in (index.get("runs") or {}).values() if isinstance(item, dict)],
        key=lambda item: str(item.get("updated_at") or ""),
        reverse=True,
    )
    for item in indexed:
        output_dir = str(item.get("output_dir") or "")
        if not output_dir:
            continue
        try:
            manifest = _read_json(runtime_file(output_dir, MANIFEST_NAME))
        except (OSError, json.JSONDecodeError):
            continue
        if str(manifest.get("run_id") or "") == str(item.get("run_id") or ""):
            return manifest
    manifests = _runtime_manifest_candidates(root)
    for path in manifests:
        try:
            return _read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
    return None


def is_path_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def validate_runtime_output_dir(output_dir: Path, *, active_output_dir: str | None = None, root: Path = ROOT, run_id: str | None = None) -> None:
    allowed = [(root / "outputs").resolve(strict=False)]
    if active_output_dir:
        allowed.append(Path(active_output_dir).resolve(strict=False))
    if run_id:
        indexed = _indexed_runtime_output_dir(run_id, root=root)
        if indexed is not None:
            allowed.append(indexed.resolve(strict=False))
    resolved = output_dir.resolve(strict=False)
    if not any(is_path_inside(resolved, item) or resolved == item for item in allowed):
        raise HTTPException(status_code=403, detail="runtime path outside output sandbox")


class RuntimeTracker:
    """Per-run event normalizer and artifact writer."""

    def __init__(self, *, root: Path = ROOT) -> None:
        self.root = root
        self._lock = threading.Lock()
        self._active_agent_corr: dict[str, str] = {}
        self._active_node_corr: dict[tuple[str, str], str] = {}
        self._active_model_corr: dict[str, str] = {}
        self._node_ordinals: dict[tuple[str, str], int] = {}
        self._model_ordinals: dict[tuple[str, str], int] = {}
        self._tool_ordinals: dict[tuple[str, str, str], int] = {}
        self._seen_event_fingerprints: set[tuple[str, str, str, str, str, str]] = set()
        self._timeout_runs: set[str] = set()

    def reset_run(self) -> None:
        self._active_agent_corr.clear()
        self._active_node_corr.clear()
        self._active_model_corr.clear()
        self._node_ordinals.clear()
        self._model_ordinals.clear()
        self._tool_ordinals.clear()
        self._seen_event_fingerprints: set[tuple[str, str, str, str, str, str]] = set()

    def initialize_run(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        self.reset_run()
        events = [
            self._build_event(
                state=state,
                event_type="run_init",
                status="running",
                message=f"runtime session initialized for {state.get('project_name') or 'run'}",
                agent="system",
                phase="studio",
                node_id="RUN.INIT",
                correlation_id=f"run:{state.get('run_id') or ''}",
                source={"type": "run_init"},
            )
        ]
        if state.get("job_id"):
            events.append(
                self._build_event(
                    state=state,
                    event_type="job_queued",
                    status="queued",
                    message=f"job queued {state.get('job_id')}",
                    agent="system",
                    phase="studio",
                    node_id="JOB.QUEUED",
                    correlation_id=f"job:{state.get('job_id')}",
                    source={"type": "job_queued"},
                )
            )
        self._write_events(state, events)
        return events

    def record_source_event(self, event: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
        if not state.get("output_dir") or not state.get("run_id"):
            return []
        events = self._events_from_source(event, state)
        events = [item for item in events if self._keep_once(item)]
        if events:
            self._write_events(state, events)
        return events

    def watchdog_timeout(self, state: dict[str, Any], *, reason: str, stale_kind: str = "subprocess") -> list[dict[str, Any]]:
        run_id = str(state.get("run_id") or "")
        if not run_id or run_id in self._timeout_runs:
            return []
        self._timeout_runs.add(run_id)
        event = self._build_event(
            state=state,
            event_type="watchdog_timeout",
            status="failed",
            message=reason,
            agent="system",
            phase="studio",
            node_id=f"WATCHDOG.{stale_kind.upper()}",
            correlation_id=f"run:{run_id}",
            error={"message": reason, "stale_kind": stale_kind},
            source={"type": "watchdog_timeout", "stale_kind": stale_kind},
        )
        self._write_events(state, [event])
        self.write_recovery_report(state, reason=reason, action="watchdog_timeout", before_status=str(state.get("status") or ""))
        return [event]

    def stale_snapshot(self, output_dir: str | Path) -> dict[str, Any]:
        events = read_runtime_events(output_dir)
        active_pairs: dict[tuple[str, str], dict[str, Any]] = {}
        last_progress_event: dict[str, Any] | None = None
        for event in events:
            event_type = str(event.get("event_type") or "")
            corr = str(event.get("correlation_id") or "")
            if event_type in {"agent_start", "node_start", "model_call_start", "tool_call_start"}:
                active_pairs[(event_type.replace("_start", ""), corr)] = event
            elif event_type in {"agent_done", "node_done", "model_call_done", "tool_call_done"}:
                active_pairs.pop((event_type.replace("_done", ""), corr), None)
            if event_type in PROGRESS_EVENT_TYPES or event_type in {"run_init", "model_call_start"}:
                last_progress_event = event
        active_model = next((event for (kind, _corr), event in reversed(list(active_pairs.items())) if kind == "model_call"), None)
        basis = active_model or last_progress_event
        timestamp = _parse_runtime_timestamp((basis or {}).get("timestamp"))
        age = max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds()) if timestamp else None
        return {
            "age_s": age,
            "stale_kind": "model_call_stale" if active_model else "backend_not_stale",
            "active_model_call": active_model,
            "last_progress_event_type": str((basis or {}).get("event_type") or ""),
            "last_progress_at": str((basis or {}).get("timestamp") or ""),
            "active_pair_count": len(active_pairs),
        }

    def last_progress_age_s(self, output_dir: str | Path) -> float | None:
        snapshot = self.stale_snapshot(output_dir)
        return snapshot.get("age_s") if isinstance(snapshot.get("age_s"), float) else None

    def write_recovery_report(self, state: dict[str, Any], *, reason: str, action: str, before_status: str = "") -> dict[str, Any]:
        output_dir = str(state.get("output_dir") or "")
        if not output_dir:
            return {}
        manifest = _safe_read_json(runtime_file(output_dir, MANIFEST_NAME)).get("payload") or {}
        report = {
            "schema_version": "studio.runtime_recovery_report.v1",
            "run_id": state.get("run_id") or "",
            "job_id": state.get("job_id") or "",
            "reason": reason,
            "action": action,
            "before_status": before_status,
            "after_status": state.get("status") or "",
            "timestamp": utc_now_iso(),
            "recoverable": bool(manifest.get("recoverable", False)),
            "active_agent": manifest.get("active_agent") or "",
            "active_node_id": manifest.get("active_node_id") or "",
            "last_runtime_event_at": manifest.get("last_runtime_event_at") or "",
        }
        _write_json_atomic(runtime_file(output_dir, RECOVERY_NAME), report)
        return report

    def _events_from_source(self, event: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
        kind = str(event.get("type") or "log")
        if kind == "runtime_event":
            return []
        if kind in {"log", "ping", "attachment_staged", "attachment_rejected"}:
            return []
        if kind.startswith("job_"):
            return [self._job_event(event, state)]
        if kind == "process_start":
            return [
                self._build_event(
                    state=state,
                    event_type="job_started",
                    status="running",
                    message=f"process started pid={event.get('pid')}",
                    agent="system",
                    phase="studio",
                    node_id="RUNNER.PROCESS",
                    correlation_id=f"job:{state.get('job_id') or event.get('job_id') or state.get('run_id')}",
                    source=event,
                )
            ]
        if kind == "process_exit":
            status = "passed" if event.get("returncode") in (0, None) and str(state.get("status")) not in {"failed", "stopped"} else "failed"
            if str(state.get("status")) == "stopped":
                status = "cancelled"
            return [
                self._build_event(
                    state=state,
                    event_type="job_done",
                    status=status,
                    message=f"process exited {event.get('returncode')}",
                    agent="system",
                    phase="studio",
                    node_id="RUNNER.PROCESS",
                    correlation_id=f"job:{state.get('job_id') or event.get('job_id') or state.get('run_id')}",
                    error=None if status in {"passed", "cancelled"} else {"returncode": event.get("returncode")},
                    source=event,
                )
            ]
        if kind == "watchdog_timeout":
            return [
                self._build_event(
                    state=state,
                    event_type="watchdog_timeout",
                    status="failed",
                    message=str(event.get("message") or "runtime watchdog timeout"),
                    agent="system",
                    phase="studio",
                    node_id="WATCHDOG.TIMEOUT",
                    correlation_id=f"run:{state.get('run_id') or ''}",
                    error={"message": event.get("message") or "runtime watchdog timeout"},
                    source=event,
                )
            ]
        if kind == "error":
            return [
                self._build_event(
                    state=state,
                    event_type="runtime_error",
                    status="failed",
                    message=str(event.get("message") or "runner error"),
                    agent=str(event.get("agent") or "system"),
                    phase=str(event.get("phase") or "studio"),
                    node_id=str(event.get("node_id") or "RUNTIME.ERROR"),
                    correlation_id=f"run:{state.get('run_id') or ''}",
                    error={"message": event.get("message") or "runner error", "traceback_tail": event.get("traceback_tail")},
                    source=event,
                )
            ]
        if kind == "artifact":
            refs = _artifact_refs(event)
            return [
                self._build_event(
                    state=state,
                    event_type="artifact_written",
                    status="passed",
                    message=str(event.get("message") or event.get("path") or "artifact written"),
                    agent=str(event.get("agent") or "system"),
                    phase=str(event.get("phase") or "studio"),
                    node_id=str(event.get("node_id") or "ARTIFACT.WRITE"),
                    correlation_id=f"run:{state.get('run_id') or ''}",
                    artifact_refs=refs,
                    metrics={"bytes": event.get("bytes")} if event.get("bytes") is not None else {},
                    source=event,
                )
            ]
        if kind == "metric":
            return [
                self._build_event(
                    state=state,
                    event_type="metric",
                    status=_status(str(event.get("status") or "info")),
                    message=str(event.get("name") or "metric"),
                    agent=str(event.get("agent") or "system"),
                    phase=str(event.get("phase") or _phase_for_agent(str(event.get("agent") or ""))),
                    node_id=f"METRIC.{_slug(str(event.get('name') or 'value')).upper()}",
                    correlation_id=f"run:{state.get('run_id') or ''}",
                    metrics={str(event.get("name") or "metric"): event.get("value")},
                    source=event,
                )
            ]
        if kind == "stage":
            stage = str(event.get("stage") or "studio")
            event_type = "node_start" if str(event.get("status") or "") in {"running", "starting"} else "node_done"
            node_id = f"STAGE.{stage.upper()}"
            corr = self._node_correlation(state, "system", node_id, start=event_type == "node_start")
            return [
                self._build_event(
                    state=state,
                    event_type=event_type,
                    status=_status(str(event.get("status") or "info")),
                    message=f"{stage} {event.get('status')}",
                    agent="system",
                    phase=stage,
                    node_id=node_id,
                    correlation_id=corr,
                    source=event,
                )
            ]
        if kind == "agent_action":
            return self._agent_action_events(event, state)
        if kind == "agent_handoff":
            corr = self._tool_correlation(state, str(event.get("from_agent") or "system"), "handoff", str(event.get("contract") or "contract"))
            return [
                self._build_event(
                    state=state,
                    event_type="tool_call_start",
                    status="running",
                    message=str(event.get("contract") or "agent handoff"),
                    agent=str(event.get("from_agent") or "system"),
                    phase=str(event.get("phase") or "studio"),
                    node_id=f"HANDOFF.{_slug(str(event.get('contract') or 'contract')).upper()}",
                    correlation_id=corr,
                    source={"type": "agent_handoff_start"},
                ),
                self._build_event(
                    state=state,
                    event_type="tool_call_done",
                    status=_status(str(event.get("status") or "passed")),
                    message=str(event.get("summary") or event.get("contract") or "agent handoff"),
                    agent=str(event.get("from_agent") or "system"),
                    phase=str(event.get("phase") or "studio"),
                    node_id=f"HANDOFF.{_slug(str(event.get('contract') or 'contract')).upper()}",
                    correlation_id=corr,
                    artifact_refs=_artifact_refs(event),
                    source=event,
                )
            ]
        if kind == "pause":
            node_id = f"PAUSE.{_slug(str(event.get('action_required') or 'human')).upper()}"
            return [
                self._build_event(
                    state=state,
                    event_type="node_done",
                    status="paused",
                    message=str(event.get("message") or event.get("action_required") or "run paused"),
                    agent="agent1" if str(event.get("action_required") or "").startswith(("PLAN", "REQUIREMENT")) else "system",
                    phase="planning",
                    node_id=node_id,
                    correlation_id=self._node_correlation(state, "agent1", node_id, start=False),
                    artifact_refs=_artifact_refs(event),
                    source=event,
                )
            ]
        if kind == "done":
            done_events: list[dict[str, Any]] = []
            for agent, corr in list(self._active_agent_corr.items()):
                done_events.append(
                    self._build_event(
                        state=state,
                        event_type="agent_done",
                        status="passed",
                        message=f"{agent} done",
                        agent=agent,
                        phase=_phase_for_agent(agent),
                        node_id=f"{agent.upper()}.DONE",
                        correlation_id=corr,
                        source={"type": "agent_done", "source_type": event.get("type")},
                    )
                )
                self._active_agent_corr.pop(agent, None)
            if not done_events:
                done_events.append(
                    self._build_event(
                        state=state,
                        event_type="job_done",
                        status="passed",
                        message=str(event.get("status") or "done"),
                        agent="system",
                        phase="signoff",
                        node_id="RUN.DONE",
                        correlation_id=f"job:{state.get('job_id') or state.get('run_id') or ''}",
                        artifact_refs=_artifact_refs(event),
                        source=event,
                    )
                )
            return done_events
        if kind == "trace_event":
            event_type = str(event.get("event_type") or "trace_event")
            status_value = _status(str(event.get("status") or "info"))
            node_id = str(event.get("node_id") or "TRACE.EVENT")
            runtime_type = "node_start" if status_value == "running" else "node_done" if status_value in {"passed", "failed", "paused", "cancelled"} else "trace_event"
            return [
                self._build_event(
                    state=state,
                    event_type=runtime_type,
                    status=status_value,
                    message=str(event.get("summary") or event_type),
                    agent=str(event.get("agent") or "system"),
                    phase=str(event.get("phase") or _phase_for_agent(str(event.get("agent") or ""))),
                    node_id=node_id,
                    correlation_id=self._node_correlation(state, str(event.get("agent") or "system"), node_id, start=runtime_type == "node_start"),
                    metrics={"latency_ms": event.get("latency_ms")} if event.get("latency_ms") is not None else {},
                    source={"type": "trace_event", "trace_file": event.get("trace_file"), "source_event_type": event_type},
                )
            ]
        if kind.startswith("live_input_"):
            corr = self._tool_correlation(state, "agent1", "LIVE_INPUT.QUEUE", "live_input")
            return [
                self._build_event(
                    state=state,
                    event_type="tool_call_start",
                    status="running",
                    message="queue live input",
                    agent="agent1",
                    phase="planning",
                    node_id="LIVE_INPUT.QUEUE",
                    correlation_id=corr,
                    source={"type": "live_input_start"},
                ),
                self._build_event(
                    state=state,
                    event_type="tool_call_done",
                    status="failed" if kind.endswith("error") else "queued",
                    message=str(event.get("message") or kind),
                    agent="agent1",
                    phase="planning",
                    node_id="LIVE_INPUT.QUEUE",
                    correlation_id=corr,
                    source=event,
                )
            ]
        return []

    def _keep_once(self, event: dict[str, Any]) -> bool:
        fingerprint = (
            str(event.get("run_id") or ""),
            str(event.get("event_type") or ""),
            str(event.get("correlation_id") or ""),
            str(event.get("status") or ""),
            str(event.get("message") or ""),
            str((event.get("source") or {}).get("type") if isinstance(event.get("source"), dict) else ""),
        )
        if fingerprint in self._seen_event_fingerprints:
            return False
        self._seen_event_fingerprints.add(fingerprint)
        return True

    def _job_event(self, event: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        mapping = {
            "job_queued": ("job_queued", "queued"),
            "job_started": ("job_started", "running"),
            "job_progress": ("job_started", _status(str(event.get("status") or "running"))),
            "job_completed": ("job_done", "passed"),
            "job_failed": ("job_done", "failed"),
            "job_cancelled": ("job_done", "cancelled"),
        }
        event_type, status = mapping.get(str(event.get("type") or ""), ("job_started", _status(str(event.get("status") or "info"))))
        return self._build_event(
            state=state,
            event_type=event_type,
            status=status,
            message=str(event.get("message") or event.get("type") or "job event"),
            agent="system",
            phase="studio",
            node_id=f"JOB.{event_type.upper()}",
            correlation_id=f"job:{event.get('job_id') or state.get('job_id') or state.get('run_id')}",
            artifact_refs=_artifact_refs(event),
            error={"message": event.get("message")} if status == "failed" else None,
            source=event,
        )

    def _agent_action_events(self, event: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
        agent = str(event.get("agent") or "system")
        phase = str(event.get("phase") or _phase_for_agent(agent))
        action = str(event.get("action") or "activity")
        summary = str(event.get("summary") or action)
        raw_status = str(event.get("status") or "info")
        status_value = _status(raw_status)
        events: list[dict[str, Any]] = []
        if status_value == "running" and agent not in self._active_agent_corr and agent.startswith("agent"):
            corr = f"agent:{state.get('run_id') or ''}:{agent}"
            self._active_agent_corr[agent] = corr
            events.append(
                self._build_event(
                    state=state,
                    event_type="agent_start",
                    status="running",
                    message=f"{agent} started",
                    agent=agent,
                    phase=phase,
                    node_id=f"{agent.upper()}.START",
                    correlation_id=corr,
                    source={"type": "agent_start", "source_type": event.get("type")},
                )
            )
        if _is_model_start(action, summary):
            corr = self._model_correlation(state, agent, action, start=True)
            events.append(
                self._build_event(
                    state=state,
                    event_type="model_call_start",
                    status="running",
                    message=summary,
                    agent=agent,
                    phase=phase,
                    node_id=f"{agent.upper()}.MODEL_CALL",
                    correlation_id=corr,
                    source=event,
                )
            )
            return events
        if _is_model_done(action, summary) or _is_model_fail(action, summary, raw_status):
            corr = self._model_correlation(state, agent, action, start=False)
            metrics = event.get("metric") if isinstance(event.get("metric"), dict) else {}
            duration_ms = _duration_ms(metrics)
            events.append(
                self._build_event(
                    state=state,
                    event_type="model_call_done",
                    status="failed" if _is_model_fail(action, summary, raw_status) else "passed",
                    message=summary,
                    agent=agent,
                    phase=phase,
                    node_id=f"{agent.upper()}.MODEL_CALL",
                    correlation_id=corr,
                    duration_ms=duration_ms,
                    metrics=metrics,
                    error={"message": summary} if _is_model_fail(action, summary, raw_status) else None,
                    source=event,
                )
            )
            return events
        node_id = str(event.get("node_id") or f"{agent.upper()}.{_slug(action).upper()}")
        event_type = "node_start" if status_value == "running" else "node_done"
        corr = self._node_correlation(state, agent, node_id, start=event_type == "node_start")
        events.append(
            self._build_event(
                state=state,
                event_type=event_type,
                status=status_value,
                message=summary,
                agent=agent,
                phase=phase,
                node_id=node_id,
                correlation_id=corr,
                artifact_refs=_artifact_refs(event),
                error={"message": summary} if status_value == "failed" else None,
                source=event,
            )
        )
        if status_value in {"failed", "paused", "cancelled"} and agent in self._active_agent_corr:
            events.append(
                self._build_event(
                    state=state,
                    event_type="agent_done",
                    status=status_value,
                    message=f"{agent} {status_value}",
                    agent=agent,
                    phase=phase,
                    node_id=f"{agent.upper()}.DONE",
                    correlation_id=self._active_agent_corr.pop(agent),
                    source={"type": "agent_done", "source_type": event.get("type")},
                )
            )
        return events

    def _build_event(
        self,
        *,
        state: dict[str, Any],
        event_type: str,
        status: str,
        message: str,
        agent: str,
        phase: str,
        node_id: str,
        correlation_id: str,
        duration_ms: int | float | None = None,
        artifact_refs: list[str] | None = None,
        metrics: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        source: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "type": "runtime_event",
            "schema_version": RUNTIME_SCHEMA_VERSION,
            "event_id": str(uuid.uuid4()),
            "correlation_id": correlation_id,
            "timestamp": utc_now_iso(),
            "run_id": str(state.get("run_id") or ""),
            "job_id": str(state.get("job_id") or ""),
            "project_name": str(state.get("project_name") or ""),
            "agent": agent if agent in AGENTS or agent.startswith("agent") else "system",
            "phase": phase if phase in PHASES else _phase_for_agent(agent),
            "node_id": node_id,
            "event_type": event_type,
            "status": status,
            "message": message,
            "duration_ms": max(0, int(duration_ms or 0)),
            "artifact_refs": list(dict.fromkeys(artifact_refs or [])),
            "metrics": metrics or {},
            "error": error,
            "source": {"type": source.get("type")} if isinstance(source, dict) else None,
        }
        return redact_runtime_payload(payload)

    def _node_correlation(self, state: dict[str, Any], agent: str, node_id: str, *, start: bool) -> str:
        key = (agent, node_id)
        if start or key not in self._active_node_corr:
            self._node_ordinals[key] = self._node_ordinals.get(key, 0) + 1
            corr = f"node:{state.get('run_id') or ''}:{agent}:{node_id}:{self._node_ordinals[key]}"
            if start:
                self._active_node_corr[key] = corr
            return corr
        return self._active_node_corr.pop(key)

    def _model_correlation(self, state: dict[str, Any], agent: str, action: str, *, start: bool) -> str:
        if start or agent not in self._active_model_corr:
            key = (agent, action if action else "model_call")
            self._model_ordinals[key] = self._model_ordinals.get(key, 0) + 1
            corr = f"model:{state.get('run_id') or ''}:{agent}:{_slug(action or 'model_call')}:{self._model_ordinals[key]}"
            if start:
                self._active_model_corr[agent] = corr
            return corr
        return self._active_model_corr.pop(agent)

    def _tool_correlation(self, state: dict[str, Any], agent: str, node_id: str, tool_name: str) -> str:
        key = (agent, node_id, tool_name)
        self._tool_ordinals[key] = self._tool_ordinals.get(key, 0) + 1
        return f"tool:{state.get('run_id') or ''}:{agent}:{node_id}:{tool_name}:{self._tool_ordinals[key]}"

    def _write_events(self, state: dict[str, Any], events: list[dict[str, Any]]) -> None:
        output_dir = str(state.get("output_dir") or "")
        if not output_dir:
            return
        with self._lock:
            trace_dir = runtime_trace_dir(output_dir)
            trace_dir.mkdir(parents=True, exist_ok=True)
            path = trace_dir / EVENTS_NAME
            with path.open("a", encoding="utf-8") as handle:
                for event in events:
                    handle.write(json.dumps(redact_runtime_payload(event), ensure_ascii=False, sort_keys=True) + "\n")
            all_events = read_runtime_events(output_dir)
            manifest = _manifest_from_events(state, all_events)
            _write_json_atomic(trace_dir / MANIFEST_NAME, manifest)
            invariant = build_runtime_invariant_report(output_dir, manifest=manifest, events=all_events)
            replay = build_runtime_replay_report(output_dir, manifest=manifest, events=all_events)
            debug = build_runtime_debug_summary(output_dir, manifest=manifest, invariant=invariant, replay=replay, events=all_events)
            _write_json_atomic(trace_dir / INVARIANT_NAME, invariant)
            _write_json_atomic(trace_dir / REPLAY_NAME, replay)
            _write_json_atomic(trace_dir / DEBUG_SUMMARY_NAME, debug)
            _ensure_default_recovery_report(output_dir, state, manifest)
            _write_runtime_index(self.root, manifest)


def _ensure_default_recovery_report(output_dir: str | Path, state: dict[str, Any], manifest: dict[str, Any]) -> None:
    path = runtime_file(output_dir, RECOVERY_NAME)
    existing = _safe_read_json(path).get("payload")
    if isinstance(existing, dict) and str(existing.get("action") or "") not in {"", "none", "run_initialized"}:
        return
    created_at = str(existing.get("timestamp") or utc_now_iso()) if isinstance(existing, dict) else utc_now_iso()
    report = {
        "schema_version": "studio.runtime_recovery_report.v1",
        "run_id": state.get("run_id") or manifest.get("run_id") or "",
        "job_id": state.get("job_id") or manifest.get("job_id") or "",
        "reason": "none",
        "action": "none",
        "before_status": str(existing.get("before_status") or "idle") if isinstance(existing, dict) else "idle",
        "after_status": manifest.get("status") or state.get("status") or "",
        "timestamp": created_at,
        "updated_at": utc_now_iso(),
        "recoverable": bool(manifest.get("recoverable", False)),
        "active_agent": manifest.get("active_agent") or "",
        "active_node_id": manifest.get("active_node_id") or "",
        "active_model_call_id": manifest.get("active_model_call_id") or "",
        "last_runtime_event_at": manifest.get("last_runtime_event_at") or "",
    }
    _write_json_atomic(path, report)


def _manifest_from_events(state: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    agents: dict[str, Any] = {}
    nodes: dict[str, Any] = {}
    model_calls: dict[str, Any] = {}
    queue: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    artifact_refs: list[str] = []
    last_event_at = ""
    active_agent = ""
    active_node_id = ""
    active_model_call_id = ""
    status = str(state.get("status") or "idle")
    for event in events:
        last_event_at = str(event.get("timestamp") or last_event_at)
        agent = str(event.get("agent") or "")
        event_type = str(event.get("event_type") or "")
        event_status = str(event.get("status") or "")
        if agent and agent.startswith("agent"):
            agents[agent] = {"status": event_status, "last_event_type": event_type, "message": event.get("message"), "updated_at": event.get("timestamp")}
            if event_status == "running":
                active_agent = agent
        if event_type in {"node_start", "node_done", "trace_event"}:
            corr = str(event.get("correlation_id") or event.get("event_id") or "")
            nodes[corr] = {
                "agent": agent,
                "node_id": event.get("node_id"),
                "status": event_status,
                "event_type": event_type,
                "message": event.get("message"),
                "updated_at": event.get("timestamp"),
            }
            if event_status == "running":
                active_node_id = str(event.get("node_id") or "")
        if event_type in {"model_call_start", "model_call_done"}:
            corr = str(event.get("correlation_id") or event.get("event_id") or "")
            model_calls[corr] = {
                "agent": agent,
                "node_id": event.get("node_id"),
                "status": event_status,
                "duration_ms": event.get("duration_ms"),
                "metrics": event.get("metrics") or {},
                "message": event.get("message"),
                "updated_at": event.get("timestamp"),
            }
            if event_type == "model_call_start" and event_status == "running":
                active_model_call_id = corr
            elif event_type == "model_call_done" and active_model_call_id == corr:
                active_model_call_id = ""
        if event_type.startswith("job_"):
            queue = {
                **queue,
                "job_id": event.get("job_id"),
                "status": event_status,
                "last_event_type": event_type,
                "updated_at": event.get("timestamp"),
            }
        for ref in event.get("artifact_refs") or []:
            if isinstance(ref, str):
                artifact_refs.append(ref)
        _merge_metrics(metrics, event)
        if event_type in TERMINAL_EVENT_TYPES:
            if event_status == "failed":
                status = "failed"
            elif event_status == "cancelled":
                status = "stopped"
            elif event_status in {"passed", "recovered"} and status not in {"failed", "stopped"}:
                status = "done"
        elif event_status == "paused":
            status = "paused"
        elif event_status == "running" and status not in {"paused", "failed", "done", "stopped"}:
            status = "running"
    if state.get("status") in {"paused", "done", "failed", "stopped", "running", "starting", "stopping"}:
        status = str(state.get("status"))
    if status in {"done", "failed", "stopped", "recovered"}:
        active_agent = ""
        active_node_id = ""
        active_model_call_id = ""
    return redact_runtime_payload(
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "run_id": str(state.get("run_id") or ""),
            "job_id": str(state.get("job_id") or ""),
            "project_name": str(state.get("project_name") or ""),
            "output_dir": str(state.get("output_dir") or ""),
            "planning_mode": str(state.get("planning_mode") or "normal"),
            "credential_ref": str(state.get("apiKeyRef") or state.get("api_key_ref") or DEFAULT_CREDENTIAL_REF),
            "status": status,
            "active_agent": active_agent,
            "active_node_id": active_node_id,
            "active_model_call_id": active_model_call_id,
            "last_runtime_event_at": last_event_at,
            "recoverable": status in {"running", "starting", "paused", "failed", "stopped"},
            "recovery_status": "none",
            "agents": agents,
            "nodes": nodes,
            "model_calls": model_calls,
            "queue": queue,
            "metrics": metrics,
            "artifact_refs": list(dict.fromkeys(artifact_refs)),
        }
    )


def _merge_metrics(metrics: dict[str, Any], event: dict[str, Any]) -> None:
    event_metrics = event.get("metrics") if isinstance(event.get("metrics"), dict) else {}
    agent = str(event.get("agent") or "system")
    by_agent = metrics.setdefault("byAgent", {})
    agent_metrics = by_agent.setdefault(agent, {"callCount": 0, "failureCount": 0, "latencyTotalMs": 0, "latencyMaxMs": 0})
    if str(event.get("event_type") or "") == "model_call_done":
        agent_metrics["callCount"] = int(agent_metrics.get("callCount") or 0) + 1
        if event.get("status") == "failed":
            agent_metrics["failureCount"] = int(agent_metrics.get("failureCount") or 0) + 1
        duration = int(event.get("duration_ms") or 0)
        agent_metrics["latencyTotalMs"] = int(agent_metrics.get("latencyTotalMs") or 0) + duration
        agent_metrics["latencyMaxMs"] = max(int(agent_metrics.get("latencyMaxMs") or 0), duration)
        if agent_metrics["callCount"]:
            agent_metrics["latencyAvgMs"] = round(agent_metrics["latencyTotalMs"] / agent_metrics["callCount"], 2)
    for key, value in event_metrics.items():
        if value is None:
            continue
        name = str(key)
        if name in {"prompt_tokens", "codex_prompt_tokens"}:
            agent_metrics["promptTokens"] = int(agent_metrics.get("promptTokens") or 0) + int(value)
        elif name in {"completion_tokens", "codex_completion_tokens"}:
            agent_metrics["completionTokens"] = int(agent_metrics.get("completionTokens") or 0) + int(value)
        elif name in {"total_tokens", "codex_total_tokens"}:
            agent_metrics["totalTokens"] = int(agent_metrics.get("totalTokens") or 0) + int(value)
        elif name in {"estimated_cost_usd", "codex_estimated_cost_usd"}:
            agent_metrics["estimatedCostUsd"] = round(float(agent_metrics.get("estimatedCostUsd") or 0.0) + float(value), 8)
        metrics[name] = value
    metrics["source"] = "runtime_event"


def build_runtime_invariant_report(output_dir: str | Path, *, manifest: dict[str, Any] | None = None, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    events = events if events is not None else read_runtime_events(output_dir)
    manifest = manifest if manifest is not None else _safe_read_json(runtime_file(output_dir, MANIFEST_NAME)).get("payload") or {}
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    seen_run_init = False
    last_ts = ""
    starts: dict[tuple[str, str], int] = {}
    start_locations: dict[tuple[str, str], list[int]] = {}
    for index, event in enumerate(events):
        event_type = str(event.get("event_type") or "")
        if event_type == "run_init":
            seen_run_init = True
        elif not seen_run_init:
            failures.append({"code": "run_init_missing_before_event", "index": index, "event_type": event_type})
        ts = str(event.get("timestamp") or "")
        if last_ts and ts and ts < last_ts:
            failures.append({"code": "timestamp_not_monotonic", "index": index})
        last_ts = ts or last_ts
        _check_secret_scan(event, failures, f"event[{index}]")
        _check_non_negative_metrics(event, failures, index)
        _check_artifact_refs(event, output_dir, failures, index)
        corr = str(event.get("correlation_id") or "")
        if event_type in {"agent_start", "node_start", "model_call_start", "tool_call_start"}:
            key = (event_type.replace("_start", ""), corr)
            starts[key] = starts.get(key, 0) + 1
            start_locations.setdefault(key, []).append(index)
        if event_type in {"agent_done", "node_done", "model_call_done", "tool_call_done"}:
            key = (event_type.replace("_done", ""), corr)
            if starts.get(key, 0) <= 0:
                issue = {"code": "done_without_start", "index": index, "kind": key[0], "event_type": event_type, "correlation_id": corr}
                if key[0] in STRICT_PAIR_KINDS:
                    failures.append(issue)
                else:
                    warnings.append(issue)
            else:
                starts[key] -= 1
                if start_locations.get(key):
                    start_locations[key].pop()
    _check_secret_scan(manifest, failures, "manifest")
    status = str(manifest.get("status") or "")
    terminal_seen = any(str(event.get("event_type") or "") in TERMINAL_EVENT_TYPES for event in events)
    if status in {"done", "failed", "stopped", "recovered"} and events and not terminal_seen:
        warnings.append({"code": "terminal_manifest_without_terminal_event", "status": status})
    unbalanced_pairs: list[dict[str, Any]] = []
    for (kind, corr), count in sorted(starts.items()):
        if count <= 0:
            continue
        issue = {
            "code": "start_without_done",
            "kind": kind,
            "correlation_id": corr,
            "count": count,
            "start_indexes": start_locations.get((kind, corr), []),
            "terminal_status": status,
        }
        unbalanced_pairs.append(issue)
        if kind in STRICT_PAIR_KINDS and status in {"done", "failed", "stopped", "recovered"}:
            failures.append(issue)
        elif status in {"done", "failed", "stopped", "recovered"} or kind in STRICT_PAIR_KINDS:
            warnings.append(issue)
    report = {
        "schema_version": "studio.runtime_invariant_report.v1",
        "output_dir": str(output_dir),
        "checked_at": utc_now_iso(),
        "ok": not failures,
        "failure_count": len(failures),
        "warning_count": len(warnings),
        "failures": failures,
        "warnings": warnings,
        "unbalanced_pairs": unbalanced_pairs,
        "secret_scan": "pass" if not any(item.get("code") == "secret_like_text" for item in failures) else "fail",
        "event_count": len(events),
    }
    return redact_runtime_payload(report)


def build_runtime_replay_report(output_dir: str | Path, *, manifest: dict[str, Any] | None = None, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    events = events if events is not None else read_runtime_events(output_dir)
    manifest = manifest if manifest is not None else _safe_read_json(runtime_file(output_dir, MANIFEST_NAME)).get("payload") or {}
    by_type: dict[str, int] = {}
    by_agent: dict[str, int] = {}
    by_source_type: dict[str, int] = {}
    terminal = ""
    for event in events:
        by_type[str(event.get("event_type") or "unknown")] = by_type.get(str(event.get("event_type") or "unknown"), 0) + 1
        by_agent[str(event.get("agent") or "system")] = by_agent.get(str(event.get("agent") or "system"), 0) + 1
        source = event.get("source") if isinstance(event.get("source"), dict) else {}
        source_type = str(source.get("type") or "unknown")
        by_source_type[source_type] = by_source_type.get(source_type, 0) + 1
        if str(event.get("event_type") or "") in TERMINAL_EVENT_TYPES:
            terminal = str(event.get("event_type") or "")
    report = {
        "schema_version": "studio.runtime_replay_report.v1",
        "output_dir": str(output_dir),
        "checked_at": utc_now_iso(),
        "run_id": manifest.get("run_id") or "",
        "manifest_status": manifest.get("status") or "",
        "terminal_event_type": terminal,
        "event_count": len(events),
        "by_type": by_type,
        "by_agent": by_agent,
        "by_source_type": by_source_type,
        "replay_status": "pass" if events else "empty",
    }
    _write_json_atomic(runtime_file(output_dir, REPLAY_NAME), report)
    return redact_runtime_payload(report)


def build_runtime_debug_summary(
    output_dir: str | Path,
    *,
    manifest: dict[str, Any] | None = None,
    invariant: dict[str, Any] | None = None,
    replay: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    events = events if events is not None else read_runtime_events(output_dir)
    manifest = manifest if manifest is not None else _safe_read_json(runtime_file(output_dir, MANIFEST_NAME)).get("payload") or {}
    invariant = invariant if invariant is not None else _safe_read_json(runtime_file(output_dir, INVARIANT_NAME)).get("payload") or {}
    replay = replay if replay is not None else _safe_read_json(runtime_file(output_dir, REPLAY_NAME)).get("payload") or {}
    last_error = next((event for event in reversed(events) if event.get("status") == "failed" or event.get("error")), None)
    summary = {
        "schema_version": "studio.runtime_debug_summary.v1",
        "output_dir": str(output_dir),
        "updated_at": utc_now_iso(),
        "run_id": manifest.get("run_id") or "",
        "job_id": manifest.get("job_id") or "",
        "status": manifest.get("status") or "unknown",
        "active_agent": manifest.get("active_agent") or "",
        "active_node_id": manifest.get("active_node_id") or "",
        "queue": manifest.get("queue") or {},
        "metrics": manifest.get("metrics") or {},
        "artifact_count": len(manifest.get("artifact_refs") or []),
        "event_count": len(events),
        "last_error": last_error,
        "invariant_ok": invariant.get("ok"),
        "secret_scan": invariant.get("secret_scan"),
        "replay_status": replay.get("replay_status"),
    }
    _write_json_atomic(runtime_file(output_dir, DEBUG_SUMMARY_NAME), summary)
    return redact_runtime_payload(summary)


def _check_secret_scan(value: Any, failures: list[dict[str, Any]], location: str) -> None:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if "Authorization" in text or "Bearer " in text or re.search(r"sk-[A-Za-z0-9_\-]{8,}", text):
        failures.append({"code": "secret_like_text", "location": location})


def _check_non_negative_metrics(event: dict[str, Any], failures: list[dict[str, Any]], index: int) -> None:
    metrics = event.get("metrics") if isinstance(event.get("metrics"), dict) else {}
    for key, value in metrics.items():
        if key in {"prompt_tokens", "completion_tokens", "total_tokens", "estimated_cost_usd", "latency_s", "latency_ms"}:
            try:
                if float(value) < 0:
                    failures.append({"code": "negative_metric", "index": index, "metric": key})
            except (TypeError, ValueError):
                continue


def _check_artifact_refs(event: dict[str, Any], output_dir: str | Path, failures: list[dict[str, Any]], index: int) -> None:
    root = Path(output_dir).resolve(strict=False)
    for ref in event.get("artifact_refs") or []:
        if not isinstance(ref, str) or not ref:
            continue
        path = Path(ref)
        if path.is_absolute() and not is_path_inside(path, root):
            failures.append({"code": "artifact_outside_output_sandbox", "index": index, "path": ref})
        if ".." in path.parts:
            failures.append({"code": "artifact_relative_traversal", "index": index, "path": ref})


def _artifact_refs(event: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ("path", "artifact", "plan_path"):
        value = event.get(key)
        if isinstance(value, str) and value:
            refs.append(value)
    value = event.get("artifact_refs")
    if isinstance(value, list):
        refs.extend(str(item) for item in value if item)
    return list(dict.fromkeys(refs))


def _status(value: str) -> str:
    lowered = value.lower()
    if lowered in {"pass", "passed", "completed", "complete", "ok", "done", "success"}:
        return "passed"
    if lowered in {"fail", "failed", "error"}:
        return "failed"
    if lowered in {"pause", "paused"}:
        return "paused"
    if lowered in {"cancel", "cancelled", "canceled", "stopped", "stop"}:
        return "cancelled"
    if lowered in {"queued", "running", "recovered"}:
        return lowered
    return "running" if lowered in {"info", "warning", "warn", "starting"} else lowered or "running"


def _phase_for_agent(agent: str) -> str:
    return {
        "agent1": "planning",
        "agent2": "rtl",
        "agent3": "dv",
        "agent4": "physical",
        "agent5": "formal",
        "agent6": "studio",
    }.get(agent, "studio")


def _slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return text[:64] or "node"


def _is_model_start(action: str, summary: str) -> bool:
    text = f"{action} {summary}".lower()
    return "codex request started" in text or text.startswith("calling ") or " calling " in text


def _is_model_done(action: str, summary: str) -> bool:
    text = f"{action} {summary}".lower()
    return "codex response received" in text or "returned architecture evidence" in text or "returned rtl" in text or "returned " in text and " evidence" in text


def _is_model_fail(action: str, summary: str, status: str) -> bool:
    text = f"{action} {summary}".lower()
    return "codex unavailable" in text or status.lower() in {"fail", "failed", "error"}


def _duration_ms(metrics: Any) -> int:
    if isinstance(metrics, dict):
        value = metrics.get("latency_s")
        try:
            return max(0, int(float(value) * 1000))
        except (TypeError, ValueError):
            return 0
    return 0
