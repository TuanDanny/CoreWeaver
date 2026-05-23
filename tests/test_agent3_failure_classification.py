import pytest

from semiconductor_swarm.agents.agent3_dv.dv_engineer import analyze_simulation_log


@pytest.mark.parametrize(
    ("log", "expected_class", "owner"),
    [
        ("ERROR rtl/timer.sv:12 syntax error near always_ff", "compile_error", "Agent2"),
        ("ERROR rtl/timer.sv:7 unknown port psel_i", "port_mismatch", "Agent2"),
        ("FAIL rtl/timer.sv:44 prdata not zero after reset", "reset_failure", "Agent2"),
        ("FAIL rtl/timer.sv:55 APB protocol pready stuck low", "apb_protocol_failure", "Agent2"),
        ("FAIL rtl/timer.sv:66 scoreboard readback expected 1 actual 0", "scoreboard_mismatch", "Agent2"),
        ("ERROR rtl/timer.sv:77 timeout deadlock waiting for pready", "apb_protocol_failure", "Agent2"),
        ("ERROR rtl/timer.sv:88 sim timeout deadlock no clock edge", "timeout_deadlock", "Agent2"),
        ("Traceback cocotb testbench helper failed", "testbench_error", "Agent3"),
        ("verilator not found on PATH", "tool_missing", "Agent3"),
    ],
)
def test_analyze_simulation_log_classifies_failure(log, expected_class, owner):
    fix = analyze_simulation_log(log, "test_timer::case")

    assert fix["failure_class"] == expected_class
    assert fix["owner"] == owner
    assert fix["failing_test"] == "test_timer::case"
    assert fix["suggested_agent2_action"]
    assert fix["rewrite_policy"] in {"minimal_patch_only", "human_triage_before_whole_file_rewrite"}


def test_log_snippet_is_capped_to_20_lines():
    log = "\n".join(f"line {idx}" for idx in range(30))
    fix = analyze_simulation_log(log, "test_long_log")

    assert len(fix["cocotb_log_snippet"].splitlines()) == 20
    assert fix["cocotb_log_snippet"].splitlines()[0] == "line 10"
