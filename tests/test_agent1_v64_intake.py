import json
from unittest.mock import patch

from semiconductor_swarm.agents.agent1_planning.agent1_llm_client import Agent1CodexResult
from semiconductor_swarm.agents.agent1_planning.agent1_subgraph import run_agent1_hierarchical_planning
from semiconductor_swarm.agents.agent1_planning.intake_council import build_requirement_clarification_markdown, detect_technical_ambiguities, run_agent1_intake_council
from semiconductor_swarm.agents.agent1_planning.replay_cli import verify_agent1_v64_replay_output

def _intake_payload(requirement: str, classification: str = "DESIGN_READY") -> dict:
    text = requirement.lower()
    has_design_fixture = "tao chip ai camera" in text or "apb 100mhz" in text
    if not has_design_fixture and ("ban la ai" in text or "bạn là ai" in text or text.strip() == "hi"):
        return {
            "classification": "NON_DESIGN_CONVERSATION",
            "normalized_requirement": "",
            "canonical_intent": {
                "purpose": None,
                "cpu": None,
                "bus": None,
                "peripheral": None,
                "accelerator": None,
                "clock": None,
                "power": None,
                "node": None,
                "memory": None,
                "interrupts": None,
                "verification_scope": None,
                "custom_ip": None,
            },
            "extracted_intent": {},
            "missing_fields": ["chip purpose", "CPU/IP/peripheral intent", "bus/protocol", "clock or constraints"],
            "user_response": "I am Agent 1. Please provide a chip design requirement.",
            "brief_form": {"chip_purpose": "", "bus_protocol": "", "cpu_ip_peripheral": "", "clock": "", "power": "", "target_flow": ""},
            "citations": [{"source": "raw_requirement", "field": "non_design", "text": "ban la ai"}],
            "conflicts": [],
            "contradictions": [],
            "confidence": 0.95,
        }
    return {
        "classification": classification,
        "normalized_requirement": "Tao chip AI camera APB 100MHz",
        "canonical_intent": {
            "purpose": "AI camera chip",
            "cpu": None,
            "bus": {"protocol": "APB"},
            "peripheral": [],
            "accelerator": "int8_mac_array",
            "clock": {"frequency_mhz": 100},
            "power": None,
            "node": None,
            "memory": None,
            "interrupts": None,
            "verification_scope": "formal-first",
            "custom_ip": None,
        },
        "extracted_intent": {"accelerator": "AI camera", "bus": "APB", "clock": "100MHz"},
        "missing_fields": [],
        "user_response": "Design-ready requirement accepted.",
        "brief_form": {"chip_purpose": "AI camera chip", "bus_protocol": "APB", "cpu_ip_peripheral": "AI accelerator", "clock": "100MHz", "power": "", "target_flow": "formal-first"},
        "citations": [
            {"source": "raw_requirement", "field": "purpose", "text": "chip AI camera"},
            {"source": "raw_requirement", "field": "accelerator", "text": "AI camera"},
            {"source": "raw_requirement", "field": "bus", "text": "APB"},
            {"source": "raw_requirement", "field": "clock", "text": "100MHz"},
        ],
        "conflicts": [],
        "contradictions": [],
        "confidence": 0.92,
    }

def _council_payload() -> dict:
    return {
        "summary": "preserve intake requirement",
        "decisions": [{"decision": "preserve_intake"}],
        "assumptions": [],
        "open_questions": [],
        "risks": [],
        "conflicts": [],
        "citations": [{"source": "raw_requirement"}],
        "confidence": 0.9,
        "needs_revision": False,
        "selected_architecture_candidate": {"summary": "APB AI camera accelerator", "primary_protocol": "APB", "external_peripherals": []},
        "requirements_preserved": True,
        "plan_ready_candidate": True,
    }

def _fake_codex(prompt: str) -> Agent1CodexResult:
    evidence = {"base_url": "mock", "model": "mock", "timestamp": "2026-05-22T00:00:00+00:00", "total_tokens": 1}
    if "Agent 1 V6.4 Intake" in prompt or "Agent 1 V6.4 JSON Repair" in prompt or "Intake Adjudicator" in prompt:
        return Agent1CodexResult(content=json.dumps(_intake_payload(prompt)), evidence=evidence)
    return Agent1CodexResult(content=json.dumps(_council_payload()), evidence=evidence)

