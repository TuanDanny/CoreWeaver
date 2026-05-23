"""Rule-based Agent 4 prototype for FPGA-first physical design collateral."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from semiconductor_swarm.agents.agent1_planning.architect import validate_architecture_spec
from semiconductor_swarm.tools.quartus_runner import (
    create_quartus_project_files,
    parse_quartus_report_text as parse_real_quartus_report_text,
    run_quartus_compile,
)

MAX_BACKEND_ITERATIONS = 5
TARGET_DEVICE = "Cyclone V 5CSEMA5F31C6"
TARGET_KEY = "fpga_cyclone_v"
ALM_USAGE_LIMIT_PCT = 80.0

QUALITY_RULES = (
    "fpga_first_cyclone_v",
    "prebuilt_quartus_recipe_only",
    "quartus_tool_wrapper_present",
    "report_parser_present",
    "timing_decision_present",
    "resource_decision_present",
    "quartus_sta_present",
    "sta_slack_parser_present",
    "sof_generation_present",
    "io_constraint_coverage_present",
    "hitl_after_five_iterations",
)


@dataclass(frozen=True)
class BackendFile:
    filename: str
    language: str
    content: str
    line_count: int
    dependencies: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {"filename": self.filename, "language": self.language, "content": self.content,
                "line_count": self.line_count, "dependencies": self.dependencies}


def generate_physical_design_files(spec: dict[str, Any], rtl_files: list[dict[str, Any]], *, debug: bool = False) -> list[dict[str, Any]]:
    validate_architecture_spec(spec)
    _validate_rtl_files(spec, rtl_files)
    project = spec["project_name"]
    top = f"{project}_top"
    design_rtl = _rtl_sv_files(rtl_files)
    rtl_names = [file["filename"] for file in design_rtl]
    files = [
        _file("quartus_flow.tcl", _quartus_flow_tcl(), "tcl", []),
        _file(f"{project}.qsf", _qsf(project, top, rtl_names), "quartus_qsf", rtl_names),
        _file(f"{project}.sdc", _sdc(spec), "sdc", []),
        _file("run_quartus_flow.py", _quartus_runner(project, top), "python", ["quartus_flow.tcl", f"{project}.qsf", f"{project}.sdc"]),
        _file("parse_quartus_reports.py", _report_parser(), "python", []),
        _file("backend_decision.py", _backend_decision(), "python", []),
        _file("physical_signoff_plan.md", _signoff_plan(project, top), "markdown", []),
    ]
    result = [file.as_dict() for file in files]
    report = verify_physical_design_files(spec, rtl_files, result)
    if not report["pass"]:
        raise ValueError(f"Generated Agent 4 collateral failed self-check: {report['failures']}")
    if debug:
        result.append(_file("agent4_debug_report.json", json.dumps(report, indent=2, sort_keys=True) + "\n", "json", []).as_dict())
    return result


def verify_physical_design_files(spec: dict[str, Any], rtl_files: list[dict[str, Any]], backend_files: list[dict[str, Any]]) -> dict[str, Any]:
    validate_architecture_spec(spec)
    by_name = {file["filename"]: file for file in backend_files}
    text = "\n".join(file.get("content", "") for file in backend_files)
    checks = {rule: True for rule in QUALITY_RULES}
    checks["fpga_first_cyclone_v"] = TARGET_DEVICE in text and TARGET_KEY in text
    checks["prebuilt_quartus_recipe_only"] = "Agent does not invent Tcl" in text and "execute_module -tool fit" in text
    checks["quartus_tool_wrapper_present"] = "def run_quartus_flow" in text and "quartus_sh" in text
    checks["report_parser_present"] = "def parse_quartus_report_text" in text and "Fmax" in text and "ALMs" in text
    checks["timing_decision_present"] = "PIPELINE_CRITICAL_PATH" in text and "fmax_mhz < target_mhz" in text
    checks["resource_decision_present"] = "OPTIMIZE_OR_SHARE_RESOURCES" in text and "alm_usage_pct > 80" in text
    checks["quartus_sta_present"] = "quartus_sta" in text and "execute_module -tool sta" in text
    checks["sta_slack_parser_present"] = "setup_slack_ns" in text and "hold_slack_ns" in text and "Setup Slack" in text and "Hold Slack" in text
    checks["sof_generation_present"] = "execute_module -tool asm" in text and ".sof" in text
    checks["io_constraint_coverage_present"] = "set_input_delay" in text and "set_output_delay" in text and "get_ports {" in text
    checks["hitl_after_five_iterations"] = "MAX_BACKEND_ITERATIONS = 5" in text and "HUMAN_CODE_OVERWRITE" in text
    rtl_names = {file["filename"] for file in _rtl_sv_files(rtl_files)}
    qsf_text = by_name.get(f"{spec['project_name']}.qsf", {}).get("content", "")
    rtl_in_qsf = all(name in qsf_text for name in rtl_names)
    failures = [rule for rule, passed in checks.items() if not passed]
    if not rtl_in_qsf:
        failures.append("all_rtl_files_listed_in_qsf")
    return {"pass": not failures, "checks": checks, "failures": failures, "target": TARGET_KEY,
            "device": TARGET_DEVICE, "alm_usage_limit_pct": ALM_USAGE_LIMIT_PCT,
            "max_backend_iterations": MAX_BACKEND_ITERATIONS, "rtl_file_count": len(rtl_names)}


def parse_quartus_report_text(report_text: str, target_mhz: float) -> dict[str, Any]:
    return parse_real_quartus_report_text(report_text, target_mhz=target_mhz)


def prepare_quartus_project(spec: dict[str, Any], rtl_files: list[dict[str, Any]], work_dir: str | Path) -> dict[str, str]:
    """Generate real Quartus `.qpf`, `.qsf`, `.sdc`, and RTL workspace files."""
    validate_architecture_spec(spec)
    top = f"{spec['project_name']}_top"
    paths = create_quartus_project_files(
        spec["project_name"],
        top,
        _rtl_sv_files(rtl_files),
        work_dir,
        target_mhz=float(spec["core_config"]["frequency_mhz"]),
    )
    return {key: str(path) for key, path in paths.items()}


def compile_physical_design(
    spec: dict[str, Any],
    rtl_files: list[dict[str, Any]],
    work_dir: str | Path,
    *,
    quartus_sh: str = "quartus_sh",
    require_quartus: bool = True,
) -> dict[str, Any]:
    """Run a real Quartus compile through subprocess and return parsed PPA metrics."""
    validate_architecture_spec(spec)
    top = f"{spec['project_name']}_top"
    result = run_quartus_compile(
        spec["project_name"],
        top,
        _rtl_sv_files(rtl_files),
        work_dir,
        target_mhz=float(spec["core_config"]["frequency_mhz"]),
        quartus_sh=quartus_sh,
        require_quartus=require_quartus,
    )
    return result.as_dict()


def decide_backend_action(metrics: dict[str, Any], debug_iterations: int = 0) -> dict[str, Any]:
    if debug_iterations > MAX_BACKEND_ITERATIONS:
        return {"action": "HUMAN_CODE_OVERWRITE", "reset_ai_context": True, "files_to_review": ["rtl/*.sv", "fpga/*.qsf", "fpga/*.sdc"]}
    if metrics.get("fmax_mhz", 0) < metrics.get("target_mhz", 0):
        return {"action": "REQUEST_AGENT2_FIX", "fix_type": "PIPELINE_CRITICAL_PATH", "reason": "Fmax below target"}
    if metrics.get("setup_slack_ns", 0) < 0 or metrics.get("hold_slack_ns", 0) < 0:
        return {"action": "REQUEST_AGENT2_FIX", "fix_type": "PIPELINE_CRITICAL_PATH", "reason": "STA setup/hold slack violation"}
    if metrics.get("alm_usage_pct", 0) > ALM_USAGE_LIMIT_PCT:
        return {"action": "REQUEST_AGENT2_FIX", "fix_type": "OPTIMIZE_OR_SHARE_RESOURCES", "reason": "ALM usage above 80%"}
    return {"action": "SIGNOFF_PASS", "signoff_status": "PASS", "programming_file": metrics.get("programming_file", "soc_top.sof")}


def _quartus_flow_tcl() -> str:
    return '''# Pre-built Quartus recipe. Agent does not invent Tcl commands from scratch.
set project_name [lindex $quartus(args) 0]
set top_module [lindex $quartus(args) 1]
if {$project_name == ""} { error "project_name argument is required" }
if {$top_module == ""} { set top_module "${project_name}_top" }
load_package flow
load_package report
file copy -force "${project_name}.qsf" "${project_name}.assignments.qsf"
project_new $project_name -overwrite
project_close
project_open $project_name
source "${project_name}.assignments.qsf"
set_global_assignment -name TOP_LEVEL_ENTITY $top_module
execute_module -tool map
execute_module -tool fit
execute_module -tool sta
execute_module -tool asm
load_report
# Export text reports for Agent 4 parsing: Fmax, Setup Slack, Hold Slack, ALMs, Registers, Block RAM, .sof
'''


def _qsf(project: str, top: str, rtl_names: list[str]) -> str:
    assignments = "\n".join(f"set_global_assignment -name SYSTEMVERILOG_FILE ../rtl/{name}" for name in rtl_names)
    return f'''set_global_assignment -name FAMILY "Cyclone V"
set_global_assignment -name DEVICE 5CSEMA5F31C6
set_global_assignment -name TOP_LEVEL_ENTITY {top}
set_global_assignment -name PROJECT_OUTPUT_DIRECTORY output_files
set_global_assignment -name SDC_FILE {project}.sdc
{assignments}
'''


def _sdc(spec: dict[str, Any]) -> str:
    freq = spec["core_config"]["frequency_mhz"]
    period_ns = round(1000.0 / freq, 3)
    input_ports = _top_level_ports(spec, direction="input", exclude={"clk_i"})
    output_ports = _top_level_ports(spec, direction="output")
    input_delay = round(period_ns * 0.20, 3)
    output_delay = round(period_ns * 0.20, 3)
    input_constraints = "\n".join(
        f"set_input_delay -clock core_clk -max {input_delay} [get_ports {{{target}}}]\n"
        f"set_input_delay -clock core_clk -min 0.000 [get_ports {{{target}}}]"
        for target in input_ports
    )
    output_constraints = "\n".join(
        f"set_output_delay -clock core_clk -max {output_delay} [get_ports {{{target}}}]\n"
        f"set_output_delay -clock core_clk -min 0.000 [get_ports {{{target}}}]"
        for target in output_ports
    )
    return f'''create_clock -name core_clk -period {period_ns} [get_ports clk_i]
derive_pll_clocks
derive_clock_uncertainty

# Board-level IO timing model: constrain every top-level APB/control input and response output.
{input_constraints}

{output_constraints}
'''


def _top_level_ports(spec: dict[str, Any], *, direction: str, exclude: set[str] | None = None) -> list[str]:
    excluded = exclude or set()
    ports: list[tuple[str, int]] = [("clk_i", 1), ("rst_ni", 1)] if direction == "input" else []
    ports.extend(
        (signal["name"], int(signal.get("width", 1)))
        for signal in spec["interfaces"]["apb_slave"]["signals"]
        if signal["dir"] == direction
    )
    if direction == "output":
        ports.append(("irq_o", 32))
    unique = dict.fromkeys((name, width) for name, width in ports if name not in excluded)
    return [f"{name}[*]" if width > 1 else name for name, width in unique]


def _quartus_runner(project: str, top: str) -> str:
    return f'''"""Tool-call wrapper for Agent 4 Quartus flow."""
import subprocess
from pathlib import Path
from semiconductor_swarm.tools.quartus_runner import run_quartus_compile

TARGET = "{TARGET_KEY}"
DEVICE = "{TARGET_DEVICE}"

def run_quartus_flow(project: str = "{project}", top_module: str = "{top}", fpga_dir: str = "fpga", rtl_files=None, quartus_sta: str = "quartus_sta") -> dict[str, object]:
    if rtl_files is None:
        raise ValueError("rtl_files are required for real quartus_sh compile")
    result = run_quartus_compile(project, top_module, rtl_files, Path(fpga_dir), target_mhz=100.0, quartus_sta=quartus_sta)
    return result.as_dict()
'''


def _report_parser() -> str:
    return '''"""Parse Quartus text reports; Agent 4 reads reports only."""
from semiconductor_swarm.tools.quartus_runner import parse_quartus_report_text as parse_real_quartus_report_text

def parse_quartus_report_text(report_text, target_mhz):
    # Extracts real Quartus Fmax, Setup Slack, Hold Slack, ALMs, Registers, Block RAM, and bandwidth metrics.
    return parse_real_quartus_report_text(report_text, target_mhz=target_mhz)
'''


def _backend_decision() -> str:
    return '''"""Agent 4 backend decision policy."""
MAX_BACKEND_ITERATIONS = 5

def decide_backend_action(metrics, debug_iterations=0):
    fmax_mhz = metrics.get("fmax_mhz", 0)
    target_mhz = metrics.get("target_mhz", 0)
    alm_usage_pct = metrics.get("alm_usage_pct", 0)
    setup_slack_ns = metrics.get("setup_slack_ns", 0)
    hold_slack_ns = metrics.get("hold_slack_ns", 0)
    if debug_iterations > MAX_BACKEND_ITERATIONS:
        return {"action": "HUMAN_CODE_OVERWRITE", "reset_ai_context": True}
    if fmax_mhz < target_mhz:
        return {"action": "REQUEST_AGENT2_FIX", "fix_type": "PIPELINE_CRITICAL_PATH"}
    if setup_slack_ns < 0 or hold_slack_ns < 0:
        return {"action": "REQUEST_AGENT2_FIX", "fix_type": "PIPELINE_CRITICAL_PATH"}
    if alm_usage_pct > 80:
        return {"action": "REQUEST_AGENT2_FIX", "fix_type": "OPTIMIZE_OR_SHARE_RESOURCES"}
    return {"action": "SIGNOFF_PASS", "signoff_status": "PASS", "programming_file": metrics.get("programming_file", "soc_top.sof")}
'''


def _signoff_plan(project: str, top: str) -> str:
    return f'''# Agent 4 Physical Signoff Plan

- Target: {TARGET_KEY} / {TARGET_DEVICE}
- Project: {project}
- Top module: {top}
- Flow: call `run_quartus_flow(project, top_module)` using pre-built `quartus_flow.tcl`.
- STA: run `quartus_sta {project}` after Quartus compile and parse Setup Slack / Hold Slack / Fmax.
- Parse reports for Fmax, Setup Slack, Hold Slack, ALMs, Registers, Block RAM.
- PASS criteria: Fmax >= Agent 1 target, Setup Slack >= 0 ns, Hold Slack >= 0 ns, ALMs <= 80%, assembler emits `{top}.sof`.
- FAIL criteria: request Agent 2 pipeline or resource sharing fix; after 5 iterations use HUMAN_CODE_OVERWRITE.
'''


def _file(filename: str, content: str, language: str, dependencies: list[str]) -> BackendFile:
    normalized = content if content.endswith("\n") else content + "\n"
    return BackendFile(filename, language, normalized, len(normalized.rstrip("\n").splitlines()), dependencies)


def _validate_rtl_files(spec: dict[str, Any], rtl_files: list[dict[str, Any]]) -> None:
    required = {f"{block['name']}.sv" for block in spec["ip_blocks"]} | {f"{spec['project_name']}_top.sv"}
    present = {file.get("filename") for file in _rtl_sv_files(rtl_files)}
    missing = sorted(required - present)
    if missing:
        raise ValueError(f"Agent 4 requires verified Agent 2 RTL files; missing {missing}")

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


def _number_after(text: str, pattern: str) -> float:
    match = re.search(pattern, text, re.I)
    return float(match.group(1).replace(",", "")) if match else 0.0


def _resource_pair(text: str, pattern: str) -> tuple[int, int] | None:
    match = re.search(pattern, text, re.I)
    if not match:
        return None
    return int(match.group(1).replace(",", "")), int(match.group(2).replace(",", ""))
