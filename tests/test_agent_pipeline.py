import json
import unittest

from semiconductor_swarm.agents.agent1_planning.architect import APB_SLAVE_INTERFACE, generate_architecture_spec, validate_architecture_spec
from semiconductor_swarm.agents.agent3_dv.dv_engineer import COVERAGE_TARGETS, generate_dv_files, next_debug_action, verify_dv_files
from semiconductor_swarm.agents.agent5_formal.formal_verifier import decide_formal_action, generate_formal_files, parse_sby_result_text, verify_formal_files
from semiconductor_swarm.agents.agent2_rtl.rtl_designer import generate_rtl_files, verify_rtl_files
from semiconductor_swarm.tools.bandwidth_calculator import calculate_bandwidth
from semiconductor_swarm.tools.ppa_calculator import calculate_ppa


class TestAgentPipeline(unittest.TestCase):
    def test_agent1_agent2_agent5_agent3_contract_is_end_to_end(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        validate_architecture_spec(spec)

        rtl_files = generate_rtl_files(spec, debug=True)
        rtl_report = json.loads(next(file for file in rtl_files if file["filename"] == "agent2_debug_report.json")["content"])
        synthesizable_rtl = [file for file in rtl_files if file["language"] == "systemverilog"]
        self.assertTrue(verify_rtl_files(spec, synthesizable_rtl)["pass"])
        self.assertTrue(rtl_report["pass"], rtl_report["failures"])

        formal_files = generate_formal_files(spec, synthesizable_rtl, debug=True)
        formal_report = json.loads(next(file for file in formal_files if file["filename"] == "agent5_debug_report.json")["content"])
        self.assertTrue(verify_formal_files(spec, synthesizable_rtl, formal_files)["pass"])
        self.assertTrue(formal_report["pass"], formal_report["failures"])
        self.assertEqual(decide_formal_action(parse_sby_result_text("PASS", "formal_gate"))["action"], "ALLOW_AGENT3_SIM")

        dv_files = generate_dv_files(spec, synthesizable_rtl, debug=True)
        dv_report = json.loads(next(file for file in dv_files if file["filename"] == "agent3_debug_report.json")["content"])
        self.assertTrue(verify_dv_files(spec, synthesizable_rtl, dv_files)["pass"])
        self.assertTrue(dv_report["pass"], dv_report["failures"])

        block_names = [block["name"] for block in spec["ip_blocks"]]
        rtl_names = {file["filename"] for file in synthesizable_rtl}
        formal_names = {file["filename"] for file in formal_files}
        dv_names = {file["filename"] for file in dv_files}
        for block in block_names:
            self.assertIn(f"{block}.sv", rtl_names)
            self.assertIn(f"fv_{block}.sv", formal_names)
            self.assertIn(f"{block}.sby", formal_names)
            self.assertIn(f"test_{block}.py", dv_names)

        top = next(file for file in synthesizable_rtl if file["filename"] == "iot_camera_top.sv")["content"]
        for block in block_names:
            self.assertIn(f"u_{block}", top)
            self.assertIn(f"iot_camera_{block}_rtl", top)

        all_rtl = "\n".join(file["content"] for file in synthesizable_rtl)
        all_dv = "\n".join(file["content"] for file in dv_files)
        for signal in APB_SLAVE_INTERFACE["signals"]:
            self.assertIn(signal["name"], all_rtl)
            self.assertIn(signal["name"], all_dv)

        self.assertEqual(spec["ppa_estimate"], calculate_ppa("28nm", 250_000, 256, 64, 100))
        self.assertEqual(spec["bandwidth_estimate"], calculate_bandwidth(64, 100))
        self.assertEqual(spec["constraints"]["hitl_after_debug_iterations"], 5)
        self.assertEqual(formal_report["formal_depth"], 50)
        self.assertEqual(dv_report["coverage_targets"], COVERAGE_TARGETS)
        self.assertEqual(next_debug_action(6, "persistent cocotb failure")["action"], "HUMAN_CODE_OVERWRITE")
        self.assertNotIn("uvm", all_dv.lower())


if __name__ == "__main__":
    unittest.main()