def test_v64_non_design_stops_after_real_intake_without_architecture():
    calls = []

    def fake(prompt: str) -> Agent1CodexResult:
        calls.append(prompt)
        return _fake_codex(prompt)

    with patch("semiconductor_swarm.agents.agent1_planning.agent1_subgraph.call_agent1_codex", side_effect=fake):
        result = run_agent1_hierarchical_planning("Hi, ban la ai", "cpu32bit_web", planning_mode="normal")

    assert len(calls) == 0
    assert result["requires_clarification"] is True
    assert result["intake_report"]["classification"] == "NON_DESIGN_CONVERSATION"
    assert result["intake_report"]["codex_call_count"] == 0
    assert result["intake_report"]["token_usage"]["total_tokens"] == 0
    assert "spec" not in result
    assert "architecture_plan.md" not in result["agent1_artifacts"]
    assert "agent1_requirement_clarification.md" in result["agent1_artifacts"]
    assert "agent1_clarification_options.json" in result["agent1_artifacts"]
    assert result["clarification_questions"]
    assert result["clarification_questions"][0]["options"]
    assert result["intake_report"]["canonical_intent"]["accelerator"] is None

def test_v64_vietnamese_identity_question_uses_zero_codex_calls():
    def fail_if_called(_prompt: str) -> Agent1CodexResult:
        raise AssertionError("Codex must not be called for pure identity chat.")

    with patch("semiconductor_swarm.agents.agent1_planning.agent1_subgraph.call_agent1_codex", side_effect=fail_if_called):
        result = run_agent1_hierarchical_planning("Bạn là ai", "yesys", planning_mode="normal")

    report = result["intake_report"]
    assert result["requires_clarification"] is True
    assert report["classification"] == "NON_DESIGN_CONVERSATION"
    assert report["codex_call_count"] == 0
    assert report["codex_evidence"]["experts"] == []
    assert report["ready_for_council"] is False
    assert "architecture_plan.md" not in result["agent1_artifacts"]

def test_v64_vietnamese_age_question_uses_zero_codex_calls():
    def fail_if_called(_prompt: str) -> Agent1CodexResult:
        raise AssertionError("Codex must not be called for pure age chat.")

    with patch("semiconductor_swarm.agents.agent1_planning.agent1_subgraph.call_agent1_codex", side_effect=fail_if_called):
        result = run_agent1_hierarchical_planning("Bạn mấy tuổi", "va", planning_mode="normal")

    report = result["intake_report"]
    assert result["requires_clarification"] is True
    assert report["classification"] == "NON_DESIGN_CONVERSATION"
    assert report["codex_call_count"] == 0
    assert report["token_usage"]["total_tokens"] == 0
    assert "không có tuổi" in report["user_response"]
    assert "architecture_plan.md" not in result["agent1_artifacts"]

def test_v64_design_ready_runs_intake_plus_v71_group_session_nodes_and_writes_policy_artifacts():
    calls = []

    def fake(prompt: str) -> Agent1CodexResult:
        calls.append(prompt)
        return _fake_codex(prompt)

    with patch("semiconductor_swarm.agents.agent1_planning.agent1_subgraph.call_agent1_codex", side_effect=fake):
        result = run_agent1_hierarchical_planning("Tao chip AI camera APB 100MHz", "ai_cam", planning_mode="normal")

    assert len(calls) == 15
    assert result["report"]["intake_router"]["classification"] == "DESIGN_READY"
    assert result["report"]["v51_council"]["iteration_count"] == 1
    assert result["spec"]["accelerator"]["type"] == "int8_mac_array"
    for name in ("agent1_intake_router_report.json", "agent1_requirement_citation_ledger.json", "agent1_policy_matrix.json", "agent1_prompt_pack_manifest.json"):
        assert name in result["agent1_artifacts"]

