import json
from pathlib import Path

import pytest

from semiconductor_swarm.agents.agent1_planning.architect import generate_architecture_spec
from semiconductor_swarm.agents.agent2_rtl.rtl_designer import generate_rtl_files
from semiconductor_swarm.agents.agent3_dv.dv_engineer import generate_dv_files


def _replace_block_rtl(rtl_files, block, old, new):
    patched = []
    for file in rtl_files:
        if file["filename"] == f"{block}.sv":
            content = file["content"].replace(old, new)
            patched.append({**file, "content": content, "line_count": len(content.rstrip("\n").splitlines())})
        else:
            patched.append(file)
    return patched


def test_scoreboard_and_coverage_reports_are_machine_readable():
    spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
    rtl = generate_rtl_files(spec)
    by_name = {file["filename"]: file for file in generate_dv_files(spec, rtl)}

    scoreboard = json.loads(by_name["agent3_scoreboard_report.json"]["content"])
    coverage = json.loads(by_name["agent3_coverage_report.json"]["content"])
    helper = by_name["dv_helpers.py"]["content"]

    assert scoreboard["protocol"] == "apb_slave"
    assert scoreboard["static_port_check_pass"] is True
    assert all(entry["checks"] for entry in scoreboard["per_block_checks"])
    assert coverage["status"] == "intent_only"
    assert coverage["covered_bins"] == []
    assert "reset" in coverage["missing_bins"]
    assert "class APBScoreboard" in helper
    assert "expect_readback" in helper
    assert "expect_illegal_address" in helper


def test_wrong_apb_port_name_fails_before_sim():
    spec = generate_architecture_spec("Timer APB controller 50MHz", "timer_ctrl")
    rtl = generate_rtl_files(spec)
    bad_rtl = _replace_block_rtl(rtl, "timer", "psel_i", "pselect_i")

    with pytest.raises(ValueError, match="missing APB port psel_i"):
        generate_dv_files(spec, bad_rtl)


def test_width_mismatch_fails_static_contract():
    spec = generate_architecture_spec("Timer APB controller 50MHz", "timer_ctrl")
    rtl = generate_rtl_files(spec)
    bad_rtl = _replace_block_rtl(rtl, "timer", "output logic [DATA_WIDTH-1:0] prdata_o", "output logic                  prdata_o")

    with pytest.raises(ValueError, match="prdata_o width mismatch"):
        generate_dv_files(spec, bad_rtl)


def test_negative_and_golden_fixture_inventory_present():
    root = Path(__file__).with_name("fixtures") / "agent3_dv"
    expected = {
        "golden_apb_slave.sv",
        "bad_apb_readback_fail.sv",
        "bad_missing_reset.sv",
        "bad_wrong_pready.sv",
        "bad_wrong_pslverr.sv",
        "bad_width_mismatch.sv",
    }

    assert {path.name for path in root.glob("*.sv")} == expected
    for filename in expected:
        assert "module demo_timer_rtl" in (root / filename).read_text(encoding="ascii")
