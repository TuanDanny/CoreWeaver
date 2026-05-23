import unittest
from unittest.mock import patch
from pathlib import Path

from semiconductor_swarm.agents.agent2_rtl.agent2_prompt import AGENT2_SYSTEM_PROMPT
from semiconductor_swarm.agents.agent3_dv.agent3_prompt import AGENT3_PROMPT
from semiconductor_swarm.agents.agent4_physical.agent4_prompt import AGENT4_SYSTEM_PROMPT
from semiconductor_swarm.agents.agent5_formal.agent5_prompt import AGENT5_SYSTEM_PROMPT
from semiconductor_swarm.agents.agent1_planning.llm_config import build_openai_compatible_headers, resolve_swarm_llm_config


class TestPromptContracts(unittest.TestCase):
    def test_shared_codex_config_matches_cline_endpoint(self):
        cfg = resolve_swarm_llm_config({"local_config_path": "missing.local.json"})
        self.assertEqual(cfg["base_url"], "http://localhost:20128/v1")
        self.assertEqual(cfg["model"], "cx/gpt-5.5")
        self.assertEqual(cfg["local_config_path"], "missing.local.json")
        self.assertEqual(cfg["api_key_env"], "SWARM_CODEX_API_KEY")

    @patch.dict("os.environ", {"SWARM_CODEX_API_KEY": "test-key"})
    def test_shared_codex_headers_use_env_api_key(self):
        cfg = resolve_swarm_llm_config({"local_config_path": "missing.local.json"})
        headers = build_openai_compatible_headers(cfg)
        self.assertEqual(headers["Authorization"], "Bearer test-key")

    def test_shared_codex_local_config_file_can_hold_key(self):
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "codex_api.local.json"
            path.write_text(json.dumps({"base_url": "http://localhost:20128/v1", "model": "cx/gpt-5.5", "api_key": "local-key"}), encoding="utf-8")
            cfg = resolve_swarm_llm_config({"local_config_path": str(path)})
            headers = build_openai_compatible_headers(cfg)
            self.assertEqual(headers["Authorization"], "Bearer local-key")

    def test_agent2_prompt_matches_master_rules(self):
        for token in [
            "Golden Micro-Patterns",
            "typedef enum logic",
            "stage_1_acc_q",
            "stage_1_acc_d",
            "APB pin names exactly unchanged",
            "$display",
            "#delay",
            "initial begin",
            "No combinational loops",
            "Bus protocol timing must match APB specification",
        ]:
            self.assertIn(token, AGENT2_SYSTEM_PROMPT)

    def test_agent3_prompt_matches_cocotb_hilt_contract(self):
        for token in [
            "Cocotb + Pytest",
            "NEVER write UVM/SV TB",
            "debug_iterations > 5",
            "HITL code overwrite",
            "run_cocotb_sim()",
            "Verilator",
            "Line >= 95%",
            "Branch >= 90%",
            "fix-request JSON",
        ]:
            self.assertIn(token, AGENT3_PROMPT)

    def test_agent4_prompt_matches_quartus_fpga_contract(self):
        for token in [
            "Cyclone V 5CSEMA5F31C6",
            "run_quartus_flow",
            "execute_module -tool map",
            "execute_module -tool fit",
            "execute_module -tool sta",
            "execute_module -tool asm",
            "Fmax MHz",
            "ALM utilization",
            "signoff_status",
        ]:
            self.assertIn(token, AGENT4_SYSTEM_PROMPT)

    def test_agent5_prompt_matches_formal_first_contract(self):
        for token in [
            "Formal-First",
            "run_symbiyosys",
            "mode bmc",
            "depth 50",
            "smtbmc z3",
            "assert property",
            "deadlock-free FSM",
            "counterexample",
            "ALLOW_AGENT3_SIM",
            "REQUEST_AGENT2_FIX",
            "HUMAN_CODE_OVERWRITE",
        ]:
            self.assertIn(token, AGENT5_SYSTEM_PROMPT)

    def test_agent1_v37_prompt_compliance_matrix_exists(self):
        matrix = Path("docs/prompt_compliance_matrix.yaml").read_text(encoding="utf-8")
        for token in [
            "A1_NO_MATH",
            "A1_PPA_TOOL_ONLY",
            "A1_BW_TOOL_ONLY",
            "A1_STRICT_PINOUT",
            "A1_NO_AGENT2_BEFORE_REVIEW",
            "A1_RDL_FW_DV_ARTIFACTS",
            "A1_VALIDATION_ROUTING",
        ]:
            self.assertIn(token, matrix)


if __name__ == "__main__":
    unittest.main()