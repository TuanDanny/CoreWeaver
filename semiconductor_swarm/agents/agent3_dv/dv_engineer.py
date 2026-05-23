"""Rule-based Agent 3 prototype for practical Cocotb/Pytest DV collateral."""
from __future__ import annotations

import importlib.util
import importlib.metadata
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import site
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from semiconductor_swarm.agents.agent1_planning.architect import validate_architecture_spec
from semiconductor_swarm.contracts.constants import AGENT3_RESULT_V1

MAX_DEBUG_ITERATIONS = 5
DV_MODES = ("demo", "dev", "strict", "nightly-real-tools")
STRICT_DV_MODES = {"strict", "nightly-real-tools"}
PRIMARY_SIMULATOR = "verilator+cocotb"
SECONDARY_SIMULATOR = "modelsim/questa"
APB_REQUIRED_PORTS = (
    "clk_i",
    "rst_ni",
    "psel_i",
    "penable_i",
    "pwrite_i",
    "paddr_i",
    "pwdata_i",
    "prdata_o",
    "pready_o",
    "pslverr_o",
)
COVERAGE_TARGETS = {"line": 95, "branch": 90, "functional": 90}
COVERAGE_GOALS = {
    "fsm_states": "All FSM states visited",
    "register_rw": "All register fields written/read",
    "bus_errors": "All bus error conditions triggered",
    "boundary": "Boundary values for all parameters",
    "interrupts": "Interrupt generation and clearing",
}
FUNCTIONAL_COVERAGE_BINS = (
    "reset",
    "apb_write",
    "apb_read",
    "boundary_zero",
    "boundary_all_ones",
    "illegal_address",
    "interrupt_clear_mask",
    "block_state_hooks",
)
QUALITY_RULES = (
    "python_cocotb_only",
    "pytest_markers_present",
    "coverage_goals_present",
    "one_testbench_per_block",
    "reset_test_present",
    "apb_write_read_test_present",
    "verilator_makefile_present",
    "coverage_targets_present",
    "hitl_after_five_iterations",
    "fix_request_schema_present",
    "modelsim_script_present",
    "modelsim_runner_present",
    "wave_dump_present",
    "generated_rtl_path_absent",
    "compile_order_present",
    "manifest_schema_present",
    "tool_health_present",
    "result_contract_present",
    "scoreboard_report_present",
    "coverage_report_present",
    "release_decision_present",
    "apb_ports_static_valid",
    "top_module_static_valid",
    "strict_mode_gate_present",
)


@dataclass(frozen=True)
class DVFile:
    filename: str
    language: str
    content: str
    line_count: int
    dependencies: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "language": self.language,
            "content": self.content,
            "line_count": self.line_count,
            "dependencies": self.dependencies,
        }


def generate_dv_files(
    spec: dict[str, Any],
    rtl_files: list[dict[str, Any]],
    *,
    debug: bool = False,
) -> list[dict[str, Any]]:
    validate_architecture_spec(spec)
    _validate_rtl_files(spec, rtl_files)

    project = spec["project_name"]
    top = _top_module(spec)
    blocks = [block["name"] for block in spec["ip_blocks"]]
    mode = _dv_mode(spec)
    requires_real_tools = _requires_real_tools(spec, mode)
    compile_order = _compile_order(spec, rtl_files)
    test_files = [f"test_{block}.py" for block in blocks]
    coverage_plan = _coverage_plan(spec, rtl_files)
    tool_health = probe_dv_tool_health(required=requires_real_tools)
    sim_report = _initial_sim_report(project, mode, requires_real_tools, tool_health)
    coverage_report = _coverage_report(project, coverage_plan, sim_report, mode)
    scoreboard_report = _scoreboard_report(spec, rtl_files, mode)
    release_decision = _release_decision(project, mode, requires_real_tools, tool_health, sim_report, coverage_report)
    result_contract = _agent3_result_contract(project, release_decision, coverage_report, tool_health, sim_report)
    manifest = _dv_manifest(
        spec=spec,
        top=top,
        rtl_files=rtl_files,
        compile_order=compile_order,
        test_files=test_files,
        mode=mode,
        requires_real_tools=requires_real_tools,
        coverage_plan=coverage_plan,
    )

    files = [
        _file("agent3_dv_manifest.json", _json(manifest), "json", [f["filename"] for f in rtl_files]),
        _file("agent3_tool_health.json", _json(tool_health), "json", []),
        _file("agent3_compile_order.f", "\n".join(compile_order) + "\n", "filelist", [f["filename"] for f in rtl_files]),
        _file("agent3_sim_report.json", _json(sim_report), "json", ["agent3_dv_manifest.json"]),
        _file("agent3_coverage_report.json", _json(coverage_report), "json", ["agent3_sim_report.json"]),
        _file("agent3_scoreboard_report.json", _json(scoreboard_report), "json", ["agent3_dv_manifest.json"]),
        _file("agent3_release_decision.json", _json(release_decision), "json", ["agent3_sim_report.json", "agent3_coverage_report.json"]),
        _file("agent3_result.json", _json(result_contract), "json", ["agent3_release_decision.json"]),
        _file("agent3_dv_dashboard.md", _dashboard(project, top, mode, release_decision, sim_report), "markdown", ["agent3_release_decision.json"]),
        _file("dv_helpers.py", _dv_helpers(), "python", ["agent3_dv_manifest.json"]),
        _file("test_plan.py", _test_plan(project, blocks, coverage_plan), "python", ["agent3_dv_manifest.json"]),
        _file("conftest.py", _conftest(), "python", []),
        _file("Makefile", _makefile(project), "makefile", ["agent3_compile_order.f", "agent3_dv_manifest.json"]),
        _file("ModelSim.mk", _modelsim_makefile(project), "makefile", ["agent3_compile_order.f", "agent3_dv_manifest.json"]),
        _file("sim.do", _modelsim_do(project, top), "modelsim_do", ["agent3_compile_order.f"]),
        _file("run_cocotb_sim.py", _runner(project), "python", ["Makefile", "agent3_dv_manifest.json"]),
        _file("run_modelsim_sim.py", _modelsim_runner(project), "python", ["sim.do", "ModelSim.mk", "agent3_dv_manifest.json"]),
        _file("debug_orchestrator.py", _debug_orchestrator(), "python", []),
    ]
    files.extend(_file(f"test_{block}.py", _block_test(project, block), "python", ["dv_helpers.py", f"{block}.sv"]) for block in blocks)

    result = [file.as_dict() for file in files]
    report = verify_dv_files(spec, rtl_files, result)
    if not report["pass"]:
        raise ValueError(f"Generated DV collateral failed Agent 3 self-check: {report['failures']}")
    if debug:
        result.append(_file("agent3_debug_report.json", _json(report), "json", []).as_dict())
    return result


