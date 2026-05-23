"""SymbiYosys health probe and smoke runner for Agent 2 V3."""
from __future__ import annotations

from typing import Any

from semiconductor_swarm.agents.agent2_rtl.tools.tool_health_matrix import probe_command, run_command_args


def probe_symbiyosys() -> dict[str, object]:
    return probe_command("symbiyosys", [["sby", "--version"]])


def run_symbiyosys_smoke(files: list[dict[str, Any]]) -> dict[str, Any]:
    del files
    return run_command_args(["sby", "--version"])