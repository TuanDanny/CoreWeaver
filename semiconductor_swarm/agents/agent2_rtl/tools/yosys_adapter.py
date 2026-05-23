"""Yosys health probe and smoke runner for Agent 2 V3."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from semiconductor_swarm.agents.agent2_rtl.tools.tool_health_matrix import probe_command, run_command


def probe_yosys() -> dict[str, object]:
    return probe_command("yosys", [["yosys", "-V"]])


def run_yosys_smoke(files: list[dict[str, Any]]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="agent2_yosys_") as temp_dir:
        _materialize_sv_files(files, Path(temp_dir))
        return run_command("yosys", _script(files), cwd=temp_dir)


def _script(files: list[dict[str, Any]]) -> str:
    sv_files = [str(file.get("filename")) for file in files if file.get("language") == "systemverilog"]
    reads = "\n".join(f"read_verilog -sv {name}" for name in sv_files)
    return f"{reads}\nhierarchy -check\nproc\ncheck\n"


def _materialize_sv_files(files: list[dict[str, Any]], root: Path) -> None:
    for file in files:
        if file.get("language") != "systemverilog":
            continue
        path = root / str(file.get("filename"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(file.get("content", "")), encoding="utf-8")
