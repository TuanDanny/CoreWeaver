import json
import unittest
from pathlib import Path

from semiconductor_swarm.agents.agent1_planning.architect import APB_SLAVE_INTERFACE, generate_architecture_spec
from semiconductor_swarm.agents.agent2_rtl.orchestrator import run_agent2_orchestrator
from semiconductor_swarm.agents.agent2_rtl.phase1_artifacts import build_phase1_artifacts
from semiconductor_swarm.agents.agent2_rtl.subagents import get_milestone_a_registry, get_milestone_b_registry, get_milestone_b_review_registry, get_milestone_f_registry, get_milestone_g_registry
from semiconductor_swarm.agents.agent2_rtl.pattern_library import pattern_manifest
from semiconductor_swarm.agents.agent2_rtl.rag_stub import query_rtl_knowledge_base, retrieve_agent2_context
from semiconductor_swarm.agents.agent2_rtl.rtl_designer import generate_rtl_files, verify_rtl_files
from semiconductor_swarm.agents.agent2_rtl.schema_validation import SCHEMA_DIR, build_schema_validation_report, validate_payload
from semiconductor_swarm.agents.agent2_rtl.semantic.validators import build_semantic_review_report
from semiconductor_swarm.contracts.constants import SWARM_FALLBACK_POLICIES, SWARM_MODE_DEMO, SWARM_MODE_DEV, SWARM_MODE_NIGHTLY_REAL_TOOLS, SWARM_MODE_REQUIRES_REAL_TOOLS, SWARM_MODE_STRICT, SWARM_RUN_MODES
from semiconductor_swarm.tools.rag_retriever_stub import query_rtl_knowledge_base as query_plan_rtl_knowledge_base
from semiconductor_swarm.tools.rtl_linter import lint_rtl_files as lint_plan_rtl_files


