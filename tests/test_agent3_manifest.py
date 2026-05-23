import copy
import json
from unittest.mock import patch

from semiconductor_swarm.agents.agent1_planning.architect import generate_architecture_spec
from semiconductor_swarm.agents.agent2_rtl.rtl_designer import generate_rtl_files
from semiconductor_swarm.agents.agent3_dv.dv_engineer import (
    generate_dv_files,
    parse_verilator_coverage_output,
    run_cocotb_sim,
    verify_dv_files,
    write_agent3_runtime_failure,
)
from semiconductor_swarm.contracts.constants import AGENT3_RESULT_V1
from semiconductor_swarm.contracts.registry import validate_contract


def _by_name(files):
    return {file["filename"]: file for file in files}


def test_manifest_compile_order_and_result_contract_are_emitted():
    spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
    rtl = generate_rtl_files(spec)
    dv = generate_dv_files(spec, rtl)
    by_name = _by_name(dv)

    manifest = json.loads(by_name["agent3_dv_manifest.json"]["content"])
    result = json.loads(by_name["agent3_result.json"]["content"])
    release = json.loads(by_name["agent3_release_decision.json"]["content"])
    compile_order = by_name["agent3_compile_order.f"]["content"].splitlines()

    assert manifest["contract_version"] == "agent3_dv_manifest/v1"
    assert manifest["project_name"] == "spi_ctrl"
    assert manifest["top_module"] == "spi_ctrl_top"
    assert manifest["simulator_profile"]["primary"] == "verilator+cocotb"
    assert "spi_ctrl_top.sv" in manifest["compile_order"]
    assert compile_order == manifest["compile_order"]
    assert all("../generated_rtl" not in file["content"] for file in dv)
    assert result["contract_version"] == "agent3_result/v1"
    assert result["pass_fail_status"] == release["pass_fail_status"]
    assert validate_contract(AGENT3_RESULT_V1, result) is True


def test_manifest_compile_order_excludes_contract_only_rtl():
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

    dv = generate_dv_files(spec, rtl)
    by_name = _by_name(dv)
    manifest = json.loads(by_name["agent3_dv_manifest.json"]["content"])
    compile_order = by_name["agent3_compile_order.f"]["content"].splitlines()

    assert "interface_contracts.sv" not in manifest["rtl_files"]
    assert "interface_contracts.sv" not in manifest["compile_order"]
    assert "interface_contracts.sv" not in compile_order
    assert verify_dv_files(spec, rtl, dv)["pass"]

def test_manifest_scoreboard_uses_readable_register_for_uart_readback():
    spec = generate_architecture_spec(
        "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
        "cpu32bit",
    )
    rtl = generate_rtl_files(spec)
    dv = generate_dv_files(spec, rtl)
    manifest = json.loads(_by_name(dv)["agent3_dv_manifest.json"]["content"])
    uart_readback = manifest["scoreboard"]["readback_address_by_block"]["uart"]
    uart_legal = manifest["scoreboard"]["legal_addresses_by_block"]["uart"]
    test_uart = _by_name(dv)["test_uart.py"]["content"]

    assert uart_readback == 0x0C
    assert 0x00 in uart_legal
    assert "driver.write(readback_addr, 0xDEADBEEF)" in test_uart
    assert "driver.read(readback_addr)" in test_uart

def test_manifest_missing_rtl_reference_fails_validation():
    spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
    rtl = generate_rtl_files(spec)
    dv = generate_dv_files(spec, rtl)
    bad_dv = copy.deepcopy(dv)
    manifest_file = next(file for file in bad_dv if file["filename"] == "agent3_dv_manifest.json")
    manifest = json.loads(manifest_file["content"])
    manifest["rtl_files"].append("missing_block.sv")
    manifest_file["content"] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"

    report = verify_dv_files(spec, rtl, bad_dv)

    assert not report["pass"]
    assert any("manifest references missing RTL files" in failure for failure in report["failures"])


def test_manifest_wrong_top_fails_validation():
    spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
    rtl = generate_rtl_files(spec)
    dv = generate_dv_files(spec, rtl)
    bad_dv = copy.deepcopy(dv)
    manifest_file = next(file for file in bad_dv if file["filename"] == "agent3_dv_manifest.json")
    manifest = json.loads(manifest_file["content"])
    manifest["top_module"] = "wrong_top"
    manifest_file["content"] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"

    report = verify_dv_files(spec, rtl, bad_dv)

    assert not report["pass"]
    assert any("top_module mismatch" in failure or "top mismatch" in failure for failure in report["failures"])


def test_strict_mode_missing_tools_emits_fail_not_static_pass():
    spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
    spec["constraints"]["swarm_mode"] = "strict"
    spec["constraints"]["requires_real_tools"] = True
    rtl = generate_rtl_files(spec)

    with patch("semiconductor_swarm.agents.agent3_dv.dv_engineer.shutil.which", return_value=None), patch(
        "semiconductor_swarm.agents.agent3_dv.dv_engineer.importlib.util.find_spec", return_value=None
    ):
        dv = generate_dv_files(spec, rtl)

    by_name = _by_name(dv)
    release = json.loads(by_name["agent3_release_decision.json"]["content"])
    result = json.loads(by_name["agent3_result.json"]["content"])
    tool_health = json.loads(by_name["agent3_tool_health.json"]["content"])

    assert release["decision_label"] == "DV_FAIL"
    assert release["pass_fail_status"] == "fail"
    assert result["pass_fail_status"] == "fail"
    assert tool_health["missing_required"] == ["verilator", "make", "cocotb"]
    assert "DV_STRICT_PASS" not in by_name["agent3_release_decision.json"]["content"]


