import unittest
import importlib.util
import json
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from semiconductor_swarm.agents.agent1_planning.agent1_llm_client import Agent1CodexResult

LANGGRAPH_AVAILABLE = importlib.util.find_spec("langgraph") is not None
pytestmark = pytest.mark.skipif(not LANGGRAPH_AVAILABLE, reason="langgraph is not installed")

if LANGGRAPH_AVAILABLE:
    from langgraph.types import Command

    from main import _ensure_resume_checkpoint
    from semiconductor_swarm.swarm_graph import build_swarm_graph, rtl_lint_gate, rtl_lint_node, agent2_syntax_linter_node, write_outputs
else:
    Command = None


def test_rtl_lint_gate_routes_pass_to_formal():
    state = {"reports": {"agent2": {"pass": True}}, "debug_iterations": 0, "max_debug_iterations": 5}
    assert rtl_lint_gate(state) == "agent5_formal"


def test_rtl_lint_gate_routes_fail_to_auto_debug():
    state = {"reports": {"agent2": {"pass": False}}, "debug_iterations": 0, "max_debug_iterations": 5}
    assert rtl_lint_gate(state) == "auto_debug_agent2"


def test_agent2_syntax_linter_node_symbol_exists_for_upgrade_plan():
    assert callable(agent2_syntax_linter_node)


def _intake_payload_for_prompt(prompt: str) -> dict:
    text = prompt.lower()
    ontology = {
        "purpose": "AI camera chip",
        "cpu": None,
        "bus": {"protocol": "APB"},
        "peripheral": [],
        "accelerator": "int8_mac_array",
        "clock": {"frequency_mhz": 100},
        "power": "<1W",
        "node": None,
        "memory": None,
        "interrupts": None,
        "verification_scope": "formal-first",
        "custom_ip": None,
    }
    normalized = "IoT AI camera chip APB <1W 100MHz"
    classification = "DESIGN_READY"
    missing = []
    if "spi" in text:
        ontology.update({"purpose": "SPI controller", "peripheral": ["spi"], "accelerator": None, "clock": {"frequency_mhz": 50}})
        normalized = "SPI controller APB 50MHz"
    if "temperature" in text or "thermal" in text:
        ontology.update({"purpose": "temperature monitor", "accelerator": None, "custom_ip": "temperature_monitor", "clock": {"frequency_mhz": 50}})
        normalized = "temperature monitor APB 50MHz"
    if ("con chip ai" in text or "chip ai" in text) and "100mhz" not in text:
        classification = "DESIGN_NEEDS_CLARIFICATION"
        missing = ["clock", "power", "bus/protocol"]
    if "hi" in text and "chip" not in text:
        classification = "NON_DESIGN_CONVERSATION"
        normalized = ""
        ontology = {key: None for key in ontology}
        missing = ["chip purpose", "CPU/IP/peripheral intent", "bus/protocol", "clock"]
    clock = ontology.get("clock") if isinstance(ontology.get("clock"), dict) else {}
    return {
        "classification": classification,
        "normalized_requirement": normalized,
        "canonical_intent": ontology,
        "extracted_intent": ontology,
        "missing_fields": missing,
        "user_response": "Agent 1 needs more chip details." if missing else "Design-ready requirement accepted.",
        "brief_form": {"chip_purpose": ontology.get("purpose") or "", "bus_protocol": "APB", "cpu_ip_peripheral": ontology.get("custom_ip") or ontology.get("accelerator") or ontology.get("peripheral"), "clock": ontology.get("clock"), "power": ontology.get("power"), "target_flow": "formal-first"},
        "citations": [
            {"source": "raw_requirement", "field": "purpose", "text": str(ontology.get("purpose"))},
            {"source": "raw_requirement", "field": "bus", "text": "APB"},
            {"source": "raw_requirement", "field": "clock", "text": "100MHz" if clock.get("frequency_mhz") == 100 else "50MHz"},
            {"source": "raw_requirement", "field": "power", "text": str(ontology.get("power"))},
            {"source": "raw_requirement", "field": "accelerator", "text": str(ontology.get("accelerator") or ontology.get("custom_ip") or ontology.get("peripheral"))},
            {"source": "raw_requirement", "field": "peripheral", "text": str(ontology.get("peripheral"))},
            {"source": "raw_requirement", "field": "custom_ip", "text": str(ontology.get("custom_ip"))},
        ],
        "conflicts": [],
        "contradictions": [],
        "confidence": 0.9,
    }