def test_v64_contradictory_bus_requirement_blocks_council():
    calls = []

    def fake(prompt: str) -> Agent1CodexResult:
        calls.append(prompt)
        return _fake_codex(prompt)

    with patch("semiconductor_swarm.agents.agent1_planning.agent1_subgraph.call_agent1_codex", side_effect=fake):
        result = run_agent1_hierarchical_planning("Tao chip AI camera APB only but AXI bus 100MHz", "ai_cam", planning_mode="normal")

    assert len(calls) == 6
    assert result["requires_clarification"] is True
    assert result["intake_report"]["classification"] == "DESIGN_NEEDS_CLARIFICATION"
    assert result["intake_report"]["contradictions"]

def test_v64_intake_invalid_json_gets_one_repair_retry():
    calls = []

    def fake(prompt: str) -> Agent1CodexResult:
        calls.append(prompt)
        evidence = {"base_url": "mock", "model": "mock", "timestamp": "2026-05-22T00:00:00+00:00"}
        if len(calls) == 1:
            return Agent1CodexResult(content="not json", evidence=evidence)
        return Agent1CodexResult(content=json.dumps(_intake_payload("Tao chip AI camera APB 100MHz")), evidence=evidence)

    report = run_agent1_intake_council("Tao chip AI camera APB 100MHz", "ai_cam", fake)

    assert len(calls) == 7
    first = report["codex_evidence"]["experts"][0]
    assert first["repair_attempted"] is True
    assert first["repair_pass"] is True
    assert report["ready_for_council"] is True

def test_v64_mixed_identity_question_with_uart_requirement_stays_design_ready():
    payload = {
        "classification": "DESIGN_READY",
        "normalized_requirement": "ban la ai, tao UART APB controller 50MHz",
        "canonical_intent": {
            "purpose": "UART APB controller",
            "cpu": None,
            "bus": {"protocol": "APB"},
            "peripheral": ["uart"],
            "accelerator": None,
            "clock": {"frequency_mhz": 50},
            "power": None,
            "node": None,
            "memory": None,
            "interrupts": {"uart_irq": True},
            "verification_scope": "formal-first",
            "custom_ip": "uart_apb_controller",
        },
        "extracted_intent": {},
        "missing_fields": [],
        "user_response": "Design-ready requirement accepted.",
        "brief_form": {"chip_purpose": "UART APB controller", "bus_protocol": "APB", "cpu_ip_peripheral": "uart_apb_controller", "clock": "50MHz", "power": "", "target_flow": "formal-first"},
        "citations": [
            {"source": "raw_requirement", "field": "purpose", "text": "UART APB controller"},
            {"source": "raw_requirement", "field": "bus", "text": "APB"},
            {"source": "raw_requirement", "field": "peripheral", "text": "uart"},
            {"source": "raw_requirement", "field": "custom_ip", "text": "uart_apb_controller"},
            {"source": "raw_requirement", "field": "clock", "text": "50MHz"},
        ],
        "conflicts": [],
        "contradictions": [],
        "confidence": 0.92,
    }

    def fake(_prompt: str) -> Agent1CodexResult:
        return Agent1CodexResult(content=json.dumps(payload), evidence={"base_url": "mock", "model": "mock", "timestamp": "2026-05-22T00:00:00+00:00", "total_tokens": 1})

    report = run_agent1_intake_council("ban la ai, tao UART APB controller 50MHz", "mixed_uart", fake)

    assert report["classification"] == "DESIGN_READY"
    assert report["ready_for_council"] is True
    assert report["codex_call_count"] == 0
    assert report["fast_path"]["kind"] == "DESIGN_READY_SIMPLE_IP"
    assert report["canonical_intent"]["custom_ip"] == "uart_apb_controller"

