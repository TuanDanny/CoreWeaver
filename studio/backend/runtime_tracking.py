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
DEBUG_ISSUES_NAME = "debug_issues.jsonl"
MANIFEST_NAME = "runtime_session_manifest.json"
RECOVERY_NAME = "runtime_recovery_report.json"
INVARIANT_NAME = "runtime_invariant_report.json"
REPLAY_NAME = "runtime_replay_report.json"
FLOW_COVERAGE_NAME = "runtime_flow_coverage_report.json"
DEBUG_SUMMARY_NAME = "runtime_debug_summary.json"
RUNTIME_INDEX_NAME = "runtime_index.json"

AGENTS = {"system", "agent1", "agent2", "agent3", "agent4", "agent5", "agent6", "studio", "runner", "console"}
PHASES = {"planning", "rtl", "formal", "hitl", "dv", "physical", "signoff", "studio", "backend", "runner"}
TERMINAL_EVENT_TYPES = {"job_done", "runtime_error", "watchdog_timeout", "runtime_recovered"}
PROGRESS_EVENT_TYPES = {"node_start", "node_done", "model_call_done", "artifact_written", "job_started", "job_done"}
STRICT_PAIR_KINDS = {"tool_call"}
WARNING_PAIR_KINDS = {"agent", "model_call"}
AGENT1_CLUSTER_EVENT_TYPES = {
    "agent1_topology_loaded",
    "agent1_cluster_assignment",
    "agent1_group_session_start",
    "agent1_group_session_done",
    "agent1_group_session_failed",
    "agent1_group_retry",
    "agent1_leaf_expert_start",
    "agent1_leaf_expert_done",
    "agent1_leaf_expert_failed",
    "agent1_leaf_expert_retry",
    "agent1_cross_group_challenge",
    "agent1_principal_group_review",
    "agent1_clarification_question",
    "agent1_clarification_answer",
    "agent1_council_mode_selected",
}
AGENT1_GROUP_SESSION_TERMINALS = {"agent1_group_session_done", "agent1_group_session_failed"}
RUNTIME_SOURCE_FIELDS = {
    "type",
    "run_id",
    "revision_id",
    "iteration",
    "span_id",
    "parent_span_id",
    "group_id",
    "target_group_id",
    "target_group_ids",
    "owner_group_id",
    "manager_id",
    "expert_id",
    "leaf_expert_ids",
    "guest_expert_ids",
    "group_count",
    "attachment_ids",
    "run_span_id",
    "ui_action_span_id",
    "backend_request_span_id",
    "job_span_id",
    "process_span_id",
    "agent_span_id",
    "artifact_span_id",
    "event_id",
    "last_event_id",
    "replay_event_id",
    "model_call_id",
    "attempt",
    "retry_count",
    "backoff_s",
    "error_class",
    "latency_s",
    "latency_ms",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "estimated_cost_usd",
    "confidence",
    "mode",
    "topology_hash",
    "cluster_assignment_hash",
    "challenge_id",
    "question_id",
    "answer_id",
    "code",
    "severity",
    "artifact_ref",
    "flow_segment",
    "source_layer",
    "options",
    "status",
    "resolution",
    "from_agent",
    "to_agent",
    "contract",
    "action_required",
    "prompt_sha256",
    "response_sha256",
}
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

