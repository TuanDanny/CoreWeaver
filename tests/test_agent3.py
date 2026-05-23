import json
import unittest

from semiconductor_swarm.agents.agent1_planning.architect import generate_architecture_spec
from semiconductor_swarm.agents.agent3_dv.dv_engineer import COVERAGE_GOALS, analyze_simulation_log, generate_dv_files, next_debug_action, run_modelsim_sim, verify_dv_files
from semiconductor_swarm.agents.agent2_rtl.rtl_designer import generate_rtl_files


class TestAgent3DVEngineer(unittest.TestCase):
    def test_generates_test_plan_makefile_and_block_testbenches(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        rtl_files = generate_rtl_files(spec)
        names = {file["filename"] for file in generate_dv_files(spec, rtl_files)}
        self.assertIn("test_plan.py", names)
        self.assertIn("Makefile", names)
        self.assertIn("ModelSim.mk", names)
        self.assertIn("sim.do", names)
        self.assertIn("run_cocotb_sim.py", names)
        self.assertIn("run_modelsim_sim.py", names)
        self.assertIn("debug_orchestrator.py", names)
        self.assertIn("dv_helpers.py", names)
        self.assertIn("agent3_dv_manifest.json", names)
        self.assertIn("agent3_tool_health.json", names)
        self.assertIn("agent3_compile_order.f", names)
        self.assertIn("agent3_sim_report.json", names)
        self.assertIn("agent3_coverage_report.json", names)
        self.assertIn("agent3_scoreboard_report.json", names)
        self.assertIn("agent3_release_decision.json", names)
        self.assertIn("agent3_result.json", names)
        self.assertIn("agent3_dv_dashboard.md", names)
        for block in [block["name"] for block in spec["ip_blocks"]]:
            self.assertIn(f"test_{block}.py", names)

    def test_output_format_is_json_contract(self):
        spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
        files = generate_dv_files(spec, generate_rtl_files(spec))
        json.loads(json.dumps(files))
        for file in files:
            self.assertEqual(set(file), {"filename", "language", "content", "line_count", "dependencies"})
            self.assertEqual(file["line_count"], len(file["content"].rstrip("\n").splitlines()))

    def test_cocotb_pytest_rules_and_no_uvm(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        text = "\n".join(file["content"] for file in generate_dv_files(spec, generate_rtl_files(spec)))
        self.assertIn("import cocotb", text)
        self.assertIn("@cocotb.test()", text)
        self.assertIn("import pytest", text)
        self.assertIn("@pytest.mark", text)
        self.assertNotIn("uvm_component", text)

    def test_coverage_verilator_debug_and_hitl(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        files = generate_dv_files(spec, generate_rtl_files(spec), debug=True)
        text = "\n".join(file["content"] for file in files)
        report = json.loads(next(file for file in files if file["filename"] == "agent3_debug_report.json")["content"])
        for goal in COVERAGE_GOALS:
            self.assertIn(goal, text)
        self.assertIn("SIM ?= verilator", text)
        self.assertIn("vsim -c", text)
        self.assertIn("vlog -sv", text)
        self.assertIn("../rtl/", text)
        self.assertNotIn("../generated_rtl", text)
        self.assertNotIn("python -c", text)
        self.assertIn("wave.wlf", text)
        self.assertIn("dump.vcd", text)
        self.assertIn("verilator_coverage --annotate", text)
        self.assertTrue(report["pass"], report["failures"])
        self.assertEqual(next_debug_action(6, "fail")["action"], "HUMAN_CODE_OVERWRITE")

    def test_fix_request_and_violation_detection(self):
        fix = analyze_simulation_log("ERROR rtl/mac_array.sv:142 assertion failed\nlast", "test_mac::test_overflow")
        self.assertEqual(fix["file"], "rtl/mac_array.sv")
        self.assertEqual(fix["line"], 142)
        self.assertEqual(fix["failing_test"], "test_mac::test_overflow")
        spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
        rtl = generate_rtl_files(spec)
        dv = generate_dv_files(spec, rtl)
        dv[0]["content"] += "\n# uvm forbidden\n"
        report = verify_dv_files(spec, rtl, dv)
        self.assertFalse(report["pass"])

    def test_modelsim_runner_uses_vlog_vsim_and_waveforms(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        def fake_run(cmd, cwd, text, capture_output, check, timeout):
            return type("Proc", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

        with tempfile.TemporaryDirectory() as tmp, patch("semiconductor_swarm.agents.agent3_dv.dv_engineer.shutil.which", return_value="tool"), patch(
            "semiconductor_swarm.agents.agent3_dv.dv_engineer.subprocess.run", side_effect=fake_run
        ) as run_mock:
            Path(tmp, "sim.do").write_text("quit -f", encoding="ascii")
            Path(tmp, "agent3_compile_order.f").write_text("pkg.sv\nblock.sv\n", encoding="ascii")
            result = run_modelsim_sim(tmp)

        self.assertEqual(run_mock.call_args_list[0].args[0], ["vlog", "-sv", "../rtl/pkg.sv", "../rtl/block.sv"])
        self.assertEqual(run_mock.call_args_list[1].args[0], ["vsim", "-c", "-do", "sim.do"])
        self.assertTrue(result["pass"])
        self.assertTrue(result["waveform_wlf"].endswith("wave.wlf"))
        self.assertTrue(result["waveform_vcd"].endswith("dump.vcd"))


if __name__ == "__main__":
    unittest.main()
