import json
import urllib.error

import pytest

from semiconductor_swarm.agents.agent1_planning.architect import generate_architecture_spec
from semiconductor_swarm.agents.agent2_rtl.ai_repair import apply_json_patch, build_context_slice, validate_ai_review, validate_repair_suggestions
from semiconductor_swarm.agents.agent2_rtl.agent2_llm_client import Agent2CodexUnavailable, call_agent2_codex
from semiconductor_swarm.agents.agent2_rtl.orchestrator import agent2_rollup_stage
from semiconductor_swarm.agents.agent2_rtl.rtl_designer import generate_rtl_files
from semiconductor_swarm.runtime_events import set_runtime_event_sink
from semiconductor_swarm.swarm_graph import _rtl_file_rel_path


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_agent2_codex_client_success(monkeypatch):
    events = []
    set_runtime_event_sink(events.append)
    payload = {
        "choices": [{"message": {"content": "review ok"}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 250, "total_tokens": 1250},
    }
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: _FakeResponse(payload))

    try:
        result = call_agent2_codex(
            "prompt",
            config={
                "base_url": "http://localhost:20128/v1",
                "model": "cx/gpt-5.5",
                "api_key": "secret",
                "max_retries": 0,
                "input_usd_per_1m_tokens": 1.0,
                "output_usd_per_1m_tokens": 2.0,
            },
        )
    finally:
        set_runtime_event_sink(None)

    assert result.content == "review ok"
    assert result.evidence["schema_version"] == "agent2.codex_evidence.v1"
    assert result.evidence["model"] == "cx/gpt-5.5"
    assert result.evidence["auth_header_present"] is True
    assert result.evidence["prompt_tokens"] == 1000
    assert result.evidence["completion_tokens"] == 250
    assert result.evidence["estimated_cost_usd"] == 0.0015
    assert "secret" not in json.dumps(result.evidence)
    assert any(event.get("type") == "agent_action" and event.get("action") == "Codex request started" and event.get("agent") == "agent2" for event in events)
    assert any(event.get("type") == "agent_action" and event.get("action") == "Codex response received" and event.get("agent") == "agent2" for event in events)
    assert any(event.get("type") == "metric" and event.get("name") == "codex_total_tokens" and event.get("agent") == "agent2" for event in events)


def test_agent2_codex_client_failure_blocks_hybrid(monkeypatch):
    def fail(*_args, **_kwargs):
        raise urllib.error.URLError("down")

    monkeypatch.setattr("urllib.request.urlopen", fail)

    with pytest.raises(Agent2CodexUnavailable):
        call_agent2_codex("prompt", config={"base_url": "http://localhost:20128/v1", "max_retries": 0})


def test_agent2_codex_usage_telemetry_present_or_not_reported(monkeypatch):
    payload = {"choices": [{"message": {"content": "no usage"}}]}
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: _FakeResponse(payload))

    result = call_agent2_codex("prompt", config={"base_url": "http://localhost:20128/v1", "max_retries": 0})

    assert result.evidence["usage_status"] == "not_reported_by_endpoint"
    assert result.evidence["prompt_tokens"] is None
    assert result.evidence["estimated_cost_usd"] is None


def _spec():
    spec = generate_architecture_spec("Generate a 32-bit CPU architecture using APB and UART", "codex_agent2_test")
    spec.setdefault("constraints", {})["agent2_codex_required"] = True
    return spec


def _deterministic_spec():
    spec = generate_architecture_spec("Generate a 32-bit CPU architecture using APB and UART", "agent2_events_test")
    spec.setdefault("constraints", {})["agent2_codex_required"] = False
    return spec


def test_agent2_hybrid_generates_codex_artifacts(monkeypatch):
    def fake_codex(_prompt, *, purpose="rtl_review", config=None):
        if purpose == "rtl_review":
            return type("R", (), {"content": '{"summary":"ok","findings":[]}', "evidence": {"schema_version": "agent2.codex_evidence.v1", "model": "mock", "usage_status": "reported", "total_tokens": 12}})()
        return type("R", (), {"content": "# plan", "evidence": {"schema_version": "agent2.codex_evidence.v1", "model": "mock", "usage_status": "reported", "total_tokens": 10}})()

    monkeypatch.setattr("semiconductor_swarm.agents.agent2_rtl.orchestrator.call_agent2_codex", fake_codex)

    files = generate_rtl_files(_spec(), debug=True)
    by_name = {file["filename"]: file for file in files}

    assert "agent2_codex_plan.md" in by_name
    assert "agent2_codex_evidence.json" in by_name
    assert "agent2_ai_review.json" in by_name
    assert "agent2_ai_repair_suggestions.json" in by_name
    assert "agent2_ai_contract.json" in by_name