class TestAgent2RTLDesigner(unittest.TestCase):
    def test_swarm_run_modes_define_explicit_fallback_policy(self):
        self.assertEqual(SWARM_RUN_MODES, (SWARM_MODE_DEMO, SWARM_MODE_DEV, SWARM_MODE_STRICT, SWARM_MODE_NIGHTLY_REAL_TOOLS))
        self.assertEqual(set(SWARM_FALLBACK_POLICIES), set(SWARM_RUN_MODES))
        self.assertFalse(SWARM_MODE_REQUIRES_REAL_TOOLS[SWARM_MODE_DEMO])
        self.assertFalse(SWARM_MODE_REQUIRES_REAL_TOOLS[SWARM_MODE_DEV])
        self.assertTrue(SWARM_MODE_REQUIRES_REAL_TOOLS[SWARM_MODE_STRICT])
        self.assertTrue(SWARM_MODE_REQUIRES_REAL_TOOLS[SWARM_MODE_NIGHTLY_REAL_TOOLS])
        self.assertIn("no_silent_pass", SWARM_FALLBACK_POLICIES[SWARM_MODE_DEMO])
        self.assertIn("fallback_forbidden", SWARM_FALLBACK_POLICIES[SWARM_MODE_STRICT])

    def test_generates_files_for_every_agent1_ip_block_and_top(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        files = generate_rtl_files(spec)
        names = {file["filename"] for file in files}

        for block in [block["name"] for block in spec["ip_blocks"]]:
            self.assertIn(f"{block}.sv", names)
            self.assertIn(f"{block}_pkg.sv", names)
            self.assertIn(f"{block}_intf.sv", names)
        self.assertIn("iot_camera_top.sv", names)

    def test_output_format_is_prompt_json_contract(self):
        spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
        files = generate_rtl_files(spec)

        json.loads(json.dumps(files))
        for file in files:
            self.assertEqual(set(file), {"filename", "language", "content", "line_count", "dependencies"})
            self.assertEqual(file["language"], "systemverilog")
            self.assertEqual(file["line_count"], len(file["content"].rstrip("\n").splitlines()))

    def test_apb_pinout_is_not_renamed_in_generated_rtl(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        files = generate_rtl_files(spec)
        rtl = "\n".join(file["content"] for file in files)

        for signal in APB_SLAVE_INTERFACE["signals"]:
            self.assertIn(signal["name"], rtl)
        self.assertNotIn("paddr_o", rtl)
        self.assertNotIn("apb_addr_i", rtl)

    def test_synthesizable_style_rules_are_present(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        files = generate_rtl_files(spec)
        rtl = "\n".join(file["content"] for file in files)

        self.assertIn("always_ff @(posedge clk_i)", rtl)
        self.assertIn("always_comb", rtl)
        self.assertIn("typedef enum logic", rtl)
        self.assertIn("stage_1_acc_q", rtl)
        self.assertIn("stage_1_acc_d", rtl)
        self.assertNotIn("$display", rtl)
        self.assertNotIn("#", rtl.replace("#(", ""))
        self.assertNotIn("initial begin", rtl)

    def test_mac_array_extra_ports_keep_valid_sv_port_separator(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        files = generate_rtl_files(spec)
        mac_rtl = next(file for file in files if file["filename"] == "mac_array.sv")["content"]

        self.assertIn("output logic                  irq_o,      // Interrupt request", mac_rtl)
        self.assertIn("output logic [31:0] mac_result_o", mac_rtl)
        self.assertIn("output logic        mac_valid_o", mac_rtl)

    def test_debug_self_check_proves_prompt_quality_rules(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        files = generate_rtl_files(spec, debug=True)
        report = json.loads(next(file for file in files if file["filename"] == "agent2_debug_report.json")["content"])

        self.assertTrue(report["pass"], report["failures"])
        self.assertEqual(report["failures"], [])
        self.assertTrue(all(report["checks"].values()))
        self.assertEqual(report["block_count"], len(spec["ip_blocks"]))
        self.assertEqual(report["rag_context"]["retriever"], "deterministic_local_rag_stub")
        self.assertTrue(report["linter_report"]["pass"])

    def test_cpu32_uart_i2c_blocks_use_agent1_register_map_not_reg0_template(self):
        spec = generate_architecture_spec(
            "Generate a 32-bit CPU architecture using an APB bus, with UART and I2C as the external peripherals",
            "cpu32bitv2",
        )
        files = generate_rtl_files(spec, debug=True)
        by_name = {file["filename"]: file for file in files}

        uart = by_name["uart.sv"]["content"]
        i2c = by_name["i2c.sv"]["content"]
        for token in ("txdata_q", "rxdata_q", "baud_div_q", "irq_status_q", "irq_enable_q"):
            self.assertIn(token, uart)
        for token in ("target_addr_q", "timing_q", "irq_status_q", "irq_enable_q"):
            self.assertIn(token, i2c)
        self.assertNotIn("reg0_q", uart)
        self.assertNotIn("reg0_q", i2c)
        self.assertIn("assign pslverr_o = pslverr_q", uart)
        self.assertIn("assign pslverr_o = pslverr_q", i2c)

        report = verify_rtl_files(spec, files)
        self.assertTrue(report["pass"], report["failures"])

    def test_lock_register_intent_generates_set_only_and_guarded_writes(self):
        spec = generate_architecture_spec(
            "Design an APB4 GPIO watchdog subsystem. No CPU. "
            "Watchdog lock prevents disable after lock and protects GPIO direction. "
            "Formal-first SVA plus cocotb.",
            "lock_subsystem",
        )
        files = generate_rtl_files(spec, debug=True)
        by_name = {file["filename"]: file for file in files}

        gpio = by_name["gpio.sv"]["content"]
        timer = by_name["timer.sv"]["content"]
        self.assertIn("logic [DATA_WIDTH-1:0] lock_q;", gpio)
        self.assertIn("logic [DATA_WIDTH-1:0] lock_q;", timer)
        self.assertIn("8'h18: lock_d = lock_q | pwdata_i;", gpio)
        self.assertIn("8'h1C: lock_d = lock_q | pwdata_i;", timer)
        self.assertIn("8'h08: direction_d = lock_q[0] ? direction_q : pwdata_i;", gpio)
        self.assertIn("8'h00: ctrl_d = lock_q[0] ? ctrl_q : pwdata_i;", timer)

        report = verify_rtl_files(spec, files)
        self.assertTrue(report["pass"], report["failures"])

    def test_agent2_milestone_a_registry_contains_full_36_agent_swarm(self):
        registry = get_milestone_a_registry()
        ids = [agent.agent_id for agent in registry]

        self.assertEqual(len(get_milestone_b_registry()), 36)
        for agent_id in [f"A2.{index:02d}" for index in range(1, 37)]:
            self.assertIn(agent_id, ids + [agent.agent_id for agent in get_milestone_b_review_registry()] + [agent.agent_id for agent in get_milestone_b_registry()])

    def test_agent2_milestone_b_registry_contains_review_and_repair_agents(self):
        ids = [agent.agent_id for agent in get_milestone_b_registry()]
        review_ids = [agent.agent_id for agent in get_milestone_b_review_registry()]

        for agent_id in ["A2.28", "A2.29", "A2.31", "A2.32", "A2.33", "A2.34", "A2.35"]:
            self.assertIn(agent_id, ids)
        self.assertEqual(review_ids, ["A2.28", "A2.29", "A2.31", "A2.32"])

    def test_agent2_v25_mf_registry_contains_full_51_agent_swarm(self):
        ids = [agent.agent_id for agent in get_milestone_f_registry()]

        self.assertEqual(len(ids), 51)
        self.assertEqual(ids, [f"A2.{index:02d}" for index in range(1, 52)])

    def test_agent2_v26_mg_registry_contains_full_56_agent_swarm(self):
        ids = [agent.agent_id for agent in get_milestone_g_registry()]

        self.assertEqual(len(ids), 56)
        self.assertEqual(ids, [f"A2.{index:02d}" for index in range(1, 57)])

    def test_agent2_v31_domain_registry_boundaries_preserve_existing_agents(self):
        from semiconductor_swarm.agents.agent2_rtl.subagents.advanced import get_advanced_registry
        from semiconductor_swarm.agents.agent2_rtl.subagents.intake import get_intake_registry
        from semiconductor_swarm.agents.agent2_rtl.subagents.manufacturing import get_manufacturing_registry
        from semiconductor_swarm.agents.agent2_rtl.subagents.planning import get_planning_registry
        from semiconductor_swarm.agents.agent2_rtl.subagents.repair import get_repair_registry
        from semiconductor_swarm.agents.agent2_rtl.subagents.review import get_review_registry
        from semiconductor_swarm.agents.agent2_rtl.subagents.signoff import get_signoff_registry
        from semiconductor_swarm.agents.agent2_rtl.subagents.writers import get_writer_registry

        self.assertEqual([agent.agent_id for agent in get_intake_registry()], ["A2.01", "A2.02", "A2.03", "A2.04", "A2.05"])
        self.assertEqual([agent.agent_id for agent in get_planning_registry()], [f"A2.{index:02d}" for index in range(6, 13)])
        self.assertEqual([agent.agent_id for agent in get_writer_registry()], [f"A2.{index:02d}" for index in range(13, 28)])
        self.assertEqual([agent.agent_id for agent in get_repair_registry()], ["A2.33", "A2.34", "A2.35"])
        self.assertEqual([agent.agent_id for agent in get_manufacturing_registry()], ["A2.49", "A2.50", "A2.51"])
        self.assertEqual([agent.agent_id for agent in get_advanced_registry()], ["A2.52", "A2.53", "A2.54", "A2.55", "A2.56"])
        self.assertEqual([agent.agent_id for agent in get_signoff_registry()], [f"A2.{index:02d}" for index in range(37, 57)])
        self.assertIn("A2.28", [agent.agent_id for agent in get_review_registry()])

    def test_agent2_debug_emits_manifest_and_subgraph_trace(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        files = generate_rtl_files(spec, debug=True)
        by_name = {file["filename"]: file for file in files}

        self.assertIn("rtl_manifest.json", by_name)
        self.assertIn("repair_package.json", by_name)
        self.assertIn("release_gate.json", by_name)
        self.assertIn("agent2_subgraph_trace.json", by_name)
        self.assertIn("rtl_module_index.json", by_name)
        self.assertIn("semantic_module_index.json", by_name)
        self.assertIn("semantic_lint_report.json", by_name)
        self.assertIn("semantic_review_report.json", by_name)
        self.assertIn("tool_health_matrix.json", by_name)
        self.assertIn("synthesis_smoke_report.json", by_name)
        self.assertIn("formal_smoke_report.json", by_name)
        self.assertIn("schema_validation_report.json", by_name)
        manifest = json.loads(by_name["rtl_manifest.json"]["content"])
        repair_package = json.loads(by_name["repair_package.json"]["content"])
        release_gate = json.loads(by_name["release_gate.json"]["content"])
        trace = json.loads(by_name["agent2_subgraph_trace.json"]["content"])
        semantic_index = json.loads(by_name["semantic_module_index.json"]["content"])
        rtl_module_index = json.loads(by_name["rtl_module_index.json"]["content"])
        semantic_lint = json.loads(by_name["semantic_lint_report.json"]["content"])
        semantic_review = json.loads(by_name["semantic_review_report.json"]["content"])
        tool_health = json.loads(by_name["tool_health_matrix.json"]["content"])
        synthesis_smoke = json.loads(by_name["synthesis_smoke_report.json"]["content"])
        formal_smoke = json.loads(by_name["formal_smoke_report.json"]["content"])
        schema_validation = json.loads(by_name["schema_validation_report.json"]["content"])

        self.assertEqual(manifest["schema_version"], "agent2.rtl_manifest.v1")
        self.assertEqual(manifest["project"], "iot_camera")
        self.assertEqual(manifest["top_module"], "iot_camera_top")
        self.assertEqual(manifest["blocks"], [block["name"] for block in spec["ip_blocks"]])
        self.assertEqual(manifest["milestone"], "AGENT_2_V2.6_MG")
        self.assertEqual(manifest["subagent_count"], 53)
        self.assertEqual(manifest["available_subagent_count"], 56)
        self.assertEqual(manifest["available_subagent_ids"], [f"A2.{index:02d}" for index in range(1, 57)])
        self.assertEqual(manifest["review_stage"]["agent_ids"], ["A2.28", "A2.29", "A2.31", "A2.32"])
        self.assertEqual(manifest["review_stage"]["repair_max_iterations"], 3)
        self.assertIn("iot_camera_top.sv", manifest["files"])
        self.assertIn("compile_order_hash", manifest)
        self.assertEqual(manifest["handoff_artifacts"]["repair_package"], "repair_package.json")
        self.assertEqual(manifest["handoff_artifacts"]["release_gate"], "release_gate.json")
        self.assertEqual(repair_package["schema_version"], "agent2.repair_package.v1")
        self.assertTrue(repair_package["closed"])
        self.assertEqual(repair_package["open_findings"], [])
        self.assertEqual(release_gate["schema_version"], "agent2.release_gate.v1")
        self.assertTrue(release_gate["pass"])
        self.assertTrue(release_gate["handoff_ready"])
        self.assertEqual(release_gate["blocking_agent_ids"], [])
        self.assertEqual(manifest["pattern_manifest"]["manifest_path"], "patterns/pattern_manifest.yaml")
        self.assertIn("file_section_owners", manifest)
        self.assertEqual(manifest["file_section_owners"]["iot_camera_top.sv"][0]["owner_agent"], "A2.24 Top-Level Integrator")
        self.assertTrue(any(item["agent_id"] == "A2.15" for item in manifest["skipped_capabilities"]))

        self.assertEqual(trace["schema_version"], "agent2.subgraph_trace.v1")
        self.assertEqual(trace["milestone"], "AGENT_2_V2.6_MG")
        self.assertEqual(len(trace["ordered_agent_ids"]), 53)
        self.assertEqual(trace["ordered_agent_ids"][:21], [f"A2.{index:02d}" for index in range(1, 22)])
        self.assertEqual(trace["ordered_agent_ids"][-8:], ["A2.49", "A2.50", "A2.51", "A2.52", "A2.53", "A2.54", "A2.55", "A2.56"])
        self.assertTrue(all(result["pass"] for result in trace["results"]))
        self.assertEqual(semantic_index["schema_version"], "agent2.semantic_module_index.v1")
        self.assertEqual(rtl_module_index, semantic_index)
        self.assertIn("rtl_module_index.json", semantic_index["artifact_aliases"])
        self.assertEqual(semantic_index["duplicate_modules"], [])
        self.assertEqual(semantic_index["unresolved_instances"], [])
        self.assertGreaterEqual(semantic_index["module_count"], len(spec["ip_blocks"]) + 1)
        indexed_modules = {module["module_name"] for module in semantic_index["modules"]}
        self.assertIn("iot_camera_top", indexed_modules)
        top_entry = next(module for module in semantic_index["modules"] if module["module_name"] == "iot_camera_top")
        self.assertGreaterEqual(len(top_entry["ports"]), 3)
        self.assertGreaterEqual(len(top_entry["instances"]), len(spec["ip_blocks"]))
        self.assertGreaterEqual(len(semantic_index["dependency_edges"]), len(spec["ip_blocks"]))
        self.assertEqual(semantic_lint["schema_version"], "agent2.semantic_lint_report.v1")
        self.assertTrue(semantic_lint["pass"], semantic_lint["findings"])
        self.assertIn("apb_pinout", semantic_lint["rules"])
        self.assertIn("duplicate_modules", semantic_lint["rules"])
        self.assertIn("unresolved_instances", semantic_lint["rules"])
        self.assertEqual(semantic_review["schema_version"], "agent2.semantic_review_report.v1")
        self.assertEqual(semantic_review["milestone"], "AGENT_2_V3.4_ME")
        self.assertEqual(semantic_review["reviewers"], ["apb_protocol", "reset_coverage", "width_mismatch", "x_propagation"])
        self.assertIn("sva_targets", semantic_review)
        self.assertEqual(semantic_review["coverage_matrix"]["schema_version"], "agent2.semantic_review_coverage_matrix.v1")
        self.assertIn("setup_access_intent", semantic_review["coverage_matrix"]["apb_protocol"])
        self.assertIn("polarity_consistency", semantic_review["coverage_matrix"]["reset_coverage"])
        self.assertIn("param_width_propagation", semantic_review["coverage_matrix"]["width_mismatch"])
        self.assertIn("enum_packed_width_risk", semantic_review["coverage_matrix"]["width_mismatch"])
        self.assertIn("packed_struct_width_risk", semantic_review["coverage_matrix"]["width_mismatch"])
        self.assertEqual(semantic_review["reset_waiver_policy"]["schema_version"], "agent2.reset_waiver_policy.v1")
        self.assertIn("waivers_required", semantic_review["reset_waiver_policy"])
        self.assertGreaterEqual(semantic_review["module_count"], len(spec["ip_blocks"]) + 1)
        self.assertEqual(tool_health["schema_version"], "agent2.tool_health_matrix.v1")
        self.assertEqual(set(tool_health["valid_statuses"]), {"missing", "healthy", "broken", "degraded"})
        self.assertEqual(set(tool_health["tools"]), {"verilator", "yosys", "symbiyosys"})
        for tool in tool_health["tools"].values():
            self.assertIn(tool["status"], tool_health["valid_statuses"])
            self.assertIn("provenance", tool)
        self.assertEqual(synthesis_smoke["schema_version"], "agent2.synthesis_smoke_report.v1")
        self.assertEqual(formal_smoke["schema_version"], "agent2.formal_smoke_report.v1")
        for smoke in [synthesis_smoke, formal_smoke]:
            self.assertIn(smoke["tool_status"], tool_health["valid_statuses"])
            self.assertIn("fallback_provenance", smoke)
            self.assertIn("provenance", smoke)
            self.assertIn("blocking_findings", smoke)
            if smoke["ran"]:
                self.assertIsNone(smoke["fallback_provenance"])
            else:
                self.assertFalse(smoke["pass"])
                self.assertIsNotNone(smoke["fallback_provenance"])
        self.assertEqual(schema_validation["schema_version"], "agent2.schema_validation_report.v1")
        self.assertEqual(schema_validation["milestone"], "AGENT_2_V3.5_MF")
        self.assertTrue(schema_validation["valid"], schema_validation["findings"])
        checked_names = {item["artifact"] for item in schema_validation["checked_artifacts"]}
        self.assertIn("rtl_manifest.json", checked_names)
        self.assertIn("semantic_review_report.json", checked_names)
        self.assertEqual(schema_validation["blocking_findings"], [])

    def test_agent2_v4_phase1_emits_industrial_signoff_artifacts(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        files = generate_rtl_files(spec, debug=True)
        by_name = {file["filename"]: file for file in files}

        for filename in [
            "compile_order.f",
            "compile_order_report.json",
            "ast_dependency_graph.json",
            "strict_eda_report.json",
            "verilator_lint_report.json",
            "yosys_synth_report.json",
            "csr_codegen_report.json",
            "csr_integration_report.json",
            "peakrdl_regblock_provenance.json",
            "agent2_handoff_bundle.json",
            "pattern_coverage_report.json",
            "semantic_deep_report.json",
            "rtl_style_report.json",
            "protocol_contract_report.json",
            "cdc_rdc_screen_report.json",
            "upf_consistency_report.json",
            "interface_contracts.sv",
        ]:
            self.assertIn(filename, by_name)

        compile_order = by_name["compile_order.f"]["content"].strip().splitlines()
        compile_report = json.loads(by_name["compile_order_report.json"]["content"])
        ast_graph = json.loads(by_name["ast_dependency_graph.json"]["content"])
        strict = json.loads(by_name["strict_eda_report.json"]["content"])
        verilator = json.loads(by_name["verilator_lint_report.json"]["content"])
        yosys = json.loads(by_name["yosys_synth_report.json"]["content"])
        csr = json.loads(by_name["csr_codegen_report.json"]["content"])
        csr_integration = json.loads(by_name["csr_integration_report.json"]["content"])
        peakrdl = json.loads(by_name["peakrdl_regblock_provenance.json"]["content"])
        handoff = json.loads(by_name["agent2_handoff_bundle.json"]["content"])
        pattern = json.loads(by_name["pattern_coverage_report.json"]["content"])
        semantic_deep = json.loads(by_name["semantic_deep_report.json"]["content"])
        style = json.loads(by_name["rtl_style_report.json"]["content"])
        protocol = json.loads(by_name["protocol_contract_report.json"]["content"])
        cdc_rdc = json.loads(by_name["cdc_rdc_screen_report.json"]["content"])
        upf = json.loads(by_name["upf_consistency_report.json"]["content"])
        schema_validation = json.loads(by_name["schema_validation_report.json"]["content"])

        self.assertEqual(compile_report["schema_version"], "agent2.compile_order_report.v1")
        self.assertTrue(compile_report["pass"])
        self.assertEqual(compile_report["compile_order"], compile_order)
        self.assertEqual(compile_report["compile_order_file"], "compile_order.f")
        self.assertEqual(len(compile_report["compile_order_hash"]), 64)
        self.assertTrue(compile_order[0].endswith("_pkg.sv"))
        self.assertTrue(compile_order[-1].endswith("_top.sv"))
        self.assertEqual(ast_graph["schema_version"], "agent2.ast_dependency_graph.v1")
        self.assertEqual(ast_graph["source"], "regex_ast_dependency_extractor")
        self.assertGreaterEqual(len(ast_graph["nodes"]), len(spec["ip_blocks"]) + 1)
        self.assertGreaterEqual(len(ast_graph["edges"]), len(spec["ip_blocks"]))
        self.assertEqual(strict["schema_version"], "agent2.strict_eda_report.v1")
        self.assertFalse(strict["requires_real_tools"])
        self.assertFalse(strict["fallback_forbidden"])
        self.assertTrue(strict["pass"])
        for report, expected_tool in [(verilator, "verilator"), (yosys, "yosys")]:
            self.assertEqual(report["tool"], expected_tool)
            self.assertIn(report["tool_status"], {"missing", "healthy", "broken", "degraded"})
            self.assertIn("environment", report)
            self.assertIn("blocking_findings", report)
        self.assertEqual(csr["schema_version"], "agent2.csr_codegen_report.v1")
        self.assertEqual(csr["generator"], "deterministic_agent2_csr_stub")
        self.assertTrue(csr["pass"])
        self.assertEqual(csr_integration["schema_version"], "agent2.csr_integration_report.v1")
        self.assertEqual(csr_integration["csr_codegen_report"], "csr_codegen_report.json")
        self.assertGreaterEqual(len(csr_integration["rtl_files_checked"]), len(spec["ip_blocks"]) + 1)
        self.assertEqual(peakrdl["schema_version"], "agent2.peakrdl_regblock_provenance.v1")
        self.assertEqual(peakrdl["project"], "iot_camera")
        self.assertTrue(peakrdl["fallback"])
        self.assertEqual(handoff["schema_version"], "agent2.handoff_bundle.v2")
        self.assertEqual(handoff["project"], "iot_camera")
        self.assertEqual(handoff["compile_order_file"], "compile_order.f")
        self.assertEqual(handoff["compile_order"], compile_order)
        self.assertEqual(handoff["evidence"]["strict_eda_report"], "strict_eda_report.json")
        self.assertEqual(handoff["evidence"]["peakrdl_regblock_provenance"], "peakrdl_regblock_provenance.json")
        self.assertEqual(handoff["agent3_bundle"]["compile_order"], "compile_order.f")
        self.assertEqual(handoff["agent4_bundle"]["tool_evidence"]["compile_order_report"], "compile_order_report.json")
        self.assertEqual(handoff["agent5_bundle"]["tool_evidence"]["ast_dependency_graph"], "ast_dependency_graph.json")
        self.assertTrue(handoff["pass"])
        self.assertEqual(pattern["schema_version"], "agent2.pattern_coverage_report.v1")
        self.assertTrue(pattern["pass"], pattern["blocking_findings"])
        self.assertIn("apb", {item["pattern_id"] for item in pattern["requirements"]})
        self.assertEqual(semantic_deep["schema_version"], "agent2.semantic_deep_report.v1")
        self.assertTrue(semantic_deep["pass"], semantic_deep["blocking_findings"])
        self.assertEqual(style["schema_version"], "agent2.rtl_style_report.v1")
        self.assertTrue(style["pass"], style["blocking_findings"])
        self.assertEqual(protocol["schema_version"], "agent2.protocol_contract_report.v1")
        self.assertEqual(protocol["contract_file"], "interface_contracts.sv")
        self.assertEqual(cdc_rdc["schema_version"], "agent2.cdc_rdc_screen_report.v1")
        self.assertTrue(cdc_rdc["pass"], cdc_rdc["blocking_findings"])
        self.assertEqual(upf["schema_version"], "agent2.upf_consistency_report.v1")
        self.assertIn("apb_access_eventually_ready", by_name["interface_contracts.sv"]["content"])
        checked_names = {item["artifact"] for item in schema_validation["checked_artifacts"]}
        for filename in ["compile_order_report.json", "strict_eda_report.json", "agent2_handoff_bundle.json", "pattern_coverage_report.json", "semantic_deep_report.json", "rtl_style_report.json", "protocol_contract_report.json", "cdc_rdc_screen_report.json", "upf_consistency_report.json"]:
            self.assertIn(filename, checked_names)

    def test_agent2_v4_phase2_reports_block_semantic_gaps(self):
        spec = {"project_name": "semantic_gap", "interfaces": {"apb_slave": {"signals": []}}, "ip_blocks": [{"name": "interrupt_ctrl"}, {"name": "sram_controller"}]}
        files = [{"filename": "semantic_gap_top.sv", "language": "systemverilog", "content": "module semantic_gap_top(input logic clk_i, input logic rst_ni); always_ff @(posedge clk_i) begin end endmodule\n", "line_count": 1, "dependencies": []}]
        tool_health = {"swarm_mode": "demo", "requires_real_tools": False, "tools": {"verilator": {"status": "missing"}, "yosys": {"status": "missing"}}, "real_tool_gate": {"pass": True}}

        artifacts = build_phase1_artifacts(spec, files, {}, tool_health)

        self.assertFalse(artifacts["pattern_coverage_report"]["pass"])
        self.assertTrue(any(item["pattern_id"] == "w1c" for item in artifacts["pattern_coverage_report"]["blocking_findings"]))
        self.assertTrue(artifacts["semantic_deep_report"]["pass"])
        self.assertTrue(artifacts["protocol_contract_report"]["pass"])
        self.assertIn("interface_contracts", artifacts["interface_contracts_sv"])

    def test_agent2_v4_phase2_blocks_high_risk_style_and_semantic_errors(self):
        spec = {"project_name": "bad_style", "interfaces": {}, "ip_blocks": []}
        files = [{"filename": "bad_style_top.sv", "language": "systemverilog", "content": "module bad_style_top(input logic clk_i, input logic rst_ni); initial begin end always_latch begin end always_ff @(posedge clk_i) begin q = 'x; end endmodule\n", "line_count": 1, "dependencies": []}]
        tool_health = {"swarm_mode": "demo", "requires_real_tools": False, "tools": {"verilator": {"status": "missing"}, "yosys": {"status": "missing"}}, "real_tool_gate": {"pass": True}}

        artifacts = build_phase1_artifacts(spec, files, {}, tool_health)

        self.assertFalse(artifacts["rtl_style_report"]["pass"])
        self.assertTrue(any(item["rule"] == "initial_block" for item in artifacts["rtl_style_report"]["blocking_findings"]))
        self.assertFalse(artifacts["semantic_deep_report"]["pass"])
        self.assertTrue(any(item["rule"] == "no_x_assignment" for item in artifacts["semantic_deep_report"]["blocking_findings"]))

    def test_agent2_v4_phase2_keeps_implicit_net_risk_non_blocking(self):
        spec = {"project_name": "style_warn", "interfaces": {}, "ip_blocks": []}
        files = [{"filename": "style_warn_top.sv", "language": "systemverilog", "content": "module style_warn_top(input logic clk_i, input logic rst_ni);\n  logic tmp;\n  always_ff @(posedge clk_i) if (!rst_ni) tmp <= 1'b0; else tmp <= 1'b1;\nendmodule\n", "line_count": 4, "dependencies": []}]
        tool_health = {"swarm_mode": "demo", "requires_real_tools": False, "tools": {"verilator": {"status": "missing"}, "yosys": {"status": "missing"}}, "real_tool_gate": {"pass": True}}

        artifacts = build_phase1_artifacts(spec, files, {}, tool_health)

        self.assertTrue(artifacts["rtl_style_report"]["pass"], artifacts["rtl_style_report"]["blocking_findings"])
        self.assertTrue(any(item["rule"] == "implicit_net_risk" and item["severity"] == "medium" for item in artifacts["rtl_style_report"]["findings"]))

    def test_agent2_v4_phase1_strict_mode_blocks_missing_real_tools(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        files = generate_rtl_files(spec)
        tool_health = {
            "swarm_mode": "strict",
            "requires_real_tools": True,
            "blocking_findings": [{"severity": "error", "tool": "verilator", "message": "missing verilator"}],
            "real_tool_gate": {"pass": False, "blocking_findings": [{"severity": "error", "tool": "yosys", "message": "missing yosys"}]},
            "tools": {"verilator": {"status": "missing"}, "yosys": {"status": "missing"}},
        }

        artifacts = build_phase1_artifacts(spec, files, {}, tool_health)

        self.assertFalse(artifacts["strict_eda_report"]["pass"])
        self.assertTrue(artifacts["strict_eda_report"]["fallback_forbidden"])
        self.assertFalse(artifacts["agent2_handoff_bundle"]["pass"])
        self.assertGreaterEqual(len(artifacts["agent2_handoff_bundle"]["blocking_findings"]), 2)

    def test_agent2_v4_phase1_compile_order_report_blocks_unresolved_instances(self):
        spec = {"project_name": "bad_chip"}
        files = [{"filename": "bad_chip_top.sv", "language": "systemverilog", "content": "module bad_chip_top; missing_ip u_missing(); endmodule\n", "line_count": 1, "dependencies": []}]
        tool_health = {"swarm_mode": "demo", "requires_real_tools": False, "tools": {"verilator": {"status": "missing"}, "yosys": {"status": "missing"}}, "real_tool_gate": {"pass": True}}

        artifacts = build_phase1_artifacts(spec, files, {}, tool_health)

        self.assertFalse(artifacts["compile_order_report"]["pass"])
        self.assertEqual(artifacts["compile_order_report"]["blocking_findings"][0]["rule"], "unresolved_instance")
        self.assertFalse(artifacts["agent2_handoff_bundle"]["pass"])

    def test_agent2_v35_schema_validation_blocks_missing_required_keys(self):
        result = validate_payload("rtl_manifest.json", {"schema_version": "agent2.rtl_manifest.v1"})

        self.assertFalse(result["valid"])
        self.assertTrue(any(finding["key"] == "project" for finding in result["findings"]))

    def test_agent2_v35_schema_validation_blocks_type_mismatch(self):
        result = validate_payload("semantic_lint_report.json", {"schema_version": "agent2.semantic_lint_report.v1", "pass": "yes", "rules": [], "findings": []})

        self.assertFalse(result["valid"])
        self.assertTrue(any(finding["rule"] == "type" and finding["key"] == "pass" for finding in result["findings"]))

    def test_agent2_v35_schema_files_exist_for_prompt_critical_artifacts(self):
        for filename in ["rtl_manifest.schema.json", "agent2_subgraph_trace.schema.json", "semantic_review_report.schema.json"]:
            self.assertTrue((SCHEMA_DIR / filename).exists(), filename)

    def test_agent2_v35_schema_validation_uses_jsonschema_when_available(self):
        result = validate_payload("rtl_manifest.json", {"schema_version": "agent2.rtl_manifest.v1", "project": 7, "top_module": "demo_top", "files": [], "handoff_artifacts": {}})

        self.assertFalse(result["valid"])
        if "validator" in result:
            self.assertEqual(result["validator"], "jsonschema")
            self.assertIn("schema_file", result)
            self.assertTrue(any(finding["key"] == "project" for finding in result["findings"]))
        else:
            self.assertTrue(any(finding["rule"] == "type" and finding["key"] == "project" for finding in result["findings"]))

    def test_agent2_v35_schema_validation_report_collects_blocking_findings(self):
        files = [{"filename": "rtl_manifest.json", "language": "json", "content": json.dumps({"schema_version": "agent2.rtl_manifest.v1"}), "line_count": 1, "dependencies": []}]
        report = build_schema_validation_report(files)

        self.assertFalse(report["valid"])
        self.assertEqual(report["schema_version"], "agent2.schema_validation_report.v1")
        self.assertTrue(report["blocking_findings"])

    def test_agent2_milestone_d_emits_formal_dv_and_ppa_handoff_files(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        files = generate_rtl_files(spec, debug=True)
        by_name = {file["filename"]: file for file in files}

        self.assertIn("formal_hooks.json", by_name)
        self.assertIn("dv_hooks.json", by_name)
        self.assertIn("ppa_handoff.json", by_name)

        manifest = json.loads(by_name["rtl_manifest.json"]["content"])
        formal_hooks = json.loads(by_name["formal_hooks.json"]["content"])
        dv_hooks = json.loads(by_name["dv_hooks.json"]["content"])
        ppa_handoff = json.loads(by_name["ppa_handoff.json"]["content"])

        self.assertEqual(formal_hooks["schema_version"], "agent2.formal_hooks.v1")
        self.assertEqual(dv_hooks["schema_version"], "agent2.dv_hooks.v1")
        self.assertEqual(ppa_handoff["schema_version"], "agent2.ppa_handoff.v1")
        self.assertEqual(len(formal_hooks["hooks"]), len(spec["ip_blocks"]))
        self.assertEqual(len(dv_hooks["hooks"]), len(spec["ip_blocks"]))
        self.assertEqual(manifest["handoff_artifacts"]["formal_hooks"], "formal_hooks.json")
        self.assertEqual(manifest["agent4_constraints"]["top_module"], "iot_camera_top")
        self.assertEqual(manifest["agent4_constraints"]["target_mhz"], float(spec["core_config"]["frequency_mhz"]))
        self.assertEqual(ppa_handoff["agent4_constraints"]["compile_order_hash"], manifest["compile_order_hash"])

    def test_agent2_v34_semantic_review_closes_apb_reset_width_plan_bullets(self):
        spec = {"project_name": "demo"}
        module_index = {
            "module_count": 1,
            "modules": [{
                "module_name": "demo_regs",
                "filename": "demo_regs.sv",
                "parameters": [{"name": "ADDR_WIDTH", "default": "DATA_WIDTH"}],
                "ports": [
                    {"name": "clk_i", "direction": "input", "width": "1"},
                    {"name": "rst_ni", "direction": "input", "width": "1"},
                    {"name": "paddr_i", "direction": "input", "width": "[7:0]"},
                    {"name": "psel_i", "direction": "input", "width": "1"},
                    {"name": "penable_i", "direction": "input", "width": "1"},
                    {"name": "pwrite_i", "direction": "input", "width": "1"},
                    {"name": "pwdata_i", "direction": "input", "width": "[31:0]"},
                    {"name": "prdata_o", "direction": "output", "width": "[31:0]"},
                    {"name": "pready_o", "direction": "output", "width": "1"},
                    {"name": "pslverr_o", "direction": "output", "width": "1"},
                ],
                "content": """
module demo_regs;
  typedef enum {IDLE, BUSY} state_e;
  typedef struct packed { logic valid; logic [7:0] data; } packet_t;
  logic [7:0] narrow_q;
  logic [31:0] wide_q;
  always_ff @(posedge clk_i or posedge rst_ni) begin
    if (rst_ni) begin
      wide_q <= narrow_q;
    end else begin
      narrow_q <= paddr_i;
    end
  end
  assign pready_o = 1'b1;
endmodule
""",
            }],
        }

        report = build_semantic_review_report(spec, module_index)
        rules = {finding["rule"] for finding in report["findings"]}

        self.assertEqual(report["coverage_matrix"]["schema_version"], "agent2.semantic_review_coverage_matrix.v1")
        self.assertIn("setup_access_intent", report["coverage_matrix"]["apb_protocol"])
        self.assertIn("unreset_register_waiver_policy", report["coverage_matrix"]["reset_coverage"])
        self.assertIn("param_width_propagation", report["coverage_matrix"]["width_mismatch"])
        self.assertIn("apb_setup_access_intent", rules)
        self.assertIn("reset_polarity_consistency", rules)
        self.assertIn("reset_coverage", rules)
        self.assertIn("param_width_propagation", rules)
        self.assertIn("enum_packed_width_risk", rules)
        self.assertIn("packed_struct_width_risk", rules)
        self.assertIn("width_mismatch", rules)
        self.assertEqual(report["reset_waiver_policy"]["waiver_count"], 2)
        self.assertEqual(report["reset_waiver_policy"]["waivers_required"][0]["status"], "required_if_not_reset")

    def test_agent2_milestone_c_deterministically_skips_unavailable_capabilities(self):
        spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
        files = generate_rtl_files(spec, debug=True)
        trace = json.loads(next(file for file in files if file["filename"] == "agent2_subgraph_trace.json")["content"])
        by_id = {result["agent_id"]: result for result in trace["results"]}

        self.assertTrue(by_id["A2.15"]["artifacts"]["skipped"])
        self.assertEqual(by_id["A2.15"]["artifacts"]["skip_reason"], "capability_not_requested")
        self.assertTrue(by_id["A2.16"]["artifacts"]["skipped"])
        self.assertTrue(by_id["A2.17"]["artifacts"]["skipped"])

    def test_agent2_milestone_b_emits_formal_and_dv_hooks(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        files = generate_rtl_files(spec, debug=True)
        trace = json.loads(next(file for file in files if file["filename"] == "agent2_subgraph_trace.json")["content"])
        by_id = {result["agent_id"]: result for result in trace["results"]}

        self.assertEqual(len(by_id["A2.31"]["artifacts"]["formal_hooks"]), len(spec["ip_blocks"]))
        self.assertEqual(len(by_id["A2.32"]["artifacts"]["dv_hooks"]), len(spec["ip_blocks"]))
        self.assertIn("reset_clears_state", by_id["A2.31"]["artifacts"]["formal_hooks"][0]["targets"])
        self.assertIn("apb_write_readback", by_id["A2.32"]["artifacts"]["dv_hooks"][0]["tests"])

    def test_agent2_repair_loop_patches_bad_rtl_and_emits_trace(self):
        spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")

        def bad_generator(input_spec, debug=False):
            files = generate_rtl_files(input_spec, debug=False)
            files[0]["content"] += "\n// TODO: injected placeholder\n"
            files[0]["line_count"] = len(files[0]["content"].rstrip("\n").splitlines())
            return files

        files = run_agent2_orchestrator(spec, debug=True, legacy_generator=bad_generator)
        by_name = {file["filename"]: file for file in files}
        trace = json.loads(by_name["agent2_subgraph_trace.json"]["content"])
        repair = json.loads(by_name["repair_trace.json"]["content"])

        self.assertIn("repair_trace.json", by_name)
        self.assertLessEqual(len(repair["iterations"]), 3)
        self.assertFalse(next(result for result in trace["results"] if result["agent_id"] == "A2.28")["pass"])
        self.assertTrue(repair["iterations"][-1]["post_review"]["pass"])
        self.assertNotIn("TODO", "\n".join(file["content"] for file in files if file["language"] == "systemverilog"))

    def test_agent2_v4_phase3_repair_report_classifies_patches_and_gates(self):
        spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")

        def bad_generator(input_spec, debug=False):
            files = generate_rtl_files(input_spec, debug=False)
            files[0]["content"] += "\n// TODO: injected placeholder\n"
            files[0]["line_count"] = len(files[0]["content"].rstrip("\n").splitlines())
            return files

        files = run_agent2_orchestrator(spec, debug=True, legacy_generator=bad_generator)
        by_name = {file["filename"]: file for file in files}
        report = json.loads(by_name["repair_v4_report.json"]["content"])
        trace = json.loads(by_name["repair_trace.json"]["content"])

        self.assertEqual(report["schema_version"], "agent2.repair_v4_report.v1")
        self.assertEqual(report["milestone"], "AGENT_2_V4_PHASE3_INDUSTRIAL_REPAIR")
        self.assertTrue(report["pass"])
        self.assertTrue(report["repair_ran"])
        self.assertGreaterEqual(report["classification"]["counts"]["synthesizability"], 1)
        self.assertGreaterEqual(len(report["patches"]), 1)
        self.assertEqual(report["patches"][0]["change_type"], "content_update")
        self.assertEqual(len(report["patches"][0]["pre_sha256"]), 64)
        self.assertEqual(len(report["patches"][0]["post_sha256"]), 64)
        self.assertTrue(report["rerun_matrix"]["pass"])
        self.assertEqual(report["rerun_matrix"]["rerun_scope"], "failed_review_agents_plus_full_review_stage")
        self.assertTrue(report["lec"]["required"])
        self.assertTrue(report["lec"]["pass"])
        self.assertFalse(report["rollback"]["rollback_required"])
        self.assertEqual(report["hitl_gate"]["status"], "not_required")
        self.assertEqual(trace["iterations"][-1]["patches"], report["patches"])

        schema_report = json.loads(by_name["schema_validation_report.json"]["content"])
        self.assertTrue(any(item["artifact"] == "repair_v4_report.json" and item["valid"] for item in schema_report["checked_artifacts"]))

    def test_required_golden_patterns_are_synthesizable(self):
        root = Path(__file__).resolve().parents[1]
        required = [
            root / "patterns" / "pattern_apb_slave_register_file.sv",
            root / "patterns" / "pattern_sync_reset_pipeline.sv",
        ]
        for path in required:
            self.assertTrue(path.exists(), path)
            text = path.read_text(encoding="utf-8")
            self.assertIn("AGENT2_PATTERN_ID:", text)
            self.assertIn("always_ff", text)
            self.assertIn("always_comb", text)
            self.assertNotIn("$display", text)
            self.assertNotIn("initial begin", text)
            self.assertNotIn("#delay", text)

    def test_agent2_writers_read_required_golden_patterns(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        files = generate_rtl_files(spec, debug=True)
        trace = json.loads(next(file for file in files if file["filename"] == "agent2_subgraph_trace.json")["content"])
        by_id = {result["agent_id"]: result for result in trace["results"]}

        self.assertEqual(by_id["A2.13"]["artifacts"]["pattern_path"], "patterns\\pattern_apb_slave_register_file.sv" if "\\" in by_id["A2.13"]["artifacts"]["pattern_path"] else "patterns/pattern_apb_slave_register_file.sv")
        self.assertEqual(by_id["A2.14"]["artifacts"]["pattern_path"], "patterns\\pattern_sync_reset_pipeline.sv" if "\\" in by_id["A2.14"]["artifacts"]["pattern_path"] else "patterns/pattern_sync_reset_pipeline.sv")
        self.assertTrue(by_id["A2.13"]["artifacts"]["read_ok"])
        self.assertTrue(by_id["A2.14"]["artifacts"]["read_ok"])
        self.assertEqual(len(by_id["A2.13"]["artifacts"]["pattern_sha256"]), 64)
        self.assertEqual(len(by_id["A2.14"]["artifacts"]["pattern_sha256"]), 64)

    def test_agent2_uses_golden_pattern_manifest_and_rag_stub(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        manifest = pattern_manifest(spec)
        context = retrieve_agent2_context(spec)

        self.assertEqual(manifest["manifest_path"], "patterns/pattern_manifest.yaml")
        self.assertGreaterEqual(manifest["pattern_count"], 4)
        self.assertGreaterEqual(len(context["documents"]), 4)
        self.assertIn("golden-pattern::apb_slave_template", {doc["doc_id"] for doc in context["documents"]})
        self.assertIn("patterns/apb_slave_template.sv", {doc["doc_id"] for doc in context["documents"]})

    def test_agent2_query_rtl_knowledge_base_returns_local_patterns(self):
        docs = query_rtl_knowledge_base("Need APB slave and FIFO buffering", ["apb", "fifo"])
        doc_ids = {doc["doc_id"] for doc in docs}

        self.assertIn("patterns/apb_slave_template.sv", doc_ids)
        self.assertIn("patterns/sync_fifo_template.sv", doc_ids)
        for doc in docs:
            self.assertIn("AGENT2_PATTERN_ID:", doc["content"])

    def test_plan_compatible_rag_stub_returns_string_content(self):
        content = query_plan_rtl_knowledge_base("APB slave register skeleton and FIFO", ["apb", "fifo"])

        self.assertIsInstance(content, str)
        self.assertIn("AGENT2_PATTERN_ID: apb_slave_template", content)
        self.assertIn("AGENT2_PATTERN_ID: sync_fifo_template", content)

    def test_plan_compatible_rtl_linter_report_schema(self):
        spec = generate_architecture_spec("Mạch đếm Counter 16-bit giao tiếp APB", "counter16_apb")
        files = generate_rtl_files(spec)
        report = lint_plan_rtl_files(files)

        self.assertTrue(report["pass"], report["failures"])
        self.assertIn(report["tool"], {"verilator", "static_fallback"})
        self.assertIn("command", report)
        self.assertIn("files_checked", report)
        self.assertIn("stdout", report)
        self.assertIn("stderr", report)

    def test_agent2_static_linter_detects_placeholder(self):
        spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
        files = generate_rtl_files(spec)
        files[0]["content"] += "\n// TODO: placeholder\n"
        report = verify_rtl_files(spec, files)

        self.assertFalse(report["pass"])
        self.assertFalse(report["checks"]["static_rtl_linter_pass"])

    def test_top_level_instantiates_all_blocks_and_wires_interrupts(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        files = generate_rtl_files(spec)
        top = next(file for file in files if file["filename"] == "iot_camera_top.sv")["content"]

        for block in [block["name"] for block in spec["ip_blocks"]]:
            self.assertIn(f"u_{block}", top)
            self.assertIn(f"iot_camera_{block}_rtl", top)
        self.assertIn("irq_o", top)
        self.assertIn("irq_sources", top)

    def test_verify_rtl_files_detects_prompt_rule_violation(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
        files = generate_rtl_files(spec)
        files[0]["content"] += "\ninitial begin end\n"
        report = verify_rtl_files(spec, files)

        self.assertFalse(report["pass"])
        self.assertFalse(report["checks"]["no_forbidden_rtl_tokens"])

    def test_agent2_rejects_port_renaming_allowed(self):
        spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
        spec["constraints"]["agent2_port_renaming_allowed"] = True

        with self.assertRaises(ValueError):
            generate_rtl_files(spec)

    def test_agent2_v25_mf_dft_upf_macro_handoff(self):
        spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz with SRAM ASIC DFT", "iot_camera")
        spec["constraints"]["target_flow"] = "asic_ready"
        spec["constraints"]["dft_enabled"] = True
        spec["constraints"]["pll_required"] = True
        spec["constraints"]["power_intent"] = {
            "power_domains": [{"name": "PD_CORE", "elements": ["iot_camera_top"], "primary": True}],
            "supply_nets": [{"name": "VDD", "type": "power"}, {"name": "VSS", "type": "ground"}],
        }
        files = generate_rtl_files(spec, debug=True)
        by_name = {file["filename"]: file for file in files}

        self.assertIn("dft_hooks.json", by_name)
        self.assertIn("upf_manifest.json", by_name)
        self.assertIn("macro_wrappers.json", by_name)
        self.assertIn("power_intent.upf", by_name)
        dft = json.loads(by_name["dft_hooks.json"]["content"])
        upf = json.loads(by_name["upf_manifest.json"]["content"])
        macros = json.loads(by_name["macro_wrappers.json"]["content"])
        trace = json.loads(by_name["agent2_subgraph_trace.json"]["content"])
        manifest = json.loads(by_name["rtl_manifest.json"]["content"])

        self.assertEqual(trace["milestone"], "AGENT_2_V2.6_MG")
        self.assertIn("A2.49", trace["ordered_agent_ids"])
        self.assertIn("A2.50", trace["ordered_agent_ids"])
        self.assertIn("A2.51", trace["ordered_agent_ids"])
        self.assertTrue(dft["dft_enabled"])
        self.assertEqual(dft["scan_cell_policy"], "placeholder_ports_only_no_foundry_scan_cells")
        self.assertEqual(upf["mode"], "asic_ready")
        self.assertEqual(upf["power_domains"][0]["name"], "PD_CORE")
        self.assertGreaterEqual(len(macros["wrappers"]), 1)
        self.assertIn("create_power_domain PD_CORE", by_name["power_intent.upf"]["content"])
        self.assertEqual(manifest["milestone"], "AGENT_2_V2.6_MG")
        self.assertEqual(manifest["subagent_count"], 53)
        self.assertEqual(manifest["manufacturing_handoff"]["agent_ids"], ["A2.49", "A2.50", "A2.51", "A2.52", "A2.53", "A2.54", "A2.55", "A2.56"])

    def test_agent2_v25_mf_dft_disabled_and_upf_stub_safe(self):
        spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
        files = generate_rtl_files(spec, debug=True)
        by_name = {file["filename"]: file for file in files}
        dft = json.loads(by_name["dft_hooks.json"]["content"])
        upf = json.loads(by_name["upf_manifest.json"]["content"])

        self.assertFalse(dft["dft_enabled"])
        self.assertEqual(dft["safe_tieoffs"]["scan_enable"], "1'b0")
        self.assertEqual(dft["safe_tieoffs"]["test_mode"], "1'b0")
        self.assertEqual(dft["dft_ready_ports"], [])
        self.assertEqual(upf["mode"], "fpga_safe_stub")
        self.assertIn("missing_or_partial_power_intent_single_domain_stub_emitted", upf["warnings"])

    def test_agent2_v26_mg_advanced_manifests(self):
        spec = generate_architecture_spec("Radiation hardened multicore AI camera with SRAM MAC HLS block", "iot_camera")
        spec["constraints"].update({
            "radiation_hardening": "full",
            "protected_blocks": ["interrupt_ctrl"],
            "noc_enabled": True,
            "coherency_enabled": True,
            "hls_blocks": ["mac_array"],
        })
        files = generate_rtl_files(spec, debug=True)
        by_name = {file["filename"]: file for file in files}

        for filename in ["fault_tolerance_manifest.json", "noc_coherency_manifest.json", "dse_manifest.json", "hls_bridge_manifest.json", "eco_intent.json"]:
            self.assertIn(filename, by_name)

        fault = json.loads(by_name["fault_tolerance_manifest.json"]["content"])
        noc = json.loads(by_name["noc_coherency_manifest.json"]["content"])
        dse = json.loads(by_name["dse_manifest.json"]["content"])
        hls = json.loads(by_name["hls_bridge_manifest.json"]["content"])
        eco = json.loads(by_name["eco_intent.json"]["content"])
        trace = json.loads(by_name["agent2_subgraph_trace.json"]["content"])
        manifest = json.loads(by_name["rtl_manifest.json"]["content"])

        self.assertEqual(trace["milestone"], "AGENT_2_V2.6_MG")
        for agent_id in ["A2.52", "A2.53", "A2.54", "A2.55", "A2.56"]:
            self.assertIn(agent_id, trace["ordered_agent_ids"])
            self.assertIn(agent_id, manifest["available_subagent_ids"])
        self.assertTrue(fault["enabled"])
        self.assertGreaterEqual(len(fault["fault_injection_hooks"]), 1)
        self.assertIn("single_bit_flip", fault["fault_model"])
        self.assertGreaterEqual(len(fault["protection_plan"]), 1)
        self.assertIn("agent3_handoff", fault)
        self.assertIn("agent5_handoff", fault)
        self.assertTrue(noc["enabled"])
        self.assertEqual(noc["endpoint_count"], len(noc["endpoints"]))
        self.assertIn("requests_complete_in_issue_order", noc["ordering_rules"])
        self.assertEqual(noc["coherency_status"], "intent_only_requires_downstream_dv_formal_closure")
        self.assertTrue(dse["enabled"])
        self.assertIn("pipeline_depth", dse["design_space_axes"])
        self.assertGreaterEqual(len(dse["ppa_estimates"]), 1)
        self.assertEqual(hls["requested_blocks"], ["mac_array"])
        self.assertEqual(hls["tool_probe_source"], "constraints.hls_tool_present")
        self.assertEqual(hls["wrapper_interface_policy"]["control"], "apb_lite_or_axi_lite")
        self.assertTrue(eco["approval_gate_required"])
        self.assertFalse(eco["auto_apply_netlist_patches"])
        self.assertEqual(eco["owner_approval_record"]["status"], "pending")

    def test_agent2_v26_mg_strict_dod_emits_required_rtl_stubs(self):
        spec = generate_architecture_spec("Radiation hardened multicore AI camera with SRAM MAC HLS block", "iot_camera")
        spec["constraints"].update({
            "radiation_hardening": "full",
            "noc_enabled": True,
            "hls_blocks": ["mac_array"],
            "hls_tool_present": True,
            "pll_required": True,
        })
        files = generate_rtl_files(spec, debug=True)
        by_name = {file["filename"]: file for file in files}
        names = set(by_name)

        self.assertIn("iot_camera_sram_controller_secded_ecc_wrapper.sv", names)
        self.assertIn("iot_camera_noc_router_stub.sv", names)
        self.assertIn("iot_camera_mac_array_hls_wrapper_stub.sv", names)
        self.assertIn("iot_camera_sram_controller_macro_wrapper.sv", names)
        self.assertIn("iot_camera_pll_macro_wrapper.sv", names)

        ecc_rtl = by_name["iot_camera_sram_controller_secded_ecc_wrapper.sv"]["content"]
        noc_rtl = by_name["iot_camera_noc_router_stub.sv"]["content"]
        hls_rtl = by_name["iot_camera_mac_array_hls_wrapper_stub.sv"]["content"]
        self.assertIn("SECDED ECC wrapper", ecc_rtl)
        self.assertIn("AGENT2_PATTERN_ID: secded_39_32_encoder_decoder", ecc_rtl)
        self.assertIn("correctable_error_o", ecc_rtl)
        self.assertIn("corrected_data_d", ecc_rtl)
        self.assertIn("Router/crossbar skeleton", noc_rtl)
        self.assertIn("AGENT2_PATTERN_ID: simple_apb_crossbar_1m_ns", noc_rtl)
        self.assertIn("ENDPOINTS", noc_rtl)
        self.assertIn("SELECT_WIDTH", noc_rtl)
        self.assertIn("route_error_o", noc_rtl)
        self.assertIn("HLS bridge wrapper stub", hls_rtl)
        self.assertIn("control_policy: apb_lite_or_axi_lite", hls_rtl)

        hls = json.loads(by_name["hls_bridge_manifest.json"]["content"])
        self.assertTrue(hls["tool_detected"])
        self.assertEqual(hls["mode"], "tool_present_wrapper_recorded")
        self.assertEqual(hls["tool_command"], "vitis_hls -f agent2_hls_bridge.tcl")
        self.assertEqual(hls["tool_result"]["provenance"], "dry_run_manifest_only")
        self.assertFalse(hls["tool_result"]["ran"])
        self.assertEqual(hls["generated_tcl"], "agent2_hls_bridge.tcl")
        self.assertIn("iot_camera_mac_array_hls_wrapper_stub.sv", hls["generated_rtl_wrappers"])

    def test_agent2_v37_eco_derives_affected_cones_and_schema_gates(self):
        from semiconductor_swarm.agents.agent2_rtl.schema_validation import validate_payload

        spec = generate_architecture_spec("AI camera ECO request", "iot_camera")
        spec["constraints"]["eco_requests"] = [{"block": "mac_array", "reason": "timing_fix"}]
        files = generate_rtl_files(spec, debug=True)
        by_name = {file["filename"]: file for file in files}
        eco = json.loads(by_name["eco_intent.json"]["content"])

        self.assertEqual(eco["affected_cones"][0]["block"], "mac_array")
        self.assertEqual(eco["affected_cones"][0]["cone"], "mac_array_logic_cone")
        self.assertEqual(eco["affected_cones"][0]["reason"], "timing_fix")
        self.assertEqual(eco["affected_cones"][0]["derived_from"], "rtl_file_content_dependency_scan")
        self.assertIn("mac_array.sv", eco["affected_cones"][0]["affected_files"])
        self.assertEqual(eco["patch_script_skeletons"][0]["script"], "eco_patch_mac_array.tcl")
        self.assertFalse(eco["patch_script_skeletons"][0]["auto_apply"])
        self.assertIn("rollback_plan", eco)

        invalid_fault = {"schema_version": "agent2.fault_tolerance_manifest.v1", "policy": "none", "enabled": False}
        result = validate_payload("fault_tolerance_manifest.json", invalid_fault)
        self.assertFalse(result["valid"])
        self.assertIn("protection_plan", {finding.get("key") for finding in result["findings"]})

    def test_agent2_v39_release_decision_artifact_is_schema_gated(self):
        spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
        files = generate_rtl_files(spec, debug=True)
        by_name = {file["filename"]: file for file in files}

        self.assertIn("agent2_release_decision.json", by_name)
        decision = json.loads(by_name["agent2_release_decision.json"]["content"])
        manifest = json.loads(by_name["rtl_manifest.json"]["content"])
        schema_report = json.loads(by_name["schema_validation_report.json"]["content"])

        self.assertEqual(decision["schema_version"], "agent2.release_decision.v1")
        self.assertEqual(decision["milestone"], "AGENT_2_V3.9_RELEASE_DECISION")
        self.assertIn(decision["decision"], decision["allowed_decisions"])
        self.assertEqual(decision["pass"], decision["decision"] in {"pass", "pass_with_waivers"})
        self.assertEqual(decision["handoff_ready"], decision["decision"] in {"pass", "pass_with_waivers"})
        self.assertEqual(decision["tool_health_matrix"], "tool_health_matrix.json")
        self.assertEqual(decision["waiver_policy"]["required_fields"], ["owner", "reason", "expiration", "signoff"])
        self.assertEqual(manifest["handoff_artifacts"]["release_gate"], "release_gate.json")
        self.assertTrue(any(item["artifact"] == "agent2_release_decision.json" and item["valid"] for item in schema_report["checked_artifacts"]))

    def test_agent2_v39_release_decision_supports_pass_with_waivers_helper(self):
        from semiconductor_swarm.agents.agent2_rtl.orchestrator import _findings_without_waiver, _waived_findings

        findings = [{"severity": "error", "owner": "A2.37 Protocol Compliance Agent", "rule": "apb_setup_access_response_semantics", "message": "example"}]
        waivers = [{"owner": "lead", "reason": "accepted", "expiration": "2099-12-31", "signoff": "chief", "rule": "apb_setup_access_response_semantics", "valid": True}]

        self.assertEqual(_findings_without_waiver(findings, waivers), [])
        self.assertEqual(_waived_findings(findings, waivers), findings)


if __name__ == "__main__":
    unittest.main()