def _runtime_source(source: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        return None
    compact = {key: source.get(key) for key in RUNTIME_SOURCE_FIELDS if key in source}
    if "type" not in compact:
        compact["type"] = source.get("type") or "source_event"
    return redact_runtime_payload(compact)


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


def read_debug_issues(output_dir: str | Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    path = runtime_file(output_dir, DEBUG_ISSUES_NAME)
    if not path.is_file():
        return []
    issues: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            item = {"type": "debug_issue", "severity": "warning", "source": "runtime", "code": "invalid_debug_issue_jsonl", "message": line[:200]}
        if isinstance(item, dict):
            issues.append(redact_runtime_payload(item))
    return issues[-limit:] if limit else issues


def load_runtime_bundle(output_dir: str | Path, *, recent_limit: int = 400) -> dict[str, Any]:
    trace_dir = runtime_trace_dir(output_dir)
    manifest = _safe_read_json(trace_dir / MANIFEST_NAME)
    signoff = load_agent1_signoff_bundle(output_dir)
    return {
        "manifest": manifest.get("payload"),
        "recentEvents": read_runtime_events(output_dir, limit=recent_limit),
        "debugIssues": read_debug_issues(output_dir, limit=recent_limit),
        "signoff": signoff,
        "recoveryReport": _safe_read_json(trace_dir / RECOVERY_NAME).get("payload"),
        "invariantReport": _safe_read_json(trace_dir / INVARIANT_NAME).get("payload"),
        "replayReport": _safe_read_json(trace_dir / REPLAY_NAME).get("payload"),
        "flowCoverage": _safe_read_json(trace_dir / FLOW_COVERAGE_NAME).get("payload"),
        "debugSummary": _safe_read_json(trace_dir / DEBUG_SUMMARY_NAME).get("payload"),
        "errors": [item for item in (
            manifest.get("error"),
            _safe_read_json(trace_dir / RECOVERY_NAME).get("error"),
            _safe_read_json(trace_dir / INVARIANT_NAME).get("error"),
            _safe_read_json(trace_dir / REPLAY_NAME).get("error"),
            _safe_read_json(trace_dir / FLOW_COVERAGE_NAME).get("error"),
            _safe_read_json(trace_dir / DEBUG_SUMMARY_NAME).get("error"),
            *(signoff.get("errors") or []),
        ) if item],
    }

def load_agent1_signoff_bundle(output_dir: str | Path) -> dict[str, Any]:
    agent1_dir = Path(output_dir) / "reports" / "agent1"
    files = {
        "certificate": "agent1_final_signoff_certificate.json",
        "gateReport": "agent1_signoff_gate_report.json",
        "evidenceManifest": "agent1_signoff_evidence_manifest.json",
        "runtimeManifest": "agent1_signoff_runtime_manifest.json",
        "handoff": "agent1_to_agent2_signoff_handoff.json",
        "benchmarkReport": "agent1_signoff_benchmark_report.json",
        "falsePassReport": "agent1_signoff_false_pass_report.json",
        "oracleDisagreements": "agent1_signoff_oracle_disagreements.json",
        "benchmarkManifestHash": "agent1_signoff_benchmark_manifest_hash.json",
        "waivers": "signoff_waivers.json",
    }
    bundle: dict[str, Any] = {
        "schema_version": "studio.agent1_signoff_bundle.v1",
        "state": "NOT_REACHED",
        "stateReason": "Agent1 signoff artifacts have not been generated yet.",
        "artifactRefs": {},
        "artifactStatus": {},
        "errors": [],
    }
    for key, filename in files.items():
        path = agent1_dir / filename
        bundle["artifactRefs"][key] = str(path)
        bundle["artifactStatus"][key] = {"path": str(path), "exists": path.is_file()}
        parsed = _safe_read_json(path)
        bundle[key] = parsed.get("payload")
        if parsed.get("error"):
            bundle["errors"].append({key: parsed["error"]})
    partial = agent1_dir / "agent1_partial_evidence.json"
    if partial.is_file() and not bundle.get("certificate"):
        bundle["state"] = "PARTIAL"
        bundle["stateReason"] = "Agent1 stopped with partial output before signoff."
    elif bundle.get("certificate"):
        cert = bundle.get("certificate") if isinstance(bundle.get("certificate"), dict) else {}
        decision = str(cert.get("decision") or "").upper()
        handoff_allowed = cert.get("handoff_allowed")
        if decision == "PASS" and handoff_allowed is True:
            bundle["state"] = "PASSED"
            bundle["stateReason"] = "Agent1 final signoff certificate passed."
        elif handoff_allowed is False:
            bundle["state"] = "BLOCKED"
            bundle["stateReason"] = "Agent1 final signoff exists but blocks Agent2 handoff."
        else:
            bundle["state"] = "FAILED" if decision in {"FAIL", "FAILED"} else "BLOCKED"
            bundle["stateReason"] = f"Agent1 signoff decision is {decision or 'unknown'}."
    elif bundle.get("gateReport") or bundle.get("handoff"):
        bundle["state"] = "BLOCKED"
        bundle["stateReason"] = "Signoff started but final certificate is missing."
    return redact_runtime_payload(bundle)


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
        self._lock = threading.RLock()
        self._active_agent_corr: dict[str, str] = {}
        self._active_node_corr: dict[tuple[str, str], str] = {}
        self._active_model_corr: dict[str, list[str]] = {}
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
        if str(event.get("type") or "") == "debug_issue":
            self._write_debug_issues(state, [event])
        else:
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
        if kind == "start_preflight":
            status = _status(str(event.get("status") or "pass"))
            return [
                self._build_event(
                    state=state,
                    event_type="node_done",
                    status="failed" if status == "failed" else "passed",
                    message=str(event.get("message") or "start credential preflight"),
                    agent="system",
                    phase="backend",
                    node_id="START.PREFLIGHT",
                    correlation_id=f"preflight:{state.get('run_id') or ''}",
                    error={"message": event.get("message") or "start credential preflight failed"} if status == "failed" else None,
                    source={**event, "flow_segment": "credential_preflight", "source_layer": "backend"},
                )
            ]
        if kind in {"websocket_connect", "websocket_replay", "websocket_hydrate"}:
            return [
                self._build_event(
                    state=state,
                    event_type="node_done",
                    status=_status(str(event.get("status") or "pass")),
                    message=str(event.get("message") or kind),
                    agent="studio",
                    phase="studio",
                    node_id=f"WEBSOCKET.{_slug(kind).upper()}",
                    correlation_id=f"websocket:{state.get('run_id') or ''}",
                    source={**event, "flow_segment": "websocket", "source_layer": "frontend"},
                )
            ]
        if kind in AGENT1_CLUSTER_EVENT_TYPES:
            return [self._agent1_cluster_event(event, state)]
        if kind == "debug_issue":
            severity = str(event.get("severity") or "warning").lower()
            return [
                self._build_event(
                    state=state,
                    event_type="debug_issue",
                    status="failed" if severity in {"error", "fatal"} else "running",
                    message=str(event.get("message") or event.get("code") or "debug issue"),
                    agent=str(event.get("agent") or "system"),
                    phase=str(event.get("phase") or "studio"),
                    node_id=str(event.get("node_id") or f"DEBUG.{_slug(str(event.get('code') or 'issue')).upper()}"),
                    correlation_id=f"issue:{state.get('run_id') or ''}:{uuid.uuid4()}",
                    artifact_refs=[str(event.get("artifact_ref"))] if event.get("artifact_ref") else [],
                    error={"severity": severity, "code": event.get("code"), "details": event.get("details")} if severity in {"warning", "error", "fatal"} else None,
                    source={"type": "debug_issue"},
                )
            ]
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
            runtime_type = _trace_runtime_type(event_type, status_value)
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

    def _agent1_cluster_event(self, event: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        kind = str(event.get("type") or "agent1_cluster_event")
        group_id = str(event.get("group_id") or event.get("target_group_id") or event.get("owner_group_id") or "")
        iteration = str(event.get("iteration") or "1")
        span_id = str(event.get("span_id") or event.get("model_call_id") or f"{kind}:{iteration}:{group_id or 'global'}")
        status = _agent1_cluster_status(kind, event)
        node_id = _agent1_cluster_node_id(kind, group_id)
        source = dict(event)
        source["type"] = kind
        return self._build_event(
            state=state,
            event_type=kind,
            status=status,
            message=str(event.get("message") or event.get("summary") or kind),
            agent="agent1",
            phase="planning",
            node_id=node_id,
            correlation_id=f"agent1-cluster:{state.get('run_id') or ''}:{span_id}",
            duration_ms=_cluster_duration_ms(event),
            metrics=_cluster_metrics(event),
            error={"message": event.get("message") or kind, "code": kind} if status == "failed" else None,
            source=source,
        )

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
        node_id = str(event.get("node_id") or _agent_action_node_id(agent, action))
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
            "source": _runtime_source(source),
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
        active = self._active_model_corr.setdefault(agent, [])
        if start or not active:
            key = (agent, action if action else "model_call")
            self._model_ordinals[key] = self._model_ordinals.get(key, 0) + 1
            corr = f"model:{state.get('run_id') or ''}:{agent}:{_slug(action or 'model_call')}:{self._model_ordinals[key]}"
            if start:
                active.append(corr)
            return corr
        corr = active.pop(0)
        if not active:
            self._active_model_corr.pop(agent, None)
        return corr

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
            flow = build_runtime_flow_coverage_report(output_dir, manifest=manifest, events=all_events)
            debug = build_runtime_debug_summary(output_dir, manifest=manifest, invariant=invariant, replay=replay, flow=flow, events=all_events)
            _write_json_atomic(trace_dir / INVARIANT_NAME, invariant)
            _write_json_atomic(trace_dir / REPLAY_NAME, replay)
            _write_json_atomic(trace_dir / FLOW_COVERAGE_NAME, flow)
            _write_json_atomic(trace_dir / DEBUG_SUMMARY_NAME, debug)
            self._write_invariant_debug_issues(state, invariant)
            _ensure_default_recovery_report(output_dir, state, manifest)
            _write_runtime_index(self.root, manifest)

    def _write_debug_issues(self, state: dict[str, Any], issues: list[dict[str, Any]]) -> None:
        output_dir = str(state.get("output_dir") or "")
        if not output_dir or not issues:
            return
        with self._lock:
            trace_dir = runtime_trace_dir(output_dir)
            trace_dir.mkdir(parents=True, exist_ok=True)
            path = trace_dir / DEBUG_ISSUES_NAME
            with path.open("a", encoding="utf-8") as handle:
                for issue in issues:
                    clean = {
                        "type": "debug_issue",
                        "schema_version": str(issue.get("schema_version") or "swarm.debug_issue.v1"),
                        "severity": str(issue.get("severity") or "warning"),
                        "source": str(issue.get("source") or "backend"),
                        "code": str(issue.get("code") or "debug_issue"),
                        "message": str(issue.get("message") or issue.get("code") or "debug issue"),
                        "details": issue.get("details") or {},
                        "run_id": str(issue.get("run_id") or state.get("run_id") or ""),
                        "revision_id": str(issue.get("revision_id") or ""),
                        "artifact_ref": str(issue.get("artifact_ref") or ""),
                        "node_id": str(issue.get("node_id") or ""),
                        "timestamp": str(issue.get("timestamp") or utc_now_iso()),
                    }
                    for key in ("flow_segment", "source_layer", "span_id", "parent_span_id", "group_id", "model_call_id"):
                        if issue.get(key) is not None:
                            clean[key] = str(issue.get(key) or "")
                    handle.write(json.dumps(redact_runtime_payload(clean), ensure_ascii=False, sort_keys=True) + "\n")

    def _write_invariant_debug_issues(self, state: dict[str, Any], invariant: dict[str, Any]) -> None:
        output_dir = str(state.get("output_dir") or "")
        if not output_dir:
            return
        issues = _debug_issues_from_invariant(state, output_dir, invariant)
        if not issues:
            return
        self._write_debug_issues(state, issues)


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
    agent1_cluster_council = _agent1_cluster_council_from_events(events)
    flow_coverage = _flow_coverage_from_events(events, state=state)
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
            "attachment_manifest_path": str(state.get("attachment_manifest_path") or ""),
            "attachment_context_path": str(state.get("attachment_context_path") or ""),
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
            "agent1_cluster_council": agent1_cluster_council,
            "flow_coverage": flow_coverage,
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
    source = event.get("source") if isinstance(event.get("source"), dict) else {}
    if str(event.get("event_type") or "") in AGENT1_CLUSTER_EVENT_TYPES:
        group_id = str(source.get("group_id") or source.get("target_group_id") or source.get("owner_group_id") or "")
        cluster = metrics.setdefault("agent1Cluster", {"groups": {}})
        if group_id:
            group_metrics = cluster.setdefault("groups", {}).setdefault(group_id, {"callCount": 0, "retryCount": 0, "failureCount": 0})
            if str(event.get("event_type") or "") in {"agent1_group_session_done", "agent1_leaf_expert_done"}:
                group_metrics["callCount"] = int(group_metrics.get("callCount") or 0) + 1
            if str(event.get("event_type") or "") in {"agent1_group_session_failed", "agent1_leaf_expert_failed"}:
                group_metrics["failureCount"] = int(group_metrics.get("failureCount") or 0) + 1
            if str(event.get("event_type") or "") in {"agent1_group_retry", "agent1_leaf_expert_retry"}:
                group_metrics["retryCount"] = int(group_metrics.get("retryCount") or 0) + 1
            for key in ("latency_s", "latency_ms", "prompt_tokens", "completion_tokens", "total_tokens", "estimated_cost_usd"):
                if key in event_metrics:
                    group_metrics[key] = event_metrics[key]
    metrics["source"] = "runtime_event"

FLOW_SEGMENT_DEFS: tuple[dict[str, str], ...] = (
    {"id": "frontend_input", "label": "Frontend Input", "owner": "frontend"},
    {"id": "settings_preflight", "label": "Settings/Test Connection", "owner": "frontend"},
    {"id": "credential_preflight", "label": "Credential Preflight", "owner": "backend"},
    {"id": "attachment_staging", "label": "Attachment Staging", "owner": "backend"},
    {"id": "start_request", "label": "Start Request", "owner": "backend"},
    {"id": "job_queue", "label": "Job Queue", "owner": "backend"},
    {"id": "runner_process", "label": "Runner Process", "owner": "runner"},
    {"id": "websocket", "label": "WebSocket Replay/Hydration", "owner": "websocket"},
    {"id": "live_input", "label": "Live Follow-Up Input", "owner": "frontend"},
    {"id": "agent1_intake", "label": "Agent1 Intake", "owner": "agent1"},
    {"id": "agent1_cluster", "label": "Agent1 Cluster Council", "owner": "agent1"},
    {"id": "agent1_guardrail", "label": "Agent1 Guardrails", "owner": "agent1"},
    {"id": "plan_review", "label": "Plan Review", "owner": "frontend"},
    {"id": "agent1_artifacts", "label": "Agent1 Artifacts", "owner": "artifact"},
    {"id": "agent2_gate", "label": "Agent2 Handoff Gate", "owner": "agent2"},
    {"id": "agent2_rtl", "label": "Agent2 RTL", "owner": "agent2"},
    {"id": "downstream_agents", "label": "Agent3/4/5 Downstream", "owner": "agent3"},
    {"id": "signoff", "label": "Final Signoff", "owner": "signoff"},
)

FLOW_SEGMENT_ORDER = {item["id"]: index for index, item in enumerate(FLOW_SEGMENT_DEFS)}

def _flow_coverage_from_events(events: list[dict[str, Any]], *, state: dict[str, Any] | None = None, debug_issues: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    state = state or {}
    debug_issues = debug_issues or []
    segments = {
        item["id"]: {
            "id": item["id"],
            "label": item["label"],
            "owner_layer": item["owner"],
            "status": "missing",
            "first_timestamp": "",
            "last_timestamp": "",
            "span_ids": [],
            "last_issue_code": "",
        }
        for item in FLOW_SEGMENT_DEFS
    }

    def mark(segment_id: str, status: str, event: dict[str, Any] | None = None, *, issue_code: str = "") -> None:
        if segment_id not in segments:
            return
        segment = segments[segment_id]
        current = str(segment.get("status") or "missing")
        if _flow_status_rank(status) >= _flow_status_rank(current):
            segment["status"] = status
        ts = str((event or {}).get("timestamp") or "")
        if ts and not segment["first_timestamp"]:
            segment["first_timestamp"] = ts
        if ts:
            segment["last_timestamp"] = ts
        corr = str((event or {}).get("correlation_id") or "")
        if corr and corr not in segment["span_ids"]:
            segment["span_ids"].append(corr)
        if issue_code:
            segment["last_issue_code"] = issue_code

    if state.get("run_id"):
        mark("frontend_input", "completed")
    if state.get("attachment_manifest_path"):
        mark("attachment_staging", "completed")
    if not state.get("attachment_manifest_path"):
        mark("attachment_staging", "skipped")

    agent1_cluster_event_seen = False
    agent1_fast_path_seen = False
    for event in events:
        event_type = str(event.get("event_type") or "")
        status = str(event.get("status") or "")
        node_id = str(event.get("node_id") or "")
        agent = str(event.get("agent") or "")
        message = str(event.get("message") or "")
        source = event.get("source") if isinstance(event.get("source"), dict) else {}
        source_type = str(source.get("type") or "")
        source_flow = str(source.get("flow_segment") or "")
        if source_flow:
            mark(source_flow, "failed" if status == "failed" else "completed" if status in {"passed", "queued", "cancelled"} else "started", event)
        if event_type == "run_init":
            mark("start_request", "completed", event)
        if event_type == "job_queued":
            mark("job_queue", "started", event)
        if event_type == "job_started":
            mark("job_queue", "completed", event)
            mark("runner_process", "started", event)
        if event_type == "job_done":
            mark("runner_process", "failed" if status == "failed" else "completed", event)
            if status == "passed":
                mark("signoff", "completed", event)
            elif status in {"failed", "cancelled"}:
                mark("signoff", "failed" if status == "failed" else "skipped", event)
        if event_type == "watchdog_timeout":
            mark("runner_process", "failed", event, issue_code="watchdog_timeout")
        if event_type in {"tool_call_start", "tool_call_done"} and "LIVE_INPUT" in node_id:
            mark("live_input", "failed" if status == "failed" else "completed" if event_type.endswith("_done") else "started", event)
        if source_type in {"websocket_connect", "websocket_replay", "websocket_hydrate"} or "WEBSOCKET" in node_id:
            mark("websocket", "failed" if status == "failed" else "completed", event)
        if "INTAKE" in node_id or "intake" in message.lower():
            mark("agent1_intake", "failed" if status == "failed" else "completed" if status in {"passed", "paused"} else "started", event)
        if event_type in AGENT1_CLUSTER_EVENT_TYPES:
            agent1_cluster_event_seen = True
            mark("agent1_cluster", "failed" if status == "failed" else "completed" if event_type in {"agent1_principal_group_review", "agent1_group_session_done"} else "started", event)
        if "SIMPLE_DESIGN_FAST_PATH" in node_id or "simple design fast-path" in message.lower():
            agent1_fast_path_seen = True
        if "GUARDRAIL" in node_id or "guardrail" in message.lower():
            mark("agent1_guardrail", "failed" if status == "failed" else "completed" if status == "passed" else "started", event)
        if "PLAN_REVIEW" in node_id or "PLAN_REVIEW" in message or source.get("action_required") == "PLAN_REVIEW":
            mark("plan_review", "failed" if status == "failed" else "started" if status == "paused" else "completed", event)
        if event_type == "artifact_written" and (agent == "agent1" or "agent1" in " ".join(str(ref) for ref in event.get("artifact_refs") or [])):
            mark("agent1_artifacts", "failed" if status == "failed" else "completed", event)
        if event_type == "tool_call_done" and (str(source.get("to_agent") or "") == "agent2" or "agent2" in str(source.get("contract") or "").lower() or "AGENT2" in node_id):
            mark("agent2_gate", "failed" if status == "failed" else "completed", event)
        if agent == "agent2" or node_id.startswith("STAGE.RTL") or ("RTL" in node_id and not node_id.startswith("HANDOFF.")):
            mark("agent2_rtl", "failed" if status == "failed" else "completed" if status == "passed" else "started", event)
        if agent in {"agent3", "agent4", "agent5"} or any(token in node_id for token in ("AGENT3", "AGENT4", "AGENT5", "FORMAL", "DV", "PHYSICAL")):
            mark("downstream_agents", "failed" if status == "failed" else "completed" if status == "passed" else "started", event)
        if event_type in TERMINAL_EVENT_TYPES and status == "failed":
            mark("signoff", "failed", event, issue_code=event_type)

    for optional in ("settings_preflight", "job_queue", "websocket", "live_input", "downstream_agents"):
        if segments[optional]["status"] == "missing":
            segments[optional]["status"] = "skipped"
    cluster_manifest = state.get("agent1_cluster_council") if isinstance(state.get("agent1_cluster_council"), dict) else {}
    cluster_mode = str(cluster_manifest.get("mode") or "").lower()
    if not agent1_cluster_event_seen and (agent1_fast_path_seen or cluster_mode in {"legacy", "fast_path", "simple_fast_path", "deterministic_fast_path"}):
        for optional in ("agent1_cluster", "agent1_guardrail"):
            if segments[optional]["status"] == "missing":
                segments[optional]["status"] = "skipped"
                segments[optional]["last_issue_code"] = ""
    if segments["credential_preflight"]["status"] == "missing" and segments["runner_process"]["status"] in {"started", "completed"}:
        segments["credential_preflight"]["last_issue_code"] = "flow_missing_credential_preflight"
    if segments["agent2_gate"]["status"] == "missing" and segments["agent2_rtl"]["status"] in {"started", "completed", "failed"}:
        segments["agent2_gate"]["last_issue_code"] = "flow_missing_agent2_gate"

    for issue in debug_issues:
        details = issue.get("details") if isinstance(issue.get("details"), dict) else {}
        segment_id = str(issue.get("flow_segment") or details.get("flow_segment") or "")
        if segment_id in segments:
            if str(issue.get("code") or "") == "flow_missing_required_span" and str(segments[segment_id].get("status") or "") == "skipped":
                continue
            mark(segment_id, "failed" if str(issue.get("severity") or "") in {"error", "fatal"} else str(segments[segment_id]["status"]), issue, issue_code=str(issue.get("code") or "debug_issue"))

    missing = [segment_id for segment_id, segment in segments.items() if segment["status"] == "missing"]
    failed = [segment_id for segment_id, segment in segments.items() if segment["status"] == "failed"]
    return redact_runtime_payload(
        {
            "schema_version": "studio.runtime_flow_coverage.v1",
            "segments": segments,
            "missing_segments": missing,
            "failed_segments": failed,
            "missing_span_count": len(missing),
            "failed_segment_count": len(failed),
            "ok": not failed and not any(segments[item]["last_issue_code"] for item in segments if segments[item]["status"] == "missing"),
        }
    )

def _flow_status_rank(status: str) -> int:
    return {"missing": 0, "skipped": 1, "started": 2, "completed": 3, "failed": 4}.get(status, 0)

def _agent1_cluster_council_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    group_sessions: dict[str, dict[str, Any]] = {}
    assignments: list[dict[str, Any]] = []
    leaf_experts: dict[str, dict[str, Any]] = {}
    retry_tree: list[dict[str, Any]] = []
    challenges: list[dict[str, Any]] = []
    principal_reviews: list[dict[str, Any]] = []
    questions: dict[str, dict[str, Any]] = {}
    answers: list[dict[str, Any]] = []
    mode = "legacy"
    topology_hash = ""
    cluster_assignment_hash = ""
    for event in events:
        event_type = str(event.get("event_type") or "")
        if event_type not in AGENT1_CLUSTER_EVENT_TYPES:
            continue
        source = event.get("source") if isinstance(event.get("source"), dict) else {}
        timestamp = str(event.get("timestamp") or "")
        group_id = str(source.get("group_id") or source.get("target_group_id") or source.get("owner_group_id") or "")
        session_key = _cluster_session_key(event, source)
        if event_type == "agent1_council_mode_selected":
            mode = str(source.get("mode") or "group_session")
        elif event_type == "agent1_topology_loaded":
            topology_hash = str(source.get("topology_hash") or topology_hash)
        elif event_type == "agent1_cluster_assignment":
            cluster_assignment_hash = str(source.get("cluster_assignment_hash") or cluster_assignment_hash)
            assignments.append(_cluster_source_snapshot(event, source))
        elif event_type in {"agent1_group_session_start", "agent1_group_session_done", "agent1_group_session_failed"}:
            session = group_sessions.setdefault(
                session_key,
                {
                    "span_id": str(source.get("span_id") or session_key),
                    "group_id": group_id,
                    "manager_id": str(source.get("manager_id") or ""),
                    "leaf_expert_ids": source.get("leaf_expert_ids") or [],
                    "guest_expert_ids": source.get("guest_expert_ids") or [],
                    "attempt": source.get("attempt") or 1,
                    "status": "running",
                    "metrics": {},
                },
            )
            session["status"] = "failed" if event_type == "agent1_group_session_failed" else "passed" if event_type == "agent1_group_session_done" else "running"
            session["updated_at"] = timestamp
            if event_type == "agent1_group_session_start":
                session["started_at"] = timestamp
            else:
                session["ended_at"] = timestamp
            session["metrics"] = {**(session.get("metrics") or {}), **(event.get("metrics") if isinstance(event.get("metrics"), dict) else {})}
            session["model_call_id"] = str(source.get("model_call_id") or session.get("model_call_id") or "")
            session["confidence"] = source.get("confidence", session.get("confidence"))
        elif event_type in {"agent1_leaf_expert_start", "agent1_leaf_expert_done", "agent1_leaf_expert_failed", "agent1_leaf_expert_retry"}:
            expert_id = str(source.get("expert_id") or session_key)
            leaf = leaf_experts.setdefault(
                expert_id,
                {
                    "expert_id": expert_id,
                    "span_id": str(source.get("span_id") or session_key),
                    "group_id": group_id,
                    "iteration": source.get("iteration") or 1,
                    "status": "running",
                    "retry_count": 0,
                    "metrics": {},
                },
            )
            leaf["updated_at"] = timestamp
            leaf["model_call_id"] = str(source.get("model_call_id") or leaf.get("model_call_id") or "")
            if event_type == "agent1_leaf_expert_start":
                leaf["status"] = "running"
                leaf["started_at"] = timestamp
            elif event_type == "agent1_leaf_expert_retry":
                leaf["retry_count"] = max(int(leaf.get("retry_count") or 0), int(source.get("retry_count") or 1))
                leaf.setdefault("retry_events", []).append(_cluster_source_snapshot(event, source))
            else:
                leaf["status"] = "failed" if event_type == "agent1_leaf_expert_failed" else "passed"
                leaf["ended_at"] = timestamp
                leaf["retry_count"] = max(int(leaf.get("retry_count") or 0), int(source.get("retry_count") or 0))
                if source.get("error_class"):
                    leaf["error_class"] = str(source.get("error_class"))
            leaf["metrics"] = {**(leaf.get("metrics") or {}), **(event.get("metrics") if isinstance(event.get("metrics"), dict) else {})}
        elif event_type == "agent1_group_retry":
            retry_tree.append(_cluster_source_snapshot(event, source))
        elif event_type == "agent1_cross_group_challenge":
            challenges.append(_cluster_source_snapshot(event, source))
        elif event_type == "agent1_principal_group_review":
            principal_reviews.append(_cluster_source_snapshot(event, source))
        elif event_type == "agent1_clarification_question":
            question_id = str(source.get("question_id") or session_key)
            questions[question_id] = _cluster_source_snapshot(event, source)
        elif event_type == "agent1_clarification_answer":
            answers.append(_cluster_source_snapshot(event, source))
    answered = {str((item.get("source") or {}).get("question_id") or item.get("question_id") or "") for item in answers}
    pending = [question_id for question_id in questions if question_id not in answered]
    return redact_runtime_payload(
        {
            "schema_version": "studio.agent1_cluster_council.v1",
            "mode": mode,
            "topology_hash": topology_hash,
            "cluster_assignment_hash": cluster_assignment_hash,
            "cluster_assignments": assignments[-20:],
            "group_sessions": group_sessions,
            "leaf_experts": leaf_experts,
            "retry_tree": retry_tree[-50:],
            "challenges": challenges[-50:],
            "principal_reviews": principal_reviews[-50:],
            "clarification": {
                "questions": list(questions.values())[-50:],
                "answers": answers[-50:],
                "pending_question_ids": pending,
            },
        }
    )

def _cluster_session_key(event: dict[str, Any], source: dict[str, Any]) -> str:
    return str(
        source.get("span_id")
        or source.get("model_call_id")
        or event.get("correlation_id")
        or f"{source.get('iteration') or 1}:{source.get('group_id') or source.get('target_group_id') or 'global'}:{source.get('attempt') or 1}"
    )

def _cluster_source_snapshot(event: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    return redact_runtime_payload(
        {
            "event_type": event.get("event_type"),
            "status": event.get("status"),
            "timestamp": event.get("timestamp"),
            "node_id": event.get("node_id"),
            "message": event.get("message"),
            "source": source,
            "metrics": event.get("metrics") or {},
        }
    )


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
                elif key[0] in WARNING_PAIR_KINDS:
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
        elif kind in WARNING_PAIR_KINDS and status in {"done", "failed", "stopped", "recovered"}:
            warnings.append(issue)
    _check_agent1_cluster_invariants(events, manifest, failures, warnings)
    _check_flow_coverage_invariants(events, manifest, output_dir, failures, warnings)
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
        "agent1_leaf_resilience": _agent1_leaf_resilience_summary(events),
    }
    return redact_runtime_payload(report)


def _agent1_leaf_resilience_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    leaf: dict[str, dict[str, Any]] = {}
    for event in events:
        event_type = str(event.get("event_type") or "")
        if event_type not in {"agent1_leaf_expert_start", "agent1_leaf_expert_retry", "agent1_leaf_expert_done", "agent1_leaf_expert_failed"}:
            continue
        source = event.get("source") if isinstance(event.get("source"), dict) else {}
        expert_id = str(source.get("expert_id") or source.get("span_id") or event.get("correlation_id") or "")
        if not expert_id:
            continue
        item = leaf.setdefault(expert_id, {"expert_id": expert_id, "status": "unknown", "retry_count": 0, "events": []})
        item["events"].append(event_type)
        if event_type == "agent1_leaf_expert_retry":
            item["retry_count"] = max(int(item.get("retry_count") or 0), int(source.get("retry_count") or len([name for name in item["events"] if name == "agent1_leaf_expert_retry"])))
        elif event_type == "agent1_leaf_expert_done":
            item["status"] = "passed"
        elif event_type == "agent1_leaf_expert_failed":
            item["status"] = "failed"
            item["retry_count"] = max(int(item.get("retry_count") or 0), int(source.get("retry_count") or 0))
            if source.get("error_class"):
                item["error_class"] = str(source.get("error_class"))
    failed = [item for item in leaf.values() if item.get("status") == "failed"]
    retried = [item for item in leaf.values() if int(item.get("retry_count") or 0) > 0]
    return {
        "leaf_count": len(leaf),
        "failed_count": len(failed),
        "retried_count": len(retried),
        "failed_expert_ids": sorted(str(item.get("expert_id")) for item in failed),
        "retried_expert_ids": sorted(str(item.get("expert_id")) for item in retried),
        "leaf_experts": leaf,
    }


def _debug_issues_from_invariant(state: dict[str, Any], output_dir: str, invariant: dict[str, Any]) -> list[dict[str, Any]]:
    artifact_ref = str(runtime_file(output_dir, INVARIANT_NAME))
    issues: list[dict[str, Any]] = []
    for severity, findings in (("error", invariant.get("failures")), ("warning", invariant.get("warnings"))):
        if not isinstance(findings, list):
            continue
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            code = str(finding.get("code") or "runtime_invariant")
            issues.append(
                {
                    "type": "debug_issue",
                    "schema_version": "swarm.debug_issue.v1",
                    "severity": severity,
                    "source": "runtime",
                    "code": code,
                    "message": f"Runtime invariant {severity}: {code}",
                    "details": {
                        "finding": finding,
                        "invariant_ok": invariant.get("ok"),
                        "checked_at": invariant.get("checked_at"),
                    },
                    "flow_segment": str(finding.get("flow_segment") or ""),
                    "source_layer": str(finding.get("source_layer") or ""),
                    "span_id": str(finding.get("span_id") or finding.get("correlation_id") or ""),
                    "run_id": str(state.get("run_id") or invariant.get("run_id") or ""),
                    "revision_id": "",
                    "artifact_ref": artifact_ref,
                    "node_id": "RUNTIME.INVARIANT",
                    "timestamp": str(invariant.get("checked_at") or utc_now_iso()),
                }
            )
    return issues


def _debug_issue_signature(issue: dict[str, Any]) -> tuple[str, str, str, str, str]:
    details = issue.get("details") if isinstance(issue.get("details"), dict) else {}
    finding = details.get("finding") if isinstance(details.get("finding"), dict) else {}
    return (
        str(issue.get("run_id") or ""),
        str(issue.get("source") or ""),
        str(issue.get("code") or ""),
        str(finding.get("kind") or ""),
        str(finding.get("correlation_id") or finding.get("index") or finding.get("location") or ""),
    )


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
        "flow_coverage": manifest.get("flow_coverage") or _flow_coverage_from_events(events, state={"run_id": manifest.get("run_id") or ""}),
        "replay_status": "pass" if events else "empty",
    }
    _write_json_atomic(runtime_file(output_dir, REPLAY_NAME), report)
    return redact_runtime_payload(report)


def build_runtime_flow_coverage_report(output_dir: str | Path, *, manifest: dict[str, Any] | None = None, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    events = events if events is not None else read_runtime_events(output_dir)
    manifest = manifest if manifest is not None else _safe_read_json(runtime_file(output_dir, MANIFEST_NAME)).get("payload") or {}
    issues = read_debug_issues(output_dir)
    coverage = _flow_coverage_from_events(events, state=manifest, debug_issues=issues)
    missing_span_findings = _flow_missing_span_findings(coverage)
    artifact_path = _manifest_attachment_path(manifest, output_dir)
    report = {
        "schema_version": "studio.runtime_flow_coverage_report.v1",
        "output_dir": str(output_dir),
        "checked_at": utc_now_iso(),
        "run_id": manifest.get("run_id") or "",
        "revision_id": manifest.get("revision_id") or "",
        "event_count": len(events),
        "debug_issue_count": len(issues),
        "coverage": coverage,
        "segments": coverage.get("segments") or {},
        "canonical_span_model": _canonical_span_model_from_events(events, manifest),
        "missing_span_detector": {
            "missing_span_count": len([item for item in missing_span_findings if item.get("code") == "flow_missing_required_span"]),
            "finding_count": len(missing_span_findings),
            "findings": missing_span_findings,
        },
        "artifact_check": {
            "attachment_manifest_path": str(artifact_path or ""),
            "attachment_manifest_exists": bool(artifact_path),
        },
        "ok": bool(coverage.get("ok")) and not any(item.get("code") != "flow_missing_required_span" for item in missing_span_findings),
    }
    _write_json_atomic(runtime_file(output_dir, FLOW_COVERAGE_NAME), report)
    return redact_runtime_payload(report)

def build_runtime_debug_summary(
    output_dir: str | Path,
    *,
    manifest: dict[str, Any] | None = None,
    invariant: dict[str, Any] | None = None,
    replay: dict[str, Any] | None = None,
    flow: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    events = events if events is not None else read_runtime_events(output_dir)
    manifest = manifest if manifest is not None else _safe_read_json(runtime_file(output_dir, MANIFEST_NAME)).get("payload") or {}
    invariant = invariant if invariant is not None else _safe_read_json(runtime_file(output_dir, INVARIANT_NAME)).get("payload") or {}
    replay = replay if replay is not None else _safe_read_json(runtime_file(output_dir, REPLAY_NAME)).get("payload") or {}
    flow = flow if flow is not None else _safe_read_json(runtime_file(output_dir, FLOW_COVERAGE_NAME)).get("payload") or {}
    flow_coverage = flow.get("coverage") if isinstance(flow.get("coverage"), dict) else manifest.get("flow_coverage") if isinstance(manifest.get("flow_coverage"), dict) else {}
    flow_missing = flow.get("missing_span_detector") if isinstance(flow.get("missing_span_detector"), dict) else {}
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
        "flow_coverage_ok": flow.get("ok", flow_coverage.get("ok")),
        "flow_missing_span_count": flow_missing.get("missing_span_count", flow_coverage.get("missing_span_count")),
        "flow_failed_segment_count": flow_coverage.get("failed_segment_count"),
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
    event_type = str(event.get("event_type") or "")
    for ref in event.get("artifact_refs") or []:
        if not isinstance(ref, str) or not ref:
            continue
        path = Path(ref)
        if path.is_absolute() and not is_path_inside(path, root):
            failures.append({"code": "artifact_outside_output_sandbox", "index": index, "path": ref})
        if ".." in path.parts:
            failures.append({"code": "artifact_relative_traversal", "index": index, "path": ref})
        if event_type == "artifact_written":
            resolved = path if path.is_absolute() else root / path
            if not resolved.exists():
                failures.append({"code": "flow_missing_artifact_file", "index": index, "path": ref, "flow_segment": "agent1_artifacts" if str(event.get("agent") or "") == "agent1" else "agent2_gate", "source_layer": "artifact"})

def _check_agent1_cluster_invariants(events: list[dict[str, Any]], manifest: dict[str, Any], failures: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    known_groups: set[str] = set()
    known_questions: set[str] = set()
    answered_questions: set[str] = set()
    span_ids: set[str] = set()
    group_starts: dict[str, dict[str, Any]] = {}
    group_failures: dict[str, dict[str, Any]] = {}
    leaf_starts: dict[str, dict[str, Any]] = {}
    leaf_retries: dict[str, int] = {}
    challenges: dict[str, dict[str, Any]] = {}
    agent2_handoff_seen = False
    status = str(manifest.get("status") or "")
    terminal = status in {"done", "failed", "stopped", "recovered"}
    for index, event in enumerate(events):
        event_type = str(event.get("event_type") or "")
        source = event.get("source") if isinstance(event.get("source"), dict) else {}
        source_type = str(source.get("type") or "")
        span_id = str(source.get("span_id") or event.get("correlation_id") or "")
        parent_span_id = str(source.get("parent_span_id") or "")
        if span_id:
            span_ids.add(span_id)
        if parent_span_id and parent_span_id not in span_ids and parent_span_id not in {"agent1:intake:done", "agent1:intake"}:
            failures.append({"code": "agent1_cluster_orphan_span", "index": index, "span_id": span_id, "parent_span_id": parent_span_id})
        for key in ("group_id", "owner_group_id"):
            if source.get(key):
                known_groups.add(str(source.get(key)))
        if source_type == "agent_handoff" and (str(source.get("to_agent") or "") == "agent2" or "agent2" in str(source.get("contract") or "").lower()):
            agent2_handoff_seen = True
        if event_type == "agent1_group_session_start":
            group_starts[span_id] = event
            group_failures.pop(span_id, None)
        elif event_type in AGENT1_GROUP_SESSION_TERMINALS:
            if parent_span_id not in group_starts:
                failures.append({"code": "agent1_group_done_without_start", "index": index, "span_id": span_id, "parent_span_id": parent_span_id, "event_type": event_type})
            else:
                group_starts.pop(parent_span_id, None)
            if event_type == "agent1_group_session_failed":
                group_failures[parent_span_id] = event
            else:
                group_failures.pop(parent_span_id, None)
        elif event_type == "agent1_principal_group_review" and group_starts:
            failures.append({"code": "agent1_principal_review_before_groups_done", "index": index, "running_group_spans": sorted(group_starts)})
        elif event_type == "agent1_group_retry":
            targets = _agent1_retry_targets(source)
            if not targets:
                failures.append({"code": "agent1_retry_target_group_unknown", "index": index, "target_group_id": ""})
            for target in targets:
                if target not in known_groups:
                    failures.append({"code": "agent1_retry_target_group_unknown", "index": index, "target_group_id": target})
                    continue
                for failed_span, failed_event in list(group_failures.items()):
                    failed_source = failed_event.get("source") if isinstance(failed_event.get("source"), dict) else {}
                    if str(failed_source.get("group_id") or "") == target:
                        group_failures.pop(failed_span, None)
        elif event_type == "agent1_leaf_expert_start":
            leaf_starts[span_id] = event
            if source.get("expert_id"):
                known_groups.add(str(source.get("group_id") or ""))
        elif event_type == "agent1_leaf_expert_retry":
            if span_id not in leaf_starts:
                failures.append({"code": "agent1_leaf_retry_without_start", "index": index, "span_id": span_id, "expert_id": source.get("expert_id")})
            leaf_retries[span_id] = leaf_retries.get(span_id, 0) + 1
        elif event_type in {"agent1_leaf_expert_done", "agent1_leaf_expert_failed"}:
            if span_id not in leaf_starts:
                failures.append({"code": "agent1_leaf_done_without_start", "index": index, "span_id": span_id, "expert_id": source.get("expert_id"), "event_type": event_type})
            else:
                leaf_starts.pop(span_id, None)
            if event_type == "agent1_leaf_expert_failed" and int(source.get("retry_count") or 0) != leaf_retries.get(span_id, 0):
                warnings.append({"code": "agent1_leaf_retry_count_mismatch", "index": index, "span_id": span_id, "expert_id": source.get("expert_id"), "source_retry_count": source.get("retry_count"), "observed_retry_count": leaf_retries.get(span_id, 0)})
        elif event_type == "agent1_cross_group_challenge":
            challenge_id = str(source.get("challenge_id") or span_id or f"challenge-{index}")
            challenges[challenge_id] = {"event": event, "resolved": _challenge_resolved(event)}
        elif event_type == "agent1_clarification_question":
            question_id = str(source.get("question_id") or span_id or f"question-{index}")
            known_questions.add(question_id)
        elif event_type == "agent1_clarification_answer":
            question_id = str(source.get("question_id") or "")
            if question_id not in known_questions:
                failures.append({"code": "agent1_clarification_answer_unknown_question", "index": index, "question_id": question_id})
            answered_questions.add(question_id)
    if group_starts:
        issue = {"code": "agent1_group_start_without_done", "running_group_spans": sorted(group_starts), "terminal_status": status}
        if terminal:
            failures.append(issue)
    if leaf_starts and terminal:
        failures.append({"code": "agent1_leaf_start_without_terminal", "running_leaf_spans": sorted(leaf_starts), "terminal_status": status})
    unresolved_challenges = [challenge_id for challenge_id, item in challenges.items() if not item.get("resolved")]
    pending_questions = sorted(question for question in known_questions if question not in answered_questions)
    if unresolved_challenges and agent2_handoff_seen:
        failures.append({"code": "agent2_handoff_with_unresolved_agent1_challenge", "challenge_ids": unresolved_challenges})
    if pending_questions and agent2_handoff_seen:
        failures.append({"code": "agent2_handoff_with_pending_agent1_clarification", "question_ids": pending_questions})
    if group_failures and agent2_handoff_seen:
        failures.append({"code": "agent2_handoff_with_unresolved_agent1_group_failure", "group_failure_spans": sorted(group_failures)})

def _check_flow_coverage_invariants(
    events: list[dict[str, Any]],
    manifest: dict[str, Any],
    output_dir: str | Path,
    failures: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    coverage = _flow_coverage_from_events(events, state=manifest)
    segments = coverage.get("segments") if isinstance(coverage.get("segments"), dict) else {}
    status = str(manifest.get("status") or "")
    terminal = status in {"done", "failed", "stopped", "recovered"}
    start_seen = any(str(event.get("event_type") or "") == "run_init" for event in events)
    process_seen = any(str(event.get("event_type") or "") in {"job_started", "job_done"} for event in events)
    preflight_seen = any(_source_type(event) == "start_preflight" or str(event.get("node_id") or "") == "START.PREFLIGHT" for event in events)
    agent2_seen = any(str(event.get("agent") or "") == "agent2" or "AGENT2" in str(event.get("node_id") or "") for event in events)
    agent2_gate_seen = _segment_status(segments, "agent2_gate") == "completed"
    handoff_seen = any(_is_agent2_handoff(event) for event in events)

    if process_seen and not preflight_seen:
        failures.append(
            {
                "code": "flow_missing_credential_preflight",
                "flow_segment": "credential_preflight",
                "source_layer": "backend",
                "message": "runner process started before backend credential preflight was captured",
            }
        )
    if start_seen and terminal and not process_seen:
        failures.append(
            {
                "code": "flow_missing_required_span",
                "flow_segment": "runner_process",
                "source_layer": "runner",
                "terminal_status": status,
                "message": "terminal run has no runner process span",
            }
        )
    if agent2_seen and not agent2_gate_seen:
        failures.append(
            {
                "code": "flow_missing_agent2_gate",
                "flow_segment": "agent2_gate",
                "source_layer": "agent2",
                "message": "Agent2 activity appeared without Agent1-to-Agent2 handoff gate",
            }
        )
    if handoff_seen and _segment_status(segments, "agent1_artifacts") != "completed":
        failures.append(
            {
                "code": "flow_agent2_handoff_with_stale_agent1_artifact",
                "flow_segment": "agent2_gate",
                "source_layer": "agent2",
                "message": "Agent2 handoff happened before current Agent1 artifact fingerprint was visible",
            }
        )
    _check_attachment_payload_match(events, manifest, output_dir, failures)
    _check_websocket_replay_monotonic(events, failures)

    for finding in _flow_missing_span_findings(coverage):
        segment_id = str(finding.get("flow_segment") or "")
        if finding.get("code") in {"flow_missing_agent2_gate", "flow_missing_credential_preflight"}:
            continue
        if segment_id in {"frontend_input", "start_request"} and terminal:
            failures.append(finding)
        elif segment_id in {"agent1_intake", "agent1_cluster", "agent1_guardrail", "plan_review", "agent1_artifacts"} and (terminal or handoff_seen or agent2_seen):
            warnings.append(finding)

def _source_type(event: dict[str, Any]) -> str:
    source = event.get("source") if isinstance(event.get("source"), dict) else {}
    return str(source.get("type") or "")

def _agent1_retry_targets(source: dict[str, Any]) -> list[str]:
    targets: list[str] = []
    for key in ("target_group_id", "group_id"):
        value = str(source.get(key) or "")
        if value and value not in targets:
            targets.append(value)
    raw_many = source.get("target_group_ids")
    if isinstance(raw_many, list):
        for item in raw_many:
            value = str(item or "")
            if value and value not in targets:
                targets.append(value)
    return targets

def _segment_status(segments: dict[str, Any], segment_id: str) -> str:
    segment = segments.get(segment_id) if isinstance(segments, dict) else {}
    return str(segment.get("status") or "missing") if isinstance(segment, dict) else "missing"

def _agent1_flow_started(segments: dict[str, Any]) -> bool:
    return any(_segment_status(segments, segment_id) in {"started", "completed", "failed"} for segment_id in ("agent1_intake", "agent1_cluster", "agent1_guardrail", "plan_review", "agent1_artifacts", "agent2_gate"))

def _is_agent2_handoff(event: dict[str, Any]) -> bool:
    source = event.get("source") if isinstance(event.get("source"), dict) else {}
    return (
        str(event.get("event_type") or "") == "tool_call_done"
        and _source_type(event) == "agent_handoff"
        and (str(source.get("to_agent") or "") == "agent2" or "agent2" in str(source.get("contract") or "").lower())
    )

def _check_attachment_payload_match(events: list[dict[str, Any]], manifest: dict[str, Any], output_dir: str | Path, failures: list[dict[str, Any]]) -> None:
    requested: list[str] = []
    saw_preflight = False
    for event in events:
        source = event.get("source") if isinstance(event.get("source"), dict) else {}
        if str(source.get("type") or "") != "start_preflight":
            continue
        saw_preflight = True
        value = source.get("attachment_ids")
        if isinstance(value, list):
            requested.extend(str(item) for item in value if item)
    if not saw_preflight:
        return
    requested_set = set(requested)
    manifest_path = _manifest_attachment_path(manifest, output_dir)
    if not requested_set and not manifest_path:
        return
    committed_set: set[str] = set()
    if manifest_path:
        data = _safe_read_json(manifest_path).get("payload") or {}
        attachments = data.get("attachments") if isinstance(data.get("attachments"), list) else []
        committed_set = {str(item.get("id") or "") for item in attachments if isinstance(item, dict) and item.get("id")}
    if requested_set != committed_set:
        failures.append(
            {
                "code": "flow_attachment_payload_mismatch",
                "flow_segment": "attachment_staging",
                "source_layer": "backend",
                "requested_attachment_ids": sorted(requested_set),
                "committed_attachment_ids": sorted(committed_set),
                "artifact_ref": str(manifest_path or ""),
            }
        )

def _manifest_attachment_path(manifest: dict[str, Any], output_dir: str | Path | None = None) -> Path | None:
    candidates = [str(manifest.get("attachment_manifest_path") or "")]
    if output_dir:
        candidates.append(str(Path(output_dir) / "inputs" / "attachments_manifest.json"))
    if manifest.get("output_dir"):
        candidates.append(str(Path(str(manifest.get("output_dir"))) / "inputs" / "attachments_manifest.json"))
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            return path
    return None

def _check_websocket_replay_monotonic(events: list[dict[str, Any]], failures: list[dict[str, Any]]) -> None:
    last_value: int | None = None
    for index, event in enumerate(events):
        source = event.get("source") if isinstance(event.get("source"), dict) else {}
        if str(source.get("type") or "") != "websocket_replay":
            continue
        raw = source.get("replay_event_id", source.get("last_event_id", source.get("event_id")))
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if last_value is not None and value < last_value:
            failures.append(
                {
                    "code": "flow_non_monotonic_websocket_replay",
                    "flow_segment": "websocket",
                    "source_layer": "websocket",
                    "index": index,
                    "previous_event_id": last_value,
                    "event_id": value,
                }
            )
        last_value = value

def _flow_missing_span_findings(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    segments = coverage.get("segments") if isinstance(coverage.get("segments"), dict) else {}
    findings: list[dict[str, Any]] = []
    for segment_id, raw in segments.items():
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "missing")
        issue_code = str(raw.get("last_issue_code") or "")
        if issue_code:
            findings.append(
                {
                    "code": issue_code,
                    "flow_segment": str(segment_id),
                    "source_layer": str(raw.get("owner_layer") or ""),
                    "status": status,
                    "span_ids": raw.get("span_ids") or [],
                    "message": f"flow segment {segment_id} has issue {issue_code}",
                }
            )
        elif status == "missing":
            findings.append(
                {
                    "code": "flow_missing_required_span",
                    "flow_segment": str(segment_id),
                    "source_layer": str(raw.get("owner_layer") or ""),
                    "status": status,
                    "span_ids": raw.get("span_ids") or [],
                    "message": f"flow segment {segment_id} has no captured span",
                }
            )
    return findings

def _canonical_span_model_from_events(events: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    run_id = str(manifest.get("run_id") or next((event.get("run_id") for event in events if event.get("run_id")), "") or "")
    model_call_ids: list[str] = []
    agent_span_ids: list[str] = []
    artifact_span_ids: list[str] = []
    parent_links: list[dict[str, str]] = []
    spans = {
        "run_span_id": f"run:{run_id}" if run_id else "",
        "ui_action_span_id": "",
        "backend_request_span_id": "",
        "job_span_id": "",
        "process_span_id": "",
        "agent_span_id": "",
        "model_call_id": "",
        "artifact_span_id": "",
    }
    for event in events:
        event_type = str(event.get("event_type") or "")
        corr = str(event.get("correlation_id") or event.get("event_id") or "")
        agent = str(event.get("agent") or "")
        source = event.get("source") if isinstance(event.get("source"), dict) else {}
        for key in spans:
            if source.get(key) and not spans[key]:
                spans[key] = str(source.get(key) or "")
        parent = str(source.get("parent_span_id") or "")
        child = str(source.get("span_id") or corr)
        if parent and child:
            parent_links.append({"parent_span_id": parent, "span_id": child, "event_type": event_type})
        if event_type == "run_init" and not spans["backend_request_span_id"]:
            spans["backend_request_span_id"] = corr
        elif event_type == "job_queued" and not spans["job_span_id"]:
            spans["job_span_id"] = corr
        elif event_type in {"job_started", "job_done"} and not spans["process_span_id"]:
            spans["process_span_id"] = corr
        elif event_type in {"agent_start", "agent_done"} and agent.startswith("agent"):
            if corr not in agent_span_ids:
                agent_span_ids.append(corr)
            if not spans["agent_span_id"]:
                spans["agent_span_id"] = corr
        elif event_type in {"model_call_start", "model_call_done"}:
            if corr not in model_call_ids:
                model_call_ids.append(corr)
            if not spans["model_call_id"]:
                spans["model_call_id"] = corr
        elif event_type == "artifact_written":
            artifact_span = str(source.get("artifact_span_id") or corr)
            if artifact_span not in artifact_span_ids:
                artifact_span_ids.append(artifact_span)
            if not spans["artifact_span_id"]:
                spans["artifact_span_id"] = artifact_span
    return redact_runtime_payload(
        {
            **spans,
            "agent_span_ids": agent_span_ids,
            "model_call_ids": model_call_ids,
            "artifact_span_ids": artifact_span_ids,
            "parent_links": parent_links[-200:],
        }
    )

def _challenge_resolved(event: dict[str, Any]) -> bool:
    source = event.get("source") if isinstance(event.get("source"), dict) else {}
    text = " ".join(str(value or "").lower() for value in (event.get("status"), source.get("status"), source.get("resolution")))
    return any(token in text for token in ("resolved", "accepted", "rejected", "closed", "mitigated", "passed", "pass"))


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


def _agent_action_node_id(agent: str, action: str) -> str:
    normalized = re.sub(r"\b(started|completed|complete|failed|passed|done)\b\s*$", "", action, flags=re.IGNORECASE).strip()
    return f"{agent.upper()}.{_slug(normalized or action).upper()}"


def _trace_runtime_type(event_type: str, status_value: str) -> str:
    lowered = event_type.lower()
    if lowered in {"node_started", "llm_call", "process_launch", "process_enter"}:
        return "node_start"
    if lowered in {"node_completed", "llm_call_completed", "completion", "process_finally"}:
        return "node_done"
    if lowered in {"node_start", "node_done"}:
        return lowered
    return "trace_event"

def _agent1_cluster_status(kind: str, event: dict[str, Any]) -> str:
    explicit = str(event.get("status") or "")
    if explicit:
        return _status(explicit)
    if kind == "agent1_group_session_start":
        return "running"
    if kind in {"agent1_group_session_failed", "agent1_leaf_expert_failed"}:
        return "failed"
    if kind in {"agent1_group_session_done", "agent1_leaf_expert_done", "agent1_clarification_answer", "agent1_topology_loaded", "agent1_cluster_assignment", "agent1_council_mode_selected"}:
        return "passed"
    if kind in {"agent1_leaf_expert_start", "agent1_leaf_expert_retry"}:
        return "running"
    if kind == "agent1_clarification_question":
        return "paused"
    return "running"

def _agent1_cluster_node_id(kind: str, group_id: str = "") -> str:
    base = {
        "agent1_topology_loaded": "AGENT1.TOPOLOGY",
        "agent1_cluster_assignment": "AGENT1.CLUSTER_ROUTER",
        "agent1_group_session_start": "AGENT1.GROUP_SESSION",
        "agent1_group_session_done": "AGENT1.GROUP_SESSION",
        "agent1_group_session_failed": "AGENT1.GROUP_SESSION",
        "agent1_group_retry": "AGENT1.GROUP_RETRY",
        "agent1_leaf_expert_start": "AGENT1.LEAF_EXPERT",
        "agent1_leaf_expert_done": "AGENT1.LEAF_EXPERT",
        "agent1_leaf_expert_failed": "AGENT1.LEAF_EXPERT",
        "agent1_leaf_expert_retry": "AGENT1.LEAF_RETRY",
        "agent1_cross_group_challenge": "AGENT1.CROSS_GROUP_CHALLENGE",
        "agent1_principal_group_review": "AGENT1.PRINCIPAL_GROUP_REVIEW",
        "agent1_clarification_question": "AGENT1.CLARIFICATION_QUESTION",
        "agent1_clarification_answer": "AGENT1.CLARIFICATION_ANSWER",
        "agent1_council_mode_selected": "AGENT1.COUNCIL_MODE",
    }.get(kind, f"AGENT1.{_slug(kind).upper()}")
    return f"{base}.{_slug(group_id).upper()}" if group_id else base

def _cluster_duration_ms(event: dict[str, Any]) -> int:
    for key, scale in (("latency_ms", 1), ("latency_s", 1000)):
        try:
            if event.get(key) is not None:
                return max(0, int(float(event.get(key)) * scale))
        except (TypeError, ValueError):
            continue
    return _duration_ms(event.get("metrics"))

def _cluster_metrics(event: dict[str, Any]) -> dict[str, Any]:
    metrics = dict(event.get("metrics")) if isinstance(event.get("metrics"), dict) else {}
    for key in (
        "latency_s",
        "latency_ms",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "estimated_cost_usd",
        "group_call_count",
        "group_latency_s",
        "group_prompt_tokens",
        "group_completion_tokens",
        "group_total_tokens",
        "group_estimated_cost_usd",
        "group_retry_count",
    ):
        if event.get(key) is not None:
            metrics[key] = event.get(key)
    return metrics


def _is_model_text(action: str, summary: str) -> bool:
    text = f"{action} {summary}".lower()
    return any(marker in text for marker in ("codex", "model cx/", "model call", "model returned", "http://localhost:20128", "/v1", "api unavailable", "chat/completions"))


def _is_model_start(action: str, summary: str) -> bool:
    text = f"{action} {summary}".lower()
    return "codex request started" in text or text.startswith("calling ") or " calling " in text


def _is_model_done(action: str, summary: str) -> bool:
    text = f"{action} {summary}".lower()
    return "codex response received" in text or "returned architecture evidence" in text or "returned rtl" in text or "returned " in text and " evidence" in text


def _is_model_fail(action: str, summary: str, status: str) -> bool:
    text = f"{action} {summary}".lower()
    return "codex unavailable" in text or ("unavailable" in text and _is_model_text(action, summary)) or (status.lower() in {"fail", "failed", "error"} and _is_model_text(action, summary))


def _duration_ms(metrics: Any) -> int:
    if isinstance(metrics, dict):
        value = metrics.get("latency_s")
        try:
            return max(0, int(float(value) * 1000))
        except (TypeError, ValueError):
            return 0
    return 0
