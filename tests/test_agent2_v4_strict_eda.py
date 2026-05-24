from semiconductor_swarm.agents.agent2_rtl.phase1_artifacts import build_phase1_artifacts
from semiconductor_swarm.agents.agent2_rtl import rtl_linter
from semiconductor_swarm.agents.agent2_rtl.semantic import build_rtl_module_index
from semiconductor_swarm.agents.agent2_rtl.tools import verilator_adapter

from tests.agent2_v4_fixture_utils import rtl_fixture_files, v4_fixture_spec


def test_strict_eda_blocks_missing_real_tools_when_required():
    files = rtl_fixture_files("golden_rtl")
    tool_health = {
        "requires_real_tools": True,
        "swarm_mode": "strict",
        "tools": {"verilator": {"status": "missing"}, "yosys": {"status": "missing"}, "symbiyosys": {"status": "missing"}},
        "blocking_findings": [{"severity": "high", "rule": "missing_real_tool", "tool": "verilator"}],
        "real_tool_gate": {"blocking_findings": [{"severity": "high", "rule": "fallback_forbidden"}]},
    }
    artifacts = build_phase1_artifacts(v4_fixture_spec(), files, build_rtl_module_index(files), tool_health)
    strict = artifacts["strict_eda_report"]

    assert strict["requires_real_tools"] is True
    assert strict["fallback_forbidden"] is True
    assert strict["pass"] is False
    assert {finding["rule"] for finding in strict["blocking_findings"]} == {"missing_real_tool", "fallback_forbidden"}


def test_strict_handoff_blocks_degraded_verilator_result(monkeypatch):
    files = rtl_fixture_files("golden_rtl")
    tool_health = {
        "requires_real_tools": True,
        "swarm_mode": "strict",
        "tools": {"verilator": {"status": "healthy"}, "yosys": {"status": "healthy"}, "symbiyosys": {"status": "healthy"}},
        "blocking_findings": [],
        "real_tool_gate": {"blocking_findings": []},
    }

    def degraded_verilator(_files, _compile_order):
        return {"ran": True, "pass": True, "tool_status": "degraded", "provenance": "degraded_tool_install", "command": "verilator --lint-only", "path": "verilator", "returncode": 1, "stdout": "", "stderr": "Cannot find verilated_std.sv", "blocking_findings": []}

    monkeypatch.setattr("semiconductor_swarm.agents.agent2_rtl.phase1_artifacts.run_verilator_lint", degraded_verilator)
    monkeypatch.setattr("semiconductor_swarm.agents.agent2_rtl.phase1_artifacts.run_yosys_smoke", lambda _files: {"ran": True, "pass": True, "tool_status": "healthy", "provenance": "real_tool_run", "command": "yosys", "path": "yosys", "returncode": 0, "stdout": "", "stderr": "", "blocking_findings": []})

    artifacts = build_phase1_artifacts(v4_fixture_spec(), files, build_rtl_module_index(files), tool_health)

    verilator = artifacts["verilator_lint_report"]
    assert verilator["pass"] is False
    assert verilator["tool_status"] == "degraded"
    assert verilator["environment"]["status"] == "degraded"
    assert verilator["environment"]["probed_status"] == "healthy"
    assert {finding["rule"] for finding in verilator["blocking_findings"]} == {"strict_tool_degraded_or_fallback"}
    assert artifacts["agent2_handoff_bundle"]["pass"] is False


def test_verilator_lint_materializes_in_memory_sv_before_invocation(monkeypatch):
    calls = []

    def fake_run_command_args(command, stdin=None, cwd=None):
        cwd_path = __import__("pathlib").Path(cwd)
        calls.append({"command": command, "cwd": cwd, "files": sorted(path.name for path in cwd_path.glob("*.sv"))})
        assert (cwd_path / "pkg.sv").read_text(encoding="utf-8") == "package pkg; endpackage\n"
        assert (cwd_path / "top.sv").read_text(encoding="utf-8") == "module top; endmodule\n"
        return {"ran": True, "pass": True, "tool_status": "healthy", "provenance": "real_tool_run", "command": " ".join(command), "path": command[0], "returncode": 0, "stdout": "", "stderr": "", "blocking_findings": []}

    monkeypatch.setattr(verilator_adapter, "run_command_args", fake_run_command_args)

    result = verilator_adapter.run_verilator_lint(
        [
            {"filename": "pkg.sv", "language": "systemverilog", "content": "package pkg; endpackage\n"},
            {"filename": "top.sv", "language": "systemverilog", "content": "module top; endmodule\n"},
        ],
        ["pkg.sv", "top.sv"],
    )

    assert result["pass"] is True
    assert calls
    assert calls[0]["files"] == ["pkg.sv", "top.sv"]
    assert calls[0]["command"][-2:] == ["pkg.sv", "top.sv"]

def test_verilator_self_check_skips_formal_contract_collateral(monkeypatch):
    calls = []

    class Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, cwd=None, text=None, capture_output=None, timeout=None, env=None):
        calls.append({"command": command, "env": env})
        return Proc()

    monkeypatch.setattr(rtl_linter.shutil, "which", lambda _name: "D:/APP/oss-cad-suite/bin/verilator_bin.exe")
    monkeypatch.setattr(rtl_linter.subprocess, "run", fake_run)

    result = rtl_linter._run_verilator_if_available(
        [
            {"filename": "top.sv", "language": "systemverilog", "content": "module top; endmodule\n"},
            {"filename": "interface_contracts.sv", "language": "systemverilog", "content": "property p; @(posedge clk) a |-> ##[0:8] b; endproperty\n"},
        ]
    )

    assert result["pass"] is True
    assert calls
    assert calls[0]["command"][-1].endswith("top.sv")
    assert all("interface_contracts.sv" not in item for item in calls[0]["command"])
