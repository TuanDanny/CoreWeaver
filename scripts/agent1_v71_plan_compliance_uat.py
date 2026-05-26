"""V7.1 Agent1 plan-compliance UAT with injected user inputs."""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from semiconductor_swarm.agents.agent1_planning.agent1_llm_client import Agent1CodexResult  # noqa: E402
from semiconductor_swarm.agents.agent1_planning.agent1_subgraph import run_agent1_hierarchical_planning  # noqa: E402
from semiconductor_swarm.tools.contract_lint import lint_run_dir  # noqa: E402

EVIDENCE_ROOT = ROOT / "outputs" / "uat" / "agent1_v71_plan_compliance"
FAKE_SECRET = "agent1-v71-fake-secret-never-write"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    _write_text(path, json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


def _intake_payload(requirement: str) -> dict[str, Any]:
    text = requirement.lower()
    if "làm chip ai tiết kiệm điện" in text or "lam chip ai tiet kiem dien" in text:
        missing = [
            "target AI workload/model types",
            "performance target such as TOPS, latency, or throughput",
            "power budget and/or energy efficiency target such as W or TOPS/W",
            "bus/protocol",
            "memory architecture, on-chip memory size, and external memory type",
            "target flow: FPGA or ASIC",
            "verification requirements",
        ]
        return {
            "classification": "DESIGN_NEEDS_CLARIFICATION",
            "normalized_requirement": "",
            "canonical_intent": {
                "purpose": "low-power AI chip",
                "cpu": None,
                "bus": None,
                "peripheral": [],
                "accelerator": "AI accelerator",
                "clock": None,
                "power": "low-power, unspecified budget",
                "node": None,
                "memory": None,
                "interrupts": None,
                "verification_scope": None,
                "custom_ip": None,
            },
            "extracted_intent": {"accelerator": "AI", "power": "low-power"},
            "missing_fields": missing,
            "user_response": "Need clarification before architecture release.",
            "brief_form": {
                "chip_purpose": "low-power AI chip",
                "bus_protocol": "",
                "cpu_ip_peripheral": "AI accelerator",
                "clock": "",
                "power": "low-power target, no numeric budget",
                "target_flow": "",
            },
            "citations": [{"source": "raw_requirement", "field": "purpose", "text": "chip AI tiết kiệm điện"}],
            "conflicts": [],
            "contradictions": [],
            "confidence": 0.96,
        }
    if "apb i2c temperature sensor controller" in text:
        return {
            "classification": "DESIGN_READY",
            "normalized_requirement": "Generate an APB I2C temperature sensor controller with high_threshold and low_threshold interrupt thresholds, firmware APIs init_i2c_sensor and clear_temp_interrupt, formal-first verification, 50MHz clock.",
            "canonical_intent": {
                "purpose": "I2C temperature sensor controller",
                "cpu": None,
                "bus": {"protocol": "APB"},
                "peripheral": ["i2c"],
                "accelerator": None,
                "clock": {"frequency_mhz": 50},
                "power": None,
                "node": None,
                "memory": None,
                "interrupts": {"temperature_threshold_irq": True},
                "verification_scope": "formal-first",
                "custom_ip": "i2c_temperature_sensor_controller",
            },
            "extracted_intent": {"bus": "APB", "peripheral": "I2C", "clock": "50MHz", "interrupts": "temperature thresholds"},
            "missing_fields": [],
            "user_response": "Design-ready I2C temperature sensor requirement accepted.",
            "brief_form": {
                "chip_purpose": "I2C temperature sensor controller",
                "bus_protocol": "APB",
                "cpu_ip_peripheral": "I2C peripheral",
                "clock": "50MHz",
                "power": "",
                "target_flow": "formal-first",
            },
            "citations": [
                {"source": "raw_requirement", "field": "bus", "text": "APB"},
                {"source": "raw_requirement", "field": "peripheral", "text": "I2C temperature sensor"},
                {"source": "raw_requirement", "field": "register", "text": "high_threshold and low_threshold"},
                {"source": "raw_requirement", "field": "firmware", "text": "init_i2c_sensor and clear_temp_interrupt"},
            ],
            "conflicts": [],
            "contradictions": [],
            "confidence": 0.95,
        }
    return {
        "classification": "DESIGN_READY",
        "normalized_requirement": requirement,
        "canonical_intent": {
            "purpose": "32-bit CPU with APB UART/GPIO",
            "cpu": {"width_bits": 32},
            "bus": {"protocol": "APB"},
            "peripheral": ["uart", "gpio"],
            "accelerator": None,
            "clock": {"frequency_mhz": 100},
            "power": None,
            "node": None,
            "memory": {"sram_kb": 64},
            "interrupts": {"uart_irq": True},
            "verification_scope": "formal-first",
            "custom_ip": None,
        },
        "extracted_intent": {"cpu": "32-bit", "bus": "APB", "peripheral": "UART/GPIO", "clock": "100MHz"},
        "missing_fields": [],
        "user_response": "Design-ready CPU APB requirement accepted.",
        "brief_form": {
            "chip_purpose": "32-bit CPU subsystem",
            "bus_protocol": "APB",
            "cpu_ip_peripheral": "CPU, UART, GPIO",
            "clock": "100MHz",
            "power": "",
            "target_flow": "formal-first",
        },
        "citations": [{"source": "raw_requirement", "field": "cpu", "text": "32-bit CPU"}],
        "conflicts": [],
        "contradictions": [],
        "confidence": 0.94,
    }


def _council_payload(summary: str) -> dict[str, Any]:
    return {
        "summary": summary,
        "decisions": [{"decision": "preserve cited user requirement"}],
        "assumptions": [],
        "open_questions": [],
        "risks": [],
        "conflicts": [],
        "citations": [{"source": "raw_requirement"}],
        "confidence": 0.91,
        "needs_revision": False,
        "needs_retry": False,
        "selected_architecture_candidate": {
            "summary": summary,
            "primary_protocol": "APB",
            "external_peripherals": ["i2c", "uart", "gpio"],
        },
        "requirements_preserved": True,
        "plan_ready_candidate": True,
        "leaf_outputs": [],
        "internal_challenges": [],
        "accepted_decisions": [{"decision": "release stable APB-safe contract"}],
        "rejected_decisions": [],
        "manager_summary": summary,
        "handoff_to_principal": summary,
    }


def _fake_codex(prompt: str) -> Agent1CodexResult:
    evidence = {
        "base_url": "mock",
        "model": "mock-codex",
        "timestamp": "2026-05-24T00:00:00+00:00",
        "api_key": FAKE_SECRET,
        "total_tokens": 11,
        "estimated_cost_usd": 0.0001,
    }
    if "Agent 1 V6.4 Intake" in prompt or "Agent 1 V6.4 JSON Repair" in prompt or "Intake Adjudicator" in prompt:
        return Agent1CodexResult(content=json.dumps(_intake_payload(_raw_requirement_from_prompt(prompt)), ensure_ascii=False), evidence=evidence)
    return Agent1CodexResult(content=json.dumps(_council_payload("group-session consensus ok"), ensure_ascii=False), evidence=evidence)


def _raw_requirement_from_prompt(prompt: str) -> str:
    matches = re.findall(r"```text\s*(.*?)\s*```", prompt, flags=re.DOTALL)
    return matches[-1].strip() if matches else prompt


def _write_agent1_artifacts(root: Path, artifacts: dict[str, str], spec: dict[str, Any] | None) -> None:
    for name, text in artifacts.items():
        path = root / "reports" / "architecture_plan.md" if name == "architecture_plan.md" else root / "reports" / "agent1" / name
        _write_text(path, text if isinstance(text, str) else json.dumps(text, indent=2, sort_keys=True))
    if spec and not (root / "reports" / "agent1" / "agent1_final_architecture_spec.json").is_file():
        _write_json(root / "reports" / "agent1" / "agent1_final_architecture_spec.json", spec)


def _scan_for_secret(root: Path) -> list[str]:
    leaks: list[str] = []
    if not root.exists():
        return leaks
    for path in root.rglob("*"):
        if path.is_file() and FAKE_SECRET in path.read_text(encoding="utf-8", errors="replace"):
            leaks.append(str(path))
    return leaks


def _case_ambiguous_low_power_ai() -> dict[str, Any]:
    result = run_agent1_hierarchical_planning("làm chip AI tiết kiệm điện", "ai_low_power", planning_mode="normal")
    artifacts = result.get("agent1_artifacts") or {}
    questions = result.get("clarification_questions") or []
    return {
        "name": "ambiguous_low_power_ai",
        "pass": bool(
            result.get("requires_clarification") is True
            and (result.get("intake_report") or {}).get("ready_for_council") is False
            and "architecture_plan.md" not in artifacts
            and questions
            and all((q.get("options") for q in questions[:3]))
        ),
        "classification": (result.get("intake_report") or {}).get("classification"),
        "codex_call_count": (result.get("intake_report") or {}).get("codex_call_count"),
        "question_count": len(questions),
        "missing_fields": (result.get("intake_report") or {}).get("missing_fields", []),
        "has_architecture_plan": "architecture_plan.md" in artifacts,
    }


def _case_i2c_temperature_contract() -> dict[str, Any]:
    root = EVIDENCE_ROOT / "i2c_temperature_contract"
    requirement = "Generate an APB I2C temperature sensor controller with high_threshold and low_threshold interrupt thresholds, firmware APIs init_i2c_sensor and clear_temp_interrupt, formal-first verification, 50MHz clock."
    result = run_agent1_hierarchical_planning(requirement, "i2ctempsensoruat", planning_mode="normal")
    artifacts = result.get("agent1_artifacts") or {}
    _write_agent1_artifacts(root, artifacts, result.get("spec"))
    lint = lint_run_dir(root)
    plan = artifacts.get("architecture_plan.md", "")
    rdl = artifacts.get("agent1_register_map.rdl", "")
    header = artifacts.get("fw_i2ctempsensoruat_regs.h", "")
    driver = artifacts.get("fw_i2ctempsensoruat_driver_stub.c", "")
    model = artifacts.get("tb_i2ctempsensoruat_reg_model.py", "")
    checks = {
        "ready": result.get("requires_clarification") is not True,
        "has_plan": "architecture_plan.md" in artifacts,
        "thresholds_in_plan": all(reg in plan for reg in ("temperature_data", "high_threshold", "low_threshold")),
        "thresholds_in_rdl": all(f"reg {reg}" in rdl for reg in ("temperature_data", "high_threshold", "low_threshold")),
        "thresholds_in_header": all(f"I2CTEMPSENSORUAT_I2C_{reg.upper()}_OFFSET" in header for reg in ("temperature_data", "high_threshold", "low_threshold")),
        "thresholds_in_dv": all(f"self.i2c_{reg} = Register" in model for reg in ("temperature_data", "high_threshold", "low_threshold")),
        "firmware_apis": all(token in header and token in driver for token in ("init_i2c_sensor", "clear_temp_interrupt")),
        "irq_uses_macro": "I2CTEMPSENSORUAT_I2C_IRQ_STATUS_OFFSET" in driver and "block_base + 0x14u" not in driver,
        "mermaid_interrupt_highlight": "Interrupt Controller" in plan and "classDef interrupt" in plan and "class INTERRUPT_CTRL interrupt" in plan,
        "contract_lint_pass": lint.get("pass") is True,
    }
    return {
        "name": "i2c_temperature_contract",
        "pass": all(checks.values()) and not _scan_for_secret(root),
        "checks": checks,
        "lint_issue_count": lint.get("issue_count"),
        "lint_issues": lint.get("issues", []),
        "artifact_count": len(artifacts),
        "output_dir": str(root),
        "secret_leaks": _scan_for_secret(root),
    }


def _case_group_session_cpu_uart_gpio() -> dict[str, Any]:
    result = run_agent1_hierarchical_planning(
        "Generate a 32-bit CPU using APB with UART and GPIO peripherals, 100MHz, 64KB SRAM, formal-first verification.",
        "cpu_uart_gpio",
        planning_mode="normal",
    )
    artifacts = result.get("agent1_artifacts") or {}
    assignment = json.loads(artifacts.get("agent1_cluster_assignment.json", "{}"))
    group_trace = [json.loads(line) for line in artifacts.get("agent1_group_session_trace.jsonl", "").splitlines() if line.strip()]
    bridge = json.loads(artifacts.get("agent1_v51_mode_bridge.json", "{}"))
    checks = {
        "group_session_primary": bridge.get("minimum_planned_calls") == 9,
        "one_iteration": bridge.get("iteration_count") == 1,
        "seven_groups": len(group_trace) == 7,
        "assignment_hash": bool(assignment.get("cluster_assignment_hash")),
        "topology_version": assignment.get("topology_version") == "v7.1-default",
        "plan_ready": "architecture_plan.md" in artifacts and result.get("requires_clarification") is not True,
    }
    return {
        "name": "group_session_cpu_uart_gpio",
        "pass": all(checks.values()),
        "checks": checks,
        "group_count": len(group_trace),
        "planned_calls": bridge.get("minimum_planned_calls"),
        "artifact_count": len(artifacts),
    }


def run_uat() -> dict[str, Any]:
    if EVIDENCE_ROOT.exists():
        shutil.rmtree(EVIDENCE_ROOT)
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with patch("semiconductor_swarm.agents.agent1_planning.agent1_subgraph.call_agent1_codex", side_effect=_fake_codex):
        cases = [
            _case_ambiguous_low_power_ai(),
            _case_i2c_temperature_contract(),
            _case_group_session_cpu_uart_gpio(),
        ]
    report = {
        "schema_version": "agent1.v71_plan_compliance_uat.v1",
        "ok": all(case["pass"] for case in cases),
        "elapsed_s": round(time.time() - started, 3),
        "cases": cases,
        "evidence_root": str(EVIDENCE_ROOT),
    }
    _write_json(EVIDENCE_ROOT / "agent1_plan_compliance_report.json", report)
    return report


def main() -> int:
    report = run_uat()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