def verify_dv_files(spec: dict[str, Any], rtl_files: list[dict[str, Any]], dv_files: list[dict[str, Any]]) -> dict[str, Any]:
    validate_architecture_spec(spec)
    blocks = [block["name"] for block in spec["ip_blocks"]]
    by_name = {file["filename"]: file for file in dv_files}
    text = "\n".join(file.get("content", "") for file in dv_files)
    checks = {rule: True for rule in QUALITY_RULES}
    failures: list[str] = []

    manifest = _load_json(by_name, "agent3_dv_manifest.json", failures)
    tool_health = _load_json(by_name, "agent3_tool_health.json", failures)
    sim_report = _load_json(by_name, "agent3_sim_report.json", failures)
    coverage_report = _load_json(by_name, "agent3_coverage_report.json", failures)
    scoreboard_report = _load_json(by_name, "agent3_scoreboard_report.json", failures)
    release_decision = _load_json(by_name, "agent3_release_decision.json", failures)
    result_contract = _load_json(by_name, "agent3_result.json", failures)

    checks["python_cocotb_only"] = "uvm" not in text.lower() and "import cocotb" in text
    checks["pytest_markers_present"] = "@pytest.mark" in by_name.get("test_plan.py", {}).get("content", "")
    checks["coverage_goals_present"] = all(goal in text for goal in COVERAGE_GOALS)
    checks["one_testbench_per_block"] = all(f"test_{block}.py" in by_name for block in blocks)
    checks["reset_test_present"] = "async def test_reset" in text
    checks["apb_write_read_test_present"] = "async def test_apb_write_read" in text and "0xDEADBEEF" in text
    checks["verilator_makefile_present"] = "SIM ?= verilator" in by_name.get("Makefile", {}).get("content", "")
    checks["coverage_targets_present"] = "Line>=95%" in text and "Branch>=90%" in text
    checks["hitl_after_five_iterations"] = "MAX_DEBUG_ITERATIONS = 5" in text and "HUMAN_CODE_OVERWRITE" in text
    checks["fix_request_schema_present"] = all(t in text for t in ("bug_id", "severity", "failing_test", "cocotb_log_snippet"))
    checks["modelsim_script_present"] = "sim.do" in by_name and "vsim -c" in text and "vlog -sv" in text
    checks["modelsim_runner_present"] = "def run_modelsim_sim" in text and "shutil.which(\"vlog\")" in text and "shutil.which(\"vsim\")" in text
    checks["wave_dump_present"] = all(token in text for token in ("wave.wlf", "dump.vcd", "vcd file"))
    checks["generated_rtl_path_absent"] = "../generated_rtl" not in text and "generated_rtl/*.sv" not in text
    checks["compile_order_present"] = "agent3_compile_order.f" in by_name and bool(by_name.get("agent3_compile_order.f", {}).get("content", "").strip())
    checks["manifest_schema_present"] = _manifest_valid(spec, rtl_files, manifest, failures)
    checks["tool_health_present"] = _tool_health_valid(tool_health)
    checks["result_contract_present"] = _result_contract_valid(spec, result_contract, failures)
    checks["scoreboard_report_present"] = isinstance(scoreboard_report.get("per_block_checks"), list) and bool(scoreboard_report.get("per_block_checks"))
    checks["coverage_report_present"] = isinstance(coverage_report.get("bins"), list) and bool(coverage_report.get("bins"))
    checks["release_decision_present"] = release_decision.get("decision_label") in {
        "DV_DEMO_PASS",
        "DV_DEV_PASS_WITH_WARNINGS",
        "DV_STRICT_PASS",
        "DV_FAIL",
        "DV_NOT_RUN",
    }
    apb_findings = _rtl_apb_findings(spec, rtl_files)
    checks["apb_ports_static_valid"] = not apb_findings
    failures.extend(apb_findings)
    top_findings = _top_module_findings(spec, rtl_files, manifest)
    checks["top_module_static_valid"] = not top_findings
    failures.extend(top_findings)
    checks["strict_mode_gate_present"] = _strict_gate_valid(manifest, sim_report, release_decision, result_contract)

    compile_order_lines = [line.strip() for line in by_name.get("agent3_compile_order.f", {}).get("content", "").splitlines() if line.strip()]
    rtl_names = {file.get("filename") for file in _rtl_sv_files(rtl_files)}
    missing_compile_refs = [line for line in compile_order_lines if line not in rtl_names]
    if missing_compile_refs:
        checks["compile_order_present"] = False
        failures.append(f"compile order references missing RTL files: {missing_compile_refs}")

    for rule, passed in checks.items():
        if not passed and rule not in failures:
            failures.append(rule)

    return {
        "pass": not failures,
        "checks": checks,
        "failures": failures,
        "block_count": len(blocks),
        "coverage_targets": COVERAGE_TARGETS,
        "max_debug_iterations": MAX_DEBUG_ITERATIONS,
        "mode": manifest.get("mode") if isinstance(manifest, dict) else _dv_mode(spec),
        "pass_fail_status": result_contract.get("pass_fail_status", "fail") if isinstance(result_contract, dict) else "fail",
        "release_decision": release_decision,
    }


def analyze_simulation_log(sim_log: str, failing_test: str = "unknown") -> dict[str, Any]:
    lines = [line for line in sim_log.strip().splitlines() if line.strip()]
    file_match = re.search(r"([A-Za-z0-9_./\\-]+\.sv):(\d+)", sim_log)
    failure_class = _classify_failure(sim_log)
    return {
        "bug_id": "BUG_001",
        "severity": "critical" if failure_class in {"compile_error", "reset_failure", "scoreboard_mismatch", "timeout_deadlock"} else "medium",
        "owner": _failure_owner(failure_class),
        "failure_class": failure_class,
        "file": file_match.group(1) if file_match else _default_failure_file(failure_class),
        "line": int(file_match.group(2)) if file_match else 0,
        "description": _first_error_line(lines),
        "expected": "Cocotb/Pytest checks pass with APB protocol-compliant behavior",
        "actual": "Simulation reported a failure",
        "failing_test": failing_test,
        "failing_artifact": failing_test,
        "suggested_agent2_action": _suggested_agent2_action(failure_class),
        "rewrite_policy": "minimal_patch_only" if failure_class != "unknown" else "human_triage_before_whole_file_rewrite",
        "cocotb_log_snippet": "\n".join(lines[-20:]),
    }


def probe_dv_tool_health(required: bool = False) -> dict[str, Any]:
    tools = {
        "verilator": _tool_status("verilator"),
        "iverilog": _tool_status("iverilog"),
        "vvp": _tool_status("vvp"),
        "make": _tool_status("make"),
        "cocotb": _python_module_status("cocotb"),
        "vlog": _tool_status("vlog"),
        "vsim": _tool_status("vsim"),
    }
    primary_ready = all(tools[name]["available"] for name in ("verilator", "make", "cocotb"))
    windows_cocotb_ready = all(tools[name]["available"] for name in ("iverilog", "vvp", "make", "cocotb"))
    secondary_ready = all(tools[name]["available"] for name in ("vlog", "vsim"))
    return {
        "required": bool(required),
        "primary": PRIMARY_SIMULATOR,
        "windows_real_sim_fallback": "icarus+cocotb",
        "secondary": SECONDARY_SIMULATOR,
        "primary_ready": primary_ready or (os.name == "nt" and windows_cocotb_ready),
        "secondary_ready": secondary_ready,
        "tools": tools,
        "missing_required": [name for name in ("verilator", "make", "cocotb") if not tools[name]["available"]],
    }


def run_cocotb_sim(
    tb_dir: str | Path = "tb",
    *,
    make: str = "make",
    timeout_s: int = 600,
    require_tools: bool = True,
) -> dict[str, Any]:
    """Run the generated Cocotb/Verilator per-block regression and persist reports."""
    root = Path(tb_dir)
    manifest = _read_manifest_from_dir(root)
    project = str(manifest.get("project_name", root.parent.name))
    mode = str(manifest.get("mode", "demo"))
    requires_real_tools = bool(manifest.get("requires_real_tools", require_tools))
    coverage_plan = manifest.get("coverage_plan", {"bins": list(FUNCTIONAL_COVERAGE_BINS), "threshold_percent": COVERAGE_TARGETS["functional"]})
    tool_health = probe_dv_tool_health(required=requires_real_tools)
    if require_tools:
        for exe in (make,):
            if _which(exe) is None:
                raise FileNotFoundError(f"DV executable not found on PATH: {exe}")
        if not tool_health["tools"]["verilator"]["available"]:
            raise FileNotFoundError("DV executable not found on PATH: verilator")
        if importlib.util.find_spec("cocotb") is None:
            raise FileNotFoundError("Python module not found: cocotb")

    simulator = _select_cocotb_simulator(tool_health)
    simulator_tools = ("iverilog", "vvp") if simulator == "icarus" else ("verilator",)
    if require_tools:
        for tool in simulator_tools:
            if not tool_health["tools"].get(tool, {}).get("available"):
                raise FileNotFoundError(f"DV executable not found on PATH: {tool}")

    runs = []
    for target in _cocotb_targets_from_manifest(manifest):
        _clean_cocotb_build(root)
        cmd = [make, f"MODULE={target['module']}", f"TOPLEVEL={target['toplevel']}", f"SIM={simulator}"]
        if simulator == "verilator":
            cmd.append("CFG_CXXFLAGS_NO_UNUSED=")
        env = _cocotb_env(tool_health)
        proc = subprocess.run(cmd, cwd=root, text=True, capture_output=True, check=False, timeout=timeout_s, env=env)
        runs.append({
            "block": target["block"],
            "module": target["module"],
            "toplevel": target["toplevel"],
            "command": cmd,
            "returncode": proc.returncode,
            "pass": proc.returncode == 0,
            "stdout_tail": proc.stdout.splitlines()[-80:],
            "stderr_tail": proc.stderr.splitlines()[-80:],
        })
        if proc.returncode != 0:
            break

    sim_pass = bool(runs) and all(run["pass"] for run in runs)
    sim_report = {
        "contract_version": "agent3_sim_report/v1",
        "project_name": project,
        "mode": mode,
        "simulator": f"{simulator}+cocotb",
        "simulator_version": tool_health.get("tools", {}).get(simulator if simulator != "icarus" else "iverilog", {}).get("version", ""),
        "real_sim_attempted": True,
        "pass": sim_pass,
        "pass_fail_status": "pass" if sim_pass else "fail",
        "requires_real_tools": requires_real_tools,
        "fallback_allowed": False,
        "fallback_provenance": "",
        "missing_required_tools": tool_health.get("missing_required", []),
        "runs": runs,
        "commands": [run["command"] for run in runs],
        "returncode": 0 if sim_pass else next((run["returncode"] for run in runs if not run["pass"]), 1),
        "stdout_tail": _tail_lines([line for run in runs for line in run["stdout_tail"]], 80),
        "stderr_tail": _tail_lines([line for run in runs for line in run["stderr_tail"]], 80),
        "log_path": "sim_build/sim.log",
        "waveform_path": "dump.vcd",
    }
    scoreboard_report = _scoreboard_report_from_observed(project, mode, root, manifest)
    coverage_report = _coverage_report_from_runtime(project, coverage_plan, sim_report, scoreboard_report, root, mode)
    release_decision = _release_decision(project, mode, requires_real_tools, tool_health, sim_report, coverage_report)
    result_contract = _agent3_result_contract(project, release_decision, coverage_report, tool_health, sim_report)

    _write_runtime_json(root, "agent3_tool_health.json", tool_health)
    _write_runtime_json(root, "agent3_sim_report.json", sim_report)
    _write_runtime_json(root, "agent3_scoreboard_report.json", scoreboard_report)
    _write_runtime_json(root, "agent3_coverage_report.json", coverage_report)
    _write_runtime_json(root, "agent3_release_decision.json", release_decision)
    _write_runtime_json(root, "agent3_result.json", result_contract)
    (root / "agent3_dv_dashboard.md").write_text(
        _dashboard(project, manifest.get("top_module", f"{project}_top"), mode, release_decision, sim_report),
        encoding="utf-8",
    )
    return sim_report