def test_v64_mixed_age_question_with_uart_requirement_stays_design_ready():
    calls = []
    payload = {
        "classification": "DESIGN_READY",
        "normalized_requirement": "ban may tuoi, tao UART APB controller 50MHz",
        "canonical_intent": {
            "purpose": "UART APB controller",
            "cpu": None,
            "bus": {"protocol": "APB"},
            "peripheral": ["uart"],
            "accelerator": None,
            "clock": {"frequency_mhz": 50},
            "power": None,
            "node": None,
            "memory": None,
            "interrupts": {"uart_irq": True},
            "verification_scope": "formal-first",
            "custom_ip": "uart_apb_controller",
        },
        "extracted_intent": {},
        "missing_fields": [],
        "user_response": "Design-ready requirement accepted.",
        "brief_form": {"chip_purpose": "UART APB controller", "bus_protocol": "APB", "cpu_ip_peripheral": "uart_apb_controller", "clock": "50MHz", "power": "", "target_flow": "formal-first"},
        "citations": [
            {"source": "raw_requirement", "field": "purpose", "text": "UART APB controller"},
            {"source": "raw_requirement", "field": "bus", "text": "APB"},
            {"source": "raw_requirement", "field": "peripheral", "text": "uart"},
            {"source": "raw_requirement", "field": "custom_ip", "text": "uart_apb_controller"},
            {"source": "raw_requirement", "field": "clock", "text": "50MHz"},
        ],
        "conflicts": [],
        "contradictions": [],
        "confidence": 0.92,
    }

    def fake(_prompt: str) -> Agent1CodexResult:
        calls.append(_prompt)
        return Agent1CodexResult(content=json.dumps(payload), evidence={"base_url": "mock", "model": "mock", "timestamp": "2026-05-22T00:00:00+00:00", "total_tokens": 1})

    report = run_agent1_intake_council("ban may tuoi, tao UART APB controller 50MHz", "mixed_age_uart", fake)

    assert len(calls) == 0
    assert report["classification"] == "DESIGN_READY"
    assert report["ready_for_council"] is True
    assert report["codex_call_count"] == 0
    assert report["fast_path"]["kind"] == "DESIGN_READY_SIMPLE_IP"
    assert report["canonical_intent"]["custom_ip"] == "uart_apb_controller"

def test_v71_cpu_apb_uart_schema_variants_preserve_intent_but_block_missing_fields():
    payloads = [
        {
            "classification": "DESIGN_READY",
            "normalized_requirement": "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
            "canonical_intent": {
                "cpu": {"architecture_width_bits": 32},
                "bus": {"type": "APB"},
                "external_peripherals": ["UART"],
                "memory": {"interface": "unspecified", "size": "unspecified"},
                "node": {"technology": "unspecified"},
                "power": {"power_budget": "unspecified"},
            },
            "extracted_intent": {"artifact": "CPU architecture", "cpu_width_bits": 32, "bus": "APB", "external_peripheral": "UART"},
            "missing_fields": ["clock", "node", "power"],
            "user_response": "Design-ready requirement accepted with defaults.",
            "brief_form": {"chip_purpose": "CPU architecture", "bus_protocol": "APB", "cpu_ip_peripheral": "32-bit CPU + UART", "clock": "", "power": "", "target_flow": ""},
            "citations": [
                {"source": "raw_requirement", "field": "cpu", "text": "32-bit CPU"},
                {"source": "raw_requirement", "field": "bus", "text": "APB bus"},
                {"source": "raw_requirement", "field": "peripheral", "text": "UART"},
            ],
            "conflicts": [],
            "contradictions": [],
            "confidence": 0.92,
        }
    ]

    def fake(_prompt: str) -> Agent1CodexResult:
        payload = payloads[0]
        return Agent1CodexResult(content=json.dumps(payload), evidence={"base_url": "mock", "model": "mock", "timestamp": "2026-05-22T00:00:00+00:00", "total_tokens": 1})

    report = run_agent1_intake_council(
        "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
        "cpu32bit_web",
        fake,
    )

    assert report["classification"] == "DESIGN_NEEDS_CLARIFICATION"
    assert report["ready_for_council"] is False
    assert report["canonical_intent"]["cpu"]["width_bits"] == 32
    assert report["canonical_intent"]["cpu"]["isa"] == "rv32imc"
    assert report["canonical_intent"]["bus"]["protocol"] == "APB"
    assert report["canonical_intent"]["peripheral"] == ["uart"]
    assert report["canonical_intent"]["clock"]["frequency_mhz"] == 50
    assert report["canonical_intent"]["node"] == "28nm"
    assert report["canonical_intent"]["memory"] == {"rom": "boot_rom", "sram": "single_port_sram", "cache": "none"}
    assert report["defaulted_fields"]
    assert {"clock", "node", "power"}.issubset(set(report["missing_fields"]))
    assert report["blocking_missing_fields"] == []

