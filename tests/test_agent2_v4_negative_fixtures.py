from semiconductor_swarm.agents.agent2_rtl.phase1_artifacts import build_phase1_artifacts
from semiconductor_swarm.agents.agent2_rtl.semantic import build_rtl_module_index, build_semantic_lint_report

from tests.agent2_v4_fixture_utils import rtl_fixture_files, v4_fixture_spec


def _tool_health() -> dict[str, object]:
    return {"requires_real_tools": False, "swarm_mode": "demo", "tools": {}, "blocking_findings": []}


def test_bad_latch_reset_and_apb_fixtures_produce_blocking_semantic_findings():
    spec = v4_fixture_spec()
    files = rtl_fixture_files("bad_rtl")
    artifacts = build_phase1_artifacts(spec, files, build_rtl_module_index(files), _tool_health())

    deep = artifacts["semantic_deep_report"]
    style = artifacts["rtl_style_report"]
    rules = {finding["rule"] for finding in deep["blocking_findings"] + style["blocking_findings"]}

    assert not deep["pass"]
    assert not style["pass"]
    assert "apb_handshake_present" in rules
    assert "no_obvious_latch" in rules
    assert "no_x_assignment" in rules
    assert "always_latch" in rules


def test_compile_order_fixture_is_normalized_by_phase1_ordering():
    files = rtl_fixture_files("bad_rtl")
    top_first = [file for file in files if file["filename"] == "compile_order_top_first.sv"]
    child = [file for file in files if file["filename"] == "compile_order_child.sv"]
    ordered = top_first + child
    artifacts = build_phase1_artifacts(v4_fixture_spec(), ordered, build_rtl_module_index(ordered), _tool_health())

    report = artifacts["compile_order_report"]
    rules = {finding["rule"] for finding in report["blocking_findings"]}

    assert report["pass"]
    assert "dependency_order" not in rules
    assert report["compile_order"] == ["compile_order_child.sv", "compile_order_top_first.sv"]


def test_semantic_lint_detects_duplicate_modules_from_negative_fixtures():
    dup = rtl_fixture_files("bad_rtl")[:1]
    files = [dict(dup[0], filename="dup_a.sv"), dict(dup[0], filename="dup_b.sv")]
    index = build_rtl_module_index(files)
    report = build_semantic_lint_report(v4_fixture_spec(), index)

    assert index["duplicate_modules"]
    assert not report["pass"]
    assert any(finding["rule"] == "duplicate_modules" for finding in report["findings"])