def _clean_cocotb_build(root: Path) -> None:
    shutil.rmtree(root / "sim_build", ignore_errors=True)
    for filename in ("results.xml", "coverage.dat", "dump.vcd"):
        with contextlib.suppress(FileNotFoundError):
            (root / filename).unlink()


def run_modelsim_sim(
    tb_dir: str | Path = "tb",
    *,
    vlog: str = "vlog",
    vsim: str = "vsim",
    timeout_s: int = 600,
    require_tools: bool = True,
) -> dict[str, Any]:
    """Run real QuestaSim/ModelSim compile and batch sim using generated manifest."""
    root = Path(tb_dir)
    if require_tools:
        for exe in (vlog, vsim):
            if shutil.which(exe) is None:
                raise FileNotFoundError(f"ModelSim/Questa executable not found on PATH: {exe}")
    rtl_sources = _rtl_sources_from_tb(root)
    compile_cmd = [vlog, "-sv", *rtl_sources]
    sim_cmd = [vsim, "-c", "-do", "sim.do"]
    compile_proc = subprocess.run(compile_cmd, cwd=root, text=True, capture_output=True, check=False, timeout=timeout_s)
    sim_proc = subprocess.run(sim_cmd, cwd=root, text=True, capture_output=True, check=False, timeout=timeout_s)
    return {
        "compile_command": compile_cmd,
        "sim_command": sim_cmd,
        "compile_returncode": compile_proc.returncode,
        "sim_returncode": sim_proc.returncode,
        "pass": compile_proc.returncode == 0 and sim_proc.returncode == 0,
        "waveform_wlf": str(root / "wave.wlf"),
        "waveform_vcd": str(root / "dump.vcd"),
        "stdout_tail": (compile_proc.stdout + "\n" + sim_proc.stdout).splitlines()[-80:],
        "stderr_tail": (compile_proc.stderr + "\n" + sim_proc.stderr).splitlines()[-80:],
    }


def write_agent3_runtime_failure(
    tb_dir: str | Path,
    error: Exception | str,
    *,
    requires_real_tools: bool = True,
) -> dict[str, Any]:
    """Persist fail reports when real DV could not launch or crashed before Cocotb completion."""
    root = Path(tb_dir)
    manifest = _read_manifest_from_dir(root)
    project = str(manifest.get("project_name", root.parent.name))
    mode = str(manifest.get("mode", "demo"))
    required = bool(requires_real_tools or manifest.get("requires_real_tools") or mode in STRICT_DV_MODES)
    tool_health = probe_dv_tool_health(required=required)
    message = str(error)
    sim_report = {
        "contract_version": "agent3_sim_report/v1",
        "project_name": project,
        "mode": mode,
        "simulator": PRIMARY_SIMULATOR,
        "simulator_version": tool_health.get("tools", {}).get("verilator", {}).get("version", ""),
        "real_sim_attempted": True,
        "pass": False,
        "pass_fail_status": "fail",
        "requires_real_tools": required,
        "fallback_allowed": not required,
        "fallback_provenance": "" if required else "real sim launch failed; fallback allowed only outside strict signoff",
        "missing_required_tools": tool_health.get("missing_required", []),
        "runs": [],
        "commands": [],
        "returncode": 1,
        "error": message,
        "failure_class": _classify_failure(message),
        "stdout_tail": [],
        "stderr_tail": [message],
        "log_path": "sim_build/sim.log",
        "waveform_path": "dump.vcd",
    }
    scoreboard_report = _scoreboard_report_from_observed(project, mode, root, manifest)
    coverage_report = _coverage_report_from_runtime(
        project,
        manifest.get("coverage_plan", {"bins": list(FUNCTIONAL_COVERAGE_BINS), "threshold_percent": COVERAGE_TARGETS["functional"]}),
        sim_report,
        scoreboard_report,
        root,
        mode,
    )
    release_decision = _release_decision(project, mode, required, tool_health, sim_report, coverage_report)
    result_contract = _agent3_result_contract(project, release_decision, coverage_report, tool_health, sim_report)
    _write_runtime_json(root, "agent3_tool_health.json", tool_health)
    _write_runtime_json(root, "agent3_sim_report.json", sim_report)
    _write_runtime_json(root, "agent3_scoreboard_report.json", scoreboard_report)
    _write_runtime_json(root, "agent3_coverage_report.json", coverage_report)
    _write_runtime_json(root, "agent3_release_decision.json", release_decision)
    _write_runtime_json(root, "agent3_result.json", result_contract)
    (root / "agent3_dv_dashboard.md").write_text(
        _dashboard(project, manifest.get("top_module", f"{project}_top"), mode, release_decision, sim_report),
        encoding="utf-8",
    )
    return sim_report


def next_debug_action(debug_iterations: int, last_error: str) -> dict[str, Any]:
    if debug_iterations > MAX_DEBUG_ITERATIONS:
        return {
            "action": "HUMAN_CODE_OVERWRITE",
            "channel": "discord",
            "summary": f"Agent 3 stuck after {debug_iterations} iterations. Bug: {last_error}",
            "files_to_review": ["rtl/*.sv", "tb/test_*.py"],
            "reset_ai_context": True,
            "wait_for_human_file_change": True,
        }
    return {"action": "SEND_FIX_REQUEST_TO_AGENT2", "debug_iterations": debug_iterations}


def _test_plan(project: str, blocks: list[str], coverage_plan: dict[str, Any]) -> str:
    markers = "\n".join(f"pytestmark_{block} = pytest.mark.{block}" for block in blocks)
    return f'''"""Agent 3 Pytest test plan for {project}."""
import pytest

COVERAGE_GOALS = {json.dumps(COVERAGE_GOALS, indent=4, sort_keys=True)}
COVERAGE_TARGETS = {{"line": 95, "branch": 90, "functional": 90}}  # Line>=95%, Branch>=90%
FUNCTIONAL_COVERAGE_BINS = {coverage_plan["bins"]!r}
IP_BLOCKS = {blocks!r}

@pytest.mark.fsm_states
@pytest.mark.register_rw
@pytest.mark.bus_errors
@pytest.mark.boundary
@pytest.mark.interrupts
def test_plan_manifest():
    assert set(COVERAGE_GOALS) == {{"fsm_states", "register_rw", "bus_errors", "boundary", "interrupts"}}
    assert "reset" in FUNCTIONAL_COVERAGE_BINS

{markers}
'''


def _conftest() -> str:
    return '''"""Pytest organization hooks for Agent 3 generated Cocotb suites."""
def pytest_configure(config):
    for marker in ("fsm_states", "register_rw", "bus_errors", "boundary", "interrupts"):
        config.addinivalue_line("markers", f"{marker}: Agent 3 coverage goal")
'''


def _makefile(project: str) -> str:
    return f'''SIM ?= verilator
TOPLEVEL_LANG ?= verilog
TOPLEVEL ?= {project}_top
MODULE ?= test_plan
RTL_FILELIST ?= agent3_compile_order.f
VERILOG_SOURCES ?= $(addprefix ../rtl/,$(strip $(file <$(RTL_FILELIST))))
PYTHON_BIN ?= $(shell cocotb-config --python-bin)
PYTHON_LIB_DIR ?= $(shell $(PYTHON_BIN) -c "import pathlib, sys; print((pathlib.Path(sys.base_prefix) / 'libs').as_posix())")
PYTHON_LIB_NAME ?= $(shell $(PYTHON_BIN) -c "import sys; print('python%d%d' % sys.version_info[:2])")
ifeq ($(SIM),verilator)
VERILATOR_EXTRA_ARGS += --coverage -Wall -Wno-DECLFILENAME
VERILATOR_EXTRA_ARGS += -LDFLAGS "-lpsapi -L$(PYTHON_LIB_DIR) -l$(PYTHON_LIB_NAME)"
EXTRA_ARGS += $(VERILATOR_EXTRA_ARGS)
endif

include $(shell cocotb-config --makefiles)/Makefile.sim

coverage:
\tverilator_coverage --annotate coverage_dir coverage.dat
'''


