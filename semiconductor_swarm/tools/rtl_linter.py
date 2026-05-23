"""Plan-compatible RTL lint tool wrapper for Agent 2.

Public API follows AGENT_2_Upgrade_V1 while preserving the existing Agent 2
internal linter implementation.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from semiconductor_swarm.agents.agent2_rtl.rtl_linter import lint_rtl_files as _lint_agent2_rtl_files


def lint_rtl_files(files: list[dict[str, Any]], work_dir: str | Path | None = None) -> dict[str, Any]:
    """Lint SystemVerilog files and return plan-compatible report schema."""
    spec = _infer_spec_from_files(files)
    internal = _lint_agent2_rtl_files(spec, files)
    verilator = internal.get("verilator", {})
    tool = str(verilator.get("tool", "static_fallback"))
    failures = [str(finding.get("message", finding)) for finding in internal.get("findings", [])]
    files_checked = [str(file.get("filename", "rtl.sv")) for file in files if file.get("language") == "systemverilog"]
    command = f"{tool} --lint-only -Wall " + " ".join(files_checked) if tool in {"verilator", "verilator_bin.exe"} else "static_fallback"
    return {
        "pass": bool(internal.get("pass")),
        "tool": tool,
        "command": command,
        "files_checked": files_checked,
        "failures": failures,
        "stdout": str(verilator.get("stdout", "")),
        "stderr": str(verilator.get("stderr", "")),
        "work_dir": str(work_dir) if work_dir is not None else None,
        "internal_report": internal,
    }


def _infer_spec_from_files(files: list[dict[str, Any]]) -> dict[str, Any]:
    text = "\n".join(str(file.get("content", "")) for file in files)
    interfaces: dict[str, Any] = {}
    if "AGENT2_PATTERN_ID: apb_slave_template" in text or "psel_i" in text:
        interfaces["apb"] = {}
    if "AGENT2_PATTERN_ID: sync_fifo_template" in text or "wr_ptr_q" in text:
        interfaces["fifo"] = {}
    return {"project_name": "agent2_lint", "interfaces": interfaces, "ip_blocks": []}
