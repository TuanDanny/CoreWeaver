from semiconductor_swarm.agents.agent2_rtl.phase1_artifacts import build_phase1_artifacts
from semiconductor_swarm.agents.agent2_rtl.semantic import build_rtl_module_index

from tests.agent2_v4_fixture_utils import rtl_fixture_files, v4_fixture_spec


def test_compile_order_puts_packages_interfaces_modules_top_last_for_golden_generated_like_files():
    files = [
        {"filename": "demo_top.sv", "language": "systemverilog", "content": "module demo_top; leaf u_leaf(); endmodule\n", "line_count": 1, "dependencies": []},
        {"filename": "leaf_intf.sv", "language": "systemverilog", "content": "interface leaf_intf; endinterface\n", "line_count": 1, "dependencies": []},
        {"filename": "leaf_pkg.sv", "language": "systemverilog", "content": "package leaf_pkg; endpackage\n", "line_count": 1, "dependencies": []},
        {"filename": "leaf.sv", "language": "systemverilog", "content": "module leaf; endmodule\n", "line_count": 1, "dependencies": []},
    ]
    artifacts = build_phase1_artifacts(v4_fixture_spec(), files, build_rtl_module_index(files), {"requires_real_tools": False, "swarm_mode": "demo", "tools": {}, "blocking_findings": []})

    assert artifacts["compile_order_report"]["compile_order"] == ["leaf_pkg.sv", "leaf_intf.sv", "leaf.sv", "demo_top.sv"]
    assert artifacts["compile_order_f"] == "leaf_pkg.sv\nleaf_intf.sv\nleaf.sv\ndemo_top.sv\n"


def test_golden_fixture_compile_order_report_has_hash_and_no_blockers():
    files = rtl_fixture_files("golden_rtl")
    artifacts = build_phase1_artifacts(v4_fixture_spec(), files, build_rtl_module_index(files), {"requires_real_tools": False, "swarm_mode": "demo", "tools": {}, "blocking_findings": []})
    report = artifacts["compile_order_report"]

    assert report["schema_version"] == "agent2.compile_order_report.v1"
    assert len(report["compile_order_hash"]) == 64
    assert report["pass"] is True
    assert report["blocking_findings"] == []