def _runner(project: str) -> str:
    return f'''"""Manifest-driven Cocotb/Verilator wrapper for Agent 3."""
import json
import shutil
from pathlib import Path

from semiconductor_swarm.agents.agent3_dv.dv_engineer import run_cocotb_sim

def _manifest(tb_dir):
    return json.loads(Path(tb_dir, "agent3_dv_manifest.json").read_text(encoding="ascii"))

def run(project: str = "{project}", tb_dir: str = "tb") -> dict[str, object]:
    manifest = _manifest(tb_dir)
    if shutil.which("make") is None:
        raise FileNotFoundError("make not found on PATH")
    return run_cocotb_sim(tb_dir, require_tools=True)
'''


def _modelsim_makefile(project: str) -> str:
    return f'''# ModelSim/Questa batch simulation flow for Agent 3.
VLOG ?= vlog
VSIM ?= vsim
TOPLEVEL ?= {project}_top
RTL_FILELIST ?= agent3_compile_order.f
RTL_SOURCES ?= $(addprefix ../rtl/,$(strip $(file <$(RTL_FILELIST))))

.PHONY: modelsim clean
modelsim:
\t$(VLOG) -sv $(RTL_SOURCES)
\t$(VSIM) -c -do sim.do

clean:
\t-rmdir /s /q work
\t-del transcript wave.wlf dump.vcd
'''


def _modelsim_do(project: str, top: str) -> str:
    return f'''# QuestaSim/ModelSim batch script generated by Agent 3.
transcript file transcript
# Compile step is owned by ModelSim.mk/run_modelsim_sim.py: vlog -sv entries from agent3_compile_order.f
# Batch launch command: vsim -c -do sim.do
# Run headless simulation and persist waveforms for debug triage.
vsim -wlf wave.wlf work.{top}
log -r /*
vcd file dump.vcd
vcd add -r /*
run -all
quit -f
'''


def _modelsim_runner(project: str) -> str:
    return f'''"""Manifest-driven ModelSim/Questa wrapper for Agent 3."""
import json
import shutil
from pathlib import Path

from semiconductor_swarm.agents.agent3_dv.dv_engineer import run_modelsim_sim

def _manifest(tb_dir):
    return json.loads(Path(tb_dir, "agent3_dv_manifest.json").read_text(encoding="ascii"))

def run_modelsim_sim_wrapper(project: str = "{project}", tb_dir: str = "tb") -> dict[str, object]:
    return run(project, tb_dir)

def run(project: str = "{project}", tb_dir: str = "tb") -> dict[str, object]:
    manifest = _manifest(tb_dir)
    if shutil.which("vlog") is None or shutil.which("vsim") is None:
        raise FileNotFoundError("ModelSim/Questa vlog/vsim not found on PATH")
    return run_modelsim_sim(tb_dir)
'''


def _debug_orchestrator() -> str:
    return '''"""Agent 3 HITL debug loop: code overwrite mode, not chat mode."""
MAX_DEBUG_ITERATIONS = 5
FIX_REQUEST_SCHEMA = {"bug_id": "BUG_001", "severity": "critical", "owner": "Agent2",
    "failure_class": "scoreboard_mismatch", "file": "ai_accel_mac_array.sv", "line": 142,
    "description": "MAC accumulator overflows without saturation", "expected": "Saturate at MAX_VAL",
    "actual": "Wraps to negative", "failing_test": "test_apb_slave::test_overflow",
    "failing_artifact": "agent3_scoreboard_report.json", "suggested_agent2_action": "Patch RTL behavior",
    "rewrite_policy": "minimal_patch_only", "cocotb_log_snippet": "last 20 lines only"}

def debug_action(debug_iterations, last_error):
    if debug_iterations > MAX_DEBUG_ITERATIONS:
        return {"action_required": "HUMAN_CODE_OVERWRITE", "summary": f"Agent 3 stuck after {debug_iterations} iterations. Bug: {last_error}",
                "clear_stale_ai_context": True, "wait_for_human_file_change": True}
    return {"action_required": "SEND_FIX_REQUEST_TO_AGENT2"}
'''


def _dv_helpers() -> str:
    return '''"""Reusable APB driver, monitor, and scoreboard for Agent 3 generated suites."""
import json
from pathlib import Path

from cocotb.triggers import ReadOnly, RisingEdge

def load_manifest(path="agent3_dv_manifest.json"):
    manifest_path = Path(path)
    if not manifest_path.exists():
        manifest_path = Path(__file__).with_name(path)
    return json.loads(manifest_path.read_text(encoding="ascii"))

class APBDriver:
    def __init__(self, dut):
        self.dut = dut
        self.transactions = []

    async def idle(self):
        self.dut.psel_i.value = 0
        self.dut.penable_i.value = 0
        self.dut.pwrite_i.value = 0
        await RisingEdge(self.dut.clk_i)

    async def write(self, addr, data):
        self.dut.psel_i.value = 1
        self.dut.penable_i.value = 0
        self.dut.pwrite_i.value = 1
        self.dut.paddr_i.value = addr
        self.dut.pwdata_i.value = data
        await RisingEdge(self.dut.clk_i)
        self.dut.penable_i.value = 1
        await RisingEdge(self.dut.clk_i)
        await ReadOnly()
        ready = int(self.dut.pready_o.value)
        error = int(self.dut.pslverr_o.value)
        await RisingEdge(self.dut.clk_i)
        await self.idle()
        txn = {"op": "write", "addr": int(addr), "data": int(data), "ready": ready, "error": error}
        self.transactions.append(txn)
        return txn

    async def read(self, addr):
        self.dut.psel_i.value = 1
        self.dut.penable_i.value = 0
        self.dut.pwrite_i.value = 0
        self.dut.paddr_i.value = addr
        await RisingEdge(self.dut.clk_i)
        self.dut.penable_i.value = 1
        await RisingEdge(self.dut.clk_i)
        await RisingEdge(self.dut.clk_i)
        await ReadOnly()
        result = {"op": "read", "addr": int(addr), "data": int(self.dut.prdata_o.value), "ready": int(self.dut.pready_o.value), "error": int(self.dut.pslverr_o.value)}
        await RisingEdge(self.dut.clk_i)
        await self.idle()
        self.transactions.append(result)
        return result

class APBMonitor:
    def __init__(self, dut):
        self.dut = dut
        self.samples = []

    async def sample(self):
        sample = {
            "psel": int(self.dut.psel_i.value),
            "penable": int(self.dut.penable_i.value),
            "pwrite": int(self.dut.pwrite_i.value),
            "paddr": int(self.dut.paddr_i.value),
            "pwdata": int(self.dut.pwdata_i.value),
            "prdata": int(self.dut.prdata_o.value),
            "pready": int(self.dut.pready_o.value),
            "pslverr": int(self.dut.pslverr_o.value),
        }
        self.samples.append(sample)
        return sample

class APBScoreboard:
    def __init__(self, block, legal_addresses=(0x00,), illegal_error_allowed=True):
        self.block = block
        self.legal_addresses = {int(addr) for addr in legal_addresses}
        self.illegal_error_allowed = illegal_error_allowed
        self.covered_bins = set()
        self.failures = []

    def cover(self, name):
        self.covered_bins.add(name)

    def expect_reset(self, prdata, pslverr):
        self.cover("reset")
        if int(prdata) != 0:
            self.failures.append({"check": "reset_prdata_zero", "expected": 0, "actual": int(prdata)})
        if int(pslverr) != 0:
            self.failures.append({"check": "reset_error_clear", "expected": 0, "actual": int(pslverr)})

    def expect_write_ok(self, txn):
        self.cover("apb_write")
        if int(txn["ready"]) != 1:
            self.failures.append({"check": "pready_on_write", "expected": 1, "actual": int(txn["ready"])})
        if int(txn["error"]) != 0:
            self.failures.append({"check": "pslverr_on_write", "expected": 0, "actual": int(txn["error"])})

    def expect_readback(self, addr, expected, txn):
        self.cover("apb_read")
        if int(addr) not in self.legal_addresses:
            self.failures.append({"check": "readback_legal_addr", "expected": sorted(self.legal_addresses), "actual": int(addr)})
        if int(txn["data"]) != int(expected):
            self.failures.append({"check": "readback_data", "expected": int(expected), "actual": int(txn["data"])})

    def expect_illegal_address(self, txn):
        self.cover("illegal_address")
        if int(txn["ready"]) != 1:
            self.failures.append({"check": "illegal_addr_ready", "expected": 1, "actual": int(txn["ready"])})
        if not self.illegal_error_allowed and int(txn["error"]) != 0:
            self.failures.append({"check": "illegal_addr_error_policy", "expected": 0, "actual": int(txn["error"])})

    def assert_clean(self):
        assert not self.failures, self.failures

    def as_dict(self, bins):
        return {
            "block": self.block,
            "covered_bins": sorted(self.covered_bins),
            "missing_bins": [bin_name for bin_name in bins if bin_name not in self.covered_bins],
            "failures": self.failures,
        }

def record_scoreboard_result(scoreboard, bins, test_name, transactions=None, path="agent3_scoreboard_observed.jsonl"):
    record = scoreboard.as_dict(bins)
    record["test"] = test_name
    record["transactions"] = transactions or []
    with open(path, "a", encoding="ascii") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\\n")
'''


