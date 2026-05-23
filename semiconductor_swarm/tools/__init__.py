"""EDA tool detection helpers for strict signoff and real-tool smoke tests."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


TOOL_COMMANDS = {
    "sby": ["sby", "--version"],
    "yosys": ["yosys", "-V"],
    "z3": ["z3", "--version"],
    "verilator": ["verilator", "--version"],
    "make": ["make", "--version"],
    "quartus_sh": ["quartus_sh", "--version"],
}


def detect_real_tools() -> dict[str, Any]:
    tools = {name: _detect_command(name, command) for name, command in TOOL_COMMANDS.items()}
    tools["cocotb"] = _detect_python_package("cocotb")
    groups = {
        "formal": _group(["sby", "yosys", "z3"], tools),
        "dv": _group(["verilator", "make", "cocotb"], tools),
        "quartus": _group(["quartus_sh"], tools),
    }
    return {"tools": tools, "groups": groups}


def write_tool_detection_report(path: str | Path) -> dict[str, Any]:
    report = detect_real_tools()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="ascii")
    return report


def _detect_command(name: str, command: list[str]) -> dict[str, Any]:
    executable = shutil.which(command[0])
    if executable is None:
        return {"available": False, "path": None, "version": "", "reason": f"{command[0]} not found on PATH"}
    try:
        proc = subprocess.run(command, text=True, capture_output=True, check=False, timeout=15)
        version = "\n".join((proc.stdout + "\n" + proc.stderr).splitlines()[:5]).strip()
        return {"available": proc.returncode == 0 or bool(version), "path": executable, "version": version, "returncode": proc.returncode}
    except Exception as exc:  # pragma: no cover - depends on host tool behavior
        return {"available": False, "path": executable, "version": "", "reason": str(exc)}


def _detect_python_package(name: str) -> dict[str, Any]:
    spec = importlib.util.find_spec(name)
    if spec is None:
        return {"available": False, "path": None, "version": "", "reason": f"Python package {name!r} not importable"}
    return {"available": True, "path": spec.origin, "version": "importable"}


def _group(names: list[str], tools: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing = [name for name in names if not tools.get(name, {}).get("available")]
    return {"available": not missing, "required": names, "missing": missing}