import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from semiconductor_swarm.agents.agent1_planning.architect import generate_architecture_spec
from semiconductor_swarm.agents.agent5_formal.formal_verifier import (
    decide_formal_action,
    generate_formal_files,
    parse_sby_result_text,
    run_symbiyosys,
    verify_formal_files,
)
from semiconductor_swarm.agents.agent2_rtl.rtl_designer import generate_rtl_files
from semiconductor_swarm.tools.symbiyosys_runner import SbyRunResult


class TestAgent5FormalVerifier(unittest.TestCase):
    def test_generates_sva_and_sby_per_block(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        rtl = generate_rtl_files(spec)
        files = generate_formal_files(spec, rtl)
        names = {file["filename"] for file in files}
        self.assertIn("formal_plan.md", names)
        self.assertIn("run_symbiyosys.py", names)
        self.assertIn("parse_sby_results.py", names)
        for block in [block["name"] for block in spec["ip_blocks"]]:
            self.assertIn(f"fv_{block}.sv", names)
            self.assertIn(f"{block}.sby", names)

    def test_output_format_is_json_contract(self):
        spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
        files = generate_formal_files(spec, generate_rtl_files(spec))
        json.loads(json.dumps(files))
        for file in files:
            self.assertEqual(set(file), {"filename", "language", "content", "line_count", "dependencies"})
            self.assertEqual(file["line_count"], len(file["content"].rstrip("\n").splitlines()))

    def test_formal_first_quality_rules(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        rtl = generate_rtl_files(spec)
        files = generate_formal_files(spec, rtl, debug=True)
        text = "\n".join(file["content"] for file in files)
        report = json.loads(next(file for file in files if file["filename"] == "agent5_debug_report.json")["content"])
        self.assertIn("Agent 5 runs before Agent 3", text)
        self.assertIn("assert property", text)
        self.assertIn("assume property", text)
        self.assertIn("##[1:3] pready_o", text)
        self.assertIn("run_symbiyosys", text)
        self.assertIn("smtbmc z3", text)
        self.assertIn("MAC_DEEP", text)
        self.assertIn("SRAM_DEEP", text)
        self.assertIn("scoreboard_mem", text)
        self.assertTrue(report["pass"], report["failures"])

    def test_sby_files_use_real_z3_engine(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        files = generate_formal_files(spec, generate_rtl_files(spec))
        sby_text = next(file["content"] for file in files if file["filename"] == "mac_array.sby")
        self.assertIn("[engines]\nsmtbmc z3", sby_text)
        self.assertIn("[script]", sby_text)
        self.assertIn("read -formal -sv", sby_text)

    def test_parse_sby_and_decide_actions(self):
        passed = parse_sby_result_text("SBY 12:00:00 engine_0: Status: passed\nPASS", "control_regs")
        self.assertTrue(passed["pass"])
        self.assertEqual(decide_formal_action(passed)["action"], "ALLOW_AGENT3_SIM")
        failed = parse_sby_result_text("Assert failed in fv_control_regs.sv:42\ncounterexample trace.vcd\nFAIL", "control_regs")
        action = decide_formal_action(failed)
        self.assertEqual(action["action"], "REQUEST_AGENT2_FIX")
        self.assertEqual(action["fix_type"], "FORMAL_COUNTEREXAMPLE")
        self.assertIn("counterexample", action["bug_report"]["counterexample_snippet"])
        self.assertEqual(decide_formal_action(failed, formal_iterations=6)["action"], "HUMAN_CODE_OVERWRITE")

    def test_run_symbiyosys_invokes_real_sby_command(self):
        fake = SbyRunResult(
            block="control_regs",
            command=["sby", "-f", "control_regs.sby"],
            returncode=0,
            stdout="SBY engine_0: Status: passed\nZ3\nPASS",
            stderr="",
            result={"block": "control_regs", "pass": True, "status": "PASS", "solver": "z3"},
        )
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "semiconductor_swarm.agents.agent5_formal.formal_verifier.run_real_symbiyosys", return_value=fake
        ) as mocked:
            result = run_symbiyosys("control_regs", Path(tmpdir))
        mocked.assert_called_once_with("control_regs", Path(tmpdir), sby="sby", require_sby=True)
        self.assertEqual(result["command"], ["sby", "-f", "control_regs.sby"])
        self.assertTrue(result["result"]["pass"])

    def test_violation_detection(self):
        spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
        rtl = generate_rtl_files(spec)
        files = generate_formal_files(spec, rtl)
        files[0]["content"] = files[0]["content"].replace("Formal-First", "Formal")
        report = verify_formal_files(spec, rtl, files)
        self.assertFalse(report["pass"])


if __name__ == "__main__":
    unittest.main()