def test_dev_mode_missing_tools_is_partial_with_warning():
    spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
    spec["constraints"]["swarm_mode"] = "dev"
    rtl = generate_rtl_files(spec)

    with patch("semiconductor_swarm.agents.agent3_dv.dv_engineer.shutil.which", return_value=None), patch(
        "semiconductor_swarm.agents.agent3_dv.dv_engineer.importlib.util.find_spec", return_value=None
    ):
        dv = generate_dv_files(spec, rtl)

    release = json.loads(_by_name(dv)["agent3_release_decision.json"]["content"])
    assert release["decision_label"] == "DV_DEV_PASS_WITH_WARNINGS"
    assert release["pass_fail_status"] == "partial"


def test_run_cocotb_sim_persists_real_reports(tmp_path):
    spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
    rtl = generate_rtl_files(spec)
    dv = generate_dv_files(spec, rtl)
    by_name = _by_name(dv)
    for file in dv:
        (tmp_path / file["filename"]).write_text(file["content"], encoding="ascii")
    manifest = json.loads(by_name["agent3_dv_manifest.json"]["content"])
    bins = manifest["coverage_plan"]["bins"]
    observed = {"block": "timer", "test": "unit", "covered_bins": bins, "missing_bins": [], "failures": [], "transactions": [{"op": "write", "addr": 0, "data": 1}]}
    (tmp_path / "agent3_scoreboard_observed.jsonl").write_text(json.dumps(observed, sort_keys=True) + "\n", encoding="ascii")
    (tmp_path / "coverage.dat").write_text("mock", encoding="ascii")

    def fake_run(cmd, *args, **kwargs):
        if "--version" in cmd:
            return type("Proc", (), {"returncode": 0, "stdout": "Verilator 5.0\n", "stderr": ""})()
        if "--annotate" in cmd:
            return type("Proc", (), {"returncode": 0, "stdout": "Line coverage 96%\nBranch coverage 91%\n", "stderr": ""})()
        (tmp_path / "coverage.dat").write_text("mock", encoding="ascii")
        return type("Proc", (), {"returncode": 0, "stdout": "sim pass\n", "stderr": ""})()

    with patch("semiconductor_swarm.agents.agent3_dv.dv_engineer.shutil.which", return_value="tool"), patch(
        "semiconductor_swarm.agents.agent3_dv.dv_engineer.importlib.util.find_spec", return_value=type("Spec", (), {"origin": "cocotb"})()
    ), patch("semiconductor_swarm.agents.agent3_dv.dv_engineer.importlib.metadata.version", return_value="2.0.0"), patch(
        "semiconductor_swarm.agents.agent3_dv.dv_engineer.subprocess.run", side_effect=fake_run
    ):
        sim = run_cocotb_sim(tmp_path)

    sim_report = json.loads((tmp_path / "agent3_sim_report.json").read_text(encoding="ascii"))
    coverage = json.loads((tmp_path / "agent3_coverage_report.json").read_text(encoding="ascii"))
    scoreboard = json.loads((tmp_path / "agent3_scoreboard_report.json").read_text(encoding="ascii"))

    assert sim["pass"] is True
    assert sim_report["real_sim_attempted"] is True
    assert sim_report["commands"]
    assert coverage["status"] == "coverage_pass"
    assert coverage["code_coverage"]["line_percent"] == 96.0
    assert scoreboard["observed_transactions"] == [{"addr": 0, "data": 1, "op": "write"}]


def test_write_agent3_runtime_failure_forces_strict_fail(tmp_path):
    spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
    spec["constraints"]["swarm_mode"] = "strict"
    spec["constraints"]["requires_real_tools"] = True
    rtl = generate_rtl_files(spec)
    for file in generate_dv_files(spec, rtl):
        (tmp_path / file["filename"]).write_text(file["content"], encoding="ascii")

    with patch("semiconductor_swarm.agents.agent3_dv.dv_engineer.shutil.which", return_value=None), patch(
        "semiconductor_swarm.agents.agent3_dv.dv_engineer.importlib.util.find_spec", return_value=None
    ):
        report = write_agent3_runtime_failure(tmp_path, FileNotFoundError("Python module not found: cocotb"))

    release = json.loads((tmp_path / "agent3_release_decision.json").read_text(encoding="ascii"))
    result = json.loads((tmp_path / "agent3_result.json").read_text(encoding="ascii"))
    assert report["pass"] is False
    assert release["decision_label"] == "DV_FAIL"
    assert result["pass_fail_status"] == "fail"


def test_parse_verilator_coverage_output_handles_common_text():
    parsed = parse_verilator_coverage_output("Line coverage: 97.5%\nBranch coverage: 92%\n")
    assert parsed == {"line_percent": 97.5, "branch_percent": 92.0}
