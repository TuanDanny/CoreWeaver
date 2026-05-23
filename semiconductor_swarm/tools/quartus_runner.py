"""Quartus command-line integration for real FPGA compile and report parsing."""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TARGET_DEVICE = "5CSEMA5F31C6"
TARGET_DEVICE_NAME = "Cyclone V 5CSEMA5F31C6"
ALM_USAGE_LIMIT_PCT = 80.0


@dataclass(frozen=True)
class QuartusCompileResult:
    project_name: str
    top_module: str
    work_dir: str
    command: list[str]
    returncode: int
    metrics: dict[str, Any]
    reports: dict[str, str]
    stdout_tail: list[str]
    stderr_tail: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "top_module": self.top_module,
            "work_dir": self.work_dir,
            "command": self.command,
            "returncode": self.returncode,
            "metrics": self.metrics,
            "reports": self.reports,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
        }


def create_quartus_project_files(
    project_name: str,
    top_module: str,
    rtl_files: list[dict[str, Any]],
    work_dir: str | Path,
    *,
    target_mhz: float,
    device: str = TARGET_DEVICE,
) -> dict[str, Path]:
    """Write RTL plus Quartus `.qpf`, `.qsf`, and `.sdc` files for a real compile."""
    root = Path(work_dir)
    rtl_dir = root / "rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    for rtl in rtl_files:
        if rtl.get("language") == "systemverilog" and not _contract_only_rtl(rtl):
            (rtl_dir / rtl["filename"]).write_text(rtl["content"], encoding="ascii")

    qpf = root / f"{project_name}.qpf"
    qsf = root / f"{project_name}.qsf"
    sdc = root / f"{project_name}.sdc"
    qpf.write_text(_qpf_text(project_name), encoding="ascii")
    qsf.write_text(_qsf_text(project_name, top_module, sorted(p.name for p in rtl_dir.glob("*.sv")), device), encoding="ascii")
    sdc.write_text(_sdc_text(target_mhz), encoding="ascii")
    return {"qpf": qpf, "qsf": qsf, "sdc": sdc, "rtl_dir": rtl_dir}


def run_quartus_compile(
    project_name: str,
    top_module: str,
    rtl_files: list[dict[str, Any]],
    work_dir: str | Path,
    *,
    target_mhz: float,
    quartus_sh: str = "quartus_sh",
    quartus_sta: str = "quartus_sta",
    timeout_s: int = 1800,
    require_quartus: bool = True,
) -> QuartusCompileResult:
    """Run `quartus_sh --flow compile`, then `quartus_sta`, and parse reports."""
    root = Path(work_dir)
    create_quartus_project_files(project_name, top_module, rtl_files, root, target_mhz=target_mhz)
    command = [quartus_sh, "--flow", "compile", project_name]
    sta_command = [quartus_sta, project_name]
    if require_quartus:
        for exe in (quartus_sh, quartus_sta):
            if shutil.which(exe) is None:
                raise FileNotFoundError(f"Quartus executable not found on PATH: {exe}")
    proc = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False, timeout=timeout_s)
    sta_proc = subprocess.run(sta_command, cwd=root, text=True, capture_output=True, check=False, timeout=timeout_s)
    reports = collect_quartus_reports(root, project_name)
    metrics = parse_quartus_reports(reports, target_mhz=target_mhz, top_module=top_module)
    metrics["compile_pass"] = proc.returncode == 0
    metrics["sta_pass"] = sta_proc.returncode == 0
    return QuartusCompileResult(
        project_name=project_name,
        top_module=top_module,
        work_dir=str(root),
        command=command + ["&&"] + sta_command,
        returncode=proc.returncode if proc.returncode else sta_proc.returncode,
        metrics=metrics,
        reports={name: str(path) for name, path in reports.items()},
        stdout_tail=(proc.stdout + "\n" + sta_proc.stdout).splitlines()[-80:],
        stderr_tail=(proc.stderr + "\n" + sta_proc.stderr).splitlines()[-80:],
    )


def collect_quartus_reports(work_dir: str | Path, project_name: str) -> dict[str, Path]:
    root = Path(work_dir)
    output = root / "output_files"
    candidates = [root, output]
    reports: dict[str, Path] = {}
    patterns = {
        "fit_summary": f"{project_name}.fit.summary",
        "fit_rpt": f"{project_name}.fit.rpt",
        "sta_summary": f"{project_name}.sta.summary",
        "sta_rpt": f"{project_name}.sta.rpt",
        "asm_rpt": f"{project_name}.asm.rpt",
        "sof": f"{project_name}.sof",
    }
    for key, pattern in patterns.items():
        for base in candidates:
            path = base / pattern
            if path.exists():
                reports[key] = path
                break
    return reports


def parse_quartus_reports(reports: dict[str, Path], *, target_mhz: float, top_module: str) -> dict[str, Any]:
    text = "\n".join(_safe_read(path) for path in reports.values() if path.suffix != ".sof")
    return parse_quartus_report_text(text, target_mhz=target_mhz, top_module=top_module, programming_file=reports.get("sof"))


