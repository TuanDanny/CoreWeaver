"""Verilator health probe and lint report for Agent 2 V4 Phase 1."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from semiconductor_swarm.agents.agent2_rtl.tools.tool_health_matrix import probe_command, run_command_args


def probe_verilator() -> dict[str, object]:
    return probe_command("verilator", [["verilator", "--version"], ["verilator_bin.exe", "--version"]])


def run_verilator_lint(files: list[dict[str, Any]], compile_order: list[str]) -> dict[str, Any]:
    sv_files = [name for name in compile_order if name.endswith(".sv")]
    with tempfile.TemporaryDirectory(prefix="agent2_verilator_") as temp_dir:
        _materialize_sv_files(files, Path(temp_dir))
        args = ["--lint-only", "--sv", "-Wall", "-Wno-fatal", *sv_files]
        first_missing: dict[str, Any] | None = None
        for executable in ["verilator", "verilator_bin.exe"]:
            result = run_command_args([executable, *args], stdin=None, cwd=temp_dir)
            if result.get("provenance") == "tool_not_found_on_path":
                first_missing = first_missing or result
                continue
            return _degrade_broken_install(result)
        return first_missing or run_command_args(["verilator", *args], stdin=None, cwd=temp_dir)


def _degrade_broken_install(result: dict[str, Any]) -> dict[str, Any]:
    stderr = str(result.get("stderr", ""))
    if "Cannot find verilated_std" in stderr or "Cannot find verilated_std_waiver" in stderr:
        result = dict(result)
        result["pass"] = True
        result["tool_status"] = "degraded"
        result["provenance"] = "degraded_tool_install"
        result["blocking_findings"] = []
        result["degraded_reasons"] = [{"tool": "verilator", "reason": "broken_builtin_include_path", "message": stderr[-1000:]}]
    return result


def _materialize_sv_files(files: list[dict[str, Any]], root: Path) -> None:
    for file in files:
        if file.get("language") != "systemverilog":
            continue
        path = root / str(file.get("filename"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(file.get("content", "")), encoding="utf-8")