def test_v65_raw_design_rescues_non_design_adjudicator_misroute():
    payload = {
        "classification": "NON_DESIGN_CONVERSATION",
        "normalized_requirement": "",
        "canonical_intent": {
            "purpose": None,
            "cpu": None,
            "bus": None,
            "peripheral": None,
            "accelerator": None,
            "clock": None,
            "power": None,
            "node": None,
            "memory": None,
            "interrupts": None,
            "verification_scope": None,
            "custom_ip": None,
        },
        "extracted_intent": {},
        "missing_fields": ["chip purpose", "CPU/IP/peripheral intent"],
        "user_response": "Agent 1 needs a chip design requirement before architecture planning.",
        "brief_form": {"chip_purpose": "", "bus_protocol": "", "cpu_ip_peripheral": "", "clock": "", "power": "", "target_flow": ""},
        "citations": [{"source": "raw_requirement", "field": "non_design", "text": "Project label: cpu32bit_web"}],
        "conflicts": [],
        "contradictions": [],
        "confidence": 0.9,
    }

    def fake(_prompt: str) -> Agent1CodexResult:
        return Agent1CodexResult(content=json.dumps(payload), evidence={"base_url": "mock", "model": "mock", "timestamp": "2026-05-22T00:00:00+00:00", "total_tokens": 1})

    report = run_agent1_intake_council(
        "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
        "cpu32bit_web",
        fake,
    )

    assert report["classification"] == "DESIGN_READY"
    assert report["ready_for_council"] is True
    assert report["canonical_intent"]["cpu"]["width_bits"] == 32
    assert report["canonical_intent"]["bus"]["protocol"] == "APB"
    assert report["canonical_intent"]["peripheral"] == ["uart"]
    assert "chip design requirement" not in report["user_response"]
    assert all("Project label:" not in str(item.get("text", "")) for item in report["citations"])

def test_v65_project_label_and_prompt_instruction_citations_are_quarantined():
    payload = {
        "classification": "DESIGN_READY",
        "normalized_requirement": "make a simple CPU",
        "canonical_intent": {"artifact": "CPU architecture"},
        "extracted_intent": {"cpu": "simple CPU"},
        "missing_fields": [],
        "user_response": "Design-ready.",
        "brief_form": {"chip_purpose": "CPU architecture", "bus_protocol": "", "cpu_ip_peripheral": "CPU", "clock": "", "power": "", "target_flow": ""},
        "citations": [
            {"source": "raw_requirement", "field": "purpose", "text": "Project label: simple_cpu"},
            {"source": "raw_requirement", "field": "cpu", "text": "Extract explicit CPU, bus, IP, clock, power, node, memory, and unknowns."},
            {"source": "raw_requirement", "field": "cpu", "text": "simple CPU"},
            {"source": "project_name", "field": "purpose", "text": "simple_cpu"},
        ],
        "conflicts": [],
        "contradictions": [],
        "confidence": 0.92,
    }

    def fake(_prompt: str) -> Agent1CodexResult:
        return Agent1CodexResult(content=json.dumps(payload), evidence={"base_url": "mock", "model": "mock", "timestamp": "2026-05-22T00:00:00+00:00", "total_tokens": 1})

    report = run_agent1_intake_council("make a simple CPU", "simple_cpu", fake)

    citation_text = "\n".join(str(item.get("text", "")) for item in report["citations"])
    assert "Project label:" not in citation_text
    assert "Extract explicit CPU" not in citation_text
    assert "simple CPU" in citation_text
    assert report["policy_matrix"]["pass"] is True

