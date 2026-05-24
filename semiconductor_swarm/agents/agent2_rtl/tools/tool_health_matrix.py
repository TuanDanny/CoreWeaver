"""Agent 2 V3 tool health matrix and smoke-report artifacts."""
from __future__ import annotations

import shutil
import subprocess
import os
from typing import Any

from semiconductor_swarm.contracts.constants import SWARM_FALLBACK_POLICIES, SWARM_MODE_DEMO, SWARM_MODE_REQUIRES_REAL_TOOLS

VALID_STATUSES = {"missing", "healthy", "broken", "degraded"}


def probe_command(name: str, commands: list[list[str]]) -> dict[str, object]:
    for command in commands:
        executable = shutil.which(command[0])
        if not executable:
            continue
        try:
            proc = subprocess.run([executable, *command[1:]], text=True, capture_output=True, timeout=20, check=False)
        except Exception as exc:  # pragma: no cover - platform/tool dependent
            return {"name": name, "status": "broken", "command": " ".join(command), "path": executable, "returncode": None, "stdout": "", "stderr": str(exc), "provenance": "probe_exception"}
        status = "healthy" if proc.returncode == 0 else "broken"
        return {"name": name, "status": status, "command": " ".join(command), "path": executable, "returncode": proc.returncode, "stdout": proc.stdout[-1000:], "stderr": proc.stderr[-1000:], "provenance": "version_probe"}
    return {"name": name, "status": "missing", "command": " | ".join(" ".join(command) for command in commands), "path": None, "returncode": None, "stdout": "", "stderr": "", "provenance": "tool_not_found_on_path"}


def run_command(executable_name: str, stdin: str | None = None, cwd: str | None = None) -> dict[str, Any]:
    executable = shutil.which(executable_name)
    if not executable:
        return {"ran": False, "pass": False, "command": executable_name, "path": None, "returncode": None, "stdout": "", "stderr": "", "provenance": "tool_not_found_on_path", "blocking_findings": []}
    try:
        proc = subprocess.run([executable], input=stdin, text=True, capture_output=True, timeout=30, check=False, cwd=cwd)
    except Exception as exc:  # pragma: no cover - platform/tool dependent
        return {"ran": True, "pass": False, "command": executable_name, "path": executable, "returncode": None, "stdout": "", "stderr": str(exc), "provenance": "smoke_exception", "blocking_findings": [{"severity": "error", "tool": executable_name, "message": str(exc)}]}
    message = (proc.stderr or proc.stdout or f"{executable_name} exited with returncode {proc.returncode}")[-1000:]
    blocking = [] if proc.returncode == 0 else [{"severity": "error", "tool": executable_name, "message": message}]
    return {"ran": True, "pass": proc.returncode == 0, "command": executable_name, "path": executable, "returncode": proc.returncode, "stdout": proc.stdout[-1000:], "stderr": proc.stderr[-1000:], "provenance": "real_smoke_run", "blocking_findings": blocking}


def run_command_args(command: list[str], stdin: str | None = None, cwd: str | None = None) -> dict[str, Any]:
    executable = shutil.which(command[0])
    command_text = " ".join(command)
    if not executable:
        return {"ran": False, "pass": False, "command": command_text, "path": None, "returncode": None, "stdout": "", "stderr": "", "provenance": "tool_not_found_on_path", "blocking_findings": []}
    try:
        proc = subprocess.run([executable, *command[1:]], input=stdin, text=True, capture_output=True, timeout=45, check=False, cwd=cwd, env=_tool_env())
    except Exception as exc:  # pragma: no cover - platform/tool dependent
        return {"ran": True, "pass": False, "command": command_text, "path": executable, "returncode": None, "stdout": "", "stderr": str(exc), "provenance": "tool_run_exception", "blocking_findings": [{"severity": "error", "tool": command[0], "message": str(exc)}]}
    message = (proc.stderr or proc.stdout or f"{command_text} exited with returncode {proc.returncode}")[-1000:]
    blocking = [] if proc.returncode == 0 else [{"severity": "error", "tool": command[0], "message": message}]
    return {"ran": True, "pass": proc.returncode == 0, "command": command_text, "path": executable, "returncode": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:], "provenance": "real_tool_run", "blocking_findings": blocking}