def _council_payload() -> dict:
    return {
        "summary": "council ok",
        "decisions": [{"decision": "preserve_requirement"}],
        "assumptions": [],
        "open_questions": [],
        "risks": [],
        "conflicts": [],
        "citations": [{"source": "raw_requirement"}],
        "confidence": 0.9,
        "needs_revision": False,
        "selected_architecture_candidate": {"summary": "APB candidate", "primary_protocol": "APB", "external_peripherals": []},
        "requirements_preserved": True,
        "plan_ready_candidate": True,
    }

def MOCK_CODEX_RESPONSE(prompt: str) -> Agent1CodexResult:
    evidence = {"base_url": "http://localhost:20128/v1", "model": "cx/gpt-5.5", "timestamp": "2026-05-14T00:00:00+00:00", "status": "mocked", "total_tokens": 1}
    if "Agent 1 V6.4 Intake" in prompt or "Agent 1 V6.4 JSON Repair" in prompt or "Intake Adjudicator" in prompt:
        return Agent1CodexResult(content=json.dumps(_intake_payload_for_prompt(prompt)), evidence=evidence)
    return Agent1CodexResult(content=json.dumps(_council_payload()), evidence=evidence)


class TestLangGraphSwarm(unittest.TestCase):
    def setUp(self):
        patcher = patch("semiconductor_swarm.agents.agent1_planning.agent1_subgraph.call_agent1_codex", side_effect=MOCK_CODEX_RESPONSE)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_graph_interrupts_for_human_review_then_resumes(self):
        app = build_swarm_graph()
        config = {"configurable": {"thread_id": "test-hitl"}}
        with tempfile.TemporaryDirectory() as tmp:
            paused = app.invoke({"requirement": "IoT AI camera chip <1W 100MHz", "project_name": "iot_camera", "output_dir": tmp, "reports": {}}, config=config)

            self.assertIn("__interrupt__", paused)
            payload = paused["__interrupt__"][0].value
            self.assertEqual(payload["action_required"], "PLAN_REVIEW")
            self.assertTrue((__import__("pathlib").Path(tmp) / "reports" / "architecture_plan.md").is_file())
            self.assertTrue((__import__("pathlib").Path(tmp) / "status.log").is_file())

            paused2 = app.invoke(Command(resume={"response": "ok"}), config=config)
            self.assertIn("__interrupt__", paused2)
            payload2 = paused2["__interrupt__"][0].value
            self.assertEqual(payload2["action_required"], "HUMAN_REVIEW")
            self.assertTrue(payload2["rtl_files"])
            self.assertTrue(payload2["formal_files"])

            done = app.invoke(Command(resume={"approved": True, "reviewer": "unit-test", "notes": "ok"}), config=config)
            self.assertEqual(done["status"], "SIGNOFF_READY")
            self.assertTrue(done["hitl_approved"])
            self.assertIn("agent3", done["reports"])
            self.assertIn("agent4", done["reports"])
            self.assertIn("contract_envelopes", done)
            envelopes = done["contract_envelopes"]
            for key, producer, consumer in [
                ("agent1_to_agent2", "agent1", "agent2"),
                ("agent2_to_agent3_contract", "agent2", "agent3"),
                ("agent2_to_agent4_contract", "agent2", "agent4"),
                ("agent2_to_agent5_contract", "agent2", "agent5"),
            ]:
                self.assertIn(key, envelopes)
                self.assertEqual(envelopes[key]["producer"], producer)
                self.assertEqual(envelopes[key]["consumer"], consumer)
                self.assertTrue(envelopes[key]["contract_version"])
                self.assertIsInstance(envelopes[key]["payload"], dict)

    def test_cli_resume_preflight_rejects_missing_checkpoint(self):
        class EmptyCheckpointApp:
            def get_state(self, config):
                return SimpleNamespace(values={}, next=())

        with self.assertRaises(SystemExit) as ctx:
            _ensure_resume_checkpoint(EmptyCheckpointApp(), {"configurable": {"thread_id": "missing"}}, "missing", "tmp.sqlite")
        self.assertIn("Resume error: no paused checkpoint found", str(ctx.exception))
        self.assertIn("thread_id='missing'", str(ctx.exception))

    def test_cli_resume_preflight_accepts_paused_checkpoint(self):
        class PausedCheckpointApp:
            def get_state(self, config):
                return SimpleNamespace(values={"requirement": "x"}, next=("plan_review",))

        _ensure_resume_checkpoint(PausedCheckpointApp(), {"configurable": {"thread_id": "ok"}}, "ok", "tmp.sqlite")

    def test_plan_review_accepts_incremental_requirement_update(self):
        app = build_swarm_graph()
        config = {"configurable": {"thread_id": "test-plan-update"}}
        with tempfile.TemporaryDirectory() as tmp:
            app.invoke({"requirement": "SPI controller 50MHz", "project_name": "spi_ctrl", "output_dir": tmp, "reports": {}}, config=config)
            paused = app.invoke(Command(resume={"response": "thêm I2C slave 400kHz"}), config=config)
            self.assertIn("__interrupt__", paused)
            self.assertEqual(paused["__interrupt__"][0].value["action_required"], "PLAN_REVIEW")
            state = app.get_state(config).values
            self.assertIn("Incremental update: thêm I2C slave 400kHz", state["requirement"])
            self.assertFalse(state.get("plan_approved", False))

    def test_agent1_interrupts_for_ambiguous_ai_chip_requirement(self):
        app = build_swarm_graph()
        config = {"configurable": {"thread_id": "test-ambiguous"}}
        with tempfile.TemporaryDirectory() as tmp:
            paused = app.invoke({"requirement": "Tạo một con chip AI", "project_name": "ai_chip", "output_dir": tmp, "reports": {}}, config=config)
            self.assertIn("__interrupt__", paused)
            payload = paused["__interrupt__"][0].value
            self.assertEqual(payload["action_required"], "REQUIREMENT_CLARIFICATION")
            self.assertIn("Agent 1 needs more chip details", payload["message"])
            paused2 = app.invoke(Command(resume={"response": "APB, 100MHz, <1W"}), config=config)
            self.assertIn("__interrupt__", paused2)
            self.assertEqual(paused2["__interrupt__"][0].value["action_required"], "PLAN_REVIEW")

    def test_agent1_interrupts_for_greeting_before_generating_architecture(self):
        app = build_swarm_graph()
        config = {"configurable": {"thread_id": "test-greeting-clarification"}}
        with tempfile.TemporaryDirectory() as tmp:
            paused = app.invoke({"requirement": "hi", "project_name": "cpu32bit_web", "output_dir": tmp, "reports": {}}, config=config)
            self.assertIn("__interrupt__", paused)
            payload = paused["__interrupt__"][0].value
            self.assertEqual(payload["action_required"], "REQUIREMENT_CLARIFICATION")
            self.assertFalse((__import__("pathlib").Path(tmp) / "reports" / "architecture_plan.md").exists())

    def test_write_outputs_creates_full_ip_package_reports_and_manifest(self):
        app = build_swarm_graph()
        config = {"configurable": {"thread_id": "test-package"}}
        app.invoke({"requirement": "IoT AI camera chip <1W 100MHz", "project_name": "iot_camera", "reports": {}}, config=config)
        app.invoke(Command(resume={"response": "ok"}), config=config)
        done = app.invoke(Command(resume={"approved": True, "reviewer": "unit-test", "notes": "ok"}), config=config)

        with tempfile.TemporaryDirectory() as tmp:
            write_outputs(done, tmp)
            for dirname in ["rtl", "tb", "formal", "fpga", "reports"]:
                self.assertTrue((__import__("pathlib").Path(tmp) / dirname).is_dir())
            root = __import__("pathlib").Path(tmp)
            self.assertTrue((root / "run_modelsim_gui.bat").is_file())
            self.assertTrue((root / "open_quartus_project.bat").is_file())
            self.assertTrue((root / "fpga" / "iot_camera.qpf").is_file())
            self.assertTrue((root / "tb" / "sim_gui.do").is_file())
            modelsim_bat = (root / "run_modelsim_gui.bat").read_text(encoding="ascii")
            modelsim_gui_do = (root / "tb" / "sim_gui.do").read_text(encoding="ascii")
            quartus_bat = (root / "open_quartus_project.bat").read_text(encoding="ascii")
            self.assertIn("vsim -gui -do \"do sim_gui.do\"", modelsim_bat)
            self.assertIn("tb\\sim_gui.do", modelsim_bat)
            self.assertIn("vlog -sv ../rtl/*.sv", modelsim_gui_do)
            self.assertIn("vsim -wlf wave.wlf work.iot_camera_top", modelsim_gui_do)
            self.assertIn("run -all", modelsim_gui_do)
            self.assertIn("Simulation finished. Design remains loaded", modelsim_gui_do)
            self.assertIn("quartus \"fpga\\iot_camera.qpf\"", quartus_bat)
            reports = __import__("pathlib").Path(tmp) / "reports"
            for filename in ["architecture.md", "architecture_plan.md", "rtl_quality.md", "formal_summary.md", "dv_coverage.md", "timing_summary.md", "signoff_manifest.json"]:
                self.assertTrue((reports / filename).is_file())
            manifest = json.loads((reports / "signoff_manifest.json").read_text(encoding="ascii"))
            self.assertEqual(manifest["status"], "DEMO_SIGNOFF_READY")
            self.assertEqual(manifest["raw_status"], "SIGNOFF_READY")
            self.assertTrue(manifest["demo_ready"])
            self.assertFalse(manifest["signoff_ready"])
            self.assertFalse(manifest["full_signoff_evidence_ready"])
            self.assertEqual(manifest["required_directories"], ["rtl", "tb", "formal", "fpga", "reports"])
            self.assertGreater(manifest["generated_file_count"], 0)
            generated_paths = {file["path"] for file in manifest["generated_files"]}
            self.assertIn("run_modelsim_gui.bat", generated_paths)
            self.assertIn("open_quartus_project.bat", generated_paths)
            self.assertIn("fpga/iot_camera.qpf", generated_paths)
            self.assertIn("tb/sim_gui.do", generated_paths)
            rtl_root_json = {path.name for path in (root / "rtl").glob("*.json")}
            self.assertLessEqual(
                rtl_root_json,
                {
                    "rtl_manifest.json",
                    "compile_order_report.json",
                    "ast_dependency_graph.json",
                    "agent2_quality_score.json",
                    "agent2_release_decision.json",
                },
            )
            self.assertTrue((root / "rtl" / "reports" / "strict_eda_report.json").is_file())
            self.assertTrue((root / "rtl" / "reports" / "semantic_deep_report.json").is_file())
            self.assertTrue((root / "rtl" / "contracts" / "formal_hooks.json").is_file())
            self.assertTrue((root / "rtl" / "contracts" / "dv_hooks.json").is_file())
            self.assertTrue((root / "rtl" / "contracts" / "agent2_handoff_bundle.json").is_file())
            self.assertTrue((root / "rtl" / "contracts" / "agent2_to_agent3.json").is_file())
            self.assertTrue((root / "rtl" / "repair" / "repair_package.json").is_file())
            self.assertFalse((root / "rtl" / "strict_eda_report.json").exists())
            self.assertFalse((root / "rtl" / "formal_hooks.json").exists())
            self.assertTrue((root / "contracts" / "contract_envelopes.json").is_file())
            self.assertTrue((root / "contracts" / "envelopes" / "agent1_to_agent2.json").is_file())
            self.assertTrue((root / "contracts" / "envelopes" / "agent2_to_agent3_contract.json").is_file())
            bus = json.loads((root / "contracts" / "contract_envelopes.json").read_text(encoding="ascii"))
            self.assertEqual(bus["agent1_to_agent2"]["producer"], "agent1")
            self.assertEqual(bus["agent2_to_agent3_contract"]["consumer"], "agent3")
            self.assertEqual(bus["agent1_to_agent2"]["payload"], done["contract_envelopes"]["agent1_to_agent2"]["payload"])

    def test_end_to_end_dynamic_thermal_sensor_outputs_have_no_iot_camera_leak(self):
        app = build_swarm_graph()
        config = {"configurable": {"thread_id": "test-thermal-sensor"}}
        done = None
        with tempfile.TemporaryDirectory() as tmp:
            app.invoke({"requirement": "temperature monitor 50MHz", "project_name": "thermal_sensor", "output_dir": tmp, "reports": {}}, config=config)
            app.invoke(Command(resume={"response": "ok"}), config=config)
            done = app.invoke(Command(resume={"approved": True, "reviewer": "unit-test", "notes": "ok"}), config=config)
            write_outputs(done, tmp)
            root = __import__("pathlib").Path(tmp)
            self.assertTrue((root / "rtl" / "thermal_sensor_top.sv").is_file())
            self.assertTrue((root / "fpga" / "thermal_sensor.qsf").is_file())
            self.assertTrue((root / "fpga" / "thermal_sensor.sdc").is_file())
            self.assertIn("Project: thermal_sensor", (root / "reports" / "architecture_plan.md").read_text(encoding="ascii"))
            all_text = "\n".join(path.read_text(encoding="ascii", errors="ignore") for path in root.rglob("*") if path.is_file() and path.suffix not in {".sqlite"})
            self.assertNotIn("iot_camera", all_text)

    def test_timing_violation_loops_agent4_critical_path_back_to_agent2_pipeline(self):
        app = build_swarm_graph()
        config = {"configurable": {"thread_id": "test-timing-loop"}}
        compile_reports = [
            {"pass": False, "metrics": {"compile_pass": True, "fmax_mhz": 80.0, "target_mhz": 100.0,
             "setup_slack_ns": -0.42, "hold_slack_ns": 0.11, "alm_usage_pct": 12.0,
             "programming_file": "iot_camera_top.sof", "critical_path": "mac_array reg0_q -> prdata_o"}},
            {"pass": True, "metrics": {"compile_pass": True, "fmax_mhz": 125.0, "target_mhz": 100.0,
             "setup_slack_ns": 0.08, "hold_slack_ns": 0.10, "alm_usage_pct": 13.0,
             "programming_file": "iot_camera_top.sof", "critical_path": "closed"}},
        ]
        with tempfile.TemporaryDirectory() as tmp, \
             patch("semiconductor_swarm.swarm_graph.synthesize_rtl_with_quartus", return_value={"pass": True, "metrics": {"compile_pass": True}}), \
             patch("semiconductor_swarm.swarm_graph.prove_formal_with_symbiyosys", return_value={"pass": True}), \
             patch("semiconductor_swarm.swarm_graph.compile_physical_design", side_effect=compile_reports):
            app.invoke({"requirement": "IoT AI camera chip <1W 100MHz", "project_name": "iot_camera", "output_dir": tmp,
                        "reports": {}, "run_real_tools": True, "debug_iterations": 0, "max_debug_iterations": 5}, config=config)
            app.invoke(Command(resume={"response": "ok"}), config=config)
            done = app.invoke(Command(resume={"approved": True, "reviewer": "unit-test", "notes": "ok"}), config=config)

            self.assertEqual(done["status"], "SIGNOFF_READY")
            self.assertEqual(done["reports"]["auto_debug_iteration"], 1)
            self.assertEqual(done["timing_closure_history"][0]["fix_type"], "PIPELINE_CRITICAL_PATH")
            self.assertEqual(done["timing_closure_history"][0]["reason"], "Setup Slack < 0")
            rtl_text = "\n".join(file["content"] for file in done["rtl_files"] if file["language"] == "systemverilog")
            self.assertIn("AUTO_PIPELINE_FIX: PIPELINE_CRITICAL_PATH", rtl_text)
            self.assertIn("mac_array reg0_q -> prdata_o", rtl_text)


if __name__ == "__main__":
    unittest.main()
