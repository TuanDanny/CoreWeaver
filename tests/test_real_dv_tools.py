import json
import shutil
from pathlib import Path

import pytest

from semiconductor_swarm.agents.agent1_planning.architect import generate_architecture_spec
from semiconductor_swarm.agents.agent2_rtl.rtl_designer import generate_rtl_files
from semiconductor_swarm.agents.agent3_dv.dv_engineer import generate_dv_files, run_cocotb_sim
from semiconductor_swarm.tools.tool_detection import detect_real_tools

pytestmark = pytest.mark.real_tools
FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agent3_dv"

def _require_real_dv_tools():
    report = detect_real_tools()
    if not report["groups"]["dv"]["available"]:
        pytest.skip(f"dv real tools missing: {report['groups']['dv']['missing']}")
    return report

def _materialize_single_timer_project(tmp_path, fixture_name):
    spec = generate_architecture_spec("Timer APB controller 50MHz", "timer_ctrl")
    rtl = generate_rtl_files(spec)
    dv = generate_dv_files(spec, rtl)
    rtl_dir = tmp_path / "rtl"
    tb_dir = tmp_path / "tb"
    rtl_dir.mkdir()
    tb_dir.mkdir()
    fixture = (FIXTURE_DIR / fixture_name).read_text(encoding="ascii").replace("demo_timer_rtl", "timer_ctrl_timer_rtl")
    (rtl_dir / "timer.sv").write_text(fixture, encoding="ascii")
    for file in dv:
        (tb_dir / file["filename"]).write_text(file["content"], encoding="ascii")
    manifest_path = tb_dir / "agent3_dv_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    manifest["rtl_files"] = ["timer.sv"]
    manifest["compile_order"] = ["timer.sv"]
    manifest["test_files"] = ["test_timer.py"]
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii")
    (tb_dir / "agent3_compile_order.f").write_text("timer.sv\n", encoding="ascii")
    return tb_dir

def test_real_dv_tools_available_or_skip(tmp_path):
    report = _require_real_dv_tools()
    summary = {"dv_tools_available": True, "tools": {tool: shutil.which(tool) for tool in ("verilator", "make")}, "cocotb": report["tools"]["cocotb"]}
    path = tmp_path / "dv_real_summary.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="ascii")
    assert summary["dv_tools_available"]

def test_real_cocotb_golden_fixture_passes_or_skip(tmp_path):
    _require_real_dv_tools()
    tb_dir = _materialize_single_timer_project(tmp_path, "golden_apb_slave.sv")

    result = run_cocotb_sim(tb_dir, require_tools=True)

    assert result["pass"], result
    release = json.loads((tb_dir / "agent3_release_decision.json").read_text(encoding="ascii"))
    assert release["real_sim_pass"] is True

@pytest.mark.parametrize(
    ("fixture_name", "expected_token"),
    [
        ("bad_apb_readback_fail.sv", "readback"),
        ("bad_missing_reset.sv", "reset"),
        ("bad_wrong_pready.sv", "pready"),
        ("bad_wrong_pslverr.sv", "pslverr"),
        ("bad_width_mismatch.sv", "width"),
    ],
)
def test_real_cocotb_negative_fixtures_fail_or_skip(tmp_path, fixture_name, expected_token):
    _require_real_dv_tools()
    tb_dir = _materialize_single_timer_project(tmp_path, fixture_name)

    result = run_cocotb_sim(tb_dir, require_tools=True)
    combined = "\n".join(result.get("stdout_tail", []) + result.get("stderr_tail", [])).lower()

    assert not result["pass"]
    assert expected_token in combined or "error" in combined or "fail" in combined
    release = json.loads((tb_dir / "agent3_release_decision.json").read_text(encoding="ascii"))
    assert release["decision_label"] == "DV_FAIL"