def _tool_env() -> dict[str, str]:
    env = os.environ.copy()
    if not env.get("VERILATOR_ROOT"):
        executable = shutil.which("verilator_bin.exe") or shutil.which("verilator")
        if executable:
            root = os.path.abspath(os.path.join(os.path.dirname(executable), "..", "share", "verilator"))
            if os.path.exists(os.path.join(root, "include", "verilated_std.sv")):
                env["VERILATOR_ROOT"] = root
    return env


def build_tool_health_artifacts(spec: dict[str, Any], files: list[dict[str, Any]], semantic_lint_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    from semiconductor_swarm.agents.agent2_rtl.tools.symbiyosys_adapter import probe_symbiyosys
    from semiconductor_swarm.agents.agent2_rtl.tools.verilator_adapter import probe_verilator
    from semiconductor_swarm.agents.agent2_rtl.tools.yosys_adapter import probe_yosys

    from semiconductor_swarm.agents.agent2_rtl.tools.symbiyosys_adapter import run_symbiyosys_smoke
    from semiconductor_swarm.agents.agent2_rtl.tools.yosys_adapter import run_yosys_smoke

    swarm_mode = str(spec.get("constraints", {}).get("swarm_mode", SWARM_MODE_DEMO))
    fallback_policy = SWARM_FALLBACK_POLICIES.get(swarm_mode, SWARM_FALLBACK_POLICIES[SWARM_MODE_DEMO])
    requires_real_tools = bool(SWARM_MODE_REQUIRES_REAL_TOOLS.get(swarm_mode, False))
    probes = [probe_verilator(), probe_yosys(), probe_symbiyosys()]
    tools = {str(probe["name"]): probe for probe in probes}
    blocking_findings = []
    degraded_reasons = []
    for probe in probes:
        if probe["status"] == "broken":
            degraded_reasons.append({"tool": probe["name"], "reason": probe.get("stderr") or "nonzero_version_probe"})
        if requires_real_tools and probe["status"] == "missing":
            degraded_reasons.append({"tool": probe["name"], "reason": "required_real_tool_missing", "status": "missing"})
    if tools["verilator"]["status"] == "healthy" and not semantic_lint_report.get("pass", False):
        blocking_findings.extend(semantic_lint_report.get("findings", []))
    matrix = {
        "schema_version": "agent2.tool_health_matrix.v1",
        "milestone": "AGENT_2_V3.3_TOOL_HEALTH_MATRIX",
        "project": spec.get("project_name"),
        "valid_statuses": sorted(VALID_STATUSES),
        "swarm_mode": swarm_mode,
        "fallback_policy": fallback_policy,
        "requires_real_tools": requires_real_tools,
        "tools": tools,
        "policy": {
            "missing_tool": "fallback_forbidden" if requires_real_tools else "fallback_allowed_with_explicit_provenance",
            "healthy_tool_rtl_error": "blocking_finding",
            "broken_tool": "degraded_tooling_release_decision_required",
            "fallback_policy": fallback_policy,
        },
        "blocking_findings": blocking_findings,
        "optional_smoke_findings": [],
        "degraded_reasons": degraded_reasons,
        "pass": not blocking_findings and not degraded_reasons,
    }
    synthesis_smoke = _smoke_report("agent2.synthesis_smoke_report.v1", "yosys", tools["yosys"], files, run_yosys_smoke)
    formal_smoke = _smoke_report("agent2.formal_smoke_report.v1", "symbiyosys", tools["symbiyosys"], files, run_symbiyosys_smoke)
    real_tool_gate_findings = _real_tool_gate_findings(requires_real_tools, [synthesis_smoke, formal_smoke], probes)
    if real_tool_gate_findings:
        matrix["blocking_findings"].extend(real_tool_gate_findings)
        matrix["degraded_reasons"].extend({"tool": finding["tool"], "reason": finding["rule"], "status": finding.get("tool_status")} for finding in real_tool_gate_findings)
        matrix["pass"] = False
    if not requires_real_tools:
        for smoke in [synthesis_smoke, formal_smoke]:
            if smoke["ran"] and not smoke["pass"]:
                matrix["optional_smoke_findings"].extend(_smoke_failure_findings(smoke, "optional_real_smoke_failed"))
    matrix["pass"] = not matrix["blocking_findings"] and not matrix["degraded_reasons"]
    matrix["real_tool_gate"] = {
        "requires_real_tools": requires_real_tools,
        "pass": not real_tool_gate_findings,
        "checked_tools": ["verilator", "yosys", "symbiyosys"],
        "required_smokes": ["yosys", "symbiyosys"],
        "blocking_findings": real_tool_gate_findings,
        "policy": "fallback_forbidden_when_requires_real_tools" if requires_real_tools else "fallback_allowed_with_explicit_provenance",
    }
    return {
        "tool_health_matrix": matrix,
        "synthesis_smoke_report": synthesis_smoke,
        "formal_smoke_report": formal_smoke,
    }


def _smoke_report(schema_version: str, tool_name: str, tool: dict[str, Any], files: list[dict[str, Any]], runner: Any) -> dict[str, Any]:
    status = str(tool.get("status"))
    ran = status == "healthy"
    result = runner(files) if ran else {"ran": False, "pass": False, "blocking_findings": []}
    return {
        "schema_version": schema_version,
        "tool": tool_name,
        "tool_status": status if status in VALID_STATUSES else "degraded",
        "ran": bool(result.get("ran", ran)),
        "pass": bool(result.get("pass", False)) if ran else False,
        "provenance": result.get("provenance", "not_run"),
        "command": result.get("command"),
        "returncode": result.get("returncode"),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "files_checked": [str(file.get("filename")) for file in files if file.get("language") == "systemverilog"],
        "fallback_provenance": None if ran else {"reason": tool.get("provenance", "tool_unavailable"), "tool_status": status, "policy": "no_silent_pass"},
        "blocking_findings": list(result.get("blocking_findings", [])),
    }


def _real_tool_gate_findings(requires_real_tools: bool, smoke_reports: list[dict[str, Any]], probes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not requires_real_tools:
        return []
    findings: list[dict[str, Any]] = []
    for probe in probes:
        status = str(probe.get("status"))
        if status != "healthy":
            findings.append({"severity": "error", "rule": "required_real_tool_not_healthy", "tool": probe.get("name"), "tool_status": status, "message": "strict/nightly mode requires healthy real tool"})
    for smoke in smoke_reports:
        if not smoke.get("ran"):
            findings.append({"severity": "error", "rule": "required_real_smoke_not_run", "tool": smoke.get("tool"), "tool_status": smoke.get("tool_status"), "message": "strict/nightly mode requires real smoke run"})
        elif not smoke.get("pass"):
            findings.extend(_smoke_failure_findings(smoke, "required_real_smoke_failed"))
        if smoke.get("fallback_provenance") is not None:
            findings.append({"severity": "error", "rule": "fallback_forbidden", "tool": smoke.get("tool"), "tool_status": smoke.get("tool_status"), "message": "strict/nightly mode forbids fallback provenance"})
    return findings


def _smoke_failure_findings(smoke: dict[str, Any], rule: str) -> list[dict[str, Any]]:
    tool = str(smoke.get("tool") or "tool")
    default = {
        "severity": "error",
        "rule": rule,
        "tool": tool,
        "tool_status": smoke.get("tool_status"),
        "returncode": smoke.get("returncode"),
        "message": f"{tool} smoke failed with returncode {smoke.get('returncode')}",
    }
    findings = list(smoke.get("blocking_findings", [])) or [default]
    normalized = []
    for finding in findings:
        normalized.append({
            **finding,
            "severity": finding.get("severity", "error"),
            "rule": finding.get("rule", rule),
            "tool": finding.get("tool", tool),
            "tool_status": finding.get("tool_status", smoke.get("tool_status")),
            "returncode": finding.get("returncode", smoke.get("returncode")),
            "message": finding.get("message") or default["message"],
        })
    return normalized
