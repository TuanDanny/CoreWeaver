"""Partial debug runner for step-by-step Semiconductor Swarm execution.

This script is intentionally outside main.py. It compiles the same LangGraph
with LangGraph interrupt_after so engineers can stop immediately after a target
agent node finishes.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from semiconductor_swarm.agents.agent1_planning.architect import derive_project_name, sanitize_project_name
from semiconductor_swarm.swarm_graph import build_swarm_graph, write_outputs


STOP_NODE = {
    "agent1": "agent1_architect",
    "rtl_lint": "agent2_syntax_linter",
    "agent2": "agent2_syntax_linter",
    "agent3": "agent3_dv",
    "agent4": "agent4_physical",
    "agent5": "agent5_formal",
}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Run Semiconductor Swarm partially and stop after selected agent.")
    parser.add_argument("requirement", nargs="?", default="Bộ cộng ALU 8-bit")
    parser.add_argument("--stop-after", choices=sorted(STOP_NODE), required=True)
    parser.add_argument("--project-name")
    parser.add_argument("--thread-id", default="partial-debug")
    parser.add_argument("--output-dir", default="outputs/sandbox_test")
    parser.add_argument("--checkpoint-db", default=".swarm/debug_partial.sqlite")
    parser.add_argument("--output-policy", choices=["overwrite", "merge", "abort"], default="overwrite")
    parser.add_argument("--run-real-tools", action="store_true")
    args = parser.parse_args()

    project_name = sanitize_project_name(args.project_name or derive_project_name(args.requirement))
    output_dir = _prepare_output_dir(Path(args.output_dir), args.output_policy)
    checkpoint_db = Path(args.checkpoint_db)
    checkpoint_db.parent.mkdir(parents=True, exist_ok=True)

    state: dict[str, Any]
    with SqliteSaver.from_conn_string(str(checkpoint_db)) as checkpointer:
        app = build_swarm_graph(checkpointer, interrupt_after=[STOP_NODE[args.stop_after]])
        config = {"configurable": {"thread_id": args.thread_id}}
        initial = {
            "requirement": args.requirement,
            "project_name": project_name,
            "thread_id": args.thread_id,
            "output_dir": str(output_dir),
            "run_real_tools": args.run_real_tools,
            "strict_signoff": False,
            "plan_approved": False,
            "debug_iterations": 0,
            "max_debug_iterations": 5,
            "reports": {},
        }
        state = app.invoke(initial, config=config)
        state = _resume_until_target_if_needed(app, config, state, args.stop_after)

    if args.stop_after != "agent1":
        write_outputs(state, output_dir)

    result = _summarize(args.stop_after, output_dir, checkpoint_db, state)
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    if not result["pass"]:
        raise SystemExit(1)


def _resume_until_target_if_needed(app: Any, config: dict[str, Any], state: dict[str, Any], stop_after: str) -> dict[str, Any]:
    """Auto-approve HITL gates needed to reach later agents."""
    while True:
        if not isinstance(state, dict) or not state.get("__interrupt__"):
            return state
        payloads = [item.value for item in state.get("__interrupt__", [])]
        action = payloads[0].get("action_required") if payloads else None

        if stop_after == "agent1":
            return state
        if action == "PLAN_REVIEW":
            state = app.invoke(Command(resume={"response": "ok", "approved": True, "reviewer": "partial-runner", "notes": "ok"}), config=config)
            continue
        if action == "HUMAN_REVIEW" and stop_after in {"agent3", "agent4"}:
            state = app.invoke(Command(resume={"approved": True, "reviewer": "partial-runner", "notes": "approved"}), config=config)
            continue
        return state


def _prepare_output_dir(path: Path, policy: str) -> Path:
    if path.exists() and any(path.iterdir()):
        if policy == "abort":
            raise SystemExit(f"Abort: output directory already exists: {path}")
        if policy == "overwrite":
            shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _summarize(stop_after: str, output_dir: Path, checkpoint_db: Path, state: dict[str, Any]) -> dict[str, Any]:
    status_log = output_dir / "status.log"
    status_text = status_log.read_text(encoding="utf-8", errors="replace") if status_log.exists() else ""
    plan_path = output_dir / "reports" / "architecture_plan.md"
    rtl_dir = output_dir / "rtl"
    rtl_files = list(rtl_dir.glob("*.sv")) if rtl_dir.exists() else []
    agent2_called = "[RTL] Agent 2 generating RTL" in status_text
    expected_status = {
        "agent1": "PLANNING_READY",
        "rtl_lint": "AGENT2_LINT_PASS",
        "agent2": "AGENT2_LINT_PASS",
        "agent5": "AGENT5_FORMAL_PASS",
        "agent3": "AGENT3_DV_DONE",
        "agent4": "SIGNOFF_READY",
    }[stop_after]
    checks = {
        "checkpoint_exists": checkpoint_db.exists(),
        "expected_status": state.get("status") == expected_status,
        "plan_exists": plan_path.exists(),
    }
    if stop_after == "agent1":
        checks["agent2_not_called"] = not agent2_called
        checks["no_rtl_sv_generated"] = len(rtl_files) == 0
        agent1_dir = output_dir / "reports" / "agent1"
        project_name = str(state.get("project_name", "swarm_soc"))
        v35_files = [
            agent1_dir / "agent1_register_map.rdl",
            agent1_dir / f"fw_{project_name}_regs.h",
            agent1_dir / f"fw_{project_name}_driver_stub.c",
            agent1_dir / f"tb_{project_name}_reg_model.py",
        ]
        checks["agent1_v35_rdl_fw_dv_files"] = all(path.exists() for path in v35_files)
    else:
        checks["agent2_called"] = agent2_called
    if stop_after in {"agent2", "rtl_lint"}:
        agent2_lint = state.get("reports", {}).get("agent2_lint", state.get("reports", {}).get("agent2", {}))
        lint_tool = agent2_lint.get("linter_report", {}).get("verilator", {}).get("tool")
        if lint_tool is None:
            lint_tool = agent2_lint.get("verilator", {}).get("tool", "unknown")
        rtl_text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in rtl_files)
        checks["agent2_lint_called"] = bool(agent2_lint)
        checks["agent2_lint_pass"] = bool(agent2_lint.get("pass"))
        checks["apb_pattern_marker_present"] = "AGENT2_PATTERN_ID: apb_slave_template" in rtl_text
    else:
        lint_tool = None
    return {
        "pass": all(checks.values()),
        "stop_after": stop_after,
        "status": state.get("status"),
        "output_dir": str(output_dir),
        "checkpoint_db": str(checkpoint_db),
        "checks": checks,
        "agent2_lint_pass": checks.get("agent2_lint_pass"),
        "apb_pattern_marker_present": checks.get("apb_pattern_marker_present"),
        "lint_tool": lint_tool,
        "plan_path": str(plan_path),
        "rtl_sv_count": len(rtl_files),
    }


if __name__ == "__main__":
    main()