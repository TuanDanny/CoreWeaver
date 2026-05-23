"""Agent 1 V4 audit artifacts: stable hashes, trace spans, tool ledger, replay bundle.

This module is deliberately side-effect light. It can be used by Agent 1 without
changing architecture selection behavior.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from semiconductor_swarm.tools.bandwidth_calculator import calculate_bandwidth
from semiconductor_swarm.tools.ppa_calculator import calculate_ppa


AGENT1_AUDIT_SCHEMA_VERSION = "agent1_audit_v4_phase1"
SECRET_TOKENS = ("api_key", "apikey", "authorization", "bearer", "password", "secret", "token")


def stable_json(value: Any) -> str:
    """Return deterministic JSON for hashing/audit output."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def stable_hash(value: Any) -> str:
    """Return SHA-256 hash of deterministic JSON payload."""
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_for_audit(value: Any) -> Any:
    """Remove obvious secret-bearing fields from nested audit data."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(token in key_text for token in SECRET_TOKENS):
                sanitized[key] = "<redacted>"
            else:
                sanitized[key] = sanitize_for_audit(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_for_audit(item) for item in value]
    return value


def jsonl(records: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n" for record in records)


@dataclass
class Agent1TraceRecorder:
    """Collect OpenTelemetry-style spans for Agent 1 artifact output."""

    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    records: list[dict[str, Any]] = field(default_factory=list)

    def span(
        self,
        node: str,
        event: str,
        input_payload: Any = None,
        output_payload: Any = None,
        decision: str | None = None,
        severity: str = "INFO",
        error: str | None = None,
        artifacts: list[str] | None = None,
        parent_span_id: str | None = None,
        duration_ms: int | None = None,
    ) -> dict[str, Any]:
        start_ts = utc_now_iso()
        start_perf = time.perf_counter()
        if duration_ms is None:
            duration_ms = int((time.perf_counter() - start_perf) * 1000)
        record = {
            "trace_id": self.trace_id,
            "span_id": uuid.uuid4().hex,
            "parent_span_id": parent_span_id,
            "node": node,
            "event": event,
            "start_ts": start_ts,
            "end_ts": utc_now_iso(),
            "duration_ms": duration_ms,
            "input_hash": stable_hash(sanitize_for_audit(input_payload)) if input_payload is not None else None,
            "output_hash": stable_hash(sanitize_for_audit(output_payload)) if output_payload is not None else None,
            "decision": decision,
            "severity": severity,
            "error": error,
            "artifacts": artifacts or [],
        }
        self.records.append(record)
        return record

    def to_jsonl(self) -> str:
        return jsonl(self.records)


def tool_version_hash(tool: Any) -> str:
    """Hash tool implementation source if available, else repr fallback."""
    try:
        import inspect

        payload = inspect.getsource(tool)
    except Exception:  # pragma: no cover - fallback only
        payload = repr(tool)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_tool_ledger_entry(tool_name: str, caller: str, args: dict[str, Any], output: Any, tool_hash: str | None = None) -> dict[str, Any]:
    sanitized_args = sanitize_for_audit(args)
    sanitized_output = sanitize_for_audit(output)
    return {
        "schema_version": AGENT1_AUDIT_SCHEMA_VERSION,
        "tool": tool_name,
        "caller": caller,
        "tool_version_hash": tool_hash or stable_hash(tool_name),
        "args": sanitized_args,
        "input_hash": stable_hash(sanitized_args),
        "output": sanitized_output,
        "output_hash": stable_hash(sanitized_output),
        "timestamp": utc_now_iso(),
    }


def build_tool_ledger_for_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Create ledger from final spec estimates and parse-derived tool args when present."""
    tool_inputs = spec.get("tool_inputs", {})
    ppa_args = tool_inputs.get("calculate_ppa", {})
    bandwidth_args = tool_inputs.get("calculate_bandwidth", {})
    return [
        make_tool_ledger_entry("calculate_ppa", "PPA_Bandwidth_Tool_Expert", ppa_args, spec.get("ppa_estimate", {}), tool_version_hash(calculate_ppa)),
        make_tool_ledger_entry("calculate_bandwidth", "PPA_Bandwidth_Tool_Expert", bandwidth_args, spec.get("bandwidth_estimate", {}), tool_version_hash(calculate_bandwidth)),
    ]