def _block_test(project: str, block: str) -> str:
    module = f"{project}_{block}_rtl"
    return f'''"""Cocotb APB tests for {module}."""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
import pytest

from dv_helpers import APBDriver, APBMonitor, APBScoreboard, load_manifest, record_scoreboard_result

pytestmark = [pytest.mark.register_rw, pytest.mark.fsm_states, pytest.mark.bus_errors, pytest.mark.boundary, pytest.mark.interrupts]

async def reset_dut(dut):
    clock = Clock(dut.clk_i, 20, units="ns")
    cocotb.start_soon(clock.start())
    dut.psel_i.value = 0
    dut.penable_i.value = 0
    dut.pwrite_i.value = 0
    dut.paddr_i.value = 0
    dut.pwdata_i.value = 0
    dut.rst_ni.value = 0
    await Timer(100, units="ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)

@cocotb.test()
async def test_reset(dut):
    """Verify outputs follow reset contract."""
    manifest = load_manifest()
    await reset_dut(dut)
    scoreboard = APBScoreboard("{block}")
    scoreboard.expect_reset(int(dut.prdata_o.value), int(dut.pslverr_o.value))
    assert int(dut.pready_o.value) in (0, 1), "pready must be a valid APB ready bit"
    record_scoreboard_result(scoreboard, manifest["coverage_plan"]["bins"], "test_reset")
    scoreboard.assert_clean()

@cocotb.test()
async def test_apb_write_read(dut):
    """Write then read back a readable APB register."""
    manifest = load_manifest()
    await reset_dut(dut)
    driver = APBDriver(dut)
    monitor = APBMonitor(dut)
    score_cfg = manifest["scoreboard"]
    legal_addresses = score_cfg.get("legal_addresses_by_block", {{}}).get("{block}", score_cfg["legal_addresses"])
    readback_addr = score_cfg.get("readback_address_by_block", {{}}).get("{block}", 0x00)
    scoreboard = APBScoreboard("{block}", legal_addresses=legal_addresses)
    write_txn = await driver.write(readback_addr, 0xDEADBEEF)
    scoreboard.expect_write_ok(write_txn)
    await monitor.sample()
    read_txn = await driver.read(readback_addr)
    scoreboard.expect_readback(readback_addr, 0xDEADBEEF, read_txn)
    record_scoreboard_result(scoreboard, manifest["coverage_plan"]["bins"], "test_apb_write_read", driver.transactions + monitor.samples)
    scoreboard.assert_clean()

@cocotb.test()
async def test_boundary_and_bus_error(dut):
    manifest = load_manifest()
    await reset_dut(dut)
    driver = APBDriver(dut)
    scoreboard = APBScoreboard("{block}", legal_addresses=manifest["scoreboard"]["legal_addresses"])
    for value in (0x00000000, 0xFFFFFFFF):
        txn = await driver.write(0x00, value)
        scoreboard.expect_write_ok(txn)
        scoreboard.cover("boundary_zero" if value == 0 else "boundary_all_ones")
    illegal_txn = await driver.read(0xFC)
    scoreboard.expect_illegal_address(illegal_txn)
    record_scoreboard_result(scoreboard, manifest["coverage_plan"]["bins"], "test_boundary_and_bus_error", driver.transactions)
    scoreboard.assert_clean()
'''


def _file(filename: str, content: str, language: str, dependencies: list[str]) -> DVFile:
    return DVFile(filename, language, content, len(content.rstrip("\n").splitlines()), dependencies)


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _validate_rtl_files(spec: dict[str, Any], rtl_files: list[dict[str, Any]]) -> None:
    names = {file.get("filename") for file in rtl_files}
    missing: list[str] = []
    for block in [block["name"] for block in spec["ip_blocks"]]:
        if f"{block}.sv" not in names:
            missing.append(f"{block}.sv")
    top_file = f"{_top_module(spec)}.sv"
    if top_file not in names:
        missing.append(top_file)
    if missing:
        raise ValueError(f"Missing Agent 2 RTL files for Agent 3: {missing}")
    findings = _rtl_apb_findings(spec, rtl_files) + _top_module_findings(spec, rtl_files, _dv_manifest_stub(spec, rtl_files))
    if findings:
        raise ValueError(f"Agent 3 static RTL contract check failed: {findings}")


def _rtl_sv_files(rtl_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        file
        for file in rtl_files
        if file.get("language") == "systemverilog"
        and str(file.get("filename", "")).endswith(".sv")
        and not _contract_only_rtl(file)
    ]

def _contract_only_rtl(file: dict[str, Any]) -> bool:
    filename = Path(str(file.get("filename", ""))).name
    output_path = str(file.get("output_path", "")).replace("\\", "/")
    return filename == "interface_contracts.sv" or "/rtl/contracts/" in f"/{output_path}" or output_path.startswith("rtl/contracts/")


def _compile_order(spec: dict[str, Any], rtl_files: list[dict[str, Any]]) -> list[str]:
    names = {str(file.get("filename")) for file in _rtl_sv_files(rtl_files)}
    order: list[str] = []
    for block in [block["name"] for block in spec["ip_blocks"]]:
        for name in (f"{block}_pkg.sv", f"{block}_intf.sv", f"{block}.sv"):
            if name in names and name not in order:
                order.append(name)
    top_file = f"{_top_module(spec)}.sv"
    if top_file in names and top_file not in order:
        order.append(top_file)
    for file in _rtl_sv_files(rtl_files):
        name = str(file.get("filename"))
        if name not in order:
            order.append(name)
    return order


def _dv_mode(spec: dict[str, Any]) -> str:
    constraints = spec.get("constraints", {}) if isinstance(spec.get("constraints"), dict) else {}
    mode = str(constraints.get("agent3_mode") or constraints.get("swarm_mode") or spec.get("agent3_mode") or "demo")
    return mode if mode in DV_MODES else "demo"


def _requires_real_tools(spec: dict[str, Any], mode: str) -> bool:
    constraints = spec.get("constraints", {}) if isinstance(spec.get("constraints"), dict) else {}
    return bool(constraints.get("requires_real_tools")) or mode in STRICT_DV_MODES


def _top_module(spec: dict[str, Any]) -> str:
    return str(spec.get("top_module") or f"{spec['project_name']}_top")


def _coverage_plan(spec: dict[str, Any], rtl_files: list[dict[str, Any]]) -> dict[str, Any]:
    rtl_text = "\n".join(file.get("content", "") for file in _rtl_sv_files(rtl_files))
    bins = list(FUNCTIONAL_COVERAGE_BINS)
    if "interrupt_ctrl" not in {block["name"] for block in spec["ip_blocks"]} and "irq_o" not in rtl_text:
        bins.remove("interrupt_clear_mask")
    if "typedef enum" not in rtl_text:
        bins.remove("block_state_hooks")
    return {
        "version": "agent3_coverage_plan/v1",
        "targets": COVERAGE_TARGETS,
        "bins": bins,
        "threshold_percent": COVERAGE_TARGETS["functional"],
    }


def _dv_manifest(
    *,
    spec: dict[str, Any],
    top: str,
    rtl_files: list[dict[str, Any]],
    compile_order: list[str],
    test_files: list[str],
    mode: str,
    requires_real_tools: bool,
    coverage_plan: dict[str, Any],
) -> dict[str, Any]:
    scoreboard = _scoreboard_config(spec)
    return {
        "contract_version": "agent3_dv_manifest/v1",
        "project_name": spec["project_name"],
        "top_module": top,
        "mode": mode,
        "requires_real_tools": requires_real_tools,
        "rtl_root": "../rtl",
        "rtl_files": [file["filename"] for file in _rtl_sv_files(rtl_files)],
        "compile_order": compile_order,
        "test_files": test_files,
        "test_module": "test_plan",
        "simulator_profile": {"primary": PRIMARY_SIMULATOR, "secondary": SECONDARY_SIMULATOR},
        "seeds": [1, 7, 23],
        "coverage_targets": COVERAGE_TARGETS,
        "coverage_plan": coverage_plan,
        "scoreboard": scoreboard,
        "artifacts": [
            "agent3_tool_health.json",
            "agent3_compile_order.f",
            "agent3_sim_report.json",
            "agent3_coverage_report.json",
            "agent3_scoreboard_report.json",
            "agent3_release_decision.json",
            "agent3_result.json",
        ],
    }

def _scoreboard_config(spec: dict[str, Any]) -> dict[str, Any]:
    legal_by_block: dict[str, list[int]] = {}
    readback_by_block: dict[str, int] = {}
    for block in [block["name"] for block in spec.get("ip_blocks", [])]:
        registers = spec.get("memory_map", {}).get(block, {}).get("registers", {})
        if not isinstance(registers, dict) or not registers:
            legal_by_block[block] = [0]
            readback_by_block[block] = 0
            continue
        legal = sorted(int(str(meta.get("offset", "0x00")), 0) for meta in registers.values())
        readback = next(
            (
                int(str(meta.get("offset", "0x00")), 0)
                for _name, meta in registers.items()
                if _register_access(meta, _name) == "rw"
            ),
            legal[0] if legal else 0,
        )
        legal_by_block[block] = legal
        readback_by_block[block] = readback
    return {
        "protocol": "apb_slave",
        "legal_addresses": [0],
        "legal_addresses_by_block": legal_by_block,
        "readback_address_by_block": readback_by_block,
        "illegal_address": 252,
    }