def test_v71_simple_cpu_uses_safe_defaults_but_asks_for_missing_release_fields():
    payload = {
        "classification": "DESIGN_NEEDS_CLARIFICATION",
        "normalized_requirement": "make a simple CPU",
        "canonical_intent": {"artifact": "CPU architecture"},
        "extracted_intent": {"cpu": "simple CPU"},
        "missing_fields": ["bus/protocol", "clock", "node"],
        "user_response": "Need details.",
        "brief_form": {"chip_purpose": "CPU architecture", "bus_protocol": "", "cpu_ip_peripheral": "CPU", "clock": "", "power": "", "target_flow": ""},
        "citations": [{"source": "raw_requirement", "field": "cpu", "text": "simple CPU"}],
        "conflicts": [],
        "contradictions": [],
        "confidence": 0.72,
    }

    def fake(_prompt: str) -> Agent1CodexResult:
        return Agent1CodexResult(content=json.dumps(payload), evidence={"base_url": "mock", "model": "mock", "timestamp": "2026-05-22T00:00:00+00:00", "total_tokens": 1})

    report = run_agent1_intake_council("make a simple CPU", "simple_cpu", fake)

    assert report["classification"] == "DESIGN_NEEDS_CLARIFICATION"
    assert report["ready_for_council"] is False
    assert report["canonical_intent"]["cpu"]["width_bits"] == 32
    assert report["canonical_intent"]["bus"]["protocol"] == "APB"
    assert {"bus/protocol", "clock", "node"}.issubset(set(report["missing_fields"]))

def test_v65_contradiction_still_blocks_even_with_detected_design_intent():
    payload = {
        "classification": "DESIGN_READY",
        "normalized_requirement": "APB only but AXI bus 100MHz",
        "canonical_intent": {"bus": "APB"},
        "extracted_intent": {"bus": "APB and AXI"},
        "missing_fields": [],
        "user_response": "Design-ready.",
        "brief_form": {"chip_purpose": "", "bus_protocol": "APB", "cpu_ip_peripheral": "", "clock": "100MHz", "power": "", "target_flow": ""},
        "citations": [{"source": "raw_requirement", "field": "bus", "text": "APB only but AXI bus"}],
        "conflicts": [],
        "contradictions": [],
        "confidence": 0.8,
    }

    def fake(_prompt: str) -> Agent1CodexResult:
        return Agent1CodexResult(content=json.dumps(payload), evidence={"base_url": "mock", "model": "mock", "timestamp": "2026-05-22T00:00:00+00:00", "total_tokens": 1})

    report = run_agent1_intake_council("APB only but AXI bus 100MHz", "bad_bus", fake)

    assert report["classification"] == "DESIGN_NEEDS_CLARIFICATION"
    assert report["ready_for_council"] is False
    assert report["contradictions"]

def test_v73_multi_peripheral_no_cpu_requirement_uses_zero_codex_fast_path():
    requirement = (
        "Design a release-ready APB multi-peripheral subsystem at 75MHz for FPGA-safe generic RTL. "
        "No CPU core. Use one external APB host, 32-bit data, active-low synchronous reset, 28nm planning target. "
        "Include exactly these IP blocks: UART with baud_div and IRQ, SPI master with mode0-3 and 4 chip selects, "
        "I2C controller for 100kHz/400kHz with IRQ, 32-bit GPIO with direction/data/interrupt registers, "
        "timer/watchdog with timeout IRQ. Formal-first SVA plus cocotb, no UVM. "
        "Generate clean Agent1 plan, locked APB register map, and Agent2-ready handoff. "
        "Do not invent extra CPU, DMA, cache, or interrupt controller unless required and justified."
    )

    def fail_if_called(_prompt: str) -> Agent1CodexResult:
        raise AssertionError("Codex must not be called for complete APB peripheral-only subsystem.")

    with patch("semiconductor_swarm.agents.agent1_planning.agent1_subgraph.call_agent1_codex", side_effect=fail_if_called):
        result = run_agent1_hierarchical_planning(requirement, "apb_peripheral_fast", planning_mode="normal")

    report = result["report"]["intake_router"]
    spec = result["spec"]
    assert report["classification"] == "DESIGN_READY"
    assert report["codex_call_count"] == 0
    assert report["fast_path"]["kind"] == "DESIGN_READY_SIMPLE_IP"
    assert set(report["fast_path"]["peripherals"]) == {"uart", "spi", "i2c", "gpio", "timer"}
    assert spec["requirements"]["cpu_requested"] is False
    assert spec["cpu_subsystem"]["synthesized_cpu"] is False
    assert spec["bus_topology"]["masters"] == ["external_apb_host"]
    assert {block["name"] for block in spec["ip_blocks"]} == {"uart", "spi", "i2c", "gpio", "timer"}
    assert set(spec["memory_map"]["gpio"]["registers"]) >= {"data_in", "data_out", "direction", "irq_status", "irq_enable"}
    assert set(spec["memory_map"]["timer"]["registers"]) >= {"ctrl", "load", "value", "watchdog", "irq_status", "irq_enable"}
    assert "interrupt_ctrl" not in spec["memory_map"]

