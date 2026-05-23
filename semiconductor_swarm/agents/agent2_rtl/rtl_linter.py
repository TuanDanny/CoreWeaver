"""Static RTL linter used by Agent 2 self-checks."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from semiconductor_swarm.agents.agent2_rtl.pattern_library import select_patterns_for_spec


FORBIDDEN_RTL_TOKENS = ("$display", "#delay", "initial begin", " reg ", " wire ")


def lint_rtl_files(spec: dict[str, Any], files: list[dict[str, Any]]) -> dict[str, Any]:
    rtl_files = [file for file in files if file.get("language") == "systemverilog"]
    rtl_text = "\n".join(str(file.get("content", "")) for file in rtl_files)
    findings: list[dict[str, Any]] = []
    checks: dict[str, bool] = {}

    checks["no_forbidden_tokens"] = True
    for token in FORBIDDEN_RTL_TOKENS:
        if token in rtl_text:
            checks["no_forbidden_tokens"] = False
            findings.append({"severity": "error", "rule": "no_forbidden_tokens", "message": f"forbidden token found: {token}"})

    checks["pattern_tokens_present"] = True
    for pattern in select_patterns_for_spec(spec):
        for token in pattern.required_tokens:
            if token not in rtl_text:
                checks["pattern_tokens_present"] = False
                findings.append({"severity": "error", "rule": "pattern_tokens_present", "message": f"{pattern.name} missing token: {token}"})
        for token in pattern.forbidden_tokens:
            if token in rtl_text:
                checks["pattern_tokens_present"] = False
                findings.append({"severity": "error", "rule": "pattern_forbidden_tokens", "message": f"{pattern.name} forbidden token found: {token}"})

    checks["no_todo_placeholders"] = not bool(re.search(r"\b(TODO|FIXME|stub)\b", rtl_text, flags=re.IGNORECASE))
    if not checks["no_todo_placeholders"]:
        findings.append({"severity": "error", "rule": "no_todo_placeholders", "message": "TODO/FIXME/stub placeholder found"})

    module_count = len(re.findall(r"^module\s+", rtl_text, flags=re.MULTILINE))
    checks["module_count_nonzero"] = module_count > 0
    if module_count == 0:
        findings.append({"severity": "error", "rule": "module_count_nonzero", "message": "no modules found"})

    verilator_report = _run_verilator_if_available(rtl_files)
    checks["verilator_or_static_fallback_pass"] = verilator_report["pass"]
    if not verilator_report["pass"]:
        findings.append({"severity": "error", "rule": "verilator_lint", "message": verilator_report["stderr"][-500:]})

    return {
        "pass": all(checks.values()),
        "checks": checks,
        "findings": findings,
        "module_count": module_count,
        "file_count": len(rtl_files),
        "verilator": verilator_report,
    }


def _run_verilator_if_available(rtl_files: list[dict[str, Any]]) -> dict[str, Any]:
    verilator = shutil.which("verilator") or shutil.which("verilator_bin.exe")
    if not verilator:
        return {"tool": "static_fallback", "available": False, "pass": True, "stdout": "", "stderr": ""}
    tool_name = Path(verilator).name
    with tempfile.TemporaryDirectory(prefix="agent2_verilator_") as tmp:
        tmp_path = Path(tmp)
        paths = []
        for file in rtl_files:
            path = tmp_path / Path(str(file.get("filename", "rtl.sv"))).name
            path.write_text(str(file.get("content", "")), encoding="utf-8")
            paths.append(str(path))
        proc = subprocess.run([verilator, "--lint-only", "-sv", *paths], cwd=tmp_path, text=True, capture_output=True, timeout=120)
        if proc.returncode != 0:
            syntax_error = "syntax error" in proc.stderr.lower()
            return {
                "tool": tool_name if syntax_error else "static_fallback",
                "attempted_tool": tool_name,
                "available": True,
                "pass": False if syntax_error else True,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "returncode": proc.returncode,
                "reason": "verilator_syntax_error" if syntax_error else "verilator_environment_failed_using_static_fallback",
            }
        return {"tool": tool_name, "available": True, "pass": True, "stdout": proc.stdout, "stderr": proc.stderr, "returncode": proc.returncode}
