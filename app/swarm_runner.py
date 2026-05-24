"""Subprocess runner for SWARM AI STUDIO V5.0.

The GUI owns process lifecycle. This runner owns graph execution and emits
machine-readable JSONL events on stdout.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from semiconductor_swarm.tracing import (  # noqa: E402
    TRACE_FILES,
    clear_trace_context,
    finalize_trace_reports,
    set_trace_context,
    sha256_text,
    trace_artifact_lineage,
    trace_completion,
    trace_event,
    trace_snapshot,
)

STAGE_ORDER = ("planning", "rtl", "formal", "hitl", "dv", "physical", "signoff")
MAX_EVENT_BYTES = 64 * 1024
FIELD_LIMITS = {
    "message": 4 * 1024,
    "summary": 2 * 1024,
    "traceback_tail": 8 * 1024,
    "preview_tail": 16 * 1024,
    "log_tail": 16 * 1024,
}
DEFAULT_TEXT_LIMIT = 4 * 1024
PATH_TEXT_LIMIT = 2 * 1024

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_EVENT_STDOUT = sys.stdout
_RUN_ID = ""

def _requirement_with_attachment_context(requirement: str, attachment_manifest: str, output_dir: Path) -> str:
    if not attachment_manifest:
        return requirement
    manifest_path = Path(attachment_manifest).resolve(strict=False)
    allowed_root = (output_dir / "inputs").resolve(strict=False)
    try:
        manifest_path.relative_to(allowed_root)
    except ValueError:
        log("attachment manifest rejected: outside output input sandbox", level="warning")
        return requirement
    context_path = manifest_path.with_name("attachment_context.md")
    if not context_path.exists():
        return requirement
    context = context_path.read_text(encoding="utf-8", errors="replace")
    artifact(manifest_path, output_dir)
    artifact(context_path, output_dir)
    trace_artifact_lineage(
        "attachment_context.md",
        source_nodes=["STUDIO.ATTACHMENT_STAGE"],
        artifact_path=str(context_path),
        kind="markdown",
        output_dir=output_dir,
    )
    trace_event(
        TRACE_FILES["studio_flow"],
        phase="runner",
        agent="runner",
        node_id="RUNNER.ATTACHMENT_CONTEXT",
        event_type="attachment_context_loaded",
        status="pass",
        payload={"manifest": str(manifest_path), "context_chars": len(context)},
        output_dir=output_dir,
        emit_live=False,
    )
    return f"{requirement.rstrip()}\n\nAttached input digest:\n{context}".strip()


def _truncate_text(value: str, limit: int) -> tuple[str, bool]:
    if len(value.encode("utf-8", errors="replace")) <= limit:
        return value, False
    encoded = value.encode("utf-8", errors="replace")[: max(0, limit - 80)]
    text = encoded.decode("utf-8", errors="ignore")
    return f"{text}\n...[truncated to {limit} bytes]", True


def _sanitize_value(key: str, value: Any) -> tuple[Any, bool]:
    truncated = False
    if isinstance(value, str):
        limit = PATH_TEXT_LIMIT if key in {"path", "full_path", "output_dir", "artifact", "evidence_path"} else FIELD_LIMITS.get(key, DEFAULT_TEXT_LIMIT)
        return _truncate_text(value, limit)
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for child_key, child_value in value.items():
            clean_value, child_truncated = _sanitize_value(str(child_key), child_value)
            clean[str(child_key)] = clean_value
            truncated = truncated or child_truncated
        return clean, truncated
    if isinstance(value, list):
        clean_list: list[Any] = []
        for item in value[:100]:
            clean_value, child_truncated = _sanitize_value(key, item)
            clean_list.append(clean_value)
            truncated = truncated or child_truncated
        if len(value) > 100:
            clean_list.append({"truncated": True, "omitted_items": len(value) - 100})
            truncated = True
        return clean_list, truncated
    return value, False


def sanitize_event(event: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    truncated = bool(event.get("truncated", False))
    for key, value in event.items():
        clean_value, field_truncated = _sanitize_value(str(key), value)
        clean[str(key)] = clean_value
        truncated = truncated or field_truncated
    if truncated:
        clean["truncated"] = True

    serialized = json.dumps(clean, ensure_ascii=False, sort_keys=True)
    if len(serialized.encode("utf-8", errors="replace")) <= MAX_EVENT_BYTES:
        return clean

    compact = {
        "type": clean.get("type", "log"),
        "level": clean.get("level", "warning"),
        "message": f"event payload exceeded {MAX_EVENT_BYTES} bytes and was compacted",
        "original_type": clean.get("type", "unknown"),
        "truncated": True,
    }
    for key in ("agent", "stage", "status", "action_required", "path", "output_dir"):
        if key in clean:
            compact[key] = clean[key]
    return compact


def emit(event: dict[str, Any]) -> None:
    if _RUN_ID and "run_id" not in event:
        event = {**event, "run_id": _RUN_ID}
    print(json.dumps(sanitize_event(event), ensure_ascii=False, sort_keys=True), file=_EVENT_STDOUT, flush=True)


def log(message: str, level: str = "info") -> None:
    emit({"type": "log", "level": level, "message": message})


def stage(name: str, status: str) -> None:
    emit({"type": "stage", "stage": name, "status": status})


def agent_action(
    agent: str,
    label: str,
    phase: str,
    action: str,
    status: str,
    summary: str,
    **extra: Any,
) -> None:
    emit(
        {
            "type": "agent_action",
            "agent": agent,
            "label": label,
            "phase": phase,
            "action": action,
            "status": status,
            "summary": summary,
            **extra,
        }
    )


def agent_handoff(from_agent: str, to_agent: str, contract: str, status: str, summary: str, **extra: Any) -> None:
    emit(
        {
            "type": "agent_handoff",
            "from_agent": from_agent,
            "to_agent": to_agent,
            "contract": contract,
            "status": status,
            "summary": summary,
            **extra,
        }
    )


def agent_discussion(speaker: str, audience: str, message: str, severity: str = "info", **extra: Any) -> None:
    emit(
        {
            "type": "agent_discussion",
            "speaker": speaker,
            "audience": audience,
            "message": message,
            "severity": severity,
            **extra,
        }
    )


def metric(name: str, value: Any, status: str, **extra: Any) -> None:
    emit({"type": "metric", "name": name, "value": value, "status": status, **extra})


class JsonLogWriter:
    def __init__(self, level: str) -> None:
        self.level = level
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        if len(self._buffer.encode("utf-8", errors="replace")) > 32 * 1024:
            log(self._buffer, self.level)
            self._buffer = ""
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                log(line.rstrip(), self.level)
        return len(text)

    def flush(self) -> None:
        if self._buffer.strip():
            log(self._buffer.rstrip(), self.level)
        self._buffer = ""


@contextlib.contextmanager
def graph_log_redirect():
    stdout = JsonLogWriter("info")
    stderr = JsonLogWriter("error")
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        yield
    stdout.flush()
    stderr.flush()


def artifact(path: str | Path, output_dir: str | Path | None = None) -> None:
    path_obj = Path(path)
    payload: dict[str, Any] = {"type": "artifact", "path": str(path_obj), "kind": path_obj.suffix.lstrip(".") or "directory"}
    try:
        if path_obj.exists() and path_obj.is_file():
            payload["bytes"] = path_obj.stat().st_size
    except OSError:
        pass
    if output_dir is not None:
        payload["output_dir"] = str(output_dir)
    emit(payload)


class StatusTailer:
    def __init__(self, status_path: Path, *, start_at_end: bool = True) -> None:
        self.status_path = status_path
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="status-tailer", daemon=True)
        self._offset = status_path.stat().st_size if start_at_end and status_path.exists() else 0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if self.status_path.exists():
                    size = self.status_path.stat().st_size
                    if size < self._offset:
                        self._offset = 0
                    with self.status_path.open("rb") as handle:
                        handle.seek(self._offset)
                        chunk_bytes = handle.read(64 * 1024)
                        self._offset = handle.tell()
                    chunk = chunk_bytes.decode("utf-8", errors="replace")
                    for line in chunk.splitlines():
                        if line.strip():
                            log(line.strip())
            except OSError as exc:
                log(f"status tail error: {exc}", "warning")
            time.sleep(0.25)


def _interrupt_payloads(state: dict[str, Any]) -> list[dict[str, Any]]:
    interrupts = state.get("__interrupt__") if isinstance(state, dict) else None
    payloads = []
    for item in interrupts or []:
        value = getattr(item, "value", item)
        if isinstance(value, dict):
            payloads.append(value)
    return payloads


def _plan_path_from_payload(payload: dict[str, Any], output_dir: Path) -> str:
    raw = payload.get("plan_path") or output_dir / "reports" / "architecture_plan.md"
    return str(raw)


def _emit_pause(payload: dict[str, Any], output_dir: Path) -> None:
    action = str(payload.get("action_required", "UNKNOWN"))
    plan_path = _plan_path_from_payload(payload, output_dir)
    if action == "PLAN_REVIEW":
        stage("planning", "paused")
        agent_action(
            "agent1",
            "Agent 1 Architect",
            "planning",
            "Architecture plan ready for review",
            "paused",
            "Generated architecture plan and paused for human approval.",
            artifact=plan_path,
        )
        agent_discussion(
            "agent1",
            "user",
            "Architecture plan is ready. Review the plan preview, then approve or request changes.",
            "info",
            artifact=plan_path,
        )
        artifact(plan_path, output_dir)
    elif action == "REQUIREMENT_CLARIFICATION":
        stage("planning", "paused")
        agent_action(
            "agent1",
            "Agent 1 Intake Council",
            "planning",
            "Requirement clarification needed",
            "paused",
            "Agent 1 stopped before architecture planning because intake did not find a release-ready chip requirement.",
            artifact=plan_path,
        )
        agent_discussion(
            "agent1",
            "user",
            "Requirement clarification is ready. Fill the missing chip requirement fields, then submit as a change request.",
            "warning",
            artifact=plan_path,
        )
        artifact(plan_path, output_dir)
    elif action == "HUMAN_REVIEW":
        stage("rtl", "pass")
        stage("formal", "pass")
        stage("hitl", "paused")
        agent_action("agent2", "Agent 2 RTL Designer", "rtl", "RTL collateral ready", "pass", "Generated RTL package and routed Agent 2 reports/contracts.")
        agent_action("agent5", "Agent 5 Formal Verifier", "formal", "Formal collateral ready", "pass", "Generated formal-first collateral for human review.")
        agent_handoff("agent2", "agent5", "agent2_to_agent5", "pass", "RTL and formal hooks are available for formal verification.")
        agent_handoff("agent2", "agent3", "agent2_to_agent3", "pass", "RTL compile order and DV hooks are available for DV generation.")
        agent_discussion("agent5", "user", "Formal collateral is ready for review before DV execution.", "info")
    else:
        stage("hitl", "paused")
        agent_action("agent1", "Human Review", "hitl", "Human input required", "paused", f"Paused for {action}.")

    emit(
        {
            "type": "pause",
            "action_required": action,
            "message": payload.get("message", ""),
            "plan_path": plan_path,
            "payload": payload,
        }
    )
    trace_completion(
        status="paused",
        decision=action,
        decision_reason=str(payload.get("message") or "Runner paused for human input."),
        blocking_reasons=[action],
        artifact_refs=[plan_path],
        output_dir=output_dir,
    )


def _emit_done(state: dict[str, Any], output_dir: Path) -> None:
    status = str(state.get("status", "UNKNOWN"))
    if status == "SIGNOFF_READY":
        stage("dv", "pass")
        stage("physical", "pass")
        stage("signoff", "pass")
        agent_action("agent3", "Agent 3 DV Engineer", "dv", "DV evidence summarized", "pass", "DV status artifacts were collected for signoff.")
        agent_action("agent4", "Agent 4 Physical Designer", "physical", "Physical evidence summarized", "pass", "Physical implementation reports were collected for signoff.")
        agent_discussion("agent4", "signoff", "Physical and DV evidence are available for final readiness review.", "success")
    metric("generated_files", sum(1 for path in output_dir.rglob("*") if path.is_file()) if output_dir.exists() else 0, "info")
    metric("final_status", status, "pass" if status == "SIGNOFF_READY" else "warning")
    emit({"type": "done", "status": status, "output_dir": str(output_dir)})
    trace_completion(
        status="pass" if status == "SIGNOFF_READY" else "info",
        decision="done",
        decision_reason=f"Final graph status: {status}",
        artifact_refs=[str(output_dir)],
        output_dir=output_dir,
    )


def _write_outputs_and_emit(state: dict[str, Any], output_dir: Path) -> None:
    from semiconductor_swarm.swarm_graph import write_outputs

    write_outputs(state, output_dir)
    artifact(output_dir, output_dir)
    trace_artifact_lineage(
        "output_dir",
        source_nodes=["APP.SWARM_RUNNER_START"],
        artifact_path=str(output_dir),
        kind="directory",
        output_dir=output_dir,
    )
    for rel in (
        "reports/architecture_plan.md",
        "contracts/swarm_artifact_index.json",
        "contracts/swarm_to_docs_agent.json",
        "status.log",
    ):
        path = output_dir / rel
        if path.exists():
            artifact(path, output_dir)
            trace_artifact_lineage(rel, source_nodes=["APP.SWARM_RUNNER_START"], artifact_path=str(path), output_dir=output_dir)


def run_start(args: argparse.Namespace) -> int:
    from semiconductor_swarm.swarm_graph import persistent_swarm_graph
    from semiconductor_swarm.runtime_events import set_runtime_event_sink

    global _RUN_ID
    _RUN_ID = str(args.run_id or "")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    set_trace_context(run_id=_RUN_ID, thread_id=args.thread_id, flow_id="start_run", output_dir=output_dir, project_name=args.project_name)
    requirement = _requirement_with_attachment_context(args.requirement, args.attachment_manifest, output_dir)
    status_tailer = StatusTailer(output_dir / "status.log")
    status_tailer.start()
    set_runtime_event_sink(emit)
    try:
        trace_event(
            TRACE_FILES["runner_process"],
            phase="runner",
            agent="runner",
            node_id="APP.SWARM_RUNNER_START",
            event_type="process_enter",
            status="running",
            payload={
                "project_name": args.project_name,
                "planning_mode": args.planning_mode,
                "input_hash": sha256_text(requirement),
                "input_preview": requirement[:600],
            },
        )
        log(f"start project={args.project_name} thread={args.thread_id} planning_mode={args.planning_mode}")
        agent_action(
            "agent1",
            "Agent 1 Architect",
            "planning",
            "Start architecture planning",
            "running",
            f"Project {args.project_name} entered planning.",
        )
        stage("planning", "running")
        trace_snapshot(
            "before_start_payload",
            {
                "requirement": requirement,
                "project_name": args.project_name,
                "thread_id": args.thread_id,
                "planning_mode": args.planning_mode,
                "current_stage": "planning",
            },
        )
        config = {"configurable": {"thread_id": args.thread_id}}
        with graph_log_redirect():
            with persistent_swarm_graph(args.checkpoint_db) as app:
                state = app.invoke(
                    {
                        "requirement": requirement,
                        "project_name": args.project_name,
                        "thread_id": args.thread_id,
                        "output_dir": str(output_dir),
                        "run_real_tools": False,
                        "strict_signoff": False,
                        "agent2_codex_required": True,
                        "agent1_planning_mode": args.planning_mode,
                        "plan_approved": False,
                        "debug_iterations": 0,
                        "max_debug_iterations": 5,
                        "reports": {},
                    },
                    config=config,
                )
        payloads = _interrupt_payloads(state)
        if payloads:
            _emit_pause(payloads[0], output_dir)
            return 0
        trace_snapshot("after_pause_or_handoff", {"status": state.get("status"), "current_stage": "post_graph", **state})
        _write_outputs_and_emit(state, output_dir)
        _emit_done(state, output_dir)
        return 0
    finally:
        trace_event(
            TRACE_FILES["runner_process"],
            phase="runner",
            agent="runner",
            node_id="RUNNER.PROCESS_EXIT",
            event_type="process_finally",
            status="info",
            payload={"command": "start"},
        )
        finalize_trace_reports(output_dir)
        clear_trace_context()
        set_runtime_event_sink(None)
        status_tailer.stop()


def run_resume(args: argparse.Namespace) -> int:
    from langgraph.types import Command
    from semiconductor_swarm.swarm_graph import persistent_swarm_graph
    from semiconductor_swarm.runtime_events import set_runtime_event_sink

    global _RUN_ID
    _RUN_ID = str(args.run_id or "")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    set_trace_context(run_id=_RUN_ID, thread_id=args.thread_id, flow_id="resume_run", output_dir=output_dir, project_name=args.project_name)
    status_tailer = StatusTailer(output_dir / "status.log")
    status_tailer.start()
    set_runtime_event_sink(emit)
    try:
        trace_event(
            TRACE_FILES["runner_process"],
            phase="runner",
            agent="runner",
            node_id="APP.SWARM_RUNNER_RESUME",
            event_type="process_enter",
            status="running",
            payload={"project_name": args.project_name, "planning_mode": args.planning_mode, "resume_action": args.resume_action},
        )
        response = args.change.strip() if args.change else args.notes.strip() or "ok"
        resume_action = str(args.resume_action or "").upper()
        log(f"resume project={args.project_name} thread={args.thread_id} planning_mode={args.planning_mode} response={response!r}")
        if args.change:
            stage("planning", "running")
            agent_action("agent1", "Agent 1 Architect", "planning", "Revise plan", "running", "Applying requested plan changes.")
            agent_discussion("user", "agent1", response, "warning")
            payload = {"response": response, "reviewer": "studio-user", "notes": response}
        elif resume_action == "HUMAN_REVIEW":
            stage("hitl", "pass")
            stage("dv", "running")
            stage("physical", "running")
            agent_action("agent3", "Agent 3 DV Engineer", "dv", "Start DV evidence pass", "running", "Human review approved; DV phase is collecting evidence.")
            agent_action("agent4", "Agent 4 Physical Designer", "physical", "Start physical evidence pass", "running", "Physical phase is collecting FPGA/implementation evidence.")
            agent_handoff("agent3", "agent4", "agent3_release_decision", "info", "DV decision is available to physical/signoff flow when generated.")
            payload = {"response": response, "approved": True, "reviewer": "studio-user", "notes": response}
        else:
            stage("planning", "pass")
            stage("rtl", "running")
            stage("formal", "running")
            agent_action("agent1", "Agent 1 Architect", "planning", "Plan approved", "pass", "Architecture plan approved by user.")
            agent_handoff("agent1", "agent2", "agent1_to_agent2", "pass", "Architecture/spec contract released to RTL.")
            agent_action("agent2", "Agent 2 RTL Designer", "rtl", "Start RTL generation", "running", "Generating APB/RTL collateral from locked architecture.")
            agent_action("agent5", "Agent 5 Formal Verifier", "formal", "Start formal collateral", "running", "Preparing formal-first properties and harnesses.")
            payload = {"response": response, "approved": True, "reviewer": "studio-user", "notes": response}

        config = {"configurable": {"thread_id": args.thread_id}}
        with graph_log_redirect():
            with persistent_swarm_graph(args.checkpoint_db) as app:
                state = app.invoke(Command(resume=payload), config=config)

        payloads = _interrupt_payloads(state)
        if payloads:
            _emit_pause(payloads[0], output_dir)
            return 0

        if resume_action != "HUMAN_REVIEW":
            stage("hitl", "pass")
            stage("dv", "running")
            stage("physical", "running")
            agent_action("agent3", "Agent 3 DV Engineer", "dv", "Start DV evidence pass", "running", "Human review complete; DV phase started.")
            agent_action("agent4", "Agent 4 Physical Designer", "physical", "Start physical evidence pass", "running", "Physical phase started.")
        _write_outputs_and_emit(state, output_dir)
        _emit_done(state, output_dir)
        return 0
    finally:
        trace_event(
            TRACE_FILES["runner_process"],
            phase="runner",
            agent="runner",
            node_id="RUNNER.PROCESS_EXIT",
            event_type="process_finally",
            status="info",
            payload={"command": "resume"},
        )
        finalize_trace_reports(output_dir)
        clear_trace_context()
        set_runtime_event_sink(None)
        status_tailer.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SWARM AI STUDIO JSONL subprocess runner")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "resume"):
        item = sub.add_parser(name)
        item.add_argument("--requirement", default="")
        item.add_argument("--project-name", required=True)
        item.add_argument("--thread-id", required=True)
        item.add_argument("--run-id", default="")
        item.add_argument("--output-dir", required=True)
        item.add_argument("--checkpoint-db", required=True)
        item.add_argument("--notes", default="ok")
        item.add_argument("--change", default="")
        item.add_argument("--resume-action", default="")
        item.add_argument("--planning-mode", choices=("normal", "deep_planning"), default="normal")
        item.add_argument("--attachment-manifest", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            return run_start(args)
        if args.command == "resume":
            return run_resume(args)
        parser.error(f"unknown command: {args.command}")
        return 2
    except Exception as exc:
        tail = "\n".join(traceback.format_exc().splitlines()[-30:])
        emit({"type": "error", "message": f"{type(exc).__name__}: {exc}", "traceback_tail": tail})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
