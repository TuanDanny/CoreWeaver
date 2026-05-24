import json

from semiconductor_swarm.agents.agent1_planning.architect import generate_architecture_spec
from semiconductor_swarm.agents.agent2_rtl.rtl_designer import generate_rtl_files


def _json_artifact(files: list[dict[str, object]], name: str) -> dict[str, object]:
    return json.loads(next(file for file in files if file["filename"] == name)["content"])


def test_agent2_v4_quality_score_and_release_decision_have_complete_evidence():
    spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
    files = generate_rtl_files(spec, debug=True)

    score = _json_artifact(files, "agent2_quality_score.json")
    release = _json_artifact(files, "agent2_release_decision.json")
    completion = _json_artifact(files, "agent2_v4_completion_report.json")
    physical_feedback = _json_artifact(files, "rtl_physical_feedback_report.json")
    dv_feedback = _json_artifact(files, "dv_feedback_report.json")
    formal_feedback = _json_artifact(files, "formal_feedback_report.json")
    waivers = _json_artifact(files, "agent2_waivers.json")
    dashboard = next(file for file in files if file["filename"] == "agent2_v4_signoff_dashboard.md")["content"]

    assert score["schema_version"] == "agent2.quality_score.v1"
    assert score["score"] >= 75
    assert score["max_score"] == 100
    assert set(score["gates"]) >= {"compile_order", "contract", "lint", "synthesis", "tool_health"}
    assert release["schema_version"] == "agent2.release_decision.v1"
    assert release["decision"] in {"pass", "pass_with_waivers", "fail", "degraded_tooling"}
    assert isinstance(release["pass"], bool)
    assert physical_feedback["schema_version"] == "agent2.rtl_physical_feedback.v1"
    assert physical_feedback["feedback_closed_loop"] is True
    assert dv_feedback["schema_version"] == "agent2.dv_feedback.v1"
    assert dv_feedback["feedback_closed_loop"] is True
    assert formal_feedback["schema_version"] == "agent2.formal_feedback.v1"
    assert formal_feedback["feedback_closed_loop"] is True
    assert waivers["schema_version"] == "agent2.waivers.v1"
    assert set(waivers["required_fields"]) >= {"owner", "reason", "expiration", "signoff"}
    assert completion["schema_version"] == "agent2.v4_completion_report.v1"
    assert set(completion["phase5_checks"]) >= {"agent4_timing_resource_feedback", "agent3_coverage_feedback", "agent5_proof_feedback", "waiver_governance", "nightly_score_target"}
    assert completion["feedback_reports"]["rtl_physical_feedback_report"] == "rtl_physical_feedback_report.json"
    assert "Agent 2 V4 Signoff Dashboard" in dashboard


def test_agent2_demo_release_keeps_optional_yosys_crash_as_warning(monkeypatch):
    _patch_tool_smoke(monkeypatch, yosys_pass=False)
    spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
    files = generate_rtl_files(spec, debug=True)

    tool_health = _json_artifact(files, "tool_health_matrix.json")
    synthesis_smoke = _json_artifact(files, "synthesis_smoke_report.json")
    yosys = _json_artifact(files, "yosys_synth_report.json")
    handoff = _json_artifact(files, "agent2_handoff_bundle.json")
    release = _json_artifact(files, "agent2_release_decision.json")

    assert tool_health["requires_real_tools"] is False
    assert tool_health["pass"] is True
    assert tool_health["blocking_findings"] == []
    assert tool_health["optional_smoke_findings"]
    assert synthesis_smoke["pass"] is False
    assert yosys["pass"] is False
    assert yosys["blocking_findings"] == []
    assert yosys["nonblocking_findings"]
    assert handoff["pass"] is True
    assert handoff["blocking_findings"] == []
    assert release["decision"] == "pass"
    assert release["pass"] is True
    assert release["optional_tool_findings"]


def test_agent2_strict_release_blocks_failed_yosys_smoke(monkeypatch):
    _patch_tool_smoke(monkeypatch, yosys_pass=False)
    spec = generate_architecture_spec("SPI controller 50MHz", "spi_ctrl")
    spec["constraints"]["swarm_mode"] = "strict"
    spec["constraints"]["requires_real_tools"] = True
    files = generate_rtl_files(spec, debug=True)

    tool_health = _json_artifact(files, "tool_health_matrix.json")
    yosys = _json_artifact(files, "yosys_synth_report.json")
    handoff = _json_artifact(files, "agent2_handoff_bundle.json")
    release = _json_artifact(files, "agent2_release_decision.json")

    assert tool_health["requires_real_tools"] is True
    assert tool_health["pass"] is False
    assert tool_health["real_tool_gate"]["pass"] is False
    assert any(finding["rule"] == "required_real_smoke_failed" for finding in tool_health["blocking_findings"])
    assert yosys["blocking_findings"]
    assert handoff["pass"] is False
    assert release["decision"] == "fail"
    assert release["pass"] is False
    assert release["tool_gate_blocking"] is True


def _patch_tool_smoke(monkeypatch, yosys_pass: bool) -> None:
    def healthy_probe(name):
        return {"name": name, "status": "healthy", "command": f"{name} --version", "path": name, "returncode": 0, "stdout": f"{name} ok", "stderr": "", "provenance": "version_probe"}

    def passing_smoke(command="tool"):
        return {"ran": True, "pass": True, "tool_status": "healthy", "provenance": "real_tool_run", "command": command, "path": command.split()[0], "returncode": 0, "stdout": "", "stderr": "", "blocking_findings": []}

    def yosys_smoke(_files):
        if yosys_pass:
            return passing_smoke("yosys")
        return {"ran": True, "pass": False, "tool_status": "healthy", "provenance": "real_tool_run", "command": "yosys", "path": "yosys", "returncode": 3221225477, "stdout": "", "stderr": "", "blocking_findings": [{"severity": "error", "tool": "yosys", "message": "yosys exited with returncode 3221225477"}]}

    monkeypatch.setattr("semiconductor_swarm.agents.agent2_rtl.tools.verilator_adapter.probe_verilator", lambda: healthy_probe("verilator"))
    monkeypatch.setattr("semiconductor_swarm.agents.agent2_rtl.tools.yosys_adapter.probe_yosys", lambda: healthy_probe("yosys"))
    monkeypatch.setattr("semiconductor_swarm.agents.agent2_rtl.tools.symbiyosys_adapter.probe_symbiyosys", lambda: healthy_probe("symbiyosys"))
    monkeypatch.setattr("semiconductor_swarm.agents.agent2_rtl.tools.yosys_adapter.run_yosys_smoke", yosys_smoke)
    monkeypatch.setattr("semiconductor_swarm.agents.agent2_rtl.phase1_artifacts.run_yosys_smoke", yosys_smoke)
    monkeypatch.setattr("semiconductor_swarm.agents.agent2_rtl.tools.symbiyosys_adapter.run_symbiyosys_smoke", lambda _files: passing_smoke("sby --version"))
    monkeypatch.setattr("semiconductor_swarm.agents.agent2_rtl.phase1_artifacts.run_verilator_lint", lambda _files, _compile_order: passing_smoke("verilator --lint-only"))
