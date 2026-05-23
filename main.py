"""Main LangGraph entry point for Semiconductor Swarm AI."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from langgraph.types import Command

from semiconductor_swarm.agents.agent1_planning.architect import derive_project_name, sanitize_project_name
from semiconductor_swarm.swarm_graph import apply_incremental_change, persistent_swarm_graph, write_outputs


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run the 5-agent Semiconductor Swarm LangGraph orchestrator.")
    parser.add_argument("requirement", nargs="?", default="IoT AI camera chip <1W 100MHz")
    parser.add_argument("--project-name", default=None)
    parser.add_argument("--thread-id", default="semiconductor-swarm")
    parser.add_argument("--output-dir", default="outputs/swarm_out")
    parser.add_argument("--checkpoint-db", default=".swarm/swarm_checkpoints.sqlite")
    parser.add_argument("--run-real-tools", action="store_true", help="Run available external EDA tools during graph execution.")
    parser.add_argument("--strict-signoff", action="store_true", help="Block signoff unless real formal, DV, and Quartus evidence exists.")
    parser.add_argument("--resume", action="store_true", help="Resume from HITL checkpoint with approval.")
    parser.add_argument("--reject", action="store_true", help="Resume from HITL checkpoint with rejection.")
    parser.add_argument("--change", help="Apply incremental engineer change to checkpointed state using thread_id without restarting graph.")
    parser.add_argument("--output-policy", choices=["ask", "overwrite", "merge", "abort"], default="ask")
    parser.add_argument("--reviewer", default="human")
    parser.add_argument("--notes", default="approved after code review")
    parser.add_argument("--resume-phase", choices=["plan", "code"], default="plan")
    args = parser.parse_args()
    args.project_name = sanitize_project_name(args.project_name or derive_project_name(args.requirement))

    config = {"configurable": {"thread_id": args.thread_id}}
    args.output_dir = str(_resolve_output_dir(Path(args.output_dir), args.output_policy))
    with persistent_swarm_graph(args.checkpoint_db) as app:
        if args.change:
            _print_chat_line("System", f"Đang gọi lại Agent 1 để cập nhật Plan theo yêu cầu: {args.change}...")
            _print_graph_step("Entering Agent 1 (Architect)")
            _print_graph_step("Updating State")
            state = apply_incremental_change(app, args.thread_id, args.change)
        elif args.resume or args.reject:
            _ensure_resume_checkpoint(app, config, args.thread_id, args.checkpoint_db)
            resume_payload = _resume_payload(args)
            _print_resume_banner(resume_payload, args)
            _print_graph_step("Resuming LangGraph from checkpoint")
            state = app.invoke(Command(resume=resume_payload), config=config)
        else:
            _print_graph_step("Entering Agent 1 (Architect)")
            _print_graph_step("Creating architecture plan")
            state = app.invoke({"requirement": args.requirement, "project_name": args.project_name, "thread_id": args.thread_id,
                                "output_dir": args.output_dir,
                                "run_real_tools": args.run_real_tools, "strict_signoff": args.strict_signoff,
                                "plan_approved": False, "debug_iterations": 0, "max_debug_iterations": 5,
                                "reports": {}}, config=config)
        if isinstance(state, dict) and state.get("status"):
            _print_graph_step(f"State updated: {state.get('status')}")

        interrupts = state.get("__interrupt__") if isinstance(state, dict) else None
        if interrupts:
            payloads = [item.value for item in interrupts]
            _print_interrupt(payloads, args)
            return

        _print_graph_completion(state)
        write_outputs(state, args.output_dir)
        print(json.dumps({"status": state.get("status"), "output_dir": args.output_dir, "reports": state.get("reports", {})}, indent=2, sort_keys=True))


def _resume_payload(args: argparse.Namespace) -> dict[str, object]:
    if args.reject:
        return {"approved": False, "reviewer": args.reviewer, "notes": args.notes}
    note = args.notes.strip()
    if note.lower() == "ok":
        return {"response": "ok", "approved": True, "reviewer": args.reviewer, "notes": note}
    if note and note != "approved after code review":
        return {"response": note, "reviewer": args.reviewer, "notes": note}
    return {"response": "ok", "approved": True, "reviewer": args.reviewer, "notes": note or "ok"}


def _ensure_resume_checkpoint(app: object, config: dict[str, object], thread_id: str, checkpoint_db: str) -> None:
    """Fail clearly when CLI resume has no paused checkpoint for thread_id."""
    snapshot = app.get_state(config)  # type: ignore[attr-defined]
    has_values = bool(getattr(snapshot, "values", None))
    has_next = bool(getattr(snapshot, "next", None))
    has_interrupt = "__interrupt__" in getattr(snapshot, "values", {}) if has_values else False
    if has_next or has_interrupt:
        return
    raise SystemExit(
        "Resume error: no paused checkpoint found for "
        f"thread_id='{thread_id}' in checkpoint_db='{checkpoint_db}'. "
        "Start a run first, wait for PLAN_REVIEW/HUMAN_REVIEW pause, then resume with same --thread-id and --checkpoint-db."
    )


def _print_chat_line(role: str, message: str) -> None:
    print(f"[{role}] {message}")


def _print_graph_step(message: str) -> None:
    print(f"-> {message}")


def _print_resume_banner(payload: dict[str, object], args: argparse.Namespace) -> None:
    response = str(payload.get("response", payload.get("notes", ""))).strip()
    if args.reject:
        _print_chat_line("Rejected", "Dừng workflow theo quyết định review.")
        return
    if args.resume_phase == "code":
        _print_chat_line("Approved", "RTL/Formal đã được duyệt. Bắt đầu DV/Physical...")
        _print_graph_step("Entering Agent 3 (DV Engineer)")
        return
    if response and response.lower() != "ok":
        _print_chat_line("System", f"Đang gọi lại Agent 1 để cập nhật Plan theo yêu cầu: {response}...")
        _print_graph_step("Entering Agent 1 (Architect)")
        _print_graph_step("Updating State")
        return
    _print_chat_line("Approved", "Xác nhận Plan. Bắt đầu chuyển giao cho Agent 2 (RTL Designer)...")
    _print_graph_step("Entering Agent 2 (RTL Designer)")


def _print_graph_completion(state: dict[str, object]) -> None:
    status = state.get("status")
    if status == "SIGNOFF_READY":
        _print_graph_step("Entering Agent 3 (DV Engineer)")
        _print_graph_step("Entering Agent 4 (Physical Designer)")
        _print_chat_line("Done", "Workflow hoàn tất. Signoff ready.")
    elif status:
        _print_chat_line("Done", f"Workflow kết thúc với status: {status}")


def _resolve_output_dir(path: Path, policy: str) -> Path:
    if not path.exists() or not any(path.iterdir()):
        return path
    choice = policy
    if policy == "ask":
        choice = input("Thư mục đã tồn tại. Sếp muốn Ghi đè (Overwrite), Nối tiếp (Merge), hay Dừng lại (Abort)? ").strip().lower()
    aliases = {"ghi đè": "overwrite", "overwrite": "overwrite", "o": "overwrite", "nối tiếp": "merge", "merge": "merge", "m": "merge", "dừng lại": "abort", "abort": "abort", "a": "abort"}
    action = aliases.get(choice.lower(), choice.lower())
    if action == "overwrite":
        shutil.rmtree(path)
        return path
    if action == "merge":
        return path
    raise SystemExit("Abort: output directory already exists.")


def _print_interrupt(payloads: list[dict[str, object]], args: argparse.Namespace) -> None:
    first = payloads[0] if payloads else {}
    if first.get("action_required") == "PLAN_REVIEW":
        _print_graph_step("Entering Plan Review")
        _print_plan_summary(first, args)
        print("Sếp có muốn thay đổi gì nữa không? (Gõ ok để duyệt)")
        print(f"Resume OK: python main.py --resume --notes ok --project-name {args.project_name} --checkpoint-db {args.checkpoint_db} --thread-id {args.thread_id} --output-dir {args.output_dir} --output-policy merge")
        print(f"Change:    python main.py --resume --notes \"thêm I2C slave 400kHz\" --project-name {args.project_name} --checkpoint-db {args.checkpoint_db} --thread-id {args.thread_id} --output-dir {args.output_dir} --output-policy merge")
    elif first.get("action_required") == "HUMAN_REVIEW":
        _print_graph_step("Entering Human Review")
        _print_chat_line("System", "Agent 2 RTL và Agent 5 Formal đã chạy xong. Cần Sếp review trước DV/Physical.")
        print(f"Project: {first.get('project_name')}")
        print(f"RTL files: {len(first.get('rtl_files', []))}")
        print(f"Formal files: {len(first.get('formal_files', []))}")
        print(f"Resume OK: python main.py --resume --notes ok --project-name {args.project_name} --checkpoint-db {args.checkpoint_db} --thread-id {args.thread_id} --output-dir {args.output_dir} --output-policy merge")
    else:
        print(json.dumps({"status": "PAUSED_FOR_HITL", "checkpoint_db": args.checkpoint_db, "thread_id": args.thread_id,
                          "interrupts": payloads}, indent=2, sort_keys=True))
    status_log = Path(args.output_dir) / "status.log"
    print(f"Status log: {status_log}")


def _print_plan_summary(payload: dict[str, object], args: argparse.Namespace) -> None:
    plan_path = Path(str(payload.get("plan_path") or Path(args.output_dir) / "reports" / "architecture_plan.md"))
    print("\n--- Plan Summary ---")
    if not plan_path.exists():
        print(f"- Plan file: {plan_path}")
        print("- Summary chưa có vì file chưa tồn tại.")
        print("--------------------\n")
        return

    text = plan_path.read_text(encoding="utf-8", errors="replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    headings = [line.lstrip("# ").strip() for line in lines if line.startswith("#")]
    bullets = [line.lstrip("-*").strip() for line in lines if line.startswith(("-", "*"))]
    key_lines = []
    for line in lines:
        lower = line.lower()
        if any(token in lower for token in ["project", "frequency", "power", "target", "interface", "formal", "ip block", "constraint"]):
            key_lines.append(line.lstrip("-*").strip())

    summary = []
    if headings:
        summary.append(headings[0])
    summary.extend(key_lines[:4])
    if len(summary) < 4:
        summary.extend(bullets[: 4 - len(summary)])
    if not summary:
        summary = lines[:4]
    for item in summary[:6]:
        print(f"- {item[:140]}")
    print(f"- Plan file: {plan_path}")
    print("--------------------\n")


if __name__ == "__main__":
    main()