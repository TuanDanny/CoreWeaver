"""Contract linter for Studio run outputs.

Usage:
    python -m semiconductor_swarm.tools.contract_lint <run_dir>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from semiconductor_swarm.tracing import trace_debug_issue


def lint_run_dir(run_dir: str | Path) -> dict[str, Any]:
    root = Path(run_dir)
    reports = root / "reports"
    agent1 = reports / "agent1"
    issues: list[dict[str, Any]] = []
    spec = _read_json(agent1 / "agent1_final_architecture_spec.json") or _read_json(agent1 / "agent1_v51_architecture_spec.json")
    if not spec:
        issues.append(_issue("fatal", "missing_spec", "Missing Agent1 architecture spec", str(agent1 / "agent1_final_architecture_spec.json")))
        return _write_report(root, issues)

    project = str(spec.get("project_name") or "")
    files = {
        "plan": reports / "architecture_plan.md",
        "rdl": agent1 / "agent1_register_map.rdl",
        "header": agent1 / f"fw_{project}_regs.h",
        "driver": agent1 / f"fw_{project}_driver_stub.c",
        "dv_model": agent1 / f"tb_{project}_reg_model.py",
        "fingerprint": agent1 / "agent1_artifact_fingerprint_manifest.json",
    }
    text = {name: _read_text(path) for name, path in files.items()}
    for name, path in files.items():
        if name != "fingerprint" and not text[name]:
            issues.append(_issue("error", f"missing_{name}", f"Missing {name} artifact", str(path)))

    for block, reg, meta in _iter_registers(spec):
        offset = str(meta.get("offset", "0x00"))
        prefix = f"{project}_{block}_{reg}".upper()
        if f"reg {reg}" not in text["rdl"] or offset not in text["rdl"]:
            issues.append(_issue("error", "rdl_missing_register", f"RDL missing {block}.{reg}", str(files["rdl"])))
        if f"#define {prefix}_OFFSET  {offset}u" not in text["header"]:
            issues.append(_issue("error", "header_missing_register", f"Header missing {block}.{reg}", str(files["header"])))
        if f"self.{block}_{reg} = Register" not in text["dv_model"]:
            issues.append(_issue("error", "dv_model_missing_register", f"DV model missing {block}.{reg}", str(files["dv_model"])))
        if reg == "irq_status" and f"{prefix}_OFFSET" not in text["driver"]:
            issues.append(_issue("error", "driver_irq_offset_not_macro", f"Driver does not use {prefix}_OFFSET", str(files["driver"])))

    i2c_regs = spec.get("memory_map", {}).get("i2c", {}).get("registers", {})
    if {"temperature_data", "high_threshold", "low_threshold"}.issubset(i2c_regs):
        for reg in ("temperature_data", "high_threshold", "low_threshold"):
            if reg not in text["plan"]:
                issues.append(_issue("error", "plan_missing_temperature_register", f"Plan missing {reg}", str(files["plan"])))
        for token in ("init_i2c_sensor", "clear_temp_interrupt"):
            if token not in text["header"] or token not in text["driver"]:
                issues.append(_issue("error", "firmware_missing_i2c_temperature_api", f"Firmware missing {token}", str(files["driver"])))

    if _uses_interrupts(spec) and ("classDef interrupt" not in text["plan"] or "class INTERRUPT_CTRL interrupt" not in text["plan"]):
        issues.append(_issue("error", "mermaid_missing_interrupt_highlight", "Plan Mermaid missing red Interrupt Controller class", str(files["plan"])))

    if re.search(r"block_base\s*\+\s*0x[0-9A-Fa-f]+u", text["driver"]):
        issues.append(_issue("error", "driver_hardcoded_irq_offset", "Driver contains hard-coded interrupt clear offset", str(files["driver"])))

    fingerprint = _read_json(files["fingerprint"])
    if not fingerprint:
        issues.append(_issue("warning", "missing_fingerprint_manifest", "Missing artifact fingerprint manifest", str(files["fingerprint"])))
    else:
        revision = str(fingerprint.get("revision_id") or "")
        for item in fingerprint.get("artifacts", []):
            if isinstance(item, dict) and str(item.get("status") or "") != "current":
                issues.append(_issue("error", "superseded_artifact", f"Artifact is not current: {item.get('artifact')}", str(files["fingerprint"]), {"revision_id": revision, "artifact": item}))

    return _write_report(root, issues)


def _write_report(root: Path, issues: list[dict[str, Any]]) -> dict[str, Any]:
    report = {
        "schema_version": "swarm.contract_lint_report.v1",
        "run_dir": str(root),
        "pass": not any(issue["severity"] in {"error", "fatal"} for issue in issues),
        "issue_count": len(issues),
        "issues": issues,
    }
    out = root / "reports" / "contract_lint_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    for issue in issues:
        trace_debug_issue(
            severity=issue["severity"],
            source="contract_lint",
            code=issue["code"],
            message=issue["message"],
            details=issue,
            artifact_ref=issue.get("artifact_ref", ""),
            node_id="CONTRACT_LINT",
            output_dir=root,
            emit_live=False,
        )
    return report


def _issue(severity: str, code: str, message: str, artifact_ref: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, "artifact_ref": artifact_ref, "details": details or {}}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _iter_registers(spec: dict[str, Any]):
    for block, entry in spec.get("memory_map", {}).items():
        if not isinstance(entry, dict):
            continue
        for reg, meta in entry.get("registers", {}).items():
            if isinstance(meta, dict):
                yield str(block), str(reg), meta


def _uses_interrupts(spec: dict[str, Any]) -> bool:
    return any(reg == "irq_status" for _block, reg, _meta in _iter_registers(spec))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m semiconductor_swarm.tools.contract_lint <run_dir>", file=sys.stderr)
        return 2
    report = lint_run_dir(args[0])
    print(json.dumps({"pass": report["pass"], "issue_count": report["issue_count"], "report": str(Path(args[0]) / "reports" / "contract_lint_report.json")}, sort_keys=True))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