def test_v73_cpu_soc_request_still_uses_council_not_simple_fast_path():
    calls = []

    def fake(prompt: str) -> Agent1CodexResult:
        calls.append(prompt)
        return _fake_codex(prompt)

    report = run_agent1_intake_council(
        "Design an RV32IMC microcontroller SoC with APB UART at 100MHz.",
        "rv32_soc",
        fake,
    )

    assert report["codex_call_count"] > 0
    assert "fast_path" not in report

def test_v64_replay_verifies_hashes_without_codex_and_blocks_missing_versions(tmp_path):
    output_dir = tmp_path / "run"
    agent1 = output_dir / "reports" / "agent1"
    agent1.mkdir(parents=True)
    (agent1 / "agent1_intake_router_report.json").write_text(json.dumps({"schema_version": "agent1.intake_router_report.v1"}), encoding="utf-8")
    (agent1 / "agent1_requirement_citation_ledger.json").write_text(json.dumps({"schema_version": "agent1.requirement_citation_ledger.v1"}), encoding="utf-8")
    (agent1 / "agent1_policy_matrix.json").write_text(json.dumps({"schema_version": "agent1.policy_matrix.v1"}), encoding="utf-8")
    (agent1 / "agent1_prompt_pack_manifest.json").write_text(json.dumps({"schema_version": "agent1.prompt_pack_manifest.v1"}), encoding="utf-8")

    ok = verify_agent1_v64_replay_output(output_dir)
    (agent1 / "agent1_policy_matrix.json").write_text(json.dumps({"schema_version": "wrong"}), encoding="utf-8")
    bad = verify_agent1_v64_replay_output(output_dir)

    assert ok["pass"] is True
    assert ok["codex_calls"] == 0
    assert ok["signoff_claimed"] is False
    assert bad["pass"] is False
    assert bad["signoff_claimed"] is False
    assert any(item.startswith("schema_version_mismatch") for item in bad["failures"])

def test_v71_clarification_markdown_enriches_security_missing_fields():
    markdown = build_requirement_clarification_markdown(
        {
            "classification": "DESIGN_NEEDS_CLARIFICATION",
            "consensus_score": 0.68,
            "calibrated_confidence": 0.65,
            "raw_requirement": "Add crypto, secure boot, OTP, and side-channel protection.",
            "canonical_intent": {"purpose": "secure root-of-trust controller", "custom_ip": "security_subsystem"},
            "missing_fields": [{"field": "CPU/IP/peripheral/accelerator intent"}],
            "user_response": "Need security details before release.",
            "brief_form": {"chip_purpose": "secure root-of-trust controller"},
            "policy_matrix": {"policies": []},
        }
    )

    assert "## Clarification Checklist" in markdown
    for needle in (
        "security threat model",
        "crypto accelerator algorithm suite and key management",
        "OTP/eFuse provisioning and lifecycle state flow",
        "secure debug/tamper response policy",
        "side-channel leakage model",
        "clock/reset and protected register access policy",
    ):
        assert needle in markdown

def test_v74_infra_hitl_clarification_suppresses_unrelated_domain_noise():
    markdown = build_requirement_clarification_markdown(
        {
            "classification": "DESIGN_NEEDS_CLARIFICATION",
            "action_required": "HITL_REQUIRED",
            "hitl_reason": "agent1_council_infra_hard_stop",
            "consensus_score": 0.56,
            "calibrated_confidence": 0.75,
            "raw_requirement": "RV32IMC SoC with APB4, UART, SPI, I2C, GPIO, watchdog, formal-first SVA and cocotb.",
            "canonical_intent": {
                "purpose": "CPU architecture",
                "cpu": {"isa": "RV32IMC", "width_bits": 32},
                "bus": {"protocol": "APB4"},
                "peripheral": ["uart", "spi", "i2c", "gpio", "watchdog"],
                "clock": {"frequency_mhz": 50},
                "node": "FPGA",
                "verification_scope": ["formal-first SVA", "cocotb"],
            },
            "missing_fields": [
                "security threat model",
                "crypto accelerator algorithm suite and key management",
                "Ethernet speed",
                "target workload/model type",
            ],
            "user_response": "Agent 1 deep council hit the infrastructure hard-stop threshold.",
            "policy_matrix": {"policies": [{"policy_id": "P-A1-007", "status": "fail", "failure_reason": "Agent 1 council status is HITL_REQUIRED."}]},
        }
    )

    assert "fix Agent 1 council model/API reliability before Agent2 handoff" in markdown
    assert "Open Debug > Raw Issues" in markdown
    assert "power budget or power intent" in markdown
    for noisy in ("security threat model", "crypto accelerator", "Ethernet speed", "target workload/model type"):
        assert noisy not in markdown