def _register_access(meta: dict[str, Any], reg_name: str) -> str:
    access = str(meta.get("access", "")).lower()
    if access in {"rw", "ro", "wo", "w1c"}:
        return access
    if meta.get("clear") == "W1C":
        return "w1c"
    if "status" in reg_name:
        return "ro"
    return "rw"


def _dv_manifest_stub(spec: dict[str, Any], rtl_files: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "project_name": spec["project_name"],
        "top_module": _top_module(spec),
        "rtl_files": [file["filename"] for file in _rtl_sv_files(rtl_files)],
    }


def _initial_sim_report(project: str, mode: str, requires_real_tools: bool, tool_health: dict[str, Any]) -> dict[str, Any]:
    strict = mode in STRICT_DV_MODES or requires_real_tools
    missing = tool_health.get("missing_required", [])
    status = "fail" if strict else "not_run"
    return {
        "contract_version": "agent3_sim_report/v1",
        "project_name": project,
        "mode": mode,
        "simulator": PRIMARY_SIMULATOR,
        "real_sim_attempted": False,
        "pass": False,
        "pass_fail_status": status,
        "requires_real_tools": strict,
        "fallback_allowed": not strict,
        "fallback_provenance": "static collateral generated; external simulator not run by generate_dv_files",
        "missing_required_tools": missing,
        "commands": [["make", "MODULE=test_plan", f"TOPLEVEL={project}_top", "SIM=verilator"]],
        "log_path": "sim_build/sim.log",
        "waveform_path": "dump.vcd",
    }


def _coverage_report(project: str, coverage_plan: dict[str, Any], sim_report: dict[str, Any], mode: str) -> dict[str, Any]:
    covered_bins: list[str] = []
    missing_bins = list(coverage_plan["bins"])
    return {
        "contract_version": "agent3_coverage_report/v1",
        "project_name": project,
        "mode": mode,
        "status": "real_coverage_required" if mode in STRICT_DV_MODES else "intent_only",
        "threshold_percent": coverage_plan["threshold_percent"],
        "covered_percent": 0,
        "threshold_met": False,
        "covered_bins": covered_bins,
        "missing_bins": missing_bins,
        "bins": [{"name": name, "covered": name in covered_bins} for name in coverage_plan["bins"]],
        "sim_pass": bool(sim_report.get("pass")),
    }


