import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from semiconductor_swarm.agents.agent1_planning.architect import generate_architecture_spec
from semiconductor_swarm.agents.agent4_physical.physical_designer import (
    compile_physical_design,
    decide_backend_action,
    generate_physical_design_files,
    parse_quartus_report_text,
    prepare_quartus_project,
    verify_physical_design_files,
)
from semiconductor_swarm.agents.agent2_rtl.rtl_designer import generate_rtl_files, prepare_rtl_for_quartus, synthesize_rtl_with_quartus


class TestAgent4PhysicalDesigner(unittest.TestCase):
    def test_generates_quartus_backend_collateral(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        rtl = generate_rtl_files(spec)
        names = {file["filename"] for file in generate_physical_design_files(spec, rtl)}
        self.assertIn("quartus_flow.tcl", names)
        self.assertIn("iot_camera.qsf", names)
        self.assertIn("iot_camera.sdc", names)
        self.assertIn("run_quartus_flow.py", names)
        self.assertIn("parse_quartus_reports.py", names)
        self.assertIn("backend_decision.py", names)

    def test_output_format_is_json_contract(self):
        spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
        files = generate_physical_design_files(spec, generate_rtl_files(spec))
        json.loads(json.dumps(files))
        for file in files:
            self.assertEqual(set(file), {"filename", "language", "content", "line_count", "dependencies"})
            self.assertEqual(file["line_count"], len(file["content"].rstrip("\n").splitlines()))

    def test_fpga_first_tool_call_and_no_invented_flow(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        rtl = generate_rtl_files(spec)
        files = generate_physical_design_files(spec, rtl, debug=True)
        text = "\n".join(file["content"] for file in files)
        report = json.loads(next(file for file in files if file["filename"] == "agent4_debug_report.json")["content"])
        self.assertIn("Cyclone V 5CSEMA5F31C6", text)
        self.assertIn("run_quartus_flow", text)
        self.assertIn("quartus_sh", text)
        self.assertIn("execute_module -tool fit", text)
        self.assertIn("execute_module -tool asm", text)
        self.assertTrue(report["pass"], report["failures"])

    def test_sdc_constrains_all_top_level_io(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        rtl = generate_rtl_files(spec)
        files = generate_physical_design_files(spec, rtl)
        sdc = next(file for file in files if file["filename"] == "iot_camera.sdc")["content"]
        self.assertIn("create_clock -name core_clk", sdc)
        for port in ["rst_ni", "psel_i", "penable_i", "pwrite_i", "paddr_i[*]", "pwdata_i[*]"]:
            self.assertIn(f"set_input_delay -clock core_clk -max", sdc)
            self.assertIn(f"[get_ports {{{port}}}]", sdc)
        for port in ["prdata_o[*]", "pready_o", "pslverr_o", "irq_o[*]"]:
            self.assertIn(f"set_output_delay -clock core_clk -max", sdc)
            self.assertIn(f"[get_ports {{{port}}}]", sdc)
        report = verify_physical_design_files(spec, rtl, files)
        self.assertTrue(report["checks"]["io_constraint_coverage_present"])

    def test_qsf_excludes_contract_only_rtl(self):
        spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
        rtl = generate_rtl_files(spec)
        rtl.append(
            {
                "filename": "interface_contracts.sv",
                "language": "systemverilog",
                "content": "module interface_contracts; endmodule\n",
                "line_count": 1,
                "dependencies": [],
                "output_path": "rtl/contracts/interface_contracts.sv",
            }
        )

        files = generate_physical_design_files(spec, rtl)
        qsf = next(file for file in files if file["filename"] == "spi_ctrl.qsf")["content"]

        self.assertIn("../rtl/spi_ctrl_top.sv", qsf)
        self.assertNotIn("interface_contracts.sv", qsf)
        self.assertTrue(verify_physical_design_files(spec, rtl, files)["pass"])

    def test_parse_reports_and_decide_actions(self):
        report = """Fmax: 125.3 MHz (Target: 50 MHz) PASS
Setup Slack: 0.42
Hold Slack: 0.11
ALMs: 12,340 / 32,070 (38%) PASS
Registers: 8,901
Block RAM: 45 / 397 (11%) PASS
"""
        metrics = parse_quartus_report_text(report, target_mhz=100)
        self.assertTrue(metrics["timing_pass"])
        self.assertEqual(metrics["setup_slack_ns"], 0.42)
        self.assertEqual(metrics["hold_slack_ns"], 0.11)
        self.assertAlmostEqual(metrics["alm_usage_pct"], 38.48)
        self.assertEqual(metrics["bandwidth_effective_mb_s"], 400.96)
        self.assertEqual(decide_backend_action(metrics)["action"], "SIGNOFF_PASS")
        slow = dict(metrics, fmax_mhz=75, target_mhz=100)
        self.assertEqual(decide_backend_action(slow)["fix_type"], "PIPELINE_CRITICAL_PATH")
        bad_slack = dict(metrics, setup_slack_ns=-0.1)
        self.assertEqual(decide_backend_action(bad_slack)["fix_type"], "PIPELINE_CRITICAL_PATH")
        large = dict(metrics, alm_usage_pct=85)
        self.assertEqual(decide_backend_action(large)["fix_type"], "OPTIMIZE_OR_SHARE_RESOURCES")
        self.assertEqual(decide_backend_action(metrics, debug_iterations=6)["action"], "HUMAN_CODE_OVERWRITE")

    def test_violation_detection(self):
        spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
        rtl = generate_rtl_files(spec)
        files = generate_physical_design_files(spec, rtl)
        files[0]["content"] = files[0]["content"].replace("execute_module -tool fit", "")
        report = verify_physical_design_files(spec, rtl, files)
        self.assertFalse(report["pass"])

    def test_agent2_agent4_prepare_real_quartus_project_files(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        rtl = generate_rtl_files(spec)
        rtl.append(
            {
                "filename": "interface_contracts.sv",
                "language": "systemverilog",
                "content": "module interface_contracts; endmodule\n",
                "line_count": 1,
                "dependencies": [],
                "output_path": "rtl/contracts/interface_contracts.sv",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            agent2_paths = prepare_rtl_for_quartus(spec, rtl, Path(tmp) / "a2")
            agent4_paths = prepare_quartus_project(spec, rtl, Path(tmp) / "a4")
            for paths in (agent2_paths, agent4_paths):
                self.assertTrue(Path(paths["qpf"]).exists())
                qsf = Path(paths["qsf"]).read_text(encoding="ascii")
                self.assertIn("set_global_assignment -name DEVICE 5CSEMA5F31C6", qsf)
                self.assertIn("set_global_assignment -name SYSTEMVERILOG_FILE rtl/iot_camera_top.sv", qsf)
                self.assertNotIn("interface_contracts.sv", qsf)
                self.assertFalse((Path(paths["rtl_dir"]) / "interface_contracts.sv").exists())

    def test_real_quartus_compile_uses_subprocess_and_parses_reports(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        rtl = generate_rtl_files(spec)

        def fake_run(cmd, cwd, text, capture_output, check, timeout):
            output = Path(cwd) / "output_files"
            output.mkdir(exist_ok=True)
            (output / "iot_camera.fit.summary").write_text(
                "ALMs: 12,340 / 32,070\nRegisters: 8,901\nBlock RAM: 45 / 397\n",
                encoding="utf-8",
            )
            (output / "iot_camera.sta.rpt").write_text("Fmax: 125.3 MHz\nSetup Slack: 0.42\nHold Slack: 0.11\n", encoding="utf-8")
            (output / "iot_camera.sof").write_text("sof", encoding="utf-8")
            return type("Proc", (), {"returncode": 0, "stdout": "compile ok", "stderr": ""})()

        with tempfile.TemporaryDirectory() as tmp, patch("semiconductor_swarm.tools.quartus_runner.shutil.which", return_value="quartus_sh"), patch(
            "semiconductor_swarm.tools.quartus_runner.subprocess.run", side_effect=fake_run
        ) as run_mock:
            result = compile_physical_design(spec, rtl, tmp)
            agent2_result = synthesize_rtl_with_quartus(spec, rtl, Path(tmp) / "agent2")

        self.assertEqual(run_mock.call_args_list[0].args[0], ["quartus_sh", "--flow", "compile", "iot_camera"])
        self.assertEqual(run_mock.call_args_list[1].args[0], ["quartus_sta", "iot_camera"])
        self.assertTrue(result["metrics"]["compile_pass"])
        self.assertTrue(result["metrics"]["sta_pass"])
        self.assertEqual(result["metrics"]["fmax_mhz"], 125.3)
        self.assertEqual(result["metrics"]["setup_slack_ns"], 0.42)
        self.assertEqual(result["metrics"]["hold_slack_ns"], 0.11)
        self.assertAlmostEqual(result["metrics"]["alm_usage_pct"], 38.48)
        self.assertEqual(result["metrics"]["bandwidth_peak_mb_s"], 501.2)
        self.assertTrue(agent2_result["metrics"]["compile_pass"])


if __name__ == "__main__":
    unittest.main()