def parse_quartus_report_text(
    report_text: str,
    *,
    target_mhz: float,
    top_module: str = "soc_top",
    programming_file: Path | None = None,
) -> dict[str, Any]:
    fmax = _first_number(
        report_text,
        [r"Fmax\s*[:=]\s*([0-9.]+)", r";\s*Fmax\s*;\s*([0-9.]+)", r"([0-9.]+)\s*MHz"],
    )
    setup_slack = _first_number(report_text, [
        r"Setup\s+Slack\s*[:=]\s*(-?[0-9.]+)",
        r"Worst-case\s+Setup\s+Slack\s*[:=]\s*(-?[0-9.]+)",
        r"Slack\s*\(setup\)\s*[:=]\s*(-?[0-9.]+)",
    ])
    hold_slack = _first_number(report_text, [
        r"Hold\s+Slack\s*[:=]\s*(-?[0-9.]+)",
        r"Worst-case\s+Hold\s+Slack\s*[:=]\s*(-?[0-9.]+)",
        r"Slack\s*\(hold\)\s*[:=]\s*(-?[0-9.]+)",
    ])
    alm_used, alm_total = _resource_pair(report_text, [
        r"ALMs\s*[:=]\s*([0-9,]+)\s*/\s*([0-9,]+)",
        r"Total\s+ALMs\s*;\s*([0-9,]+)\s*/\s*([0-9,]+)",
        r"Logic utilization.*?([0-9,]+)\s*/\s*([0-9,]+)",
    ])
    registers = int(_first_number(report_text, [r"Registers\s*[:=]\s*([0-9,]+)", r"Total registers\s*;\s*([0-9,]+)"]) or 0)
    ram_used, ram_total = _resource_pair(report_text, [
        r"Block RAM\s*[:=]\s*([0-9,]+)\s*/\s*([0-9,]+)",
        r"M10K blocks\s*;\s*([0-9,]+)\s*/\s*([0-9,]+)",
        r"Total block memory bits\s*;\s*([0-9,]+)\s*/\s*([0-9,]+)",
    ])
    alm_pct = round(alm_used * 100.0 / alm_total, 2) if alm_total else 0.0
    ram_pct = round(ram_used * 100.0 / ram_total, 2) if ram_total else 0.0
    bandwidth = _bandwidth_from_fmax(fmax)
    sof = str(programming_file) if programming_file else f"{top_module}.sof"
    return {
        "target": "fpga_cyclone_v",
        "device": TARGET_DEVICE_NAME,
        "target_mhz": target_mhz,
        "fmax_mhz": fmax,
        "setup_slack_ns": setup_slack,
        "hold_slack_ns": hold_slack,
        "alm_used": alm_used,
        "alm_total": alm_total,
        "alm_usage_pct": alm_pct,
        "registers": registers,
        "ram_blocks_used": ram_used,
        "ram_blocks_total": ram_total,
        "ram_usage_pct": ram_pct,
        "bandwidth_peak_mb_s": bandwidth["peak_mb_s"],
        "bandwidth_effective_mb_s": bandwidth["effective_mb_s"],
        "timing_pass": (fmax >= target_mhz and setup_slack >= 0 and hold_slack >= 0) if fmax else False,
        "resource_pass": alm_pct <= ALM_USAGE_LIMIT_PCT if alm_total else False,
        "programming_file": sof,
    }


def _qpf_text(project_name: str) -> str:
    return f'PROJECT_REVISION = "{project_name}"\n'


def _qsf_text(project_name: str, top_module: str, rtl_names: list[str], device: str) -> str:
    rtl_assignments = "\n".join(f"set_global_assignment -name SYSTEMVERILOG_FILE rtl/{name}" for name in rtl_names)
    return f'''set_global_assignment -name FAMILY "Cyclone V"
set_global_assignment -name DEVICE {device}
set_global_assignment -name TOP_LEVEL_ENTITY {top_module}
set_global_assignment -name PROJECT_OUTPUT_DIRECTORY output_files
set_global_assignment -name SDC_FILE {project_name}.sdc
{rtl_assignments}
'''


def _contract_only_rtl(file: dict[str, Any]) -> bool:
    filename = Path(str(file.get("filename", ""))).name
    output_path = str(file.get("output_path", "")).replace("\\", "/")
    return filename == "interface_contracts.sv" or "/rtl/contracts/" in f"/{output_path}" or output_path.startswith("rtl/contracts/")


def _sdc_text(target_mhz: float) -> str:
    period_ns = round(1000.0 / target_mhz, 3) if target_mhz else 10.0
    return f'''create_clock -name core_clk -period {period_ns} [get_ports clk_i]
derive_pll_clocks
derive_clock_uncertainty
'''


def _safe_read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def _first_number(text: str, patterns: list[str]) -> float:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            return float(match.group(1).replace(",", ""))
    return 0.0


def _resource_pair(text: str, patterns: list[str]) -> tuple[int, int]:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            return int(match.group(1).replace(",", "")), int(match.group(2).replace(",", ""))
    return 0, 0


def _bandwidth_from_fmax(fmax_mhz: float, bus_width_bits: int = 32, efficiency: float = 0.8) -> dict[str, float]:
    peak = bus_width_bits / 8 * fmax_mhz
    return {"peak_mb_s": round(peak, 2), "effective_mb_s": round(peak * efficiency, 2)}