def _scoreboard_report(spec: dict[str, Any], rtl_files: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    findings = _rtl_apb_findings(spec, rtl_files)
    per_block = []
    for block in [block["name"] for block in spec["ip_blocks"]]:
        per_block.append({
            "block": block,
            "checks": ["reset", "apb_write_read", "illegal_address", "ready_error_behavior"],
            "status": "planned" if not findings else "static_fail",
            "failures": [finding for finding in findings if block in finding],
        })
    return {
        "contract_version": "agent3_scoreboard_report/v1",
        "project_name": spec["project_name"],
        "mode": mode,
        "protocol": "apb_slave",
        "per_block_checks": per_block,
        "static_port_check_pass": not findings,
        "observed_transactions": [],
        "failures": findings,
    }


def _release_decision(
    project: str,
    mode: str,
    requires_real_tools: bool,
    tool_health: dict[str, Any],
    sim_report: dict[str, Any],
    coverage_report: dict[str, Any],
) -> dict[str, Any]:
    strict = mode in STRICT_DV_MODES or requires_real_tools
    real_attempted = bool(sim_report.get("real_sim_attempted"))
    real_pass = real_attempted and bool(sim_report.get("pass"))
    coverage_ok = bool(coverage_report.get("threshold_met"))
    reasons: list[str] = []
    if real_attempted and not real_pass:
        reasons.append("real simulator run failed")
    if strict and not real_pass:
        reasons.append("strict mode requires real simulator pass")
    if strict and tool_health.get("missing_required"):
        reasons.append(f"missing required DV tools: {tool_health['missing_required']}")
    if mode == "nightly-real-tools" and not coverage_ok:
        reasons.append("nightly-real-tools requires functional coverage threshold")

    if strict and not reasons and real_pass:
        label = "DV_STRICT_PASS"
        status = "pass"
    elif strict or (real_attempted and not real_pass):
        label = "DV_FAIL"
        status = "fail"
    elif mode == "dev":
        label = "DV_DEV_PASS_WITH_WARNINGS"
        status = "partial"
        reasons.append("dev mode allowed static fallback because real sim was not run")
    else:
        label = "DV_DEMO_PASS"
        status = "pass"
        reasons.append("demo mode static collateral pass; real sim optional")

    return {
        "contract_version": "agent3_release_decision/v1",
        "project_name": project,
        "mode": mode,
        "decision_label": label,
        "pass_fail_status": status,
        "real_sim_pass": real_pass,
        "coverage_threshold_met": coverage_ok,
        "tool_health_primary_ready": tool_health.get("primary_ready", False),
        "reasons": reasons,
        "rerun_command": "python run_cocotb_sim.py",
        "failing_test": None if label != "DV_FAIL" else "test_plan",
        "log_path": sim_report.get("log_path", "sim_build/sim.log"),
        "waveform_path": sim_report.get("waveform_path", "dump.vcd"),
    }


def _agent3_result_contract(
    project: str,
    release_decision: dict[str, Any],
    coverage_report: dict[str, Any],
    tool_health: dict[str, Any],
    sim_report: dict[str, Any],
) -> dict[str, Any]:
    failures = [{"reason": reason} for reason in release_decision.get("reasons", []) if release_decision.get("decision_label") == "DV_FAIL"]
    return {
        "contract_version": AGENT3_RESULT_V1,
        "project_name": project,
        "agent": "Agent 3 DV Engineer",
        "pass": release_decision.get("pass_fail_status") == "pass",
        "pass_fail_status": release_decision.get("pass_fail_status", "fail"),
        "coverage_summary": {
            "covered_percent": coverage_report.get("covered_percent", 0),
            "threshold_percent": coverage_report.get("threshold_percent", COVERAGE_TARGETS["functional"]),
            "covered_bins": coverage_report.get("covered_bins", []),
            "missing_bins": coverage_report.get("missing_bins", []),
        },
        "failures": failures,
        "tool_availability": tool_health,
        "commands": sim_report.get("commands", []),
        "artifacts": [
            {"filename": "agent3_dv_manifest.json", "kind": "manifest"},
            {"filename": "agent3_sim_report.json", "kind": "sim_report"},
            {"filename": "agent3_coverage_report.json", "kind": "coverage_report"},
            {"filename": "agent3_scoreboard_report.json", "kind": "scoreboard_report"},
            {"filename": "agent3_release_decision.json", "kind": "release_decision"},
        ],
    }


def _dashboard(project: str, top: str, mode: str, release_decision: dict[str, Any], sim_report: dict[str, Any]) -> str:
    return f"""# Agent 3 DV Dashboard

- Project: {project}
- Top: {top}
- Mode: {mode}
- Decision: {release_decision["decision_label"]}
- Status: {release_decision["pass_fail_status"]}
- Rerun: `{release_decision["rerun_command"]}`
- Failing test: `{release_decision.get("failing_test") or "none"}`
- Log: `{release_decision.get("log_path") or sim_report.get("log_path")}`
- Waveform: `{release_decision.get("waveform_path") or sim_report.get("waveform_path")}`
"""


def _load_json(by_name: dict[str, dict[str, Any]], filename: str, failures: list[str]) -> dict[str, Any]:
    raw = by_name.get(filename, {}).get("content")
    if raw is None:
        failures.append(f"missing {filename}")
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        failures.append(f"invalid JSON in {filename}: {exc}")
        return {}
    return payload if isinstance(payload, dict) else {}


def _manifest_valid(spec: dict[str, Any], rtl_files: list[dict[str, Any]], manifest: dict[str, Any], failures: list[str]) -> bool:
    required = {
        "contract_version",
        "project_name",
        "top_module",
        "mode",
        "rtl_files",
        "compile_order",
        "test_files",
        "simulator_profile",
        "seeds",
        "coverage_targets",
        "coverage_plan",
        "scoreboard",
    }
    ok = required.issubset(manifest)
    if not ok:
        failures.append(f"manifest missing keys: {sorted(required - set(manifest))}")
        return False
    rtl_names = {file.get("filename") for file in _rtl_sv_files(rtl_files)}
    if manifest.get("project_name") != spec["project_name"]:
        failures.append("manifest project_name mismatch")
        ok = False
    if manifest.get("top_module") != _top_module(spec):
        failures.append("manifest top_module mismatch")
        ok = False
    missing_rtl = [name for name in manifest.get("rtl_files", []) if name not in rtl_names]
    missing_order = [name for name in manifest.get("compile_order", []) if name not in rtl_names]
    if missing_rtl:
        failures.append(f"manifest references missing RTL files: {missing_rtl}")
        ok = False
    if missing_order:
        failures.append(f"manifest compile_order references missing RTL files: {missing_order}")
        ok = False
    if manifest.get("simulator_profile", {}).get("primary") != PRIMARY_SIMULATOR:
        failures.append("manifest primary simulator must be Verilator plus Cocotb")
        ok = False
    return ok


def _tool_health_valid(tool_health: dict[str, Any]) -> bool:
    tools = tool_health.get("tools", {})
    return all(name in tools for name in ("verilator", "make", "cocotb", "vlog", "vsim"))


def _result_contract_valid(spec: dict[str, Any], result_contract: dict[str, Any], failures: list[str]) -> bool:
    ok = True
    if result_contract.get("contract_version") != AGENT3_RESULT_V1:
        failures.append("agent3 result contract version mismatch")
        ok = False
    if result_contract.get("project_name") != spec["project_name"]:
        failures.append("agent3 result project_name mismatch")
        ok = False
    if result_contract.get("pass_fail_status") not in {"pass", "fail", "partial", "not_run"}:
        failures.append("agent3 result pass_fail_status invalid")
        ok = False
    for key in ("coverage_summary", "failures", "tool_availability", "commands", "artifacts"):
        if key not in result_contract:
            failures.append(f"agent3 result missing {key}")
            ok = False
    return ok


def _strict_gate_valid(
    manifest: dict[str, Any],
    sim_report: dict[str, Any],
    release_decision: dict[str, Any],
    result_contract: dict[str, Any],
) -> bool:
    mode = manifest.get("mode")
    strict = mode in STRICT_DV_MODES or bool(manifest.get("requires_real_tools"))
    if not strict:
        return True
    real_pass = bool(sim_report.get("real_sim_attempted")) and bool(sim_report.get("pass"))
    if release_decision.get("decision_label") == "DV_STRICT_PASS" and not real_pass:
        return False
    if not real_pass and result_contract.get("pass_fail_status") == "pass":
        return False
    return True


def _rtl_apb_findings(spec: dict[str, Any], rtl_files: list[dict[str, Any]]) -> list[str]:
    by_name = {file.get("filename"): file for file in rtl_files}
    findings: list[str] = []
    for block in [block["name"] for block in spec["ip_blocks"]]:
        filename = f"{block}.sv"
        content = by_name.get(filename, {}).get("content", "")
        if not content:
            findings.append(f"{block}: missing RTL content")
            continue
        module_name = f"{spec['project_name']}_{block}_rtl"
        if not re.search(rf"\bmodule\s+{re.escape(module_name)}\b", content):
            findings.append(f"{block}: missing module {module_name}")
        for port in APB_REQUIRED_PORTS:
            if not re.search(rf"\b{re.escape(port)}\b", content):
                findings.append(f"{block}: missing APB port {port}")
        if "output logic [DATA_WIDTH-1:0] prdata_o" not in content and "output logic [31:0] prdata_o" not in content:
            findings.append(f"{block}: prdata_o width mismatch or missing packed data width")
        if "input  logic [DATA_WIDTH-1:0] pwdata_i" not in content and "input  logic [31:0] pwdata_i" not in content:
            findings.append(f"{block}: pwdata_i width mismatch or missing packed data width")
    return findings


def _top_module_findings(spec: dict[str, Any], rtl_files: list[dict[str, Any]], manifest: dict[str, Any]) -> list[str]:
    top = _top_module(spec)
    by_name = {file.get("filename"): file for file in rtl_files}
    content = by_name.get(f"{top}.sv", {}).get("content", "")
    findings: list[str] = []
    if manifest.get("top_module") and manifest.get("top_module") != top:
        findings.append(f"top mismatch: manifest {manifest.get('top_module')} != spec {top}")
    if not content:
        findings.append(f"top missing RTL file: {top}.sv")
    elif not re.search(rf"\bmodule\s+{re.escape(top)}\b", content):
        findings.append(f"top RTL file does not define module {top}")
    return findings


def _classify_failure(sim_log: str) -> str:
    log = sim_log.lower()
    if any(token in log for token in ("not found on path", "no such file or directory", "command not found", "tool missing")):
        return "tool_missing"
    if any(token in log for token in ("syntax error", "compile error", "%error", "vlog-", "verilator")):
        return "compile_error"
    if any(token in log for token in ("port", "not found in module", "unknown port", "cannot find signal", "has no attribute")):
        return "port_mismatch"
    if any(token in log for token in ("reset", "rst_ni", "not zero after reset")):
        return "reset_failure"
    if any(token in log for token in ("apb", "psel", "penable", "pready", "pslverr", "protocol")):
        return "apb_protocol_failure"
    if any(token in log for token in ("scoreboard", "readback", "expected", "actual", "mismatch", "assert")):
        return "scoreboard_mismatch"
    if any(token in log for token in ("timeout", "deadlock", "sim timeout")):
        return "timeout_deadlock"
    if any(token in log for token in ("traceback", "testbench", "cocotb")):
        return "testbench_error"
    return "unknown"


def _failure_owner(failure_class: str) -> str:
    if failure_class in {"compile_error", "port_mismatch", "reset_failure", "apb_protocol_failure", "scoreboard_mismatch", "timeout_deadlock"}:
        return "Agent2"
    if failure_class in {"testbench_error", "tool_missing"}:
        return "Agent3"
    return "HITL"


def _default_failure_file(failure_class: str) -> str:
    if _failure_owner(failure_class) == "Agent2":
        return "rtl/*.sv"
    if failure_class == "tool_missing":
        return "agent3_tool_health.json"
    if failure_class == "testbench_error":
        return "tb/test_*.py"
    return "unknown.sv"


def _suggested_agent2_action(failure_class: str) -> str:
    return {
        "compile_error": "Fix SystemVerilog compile error without renaming locked APB ports",
        "port_mismatch": "Restore locked APB slave pinout from Agent1/Agent2 contract",
        "reset_failure": "Patch reset behavior so outputs return to contract reset values",
        "apb_protocol_failure": "Patch APB ready/error sequencing",
        "scoreboard_mismatch": "Patch RTL state/register behavior causing scoreboard mismatch",
        "timeout_deadlock": "Patch ready/liveness path causing simulation timeout",
        "testbench_error": "No Agent2 action until Agent3 testbench bug is fixed",
        "tool_missing": "No RTL action; install or configure DV toolchain",
    }.get(failure_class, "HITL triage required before requesting RTL rewrite")


def _tool_status(name: str) -> dict[str, Any]:
    aliases = {"verilator": ["verilator_bin.exe"]}.get(name, [])
    for command in [name, *aliases]:
        path = _which(command)
        if path is None:
            continue
        status = {"available": True, "path": path, "command": command, "version": ""}
        version_args = {
            "verilator": ["--version"],
            "verilator_bin.exe": ["--version"],
            "make": ["--version"],
        }.get(command)
        if version_args:
            try:
                proc = subprocess.run([command, *version_args], text=True, capture_output=True, check=False, timeout=15)
                status["returncode"] = proc.returncode
                status["version"] = "\n".join((proc.stdout + "\n" + proc.stderr).splitlines()[:5]).strip()
            except Exception as exc:  # pragma: no cover - host tool behavior
                status["version_error"] = str(exc)
        return status
    return {"available": False, "path": None, "command": name, "version": ""}


def _python_module_status(name: str) -> dict[str, Any]:
    spec = importlib.util.find_spec(name)
    version = ""
    if spec is not None:
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            version = "importable"
    return {"available": spec is not None, "module": name, "path": spec.origin if spec else None, "version": version}


def _read_manifest_from_dir(root: Path) -> dict[str, Any]:
    path = root / "agent3_dv_manifest.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="ascii"))


def _rtl_sources_from_tb(root: Path) -> list[str]:
    manifest = _read_manifest_from_dir(root)
    if manifest.get("compile_order"):
        rtl_root = manifest.get("rtl_root", "../rtl")
        return [str(Path(rtl_root) / name).replace("\\", "/") for name in manifest["compile_order"]]
    filelist = root / "agent3_compile_order.f"
    if filelist.is_file():
        return [str(Path("../rtl") / line.strip()).replace("\\", "/") for line in filelist.read_text(encoding="ascii").splitlines() if line.strip()]
    rtl_dir = root.parent / "rtl"
    return [str(Path("../rtl") / path.name).replace("\\", "/") for path in sorted(rtl_dir.glob("*.sv"))]


def _which(command: str) -> str | None:
    return shutil.which(command)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]

