import json
from pathlib import Path
import unittest
from unittest.mock import patch

from semiconductor_swarm.agents.agent1_planning.architect import (
    APB_SLAVE_INTERFACE,
    build_plan_quality_report,
    derive_project_name,
    generate_architecture_plan_markdown,
    generate_architecture_spec,
    requirement_needs_clarification,
    sanitize_project_name,
    spec_to_json,
    validate_architecture_spec,
    validate_plan_quality,
)
from semiconductor_swarm.agents.agent1_planning.agent1_config import AGENT1_LLM_CONFIG
from semiconductor_swarm.agents.agent1_planning.agent1_llm_client import Agent1CodexResult
from semiconductor_swarm.agents.agent1_planning.agent1_prompt import AGENT1_SYSTEM_PROMPT
from semiconductor_swarm.agents.agent1_planning.agent1_subgraph import (
    Agent1CodexUnavailable,
    V3_SUPER_COMMITTEE_NODES,
    _artifact_consistency_report,
    _firmware_driver_stub_artifact,
    _firmware_header_artifact,
    _memory_interface_artifact,
    _systemrdl_artifact,
    _cocotb_reg_model_artifact,
    _repair_node,
    _router_node,
    _validate_safety_security_memory_map,
    build_agent1_v3_validation_graph,
    route_after_repair,
    route_validation_decision,
    run_agent1_hierarchical_planning,
)
from semiconductor_swarm.agents.agent1_planning.intake_council import run_agent1_intake_council
from semiconductor_swarm.agents.agent1_planning.ai_expert_council import run_agent1_expert_council
from semiconductor_swarm.agents.agent1_planning.capability_registry import assess_requirement_capability
from semiconductor_swarm.agents.agent1_planning.audit_v4 import stable_hash, validate_audit_cross_checks
from semiconductor_swarm.agents.agent1_planning.proofs_v41 import build_v41_proof_report
from semiconductor_swarm.agents.agent1_planning.replay_cli import verify_replay_bundle
from semiconductor_swarm.agents.agent1_planning.spec_schema import attach_agent1_contract_manifest, attach_tool_provenance, validate_agent1_v37_spec_schema, validate_agent1_v4_spec_schema
from semiconductor_swarm.tools.bandwidth_calculator import calculate_bandwidth
from semiconductor_swarm.tools.contract_lint import lint_run_dir
from semiconductor_swarm.tools.ppa_calculator import calculate_ppa


def _v64_intake_payload(requirement: str, *, classification: str = "DESIGN_READY") -> dict:
    text = requirement.lower()
    if "aes" in text:
        normalized = "Generate an AES-128 APB crypto peripheral with KEY write-only and STATUS read-only registers at 50MHz."
        canonical = {
            "purpose": "AES-128 crypto peripheral",
            "cpu": None,
            "bus": {"protocol": "APB"},
            "peripheral": [],
            "accelerator": None,
            "clock": {"frequency_mhz": 50},
            "power": None,
            "node": None,
            "memory": None,
            "interrupts": None,
            "verification_scope": "formal-first register access",
            "custom_ip": "aes128_core",
        }
        citations = [
            {"source": "raw_requirement", "field": "purpose", "text": "AES-128"},
            {"source": "raw_requirement", "field": "bus", "text": "APB"},
            {"source": "raw_requirement", "field": "custom_ip", "text": "AES-128"},
            {"source": "raw_requirement", "field": "clock", "text": "50MHz"},
        ]
    else:
        normalized = "IoT AI camera chip <1W 100MHz"
        canonical = {
            "purpose": "IoT AI camera chip",
            "cpu": None,
            "bus": {"protocol": "APB"},
            "peripheral": [],
            "accelerator": "int8_mac_array",
            "clock": {"frequency_mhz": 100},
            "power": "<1W",
            "node": None,
            "memory": None,
            "interrupts": None,
            "verification_scope": "formal-first architecture",
            "custom_ip": None,
        }
        citations = [
            {"source": "raw_requirement", "field": "purpose", "text": "IoT AI camera chip"},
            {"source": "raw_requirement", "field": "accelerator", "text": "AI camera"},
            {"source": "raw_requirement", "field": "bus", "text": "APB"},
            {"source": "raw_requirement", "field": "clock", "text": "100MHz"},
            {"source": "raw_requirement", "field": "power", "text": "<1W"},
        ]
    return {
        "classification": classification,
        "normalized_requirement": normalized,
        "canonical_intent": canonical,
        "extracted_intent": canonical,
        "missing_fields": [],
        "user_response": "Design requirement accepted by Agent 1 intake.",
        "brief_form": {"chip_purpose": canonical["purpose"], "bus_protocol": "APB", "cpu_ip_peripheral": canonical.get("custom_ip") or canonical.get("accelerator"), "clock": canonical.get("clock"), "power": canonical.get("power"), "target_flow": "formal-first"},
        "citations": citations,
        "conflicts": [],
        "contradictions": [],
        "confidence": 0.93,
    }

def _v64_council_payload(summary: str = "ok") -> dict:
    return {
        "summary": summary,
        "decisions": [{"decision": "preserve_cited_requirement"}],
        "assumptions": [],
        "open_questions": [],
        "risks": [],
        "conflicts": [],
        "citations": [{"source": "raw_requirement"}],
        "confidence": 0.9,
        "needs_revision": False,
        "selected_architecture_candidate": {"summary": summary, "primary_protocol": "APB", "external_peripherals": []},
        "requirements_preserved": True,
        "plan_ready_candidate": True,
    }

def _fake_agent1_v64_codex(prompt):
    evidence = {"base_url": "http://localhost:20128/v1", "model": "cx/gpt-5.5", "timestamp": "2026-05-14T00:00:00+00:00", "status": "mocked", "api_key": "should_not_leak", "total_tokens": 1}
    if "Agent 1 V6.4 Intake" in prompt or "Agent 1 V6.4 JSON Repair" in prompt or "Intake Adjudicator" in prompt:
        return Agent1CodexResult(content=json.dumps(_v64_intake_payload(prompt)), evidence=evidence)
    return Agent1CodexResult(content=json.dumps(_v64_council_payload("council ok")), evidence=evidence)

class TestAgent1Tools(unittest.TestCase):
    def test_calculate_ppa_prompt_example(self):
        result = calculate_ppa("28nm", 250_000, 256, 64, 100)
        self.assertEqual(result["tech_node"], "28nm")
        self.assertEqual(result["power_mw"], 4.37)
        self.assertEqual(result["area_mm2"], 0.882)
        self.assertEqual(result["performance_tops"], 0.0128)

    def test_calculate_bandwidth(self):
        result = calculate_bandwidth(64, 100)
        self.assertEqual(result["peak_mb_s"], 800.0)
        self.assertEqual(result["effective_mb_s"], 640.0)


