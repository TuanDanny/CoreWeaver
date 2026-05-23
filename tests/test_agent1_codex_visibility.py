import json

from semiconductor_swarm.agents.agent1_planning.agent1_llm_client import call_agent1_codex
from semiconductor_swarm.runtime_events import set_runtime_event_sink


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(
            {
                "choices": [{"message": {"content": "architecture reasoning"}}],
                "usage": {"prompt_tokens": 2000, "completion_tokens": 500, "total_tokens": 2500},
            }
        ).encode("utf-8")


def test_agent1_codex_visibility_events_and_usage(monkeypatch):
    events = []
    set_runtime_event_sink(events.append)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: _FakeResponse())
    try:
        result = call_agent1_codex(
            "prompt",
            config={
                "base_url": "http://localhost:20128/v1",
                "model": "cx/gpt-5.5",
                "max_retries": 0,
                "input_usd_per_1m_tokens": 1.0,
                "output_usd_per_1m_tokens": 2.0,
            },
        )
    finally:
        set_runtime_event_sink(None)

    assert result.content == "architecture reasoning"
    assert result.evidence["usage_status"] == "reported"
    assert result.evidence["total_tokens"] == 2500
    assert result.evidence["estimated_cost_usd"] == 0.003
    assert any(event.get("type") == "agent_action" and event.get("action") == "Codex request started" for event in events)
    assert any(event.get("type") == "agent_action" and event.get("action") == "Codex response received" for event in events)
    assert any(event.get("type") == "metric" and event.get("name") == "codex_call_count" and event.get("value") == 1 for event in events)
    assert any(event.get("type") == "metric" and event.get("name") == "codex_latency_s" for event in events)
    assert any(event.get("type") == "metric" and event.get("name") == "codex_total_tokens" and event.get("agent") == "agent1" for event in events)
    assert result.evidence["timeout_s"] == 120
    assert result.evidence["max_retries"] == 0