def _cocotb_env(tool_health: dict[str, Any]) -> dict[str, str]:
    env = dict(os.environ)
    path_entries = [str(Path(sys.executable).parent)]
    base_prefix = Path(getattr(sys, "base_prefix", sys.prefix))
    if base_prefix.is_dir():
        path_entries.append(str(base_prefix))
    cocotb_spec = importlib.util.find_spec("cocotb")
    cocotb_locations = getattr(cocotb_spec, "submodule_search_locations", None)
    if cocotb_spec and cocotb_locations:
        cocotb_lib_dir = Path(next(iter(cocotb_locations))) / "libs"
        if cocotb_lib_dir.is_dir():
            path_entries.append(str(cocotb_lib_dir))
    for candidate in (
        _repo_root() / ".dv_bin",
        Path(r"C:\Program Files\Git\usr\bin"),
        Path(r"D:\APP\oss-cad-suite\bin"),
        Path(r"D:\APP\Quartus\questa_fse\gcc-7.4.0-mingw64vc16\bin"),
    ):
        if candidate.is_dir():
            path_entries.append(str(candidate))
    env["PATH"] = os.pathsep.join(path_entries + [env.get("PATH", "")])
    pythonpath_entries = [path for path in site.getsitepackages() if Path(path).is_dir()]
    if pythonpath_entries:
        env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries + [env.get("PYTHONPATH", "")])
    env.setdefault("PYGPI_PYTHON_BIN", str(Path(sys.executable)))
    python_dll = base_prefix / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    if python_dll.is_file():
        env.setdefault("LIBPYTHON_LOC", str(python_dll))
    if Path(r"D:\APP\oss-cad-suite\share\verilator").is_dir():
        env.setdefault("VERILATOR_ROOT", r"D:\APP\oss-cad-suite\share\verilator")
    verilator = tool_health.get("tools", {}).get("verilator", {})
    command = verilator.get("command")
    if command and command != "verilator":
        env.setdefault("VERILATOR", str(command))
    return env


def _select_cocotb_simulator(tool_health: dict[str, Any]) -> str:
    if os.name == "nt" and all(
        tool_health.get("tools", {}).get(name, {}).get("available")
        for name in ("iverilog", "vvp")
    ):
        return "icarus"
    return "verilator"

def _cocotb_targets_from_manifest(manifest: dict[str, Any]) -> list[dict[str, str]]:
    project = str(manifest.get("project_name", "swarm_soc"))
    tests = manifest.get("test_files") or []
    targets = []
    for test_file in tests:
        name = Path(str(test_file)).name
        if not name.startswith("test_") or not name.endswith(".py"):
            continue
        block = name.removeprefix("test_").removesuffix(".py")
        targets.append({"block": block, "module": f"test_{block}", "toplevel": f"{project}_{block}_rtl"})
    if targets:
        return targets
    return [{"block": "top", "module": str(manifest.get("test_module", "test_plan")), "toplevel": str(manifest.get("top_module", f"{project}_top"))}]


def _tail_lines(lines: list[str], count: int) -> list[str]:
    return lines[-count:] if len(lines) > count else lines


def _write_runtime_json(root: Path, filename: str, payload: dict[str, Any]) -> None:
    (root / filename).write_text(_json(payload), encoding="ascii")


def _read_observed_scoreboard(root: Path) -> list[dict[str, Any]]:
    path = root / "agent3_scoreboard_observed.jsonl"
    if not path.is_file():
        return []
    observed = []
    for line in path.read_text(encoding="ascii", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            observed.append(item)
    return observed


def _scoreboard_report_from_observed(project: str, mode: str, root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    observed = _read_observed_scoreboard(root)
    by_block: dict[str, list[dict[str, Any]]] = {}
    for item in observed:
        by_block.setdefault(str(item.get("block", "unknown")), []).append(item)
    per_block = []
    failures: list[dict[str, Any]] = []
    for target in _cocotb_targets_from_manifest(manifest):
        entries = by_block.get(target["block"], [])
        block_failures = [failure for entry in entries for failure in entry.get("failures", [])]
        failures.extend({"block": target["block"], **failure} if isinstance(failure, dict) else {"block": target["block"], "failure": failure} for failure in block_failures)
        per_block.append({
            "block": target["block"],
            "checks": ["reset", "apb_write_read", "illegal_address", "ready_error_behavior"],
            "status": "pass" if entries and not block_failures else "fail" if block_failures else "not_run",
            "covered_bins": sorted({bin_name for entry in entries for bin_name in entry.get("covered_bins", [])}),
            "missing_bins": sorted({bin_name for entry in entries for bin_name in entry.get("missing_bins", [])}),
            "failures": block_failures,
        })
    return {
        "contract_version": "agent3_scoreboard_report/v1",
        "project_name": project,
        "mode": mode,
        "protocol": manifest.get("scoreboard", {}).get("protocol", "apb_slave"),
        "per_block_checks": per_block,
        "static_port_check_pass": True,
        "observed_transactions": [txn for entry in observed for txn in entry.get("transactions", [])],
        "observed_tests": observed,
        "failures": failures,
    }


def _coverage_report_from_runtime(
    project: str,
    coverage_plan: dict[str, Any],
    sim_report: dict[str, Any],
    scoreboard_report: dict[str, Any],
    root: Path,
    mode: str,
) -> dict[str, Any]:
    bins = list(coverage_plan.get("bins", FUNCTIONAL_COVERAGE_BINS))
    covered_bins = sorted({bin_name for block in scoreboard_report.get("per_block_checks", []) for bin_name in block.get("covered_bins", [])})
    missing_bins = [bin_name for bin_name in bins if bin_name not in covered_bins]
    functional_pct = int(round(100 * len(covered_bins) / len(bins))) if bins else 100
    code_coverage = _verilator_coverage_from_files(root)
    threshold = int(coverage_plan.get("threshold_percent", COVERAGE_TARGETS["functional"]))

    if not sim_report.get("real_sim_attempted"):
        status = "intent_only"
    elif not code_coverage.get("available"):
        status = "sim_ran_no_coverage"
    else:
        line_ok = code_coverage.get("line_percent", 0) >= COVERAGE_TARGETS["line"]
        branch_ok = code_coverage.get("branch_percent", 0) >= COVERAGE_TARGETS["branch"]
        functional_ok = functional_pct >= threshold
        status = "coverage_pass" if line_ok and branch_ok and functional_ok else "coverage_fail"

    return {
        "contract_version": "agent3_coverage_report/v1",
        "project_name": project,
        "mode": mode,
        "status": status,
        "threshold_percent": threshold,
        "covered_percent": functional_pct,
        "threshold_met": status == "coverage_pass" or (status == "sim_ran_no_coverage" and mode not in STRICT_DV_MODES and functional_pct >= threshold),
        "covered_bins": covered_bins,
        "missing_bins": missing_bins,
        "bins": [{"name": name, "covered": name in covered_bins} for name in bins],
        "code_coverage": code_coverage,
        "sim_pass": bool(sim_report.get("pass")),
    }


def _verilator_coverage_from_files(root: Path) -> dict[str, Any]:
    candidates = [root / "coverage.dat", root / "sim_build" / "coverage.dat"]
    coverage_dat = next((path for path in candidates if path.is_file()), None)
    if coverage_dat is None:
        return {"available": False, "reason": "coverage.dat not found", "line_percent": 0.0, "branch_percent": 0.0}
    tool = _which("verilator_coverage")
    if tool is None:
        return {"available": False, "reason": "verilator_coverage not found on PATH", "coverage_dat": str(coverage_dat), "line_percent": 0.0, "branch_percent": 0.0}
    proc = subprocess.run([tool, "--annotate", "coverage_dir", str(coverage_dat)], cwd=root, text=True, capture_output=True, check=False, timeout=120)
    parsed = parse_verilator_coverage_output(proc.stdout + "\n" + proc.stderr)
    return {
        "available": bool(parsed),
        "coverage_dat": str(coverage_dat),
        "command": [tool, "--annotate", "coverage_dir", str(coverage_dat)],
        "returncode": proc.returncode,
        "line_percent": parsed.get("line_percent", 0.0),
        "branch_percent": parsed.get("branch_percent", 0.0),
        "raw_tail": (proc.stdout + "\n" + proc.stderr).splitlines()[-40:],
        "reason": "" if parsed else "coverage percentage not parsed",
    }


def parse_verilator_coverage_output(text: str) -> dict[str, float]:
    lowered = text.lower()
    parsed: dict[str, float] = {}
    for key, names in {"line_percent": ("line", "lines"), "branch_percent": ("branch", "branches")}.items():
        for name in names:
            match = re.search(rf"{name}[^0-9%]{{0,80}}(\d+(?:\.\d+)?)\s*%", lowered)
            if match:
                parsed[key] = float(match.group(1))
                break
    total = re.search(r"(?:total|coverage)[^0-9%]{0,80}(\d+(?:\.\d+)?)\s*%", lowered)
    if total:
        parsed.setdefault("line_percent", float(total.group(1)))
        parsed.setdefault("branch_percent", float(total.group(1)))
    return parsed


def _first_error_line(lines: list[str]) -> str:
    for line in lines:
        if any(token in line.lower() for token in ("error", "fail", "assert", "mismatch", "timeout")):
            return line[:240]
    return lines[-1][:240] if lines else "Simulation failed without a log"