def test_agent2_hybrid_failure_blocks_when_required(monkeypatch):
    def fail(*_args, **_kwargs):
        raise Agent2CodexUnavailable("down")

    monkeypatch.setattr("semiconductor_swarm.agents.agent2_rtl.orchestrator.call_agent2_codex", fail)

    with pytest.raises(Agent2CodexUnavailable):
        generate_rtl_files(_spec(), debug=True)


def test_agent2_codex_artifacts_route_to_rtl_reports():
    assert str(_rtl_file_rel_path("agent2_codex_evidence.json", "json")).replace("\\", "/") == "rtl/reports/agent2_codex_evidence.json"
    assert str(_rtl_file_rel_path("agent2_codex_plan.md", "markdown")).replace("\\", "/") == "rtl/reports/agent2_codex_plan.md"


def test_agent2_ai_review_requires_cited_rule():
    report = validate_ai_review({"findings": [{"affected_file": "timer.sv", "severity": "error"}]})
    assert not report["pass"]
    assert report["blocking_findings"][0]["rule"] == "missing_review_citation"


def test_agent2_ai_repair_rejects_full_file_rewrite():
    report = validate_repair_suggestions({"patches": [{"file": "timer.sv", "action": "replace", "content": "module whole_file; endmodule"}]})
    assert not report["pass"]
    assert report["blocking_findings"][0]["rule"] == "full_file_rewrite_forbidden"


def test_agent2_context_slicer_extracts_always_block_not_full_file():
    content = "\n".join([f"logic x{i};" for i in range(120)] + ["always_ff @(posedge clk_i) begin", "  if (!rst_ni) q <= 1'b0;", "  else q <= d;", "end"] + [f"logic y{i};" for i in range(120)])
    result = build_context_slice([{"filename": "mac_array.sv", "content": content}], {"affected_file": "mac_array.sv", "line": 123})
    assert result["pass"]
    assert result["parser_mode"] == "ast_structural_block"
    assert result["line_count"] <= 140
    assert "always_ff" in result["snippet"]


def test_agent2_ai_repair_applies_minimal_patch_only_when_old_hash_matches():
    result = apply_json_patch("assign irq = 1'b1;\n", {"file": "timer.sv", "line": 1, "action": "replace", "old_text": "assign irq = 1'b1;", "new_code": "assign irq = 1'b0;"})
    assert result.pass_
    assert result.content == "assign irq = 1'b0;\n"


def test_agent2_patch_retry_second_failure_routes_hitl():
    result = apply_json_patch("assign irq = 1'b1;\n", {"file": "timer.sv", "line": 1, "action": "replace", "old_text": "assign irq = 1'b0;", "new_code": "assign irq = 1'b0;"})
    assert not result.pass_
    assert result.report["reason"] == "old_text_mismatch"
    assert result.report["actual_old_text"] == "assign irq = 1'b1;"


def test_agent2_runtime_events_emit_subagent_actions():
    events = []
    set_runtime_event_sink(events.append)
    try:
        generate_rtl_files(_deterministic_spec(), debug=True)
    finally:
        set_runtime_event_sink(None)

    agent2_events = [event for event in events if event.get("type") == "agent_action" and event.get("agent") == "agent2"]
    assert len(agent2_events) >= 50
    assert agent2_events[0]["subagent_id"] == "A2.01"
    assert agent2_events[-1]["subagent_id"] == "A2.56"
    assert all(event["rollup_stage"] for event in agent2_events)
    assert all("artifact_count" in event and "finding_count" in event for event in agent2_events)


def test_agent2_rollup_stage_mapping_covers_all_subagents():
    stages = {agent2_rollup_stage(f"A2.{index:02d}") for index in range(1, 57)}
    assert stages == {"Intake", "Planning", "IP Writers", "Integration", "Quality Gate", "Repair"}
