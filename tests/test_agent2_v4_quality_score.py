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