def test_v78_detects_adc_width_and_irq_ambiguity_questions():
    requirement = "Deep Planning mixed-signal monitor with ADC 12-bit or 16-bit samples; IRQ polarity unspecified; reset unclear."

    ambiguities = detect_technical_ambiguities(requirement)
    ids = {item["id"] for item in ambiguities}
    markdown = build_requirement_clarification_markdown(
        {
            "classification": "DESIGN_NEEDS_CLARIFICATION",
            "action_required": "HITL_REQUIRED",
            "hitl_reason": "agent1_council_infra_hard_stop",
            "consensus_score": 0.7,
            "calibrated_confidence": 0.7,
            "raw_requirement": requirement,
            "canonical_intent": {"purpose": "mixed-signal monitor", "custom_ip": "adc_monitor"},
            "missing_fields": ["fix Agent 1 council model/API reliability before Agent2 handoff"],
            "technical_ambiguities": ambiguities,
            "user_response": "Agent 1 deep council hit the infrastructure hard-stop threshold.",
            "policy_matrix": {"policies": []},
        }
    )

    assert {"adc_resolution_conflict", "irq_polarity_type_missing", "reset_policy_missing"} <= ids
    assert "Questions To Answer Now" in markdown
    assert "Choose one ADC sample width" in markdown
    assert "Confirm IRQ type and polarity" in markdown
    assert "Infrastructure Problem" in markdown
    assert "Debug Next Steps" in markdown

def test_v78_deep_blocks_agent2_on_unanswered_technical_ambiguity():
    requirement = (
        "Design an APB ADC monitor IP at 50MHz. ADC can be 12-bit or 16-bit. "
        "IRQ polarity unspecified and reset unclear. Formal-first SVA plus cocotb."
    )
    payload = {
        "classification": "DESIGN_READY",
        "normalized_requirement": requirement,
        "canonical_intent": {
            "purpose": "ADC monitor IP",
            "custom_ip": "adc_monitor",
            "bus": "APB",
            "clock": "50MHz",
            "verification_scope": ["formal-first SVA", "cocotb"],
        },
        "extracted_intent": {"bus": "APB", "custom_ip": "adc_monitor"},
        "missing_fields": [],
        "user_response": "Ready.",
        "brief_form": {},
        "citations": [{"source": "raw_requirement", "field": "bus", "text": "APB"}],
        "conflicts": [],
        "contradictions": [],
        "confidence": 0.9,
    }
    calls = []

    def fake(prompt: str) -> Agent1CodexResult:
        calls.append(prompt)
        return Agent1CodexResult(json.dumps(payload), {"model": "mock", "total_tokens": 1})

    with patch("semiconductor_swarm.agents.agent1_planning.agent1_subgraph.call_agent1_codex", side_effect=fake):
        result = run_agent1_hierarchical_planning(requirement, "adc_monitor", planning_mode="deep_planning")

    assert result["requires_clarification"] is True
    assert result["report"]["intake_router"]["hitl_reason"] == "agent1_technical_ambiguity"
    assert "agent1_clarification_options.json" in result["agent1_artifacts"]
    options = json.loads(result["agent1_artifacts"]["agent1_clarification_options.json"])
    codes = {item["code"] for item in options["questions"]}
    assert {"adc_resolution_conflict", "irq_polarity_type_missing", "reset_policy_missing"} <= codes
    assert not any("Agent 1 V5.1" in prompt or "Cluster Council" in prompt for prompt in calls)