def _git_commit() -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    except Exception:  # pragma: no cover - git absent edge
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def build_replay_bundle(
    requirement: str,
    project_name: str,
    sanitized_project_name: str,
    codex_evidence: dict[str, Any],
    spec: dict[str, Any],
    artifacts: dict[str, str],
    trace: Agent1TraceRecorder,
    tool_ledger: list[dict[str, Any]],
    agent1_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact_manifest = {name: stable_hash(content) for name, content in sorted(artifacts.items())}
    return sanitize_for_audit({
        "schema_version": "agent1_replay_v1",
        "audit_schema_version": AGENT1_AUDIT_SCHEMA_VERSION,
        "run_id": uuid.uuid4().hex,
        "trace_id": trace.trace_id,
        "project_name": project_name,
        "sanitized_project_name": sanitized_project_name,
        "requirement_hash": stable_hash(requirement),
        "agent1_config": agent1_config or {},
        "codex": {
            "evidence": codex_evidence,
            "evidence_hash": stable_hash(codex_evidence),
        },
        "tool_ledger_hash": stable_hash(tool_ledger),
        "spec_hashes": {"final": stable_hash(spec)},
        "validator_decisions_hash": stable_hash(artifacts.get("agent1_validation_decisions.json", "")),
        "revision_history_hash": stable_hash(artifacts.get("agent1_revision_history.json", "")),
        "artifact_manifest": artifact_manifest,
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "git_commit": _git_commit(),
        },
    })


def build_agent1_audit_artifacts(
    requirement: str,
    project_name: str,
    spec: dict[str, Any],
    artifacts: dict[str, str],
    codex_evidence: dict[str, Any],
    validation: dict[str, Any],
    agent1_config: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Build V4 audit artifacts for Agent 1 output without mutating behavior."""
    trace = Agent1TraceRecorder()
    trace.span("Requirement_Intake_Expert", "requirement_parsed", requirement, spec.get("requirements"), "ACCEPT")
    trace.span("Agent1_Codex", "codex_evidence", {"project_name": project_name}, codex_evidence, "ACCEPT" if codex_evidence else "REJECT", artifacts=["agent1_codex_evidence.json"])
    trace.span("PPA_Bandwidth_Tool_Expert", "tool_backed_estimates", spec.get("tool_inputs", {}), {"ppa_estimate": spec.get("ppa_estimate"), "bandwidth_estimate": spec.get("bandwidth_estimate")}, "ACCEPT", artifacts=["agent1_tool_evidence.json"])
    try:
        decisions = json.loads(artifacts.get("agent1_validation_decisions.json", "[]"))
    except json.JSONDecodeError:
        decisions = []
    for decision in decisions:
        trace.span(decision.get("validator", "unknown_validator"), "validator_decision", spec, decision, decision.get("decision"), decision.get("severity", "INFO"), artifacts=["agent1_validation_decisions.json"])
    trace.span("Agent1_V4_Audit", "micro_expert_validation", artifacts, validation, "ACCEPT" if validation.get("pass") else "REJECT", artifacts=["agent1_micro_expert_validation.json"])

    tool_ledger = build_tool_ledger_for_spec(spec)
    replay_bundle = build_replay_bundle(requirement, project_name, spec.get("project_name", project_name), codex_evidence, spec, artifacts, trace, tool_ledger, agent1_config)
    return {
        "agent1_v4_trace.jsonl": trace.to_jsonl(),
        "agent1_v4_tool_ledger.jsonl": jsonl(tool_ledger),
        "agent1_v4_replay_bundle.json": json.dumps(replay_bundle, indent=2, sort_keys=True, ensure_ascii=False),
    }


def validate_audit_cross_checks(artifacts: dict[str, str]) -> dict[str, Any]:
    """Cross-check trace, ledger, replay bundle consistency."""
    failures: list[str] = []
    trace_lines = [json.loads(line) for line in artifacts.get("agent1_v4_trace.jsonl", "").splitlines() if line.strip()]
    ledger_lines = [json.loads(line) for line in artifacts.get("agent1_v4_tool_ledger.jsonl", "").splitlines() if line.strip()]
    replay = json.loads(artifacts.get("agent1_v4_replay_bundle.json", "{}") or "{}")
    if not trace_lines:
        failures.append("missing_trace_spans")
    if not ledger_lines:
        failures.append("missing_tool_ledger")
    if replay.get("tool_ledger_hash") != stable_hash(ledger_lines):
        failures.append("tool_ledger_hash_mismatch")
    trace_id = replay.get("trace_id")
    if trace_id and any(span.get("trace_id") != trace_id for span in trace_lines):
        failures.append("trace_id_mismatch")
    required_tools = {"calculate_ppa", "calculate_bandwidth"}
    observed_tools = {entry.get("tool") for entry in ledger_lines}
    if not required_tools.issubset(observed_tools):
        failures.append("missing_required_tool_entries")
    return {"pass": not failures, "failures": failures, "trace_spans": len(trace_lines), "tool_entries": len(ledger_lines)}