class TestAgent1Spec(unittest.TestCase):
    def test_ai_camera_spec_has_tool_outputs_and_locked_pinout(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        validate_architecture_spec(spec)

        self.assertEqual(spec["project_name"], "iot_camera")
        self.assertEqual(spec["requirements"]["power_budget_mw"], 1000)
        self.assertEqual(spec["target_node"], "28nm")
        self.assertEqual(spec["ppa_estimate"], calculate_ppa("28nm", 250_000, 256, 64, 100))
        self.assertEqual(spec["bandwidth_estimate"], calculate_bandwidth(64, 100))
        self.assertEqual(spec["interfaces"]["apb_slave"], APB_SLAVE_INTERFACE)
        self.assertFalse(spec["constraints"]["agent2_port_renaming_allowed"])
        self.assertTrue(spec["constraints"]["formal_first"])

    def test_ai_camera_without_cpu_citation_does_not_generate_cpu_core(self):
        spec = generate_architecture_spec("Tao chip AI camera APB 100MHz", "ai_camera")
        plan = generate_architecture_plan_markdown(spec)

        self.assertFalse(spec["requirements"]["cpu_requested"])
        self.assertFalse(spec["cpu_subsystem"]["synthesized_cpu"])
        self.assertEqual(spec["isa"], "none")
        self.assertEqual(spec["bus_topology"]["masters"], ["external_apb_host"])
        self.assertIn("mac_array", {block["name"] for block in spec["ip_blocks"]})
        self.assertIn("No CPU core is generated", plan)
        self.assertNotIn("rv32imc", plan.lower())
        self.assertNotIn("CPU core: `cpu_core`", plan)

    def test_json_output_is_strict_json(self):
        spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
        decoded = json.loads(spec_to_json(spec))
        self.assertEqual(decoded["project_name"], "spi_ctrl")
        self.assertIn("apb_slave", decoded["interfaces"])

    def test_uart_only_spec_does_not_over_generate_extra_blocks(self):
        spec = generate_architecture_spec("UART APB controller 50MHz", "uart_only")
        plan = generate_architecture_plan_markdown(spec)
        blocks = {block["name"] for block in spec["ip_blocks"]}

        self.assertEqual(blocks, {"uart"})
        self.assertEqual(spec["requested_block_set"], ["uart"])
        self.assertEqual(spec["allowed_derived_block_set"], [])
        self.assertNotIn("timer", spec["memory_map"])
        self.assertNotIn("control_regs", spec["memory_map"])
        self.assertNotIn("interrupt_ctrl", spec["memory_map"])
        self.assertIn("Block Minimality And Derived Blocks", plan)
        report = build_plan_quality_report(spec, plan)
        self.assertTrue(report["pass"], report["failures"])

    def test_multi_peripheral_apb_spec_has_gpio_timer_register_contract_without_cpu(self):
        requirement = (
            "Design a release-ready APB multi-peripheral subsystem at 75MHz. "
            "No CPU core. Use one external APB host, 32-bit data. "
            "Include UART, SPI, I2C, 32-bit GPIO with direction/data/interrupt registers, "
            "and timer/watchdog with timeout IRQ. Do not invent extra CPU, DMA, cache, or interrupt controller."
        )
        spec = generate_architecture_spec(requirement, "apb_multi_periph")
        plan = generate_architecture_plan_markdown(spec)
        blocks = {block["name"] for block in spec["ip_blocks"]}

        self.assertFalse(spec["requirements"]["cpu_requested"])
        self.assertFalse(spec["cpu_subsystem"]["synthesized_cpu"])
        self.assertEqual(spec["bus_topology"]["masters"], ["external_apb_host"])
        self.assertEqual(blocks, {"uart", "spi", "i2c", "gpio", "timer"})
        self.assertNotIn("interrupt_ctrl", spec["memory_map"])
        self.assertGreaterEqual(set(spec["memory_map"]["gpio"]["registers"]), {"data_in", "data_out", "direction", "irq_type", "irq_status", "irq_enable"})
        self.assertGreaterEqual(set(spec["memory_map"]["timer"]["registers"]), {"ctrl", "load", "value", "prescale", "watchdog", "irq_status", "irq_enable"})
        self.assertIn("GPIO External Peripheral", plan)
        self.assertIn("Timer/Watchdog External Peripheral", plan)
        report = build_plan_quality_report(spec, plan)
        self.assertTrue(report["pass"], report["failures"])

    def test_apb4_requirement_ignores_negated_axi_ahb_terms(self):
        requirement = (
            "Design a release-ready APB4 peripheral subsystem. "
            "One APB4 slave top with UART, SPI, I2C, GPIO, and watchdog timer. "
            "Do not invent AXI/AHB/CPU/security blocks."
        )
        spec = generate_architecture_spec(requirement, "apb4_periph")
        plan = generate_architecture_plan_markdown(spec)
        report = build_plan_quality_report(spec, plan)

        self.assertEqual(spec["requirements"]["extracted_intents"]["requested_bus_protocol"], "APB")
        self.assertEqual(spec["bus_architecture"]["primary_protocol"], "APB")
        self.assertTrue(report["pass"], report["failures"])

    def test_watchdog_without_timer_word_maps_to_timer_contract(self):
        requirement = (
            "Design an APB4 UART/GPIO/watchdog subsystem. "
            "No CPU, no DMA. Watchdog lock prevents disable after lock and protects GPIO direction. "
            "Formal-first SVA plus cocotb."
        )
        spec = generate_architecture_spec(requirement, "watchdog_subsystem")
        plan = generate_architecture_plan_markdown(spec)
        report = build_plan_quality_report(spec, plan)

        self.assertIn("timer", {block["name"] for block in spec["ip_blocks"]})
        self.assertGreaterEqual(set(spec["memory_map"]["timer"]["registers"]), {"ctrl", "load", "value", "prescale", "watchdog", "irq_status", "irq_enable"})
        self.assertIn("lock", spec["memory_map"]["timer"]["registers"])
        self.assertIn("lock", spec["memory_map"]["gpio"]["registers"])
        self.assertTrue(spec["memory_map"]["timer"]["registers"]["ctrl"]["lock_protected"])
        self.assertTrue(spec["memory_map"]["gpio"]["registers"]["direction"]["lock_protected"])
        self.assertIn("Timer/Watchdog External Peripheral", plan)
        self.assertIn("set-only", plan)
        self.assertTrue(report["pass"], report["failures"])

    def test_intake_tolerates_single_expert_codex_failure(self):
        requirement = "Design RV32IMC SoC with APB UART at 100MHz"

        def valid_payload() -> str:
            return json.dumps(
                {
                    "classification": "DESIGN_READY",
                    "normalized_requirement": requirement,
                    "canonical_intent": {
                        "purpose": "RV32IMC microcontroller SoC",
                        "cpu": "RV32IMC",
                        "bus": "APB",
                        "peripheral": ["UART"],
                        "clock": "100MHz",
                    },
                    "extracted_intent": {"cpu": "RV32IMC", "bus": "APB", "peripheral": ["UART"]},
                    "missing_fields": [],
                    "user_response": "Ready for architecture planning.",
                    "brief_form": {
                        "chip_purpose": "RV32IMC microcontroller SoC",
                        "bus_protocol": "APB",
                        "cpu_ip_peripheral": "RV32IMC UART",
                        "clock": "100MHz",
                        "power": "",
                        "target_flow": "formal-first",
                    },
                    "citations": [
                        {"source": "raw_requirement", "field": "purpose", "text": "Design RV32IMC SoC"},
                        {"source": "raw_requirement", "field": "cpu", "text": "RV32IMC"},
                        {"source": "raw_requirement", "field": "bus", "text": "APB"},
                        {"source": "raw_requirement", "field": "peripheral", "text": "UART"},
                    ],
                    "conflicts": [],
                    "contradictions": [],
                    "confidence": 0.92,
                }
            )

        def codex_call(prompt: str):
            if "UserBriefExpert" in prompt:
                raise TimeoutError("mock timeout")
            return Agent1CodexResult(valid_payload(), {"model": "mock", "total_tokens": 1})

        report = run_agent1_intake_council(requirement, "rv32_intake", codex_call)

        self.assertTrue(report["ready_for_council"])
        self.assertEqual(report["classification"], "DESIGN_READY")
        self.assertIn("A1.00-BRIEF", report["policy_matrix"]["policies"][0]["evidence"]["failed_nodes"])

    def test_intake_fast_routes_apb4_peripheral_without_negated_ahb(self):
        requirement = (
            "Design a release-ready APB4 peripheral subsystem for FPGA and ASIC reuse. "
            "One locked APB4 slave top. No CPU, no DMA, no cache, no AXI/AHB. "
            "Peripherals: UART, SPI master, I2C master, 32-bit GPIO, watchdog/timer. "
            "100MHz target, formal-first SVA, cocotb regression, RDL/C header/DV register model, safety-zero signoff."
        )

        def forbidden_codex(_prompt):
            raise AssertionError("simple APB4 peripheral should not call Codex intake")

        report = run_agent1_intake_council(requirement, "apb4_peripheral", forbidden_codex)

        self.assertTrue(report["ready_for_council"])
        self.assertEqual(report["classification"], "DESIGN_READY")
        self.assertEqual(report["codex_call_count"], 0)
        self.assertEqual(report["canonical_intent"]["bus"]["protocol"], "APB")
        self.assertIsNone(report["canonical_intent"]["cpu"])

    def test_intake_detailed_rv32imc_soc_rescues_overclarifying_model(self):
        requirement = (
            "Design a release-ready RV32IMC microcontroller SoC for FPGA bring-up and ASIC reuse. "
            "CPU: 32-bit RV32IMC, 3-stage in-order pipeline. "
            "Memory: 16KB boot ROM at 0x00000000, 64KB SRAM at 0x20000000, APB peripheral window at 0x40000000. "
            "No cache, no DMA. Bus: CPU instruction/data access to local ROM/SRAM and APB4 peripherals. "
            "Peripherals: UART, SPI master, I2C master, GPIO, watchdog timer. "
            "100MHz target. Verification: formal-first SVA, cocotb regressions, RDL/header/DV consistency, G00-G12 signoff."
        )
        payload = {
            "classification": "DESIGN_NEEDS_CLARIFICATION",
            "normalized_requirement": requirement,
            "canonical_intent": {
                "purpose": "RV32IMC microcontroller SoC",
                "cpu": "32-bit RV32IMC",
                "bus": "APB4",
                "peripheral": ["UART", "SPI", "I2C", "GPIO", "watchdog timer"],
                "memory": {"rom": "16KB", "sram": "64KB", "apb_window": "0x40000000"},
                "clock": "100MHz",
                "verification_scope": ["formal-first SVA", "cocotb", "G00-G12 signoff"],
            },
            "extracted_intent": {},
            "missing_fields": ["exact trap vector", "exact UART FIFO depth", "exact APB PSLVERR behavior"],
            "user_response": "Need more detail before release.",
            "brief_form": {},
            "citations": [{"source": "raw_requirement", "field": "cpu", "text": "CPU: 32-bit RV32IMC"}],
            "conflicts": [],
            "contradictions": [],
            "confidence": 0.7,
        }

        def codex_call(_prompt):
            return Agent1CodexResult(json.dumps(payload), {"model": "mock", "total_tokens": 1})

        report = run_agent1_intake_council(requirement, "rv32_soc", codex_call)

        self.assertTrue(report["ready_for_council"])
        self.assertEqual(report["classification"], "DESIGN_READY")
        self.assertEqual(report["missing_fields"], [])
        self.assertEqual(report["canonical_intent"]["bus"]["protocol"], "APB")
        self.assertEqual(report["canonical_intent"]["cpu"]["width_bits"], 32)

    def test_architecture_plan_contains_hitl_sections(self):
        spec = generate_architecture_spec("I2C controller 50MHz", "i2c_ctrl")
        plan = generate_architecture_plan_markdown(spec)
        self.assertIn("# Architecture Plan", plan)
        self.assertIn("## Block Diagram", plan)
        self.assertIn("```mermaid", plan)
        self.assertIn("flowchart TD", plan)
        self.assertIn("stateDiagram-v2", plan)
        self.assertNotIn("```text", plan)
        self.assertIn("## Interfaces", plan)
        self.assertIn("## Timeline", plan)
        self.assertIn("APB slave pinout is locked", plan)
        self.assertIn("## Executive Decision Ledger", plan)
        self.assertIn("## Requirement Coverage", plan)
        self.assertIn("## Interface Contract", plan)
        self.assertIn("## Verification Plan", plan)
        self.assertIn("## Signoff Evidence Expected", plan)
        self.assertNotIn("Expert calls: 0", plan)

    def test_v78_register_table_shows_write_policy_set_only(self):
        requirement = (
            "Design an APB4 GPIO watchdog subsystem. No CPU. "
            "Lock prevents GPIO direction and watchdog ctrl writes after lock. "
            "Formal-first SVA plus cocotb."
        )
        spec = generate_architecture_spec(requirement, "lock_policy")
        plan = generate_architecture_plan_markdown(spec)

        self.assertIn("| Write Policy |", plan)
        self.assertIn("| gpio |", plan)
        self.assertIn("| lock |", plan)
        self.assertIn("| set_only |", plan)
        self.assertIn("guards protected writes until reset", plan)

    def test_cpu32_apb_uart_spec_captures_requirement(self):
        requirement = "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral"
        spec = generate_architecture_spec(requirement, "cpu32bit")
        validate_architecture_spec(spec)

        self.assertEqual(spec["requirements"]["application_domain"], "embedded_cpu_platform")
        self.assertTrue(spec["requirements"]["cpu_requested"])
        self.assertEqual(spec["requirements"]["external_peripherals"], ["uart"])
        self.assertEqual(spec["cpu_subsystem"]["data_width_bits"], 32)
        self.assertEqual(spec["cpu_subsystem"]["isa"], "rv32imc")
        self.assertEqual(spec["cpu_subsystem"]["bus_role"], "APB master")
        self.assertIn("uart", {block["name"] for block in spec["ip_blocks"]})
        self.assertIn("uart", spec["bus_topology"]["slaves"])
        uart_regs = spec["memory_map"]["uart"]["registers"]
        for reg in ("txdata", "rxdata", "status", "ctrl", "baud_div", "irq_status", "irq_enable"):
            self.assertIn(reg, uart_regs)
        self.assertEqual(uart_regs["irq_status"]["clear"], "W1C")
        self.assertIn("uart", _memory_interface_artifact(spec)["interrupt_owners"])

    def test_cpu32_apb_uart_plan_is_reviewable(self):
        requirement = "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral"
        spec = generate_architecture_spec(requirement, "cpu32bit")
        plan = generate_architecture_plan_markdown(spec)
        for token in (
            "Executive Summary",
            "Requirement Extraction",
            "32-bit CPU",
            "rv32imc",
            "APB master",
            "UART",
            "baud_div",
            "irq_status",
            "Acceptance Criteria",
        ):
            self.assertIn(token, plan)

        report = build_plan_quality_report(spec, plan)
        self.assertTrue(report["pass"], report["failures"])
        self.assertTrue(validate_plan_quality(spec, plan)["pass"])

    def test_greeting_requirement_requires_clarification_without_project_name_inference(self):
        self.assertTrue(requirement_needs_clarification("hi"))
        self.assertFalse(requirement_needs_clarification("make a simple CPU"))
        with self.assertRaisesRegex(ValueError, "requirement needs clarification"):
            generate_architecture_spec("hi", "cpu32bit_web")

    def test_expert_council_does_not_default_greeting_to_cpu_apb(self):
        def fake_codex(prompt):
            return Agent1CodexResult(
                content=json.dumps({"summary": "input too sparse", "decisions": [], "assumptions": [], "open_questions": ["clarify chip intent"], "citations": []}),
                evidence={"base_url": "mock", "model": "mock", "timestamp": "2026-05-21T00:00:00+00:00", "total_tokens": 1},
            )

        analysis = run_agent1_expert_council("hi", "cpu32bit_web", fake_codex)

        self.assertEqual(analysis["selected_architecture"]["status"], "requires_clarification")
        self.assertIsNone(analysis["selected_architecture"]["primary_protocol"])
        self.assertIsNone(analysis["selected_architecture"]["cpu_width_bits"])
        self.assertEqual(analysis["capability_assessment"]["mode"], "requires_clarification")

    def test_non_uart_plan_has_no_stale_uart_irq_question(self):
        spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
        plan = generate_architecture_plan_markdown(spec)

        self.assertNotIn("UART IRQ", plan)
        self.assertNotIn("UART `baud_div`", plan)

    def test_cpu32_apb_uart_i2c_plan_captures_both_peripherals(self):
        requirement = "Generate a 32-bit CPU architecture using an APB bus, with UART and I2C as the external peripherals"
        spec = generate_architecture_spec(requirement, "cpu32bitv2")
        plan = generate_architecture_plan_markdown(spec)

        self.assertEqual(spec["requirements"]["external_peripherals"], ["uart", "i2c"])
        for reg in ("txdata", "rxdata", "status", "ctrl", "target_addr", "timing", "irq_status", "irq_enable"):
            self.assertIn(reg, spec["memory_map"]["i2c"]["registers"])
        i2c_meta = next(item for item in spec["external_peripherals"] if item["name"] == "i2c")
        self.assertTrue(i2c_meta["interrupt"])
        for token in ("I2C External Peripheral", "target_addr", "timing", "irq_status", "Acceptance Criteria"):
            self.assertIn(token, plan)

        report = build_plan_quality_report(spec, plan)
        self.assertTrue(report["pass"], report["failures"])

    def test_i2c_temperature_sensor_contract_syncs_plan_rdl_firmware_and_dv(self):
        requirement = "Generate an APB I2C temperature sensor controller with high_threshold and low_threshold interrupt thresholds"
        spec = generate_architecture_spec(requirement, "i2ctempsensoruat")
        plan = generate_architecture_plan_markdown(spec)
        rdl = _systemrdl_artifact(spec)
        header = _firmware_header_artifact(spec)
        driver = _firmware_driver_stub_artifact(spec)
        model = _cocotb_reg_model_artifact(spec)
        artifacts = {
            "architecture_plan.md": plan,
            "agent1_register_map.rdl": rdl,
            "fw_i2ctempsensoruat_regs.h": header,
            "fw_i2ctempsensoruat_driver_stub.c": driver,
            "tb_i2ctempsensoruat_reg_model.py": model,
        }
        regs = spec["memory_map"]["i2c"]["registers"]

        for reg in ("temperature_data", "high_threshold", "low_threshold", "irq_status", "irq_enable"):
            self.assertIn(reg, regs)
            self.assertIn(reg, plan)
            self.assertIn(f"reg {reg}", rdl)
            self.assertIn(f"I2CTEMPSENSORUAT_I2C_{reg.upper()}_OFFSET", header)
            self.assertIn(f"self.i2c_{reg} = Register", model)
        self.assertEqual(regs["irq_status"]["offset"], "0x18")
        self.assertIn("void init_i2c_sensor(void);", header)
        self.assertIn("void clear_temp_interrupt(uintptr_t block_base, uint32_t mask);", header)
        self.assertIn("void init_i2c_sensor(void)", driver)
        self.assertIn("void clear_temp_interrupt(uintptr_t block_base, uint32_t mask)", driver)
        self.assertIn("I2CTEMPSENSORUAT_I2C_IRQ_STATUS_OFFSET", driver)
        self.assertNotIn("block_base + 0x14u", driver)
        self.assertIn("Interrupt Controller", plan)
        self.assertIn("classDef interrupt", plan)
        self.assertIn("class INTERRUPT_CTRL interrupt", plan)
        consistency = _artifact_consistency_report(spec, plan, artifacts)
        self.assertTrue(consistency["pass"], consistency["issues"])

    def test_contract_lint_reports_synced_i2c_temperature_output(self):
        requirement = "Generate an APB I2C temperature sensor controller with high_threshold and low_threshold interrupt thresholds"
        spec = generate_architecture_spec(requirement, "i2ctempsensoruat")
        plan = generate_architecture_plan_markdown(spec)
        root = Path(self._testMethodName)
        if root.exists():
            import shutil
            shutil.rmtree(root)
        try:
            agent1 = root / "reports" / "agent1"
            agent1.mkdir(parents=True)
            (root / "reports" / "architecture_plan.md").write_text(plan, encoding="utf-8")
            (agent1 / "agent1_final_architecture_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
            (agent1 / "agent1_register_map.rdl").write_text(_systemrdl_artifact(spec), encoding="utf-8")
            (agent1 / "fw_i2ctempsensoruat_regs.h").write_text(_firmware_header_artifact(spec), encoding="utf-8")
            (agent1 / "fw_i2ctempsensoruat_driver_stub.c").write_text(_firmware_driver_stub_artifact(spec), encoding="utf-8")
            (agent1 / "tb_i2ctempsensoruat_reg_model.py").write_text(_cocotb_reg_model_artifact(spec), encoding="utf-8")
            (agent1 / "agent1_artifact_fingerprint_manifest.json").write_text(json.dumps({"revision_id": "r1", "artifacts": [{"artifact": "architecture_plan.md", "status": "current"}]}), encoding="utf-8")

            report = lint_run_dir(root)

            self.assertTrue(report["pass"], report["issues"])
            self.assertTrue((root / "reports" / "contract_lint_report.json").exists())
        finally:
            if root.exists():
                import shutil
                shutil.rmtree(root)

    def test_plan_quality_gate_rejects_missing_i2c_for_i2c_requirement(self):
        requirement = "Generate a 32-bit CPU architecture using an APB bus, with UART and I2C as the external peripherals"
        spec = generate_architecture_spec(requirement, "cpu32bitv2")
        bad_spec = json.loads(json.dumps(spec))
        bad_spec["ip_blocks"] = [block for block in bad_spec["ip_blocks"] if block["name"] != "i2c"]
        bad_spec["bus_topology"]["slaves"] = [slave for slave in bad_spec["bus_topology"]["slaves"] if slave != "i2c"]
        bad_spec["memory_map"].pop("i2c")
        bad_plan = generate_architecture_plan_markdown(bad_spec)

        report = build_plan_quality_report(bad_spec, bad_plan)
        self.assertFalse(report["pass"])
        self.assertIn("i2c_intent_satisfied", report["failures"])

    def test_plan_quality_gate_rejects_missing_uart_for_uart_requirement(self):
        requirement = "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral"
        spec = generate_architecture_spec(requirement, "cpu32bit")
        bad_spec = json.loads(json.dumps(spec))
        bad_spec["ip_blocks"] = [block for block in bad_spec["ip_blocks"] if block["name"] != "uart"]
        bad_spec["bus_topology"]["slaves"] = [slave for slave in bad_spec["bus_topology"]["slaves"] if slave != "uart"]
        bad_spec["memory_map"].pop("uart")
        bad_plan = generate_architecture_plan_markdown(bad_spec)

        report = build_plan_quality_report(bad_spec, bad_plan)
        self.assertFalse(report["pass"])
        self.assertIn("uart_intent_satisfied", report["failures"])
        with self.assertRaisesRegex(ValueError, "Agent 1 plan quality failed"):
            validate_plan_quality(bad_spec, bad_plan)

    def test_cpu64_ahb_spi_plan_preserves_requested_bus_and_peripheral(self):
        requirement = "Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral"
        spec = generate_architecture_spec(requirement, "cpu_soc")
        plan = generate_architecture_plan_markdown(spec)
        report = build_plan_quality_report(spec, plan)

        self.assertEqual(spec["requirements"]["extracted_intents"]["requested_bus_protocol"], "AHB")
        self.assertEqual(spec["bus_architecture"]["primary_protocol"], "AHB")
        self.assertEqual(spec["cpu_subsystem"]["data_width_bits"], 64)
        self.assertEqual(spec["cpu_subsystem"]["bus_role"], "AHB master")
        self.assertIn("spi", spec["requirements"]["external_peripherals"])
        self.assertIn("spi", spec["memory_map"])
        self.assertIn("AHB primary system bus", plan)
        self.assertIn("SPI External Peripheral", plan)
        self.assertIn("AI Expert Council Summary", plan)
        self.assertIn("Selected Architecture", plan)
        self.assertIn("Rejected Alternatives", plan)
        self.assertIn("Downstream Capability Assessment", plan)
        self.assertNotIn("APB fabric", plan)
        self.assertNotIn("rv32", plan.lower())
        self.assertNotIn("UART `baud_div`", plan)
        self.assertNotIn("I2C `target_addr`", plan)
        self.assertTrue(report["pass"], report["failures"])

    def test_plan_quality_gate_rejects_ahb_requirement_rewritten_to_apb_only(self):
        requirement = "Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral"
        spec = generate_architecture_spec(requirement, "cpu_soc")
        bad_spec = json.loads(json.dumps(spec))
        bad_spec["bus_architecture"]["primary_protocol"] = "APB"
        bad_spec["cpu_subsystem"]["bus_role"] = "APB master"
        bad_plan = generate_architecture_plan_markdown(bad_spec).replace("AHB", "APB")

        report = build_plan_quality_report(bad_spec, bad_plan)
        self.assertFalse(report["pass"])
        self.assertIn("bus_intent_satisfied", report["failures"])

    def test_plan_quality_gate_rejects_stale_unrequested_protocol_and_peripheral_text(self):
        requirement = "Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral"
        spec = generate_architecture_spec(requirement, "cpu_soc")
        plan = generate_architecture_plan_markdown(spec)
        stale_plan = plan + "\n- Acceptance Criteria: UART `baud_div` must exist.\n- CPU ISA not specified; Agent 1 assumes rv32imc.\n"

        report = build_plan_quality_report(spec, stale_plan)
        self.assertFalse(report["pass"])
        self.assertIn("negative_token_clean", report["failures"])

    def test_agent1_expert_council_calls_multiple_codex_experts(self):
        calls = []

        def fake_codex(prompt):
            calls.append(prompt)
            return Agent1CodexResult(
                content=json.dumps({"summary": "expert ok", "decisions": [], "assumptions": [], "open_questions": [], "citations": [{"source": "raw_requirement"}]}),
                evidence={"base_url": "mock", "model": "mock", "timestamp": "2026-05-21T00:00:00+00:00", "total_tokens": 10},
            )

        analysis = run_agent1_expert_council(
            "Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral",
            "cpu_soc",
            fake_codex,
        )

        self.assertGreaterEqual(len(calls), 6)
        self.assertEqual(analysis["schema_version"], "agent1.ai_requirement_analysis.v1")
        self.assertEqual(analysis["extracted_intents"]["requested_bus_protocol"], "AHB")
        self.assertEqual(analysis["selected_architecture"]["primary_protocol"], "AHB")
        self.assertEqual(analysis["capability_assessment"]["mode"], "bridge_supported")
        self.assertIn("expert_trace_jsonl", analysis)

    def test_capability_registry_routes_pure_ahb_to_hitl_gap(self):
        assessment = assess_requirement_capability(
            {
                "raw_requirement": "Generate a pure AHB only 64-bit CPU with SPI and no APB bridge",
                "extracted_intents": {"requested_bus_protocol": "AHB"},
                "selected_architecture": {"primary_protocol": "AHB"},
            }
        )

        self.assertEqual(assessment["mode"], "unsupported_hitl")
        self.assertTrue(assessment["capability_gaps"])

    def test_project_name_sanitized_and_derived(self):
        self.assertEqual(sanitize_project_name("My Camera SoC!"), "my_camera_soc")
        self.assertEqual(sanitize_project_name("123 chip"), "p_123_chip")
        self.assertEqual(derive_project_name("temperature monitor 50MHz"), "thermal_sensor")
        self.assertEqual(generate_architecture_spec("SPI controller 50MHz", "SPI Demo!")["project_name"], "spi_demo")

    @patch("semiconductor_swarm.agents.agent1_planning.agent1_subgraph.call_agent1_codex")
    def test_agent1_hierarchical_subgraph_contract(self, mock_codex):
        mock_codex.side_effect = _fake_agent1_v64_codex
        result = run_agent1_hierarchical_planning("IoT AI camera chip <1W 100MHz", "edge cam")
        self.assertEqual(result["spec"]["project_name"], "edge_cam")
        self.assertEqual(result["report"]["micro_experts"], V3_SUPER_COMMITTEE_NODES)
        self.assertEqual(result["report"]["codex_contract"]["base_url"], "http://localhost:20128/v1")
        self.assertEqual(result["report"]["codex_contract"]["model"], "cx/gpt-5.5")
        self.assertTrue(result["report"]["mermaid_diagrams"])
        self.assertEqual(result["report"]["codex_evidence"]["status"], "mocked")
        self.assertIn("agent1_codex_response.md", result["agent1_artifacts"])
        self.assertIn("agent1_memory_interface_plan.json", result["agent1_artifacts"])
        self.assertIn("agent1_review_scorecard.md", result["agent1_artifacts"])
        self.assertIn("agent1_validation_decisions.json", result["agent1_artifacts"])
        self.assertIn("agent1_v3_super_committee_report.md", result["agent1_artifacts"])
        self.assertIn("agent1_micro_expert_validation.json", result["agent1_artifacts"])
        tool_evidence = json.loads(result["agent1_artifacts"]["agent1_tool_evidence.json"])
        self.assertEqual(tool_evidence["tool_provenance"]["ppa_estimate"]["source_tool"], "calculate_ppa")
        self.assertEqual(tool_evidence["tool_provenance"]["bandwidth_estimate"]["source_tool"], "calculate_bandwidth")
        self.assertIn("agent1_v4_trace.jsonl", result["agent1_artifacts"])
        self.assertIn("agent1_v4_tool_ledger.jsonl", result["agent1_artifacts"])
        self.assertIn("agent1_v4_replay_bundle.json", result["agent1_artifacts"])
        self.assertIn("agent1_v4_audit_cross_check.json", result["agent1_artifacts"])
        self.assertIn("agent1_contract_manifest.json", result["agent1_artifacts"])
        self.assertIn("agent1_v41_proof_report.json", result["agent1_artifacts"])
        self.assertIn("agent1_v41_risk_register.json", result["agent1_artifacts"])
        self.assertIn("agent1_v41_trade_study.json", result["agent1_artifacts"])
        self.assertIn("agent1_v41_scorecard.md", result["agent1_artifacts"])
        self.assertIn("agent1_plan_quality_report.json", result["agent1_artifacts"])
        self.assertTrue(json.loads(result["agent1_artifacts"]["agent1_plan_quality_report.json"])["pass"])
        self.assertTrue(result["report"]["plan_quality_report"]["pass"])
        self.assertIn("formal_intent", result["spec"])
        self.assertTrue(result["report"]["v41_proof_report"]["pass"])
        self.assertFalse(result["report"]["v41_risk_register"]["hitl_required"])
        validate_agent1_v4_spec_schema(result["spec"])
        manifest = json.loads(result["agent1_artifacts"]["agent1_contract_manifest.json"])
        self.assertEqual(manifest["schema_version"], "agent1_contract_manifest_v4")
        self.assertEqual(set(manifest["handoffs"]), {"agent2", "agent3", "agent4", "agent5"})
        self.assertIn("no APB port rename", manifest["handoffs"]["agent2"]["output_contract"])
        self.assertTrue(result["report"]["v4_audit_cross_check"]["pass"])
        self.assertIn("agent1_register_map.rdl", result["agent1_artifacts"])
        self.assertIn("agent1_ai_requirement_analysis.json", result["agent1_artifacts"])
        self.assertIn("agent1_expert_council_trace.jsonl", result["agent1_artifacts"])
        self.assertIn("agent1_capability_assessment.json", result["agent1_artifacts"])
        self.assertIn("agent1_requirement_consistency_report.json", result["agent1_artifacts"])
        self.assertGreaterEqual(mock_codex.call_count, 15)
        self.assertIn("fw_edge_cam_regs.h", result["agent1_artifacts"])
        self.assertIn("fw_edge_cam_driver_stub.c", result["agent1_artifacts"])
        self.assertIn("tb_edge_cam_reg_model.py", result["agent1_artifacts"])
        decisions = json.loads(result["agent1_artifacts"]["agent1_validation_decisions.json"])
        validators = {decision["validator"] for decision in decisions}
        self.assertIn("MemoryHierarchy_vs_QoS_Validator", validators)
        self.assertIn("DFT_vs_IO_ClockPower_Validator", validators)
        self.assertIn("RDL_vs_CHeader_Validator", validators)
        self.assertIn("RDL_vs_DVModel_Validator", validators)
        self.assertIn("Super_Committee_Review_Router", result["plan_markdown"])
        self.assertIn("too many revisions", result["plan_markdown"])
        self.assertIn("agent1_register_map.rdl", result["plan_markdown"])
        self.assertTrue(result["report"]["micro_expert_validation"]["pass"])
        self.assertEqual(AGENT1_LLM_CONFIG["model"], "cx/gpt-5.5")

    @patch("semiconductor_swarm.agents.agent1_planning.agent1_subgraph.call_agent1_codex")
    def test_agent1_v4_audit_cross_checks_trace_ledger_replay(self, mock_codex):
        mock_codex.side_effect = _fake_agent1_v64_codex
        result = run_agent1_hierarchical_planning("IoT AI camera chip <1W 100MHz", "edge cam")
        artifacts = result["agent1_artifacts"]
        trace = [json.loads(line) for line in artifacts["agent1_v4_trace.jsonl"].splitlines()]
        ledger = [json.loads(line) for line in artifacts["agent1_v4_tool_ledger.jsonl"].splitlines()]
        replay = json.loads(artifacts["agent1_v4_replay_bundle.json"])

        self.assertGreaterEqual(len(trace), 5)
        self.assertEqual({entry["tool"] for entry in ledger}, {"calculate_ppa", "calculate_bandwidth"})
        self.assertEqual(replay["tool_ledger_hash"], stable_hash(ledger))
        self.assertTrue(all(span["trace_id"] == replay["trace_id"] for span in trace))
        self.assertEqual(replay["codex"]["evidence"]["api_key"], "<redacted>")
        self.assertTrue(validate_audit_cross_checks(artifacts)["pass"])

    @patch("semiconductor_swarm.agents.agent1_planning.agent1_subgraph.call_agent1_codex")
    def test_agent1_v4_replay_cli_verifies_bundle_and_detects_mutation(self, mock_codex):
        mock_codex.side_effect = _fake_agent1_v64_codex
        result = run_agent1_hierarchical_planning("IoT AI camera chip <1W 100MHz", "edge cam")
        tmp = Path(self._testMethodName)
        tmp.mkdir(exist_ok=True)
        try:
            (tmp / "bundle.json").write_text(result["agent1_artifacts"]["agent1_v4_replay_bundle.json"], encoding="utf-8")
            (tmp / "trace.jsonl").write_text(result["agent1_artifacts"]["agent1_v4_trace.jsonl"], encoding="utf-8")
            (tmp / "ledger.jsonl").write_text(result["agent1_artifacts"]["agent1_v4_tool_ledger.jsonl"], encoding="utf-8")
            (tmp / "spec.json").write_text(json.dumps(result["spec"], sort_keys=True), encoding="utf-8")
            self.assertTrue(verify_replay_bundle(tmp / "bundle.json", tmp / "trace.jsonl", tmp / "ledger.jsonl", tmp / "spec.json")["pass"])
            mutated = json.loads((tmp / "spec.json").read_text(encoding="utf-8"))
            mutated["constraints"]["formal_first"] = False
            (tmp / "spec_bad.json").write_text(json.dumps(mutated, sort_keys=True), encoding="utf-8")
            bad = verify_replay_bundle(tmp / "bundle.json", tmp / "trace.jsonl", tmp / "ledger.jsonl", tmp / "spec_bad.json")
            self.assertFalse(bad["pass"])
            self.assertTrue(any("spec_schema_invalid" in failure for failure in bad["failures"]))
        finally:
            for child in tmp.glob("*"):
                child.unlink()
            tmp.rmdir()

    def test_agent1_v37_schema_gate_requires_v3_handoff_keys(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "edge cam")
        with self.assertRaisesRegex(ValueError, "Agent1 V3.7 schema missing keys"):
            validate_agent1_v37_spec_schema(spec)

    def test_agent1_v37_tool_provenance_required(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "edge cam")
        spec.update({
            "firmware_contract": {"hal_modules": ["generic_hal"], "interrupt_flow": [], "register_access_semantics": {}},
            "io_packaging": {},
            "power_intent": {},
            "cdc_rdc_plan": {},
            "interconnect_qos": {},
            "memory_hierarchy": {},
            "dft_plan": {},
            "safety_security": {},
            "ip_reuse_cost": {},
        })
        spec = attach_tool_provenance(spec)
        validate_agent1_v37_spec_schema(spec)
        spec = attach_agent1_contract_manifest(spec)
        validate_agent1_v4_spec_schema(spec)
        spec["ppa_estimate"] = {"power_mw": 999}
        with self.assertRaisesRegex(ValueError, "provenance hash mismatch"):
            validate_agent1_v37_spec_schema(spec)

    def test_agent1_v4_schema_gate_requires_tool_inputs_and_manifest(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "edge cam")
        spec.update({
            "firmware_contract": {"hal_modules": ["generic_hal"], "interrupt_flow": [], "register_access_semantics": {}},
            "io_packaging": {},
            "power_intent": {},
            "cdc_rdc_plan": {},
            "interconnect_qos": {},
            "memory_hierarchy": {},
            "dft_plan": {},
            "safety_security": {},
            "ip_reuse_cost": {},
        })
        spec = attach_tool_provenance(spec)
        with self.assertRaisesRegex(ValueError, "Agent1 V4 schema missing keys"):
            validate_agent1_v4_spec_schema(spec)
        spec = attach_agent1_contract_manifest(spec)
        validate_agent1_v4_spec_schema(spec)
        spec["agent1_contract_manifest"]["handoffs"]["agent2"]["inputs"] = []
        with self.assertRaisesRegex(ValueError, "agent2.inputs must be non-empty list"):
            validate_agent1_v4_spec_schema(spec)

    def test_agent1_v4_schema_rejects_unlocked_apb_and_bad_registers(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "edge cam")
        spec.update({
            "firmware_contract": {"hal_modules": ["generic_hal"], "interrupt_flow": [], "register_access_semantics": {}},
            "io_packaging": {},
            "power_intent": {},
            "cdc_rdc_plan": {},
            "interconnect_qos": {},
            "memory_hierarchy": {},
            "dft_plan": {},
            "safety_security": {},
            "ip_reuse_cost": {},
        })
        spec = attach_agent1_contract_manifest(attach_tool_provenance(spec))
        validate_agent1_v4_spec_schema(spec)
        bad_pinout = json.loads(json.dumps(spec))
        bad_pinout["interfaces"]["apb_slave"]["signals"][0]["name"] = "psel"
        with self.assertRaisesRegex(ValueError, "exact locked APB"):
            validate_agent1_v4_spec_schema(bad_pinout)
        bad_reg = json.loads(json.dumps(spec))
        first_block = next(iter(bad_reg["memory_map"].values()))
        first_block["registers"] = {"bad": {"offset": "0x02", "width_bits": 7}}
        with self.assertRaisesRegex(ValueError, "offset must be 4-byte aligned"):
            validate_agent1_v4_spec_schema(bad_reg)

    def test_agent1_v41_proof_report_catches_overlap_bad_register_and_secret_readback(self):
        spec = generate_architecture_spec("AES-128 peripheral with secret key register 50MHz", "aes demo")
        spec.update({
            "firmware_contract": {"hal_modules": ["generic_hal"], "interrupt_flow": [], "register_access_semantics": {}},
            "io_packaging": {},
            "power_intent": {},
            "cdc_rdc_plan": {"reset_crossings": []},
            "interconnect_qos": {},
            "memory_hierarchy": {},
            "dft_plan": {},
            "safety_security": {},
            "ip_reuse_cost": {},
        })
        good = build_v41_proof_report(spec)
        self.assertTrue(good["pass"])
        bad = json.loads(json.dumps(spec))
        bad["memory_map"]["overlap_probe"] = {"base": bad["memory_map"]["aes128_core"]["base"], "size": "0x1000", "registers": {}}
        bad["memory_map"]["aes128_core"]["registers"]["key"]["readback"] = True
        bad["memory_map"]["aes128_core"]["registers"]["key"]["offset"] = "0x02"
        report = build_v41_proof_report(bad)
        self.assertFalse(report["pass"])
        failure_names = {failure["name"] for failure in report["failures"]}
        self.assertIn("aes128_core.key.offset_aligned", failure_names)
        self.assertIn("aes128_core.key.sensitive_no_readback", failure_names)
        self.assertTrue(any(name.endswith(".decode_disjoint") for name in failure_names))

    def test_agent1_v3_aes_register_security_feedback_loop(self):
        spec = generate_architecture_spec("AES-128 peripheral with secret key register 50MHz", "aes demo")
        self.assertIn("aes128_core", spec["memory_map"])
        key_reg = spec["memory_map"]["aes128_core"]["registers"]["key"]
        self.assertTrue(key_reg["sensitive"])
        self.assertEqual(key_reg["access"], "wo")
        self.assertEqual(spec["memory_map"]["aes128_core"]["registers"]["status"]["access"], "ro")
        self.assertFalse(key_reg.get("privileged", False))

    @patch("semiconductor_swarm.agents.agent1_planning.agent1_subgraph.call_agent1_codex")
    def test_agent1_v35_generates_systemrdl_firmware_and_cocotb_model(self, mock_codex):
        mock_codex.side_effect = _fake_agent1_v64_codex
        result = run_agent1_hierarchical_planning("Thiết kế lõi mã hóa phần cứng AES-128 APB. Phải có thanh ghi KEY (Write-Only), thanh ghi STATUS (Read-Only), 50MHz.", "aes128_core")
        artifacts = result["agent1_artifacts"]
        self.assertIn("reg key", artifacts["agent1_register_map.rdl"])
        self.assertIn("access=wo", artifacts["agent1_register_map.rdl"])
        self.assertIn("reg status", artifacts["agent1_register_map.rdl"])
        self.assertIn("access=ro", artifacts["agent1_register_map.rdl"])
        self.assertIn("#define AES128_CORE_AES128_CORE_KEY_OFFSET  0x00u", artifacts["fw_aes128_core_regs.h"])
        self.assertIn("void aes128_core_init(void)", artifacts["fw_aes128_core_driver_stub.c"])
        self.assertIn("self.aes128_core_key = Register", artifacts["tb_aes128_core_reg_model.py"])

    def test_agent1_v3_revision_limit_routes_to_hitl(self):
        decision = {"decision": "REJECT", "target_node": "Memory_Map_Interface_Expert", "max_revisions": 3}
        state = {"validation_decisions": [decision], "revision_counts": {"Memory_Map_Interface_Expert": 3}}
        self.assertEqual(route_validation_decision(state), "hitl_plan_review")

    def test_agent1_v3_reject_routes_to_exact_target_node(self):
        decision = {"decision": "REJECT", "target_node": "Clock_Power_Expert", "max_revisions": 3}
        state = {"validation_decisions": [decision], "revision_counts": {"Clock_Power_Expert": 1}}
        self.assertEqual(route_validation_decision(state), "Clock_Power_Expert")

    def test_agent1_v3_prompt_contains_full_super_committee_contract(self):
        for token in [
            "V3 Super Committee",
            "V3.5",
            "SystemRDL 2.0",
            "fw_<project_name>_regs.h",
            "tb_<project_name>_reg_model.py",
            "RDL_vs_CHeader_Validator",
            "RDL_vs_DVModel_Validator",
            "HW_SW_CoDesign_Expert",
            "Safety_Security_vs_MemoryMap_Validator",
            "ACCEPT|REJECT|HITL_REQUIRED",
            "Mandatory Peer Artifact Reads",
            "No Agent 2 RTL production before PLAN_REVIEW approval",
            "firmware_contract",
            "dft_plan",
            "ip_reuse_cost",
        ]:
            self.assertIn(token, AGENT1_SYSTEM_PROMPT)

    def test_agent1_v3_validation_graph_compiles_and_hits_hitl_on_revision_limit(self):
        app = build_agent1_v3_validation_graph()
        decision = {"decision": "REJECT", "target_node": "Memory_Map_Interface_Expert", "max_revisions": 3}
        state = {
            "requirement": "x",
            "project_name": "x",
            "codex_evidence": {},
            "artifacts": {},
            "spec_draft": {},
            "validation_decisions": [decision],
            "revision_counts": {"Memory_Map_Interface_Expert": 3},
            "next_node": None,
            "last_repaired_validator": None,
            "last_repaired_target": None,
            "hitl_required": False,
            "errors": [],
        }
        self.assertEqual(route_validation_decision(state), "hitl_plan_review")
        self.assertIsNotNone(app)

    def test_agent1_v3_accept_routes_next(self):
        state = {"validation_decisions": [{"decision": "ACCEPT", "target_node": None}], "revision_counts": {}}
        self.assertEqual(route_validation_decision(state), "next")

    def test_agent1_v36_repair_node_persists_repaired_spec_and_routes_back_to_validator(self):
        spec = generate_architecture_spec("AES-128 peripheral with secret key register 50MHz", "aes demo")
        decision = _validate_safety_security_memory_map(spec)
        self.assertEqual(decision["decision"], "REJECT")
        state = {
            "requirement": "aes",
            "project_name": "aes_demo",
            "codex_evidence": {},
            "artifacts": {},
            "spec_draft": spec,
            "validation_decisions": [decision],
            "revision_counts": {},
            "next_node": None,
            "last_repaired_validator": None,
            "last_repaired_target": None,
            "hitl_required": False,
            "errors": [],
        }
        updated = _repair_node(state)
        self.assertIsNot(updated["spec_draft"], spec)
        repaired_key = updated["spec_draft"]["memory_map"]["aes128_core"]["registers"]["key"]
        self.assertTrue(repaired_key["privileged"])
        self.assertEqual(updated["last_repaired_validator"], "Safety_Security_vs_MemoryMap_Validator")
        self.assertEqual(route_after_repair(updated), "Safety_Security_vs_MemoryMap_Validator")
        record = json.loads(updated["artifacts"]["agent1_revision_history.jsonl"].strip())
        self.assertEqual(record["route_back_to"], "Safety_Security_vs_MemoryMap_Validator")

    def test_agent1_v36_router_ignores_stale_reject_after_accept(self):
        state = {
            "validation_decisions": [
                {"validator": "Safety_Security_vs_MemoryMap_Validator", "decision": "REJECT", "target_node": "Memory_Map_Interface_Expert", "findings": [{"problem": "old"}]},
                {"validator": "Safety_Security_vs_MemoryMap_Validator", "decision": "ACCEPT", "target_node": None, "findings": []},
            ],
            "revision_counts": {},
        }
        updated = _router_node(state)
        self.assertEqual(updated["validation_decisions"][-1]["decision"], "ACCEPT")
        self.assertEqual(updated["next_node"], "next")

    def test_agent1_v36_memory_overlap_rejected(self):
        spec = {
            "memory_map": {
                "a": {"base": "0x40000000", "size": "0x1000", "registers": {}},
                "b": {"base": "0x40000800", "size": "0x1000", "registers": {}},
            }
        }
        decision = _validate_safety_security_memory_map(spec)
        self.assertEqual(decision["decision"], "REJECT")
        self.assertTrue(any(f["id"] == "MEM_RANGE_004" for f in decision["findings"]))

    def test_agent1_v36_memory_unaligned_base_rejected(self):
        spec = {"memory_map": {"a": {"base": "0x40000004", "size": "0x1000", "registers": {}}}}
        decision = _validate_safety_security_memory_map(spec)
        self.assertEqual(decision["decision"], "REJECT")
        self.assertTrue(any(f["id"] == "MEM_RANGE_003" for f in decision["findings"]))

    @patch("semiconductor_swarm.agents.agent1_planning.agent1_subgraph.call_agent1_codex", side_effect=RuntimeError("endpoint down"))
    def test_agent1_codex_is_mandatory(self, _mock_codex):
        with self.assertRaises(Agent1CodexUnavailable):
            run_agent1_hierarchical_planning("IoT AI camera chip <1W 100MHz", "edge_cam")

    def test_source_hygiene_has_no_iot_camera_default_outside_tests_and_historical_outputs(self):
        allowed_roots = {"tests", "generated_rtl", "generated_fpga", "generated_formal"}
        allowed_prefixes = ("%OUT%", "swarm_", "runs", "tmp_smoke")
        offenders = []
        for path in Path(".").rglob("*.py"):
            parts = set(path.parts)
            if parts & allowed_roots or any(str(path).startswith(prefix) for prefix in allowed_prefixes):
                continue
            if "iot_camera" in path.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(str(path))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
