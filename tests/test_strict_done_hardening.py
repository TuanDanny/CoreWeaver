import asyncio
import json
from pathlib import Path

import pytest

from coreweaver.agents.agent1.expert_parser import parse_expert_response
from coreweaver.agents.agent1.models import ArchitecturePlan, ChallengeSeverity, RegisterEntry, SignoffFinding
from coreweaver.agents.agent1.runtime import Agent1SwarmRuntime
from coreweaver.agents.agent1.signoff import IndustrialSignoffEngine
from coreweaver.contracts import HandoffValidationError, validate_agent1_to_agent2_handoff
from coreweaver.events import AsyncEventStream
from coreweaver.framework_types import stable_hash
from coreweaver.models import ModelResponse, ModelRouter
from coreweaver.runtime import RuntimeSession, RuntimeState
from studio.backend.agent_service import AgentService
from studio.backend.event_hub import EventHub
from studio.backend.job_models import AgentJob
from studio.backend.runner import RunnerManager

SECRET_SAMPLE = "sk-" + "abcdefghijklmnopqrstuvwx"


def _valid_plan() -> ArchitecturePlan:
    return ArchitecturePlan(
        title="Strict Done Plan",
        requirement_summary="Design an APB timer with CSRs, interrupt status, 100MHz clock, synchronous reset.",
        assumptions=("Process node is unspecified.",),
        open_questions=(),
        top_level_blocks=("APB control plane", "Timer core"),
        interfaces=("APB configuration interface for firmware-visible CSRs.",),
        memory_map=("0x0000-0x0FFF: APB CSR window",),
        registers=(RegisterEntry(name="CTRL", offset="0x0000", access="RW", reset="0x0", description="Control"),),
        security_model=("No explicit security mechanism requested; keep debug/trace secret-scan active.",),
        datapath_control=("Timer counter and compare control.",),
        reset_clock_cdc=("Target clock: 100MHz.", "Synchronous reset."),
        interrupt_error_policy=("Sticky interrupt status uses W1C.",),
        formal_intent=("Prove APB access policy.",),
        dv_intent=("cocotb APB CSR regressions.",),
        ppa_risks=("PPA cannot be quantified until process assumptions are known.",),
        agent2_handoff_contract=("Agent2 receives locked interfaces.",),
        provenance_refs=("M01:abcdef123456",),
    )


@pytest.mark.parametrize(
    ("patch", "gate"),
    [
        ({"open_questions": ("bus/interface contract",)}, "G00"),
        ({"interfaces": ()}, "G01"),
        ({"memory_map": ()}, "G02"),
        ({"requirement_summary": "AES key block", "registers": (RegisterEntry(name="KEY", offset="0x0100", access="RW", reset="0x0", description="Readable key"),)}, "G03"),
        ({"requirement_summary": "NO_RESET_POLICY_MUTATION"}, "G04"),
        ({"interrupt_error_policy": ()}, "G05"),
        ({"formal_intent": ()}, "G06"),
        ({"dv_intent": ()}, "G07"),
        ({"ppa_risks": ()}, "G08"),
        ({"provenance_refs": ()}, "G09"),
        ({"agent2_handoff_contract": ()}, "G10"),
        ({"requirement_summary": SECRET_SAMPLE}, "G11"),
    ],
)
def test_signoff_enforces_g00_to_g11(patch: dict[str, object], gate: str) -> None:
    certificate = IndustrialSignoffEngine().evaluate(_valid_plan().model_copy(update=patch))
    assert certificate.passed is False
    assert certificate.gate_results[gate] == "fail"


def test_signoff_g12_fails_on_verifier_blocker() -> None:
    finding = SignoffFinding(gate_id="G12", severity=ChallengeSeverity.BLOCKER, code="unresolved", message="blocked")
    certificate = IndustrialSignoffEngine().evaluate(_valid_plan(), (finding,))
    assert certificate.passed is False
    assert certificate.gate_results["G12"] == "fail"


def test_handoff_validator_requires_ready_contract_and_passing_certificate(tmp_path: Path) -> None:
    certificate = tmp_path / "cert.json"
    certificate.write_text(json.dumps({"passed": True, "gate_results": {"G00": "pass"}}), encoding="utf-8")
    handoff = tmp_path / "agent1_to_agent2.json"
    handoff.write_text(json.dumps({"ready": True, "blockers": [], "signoff_certificate_ref": str(certificate)}), encoding="utf-8")
    assert validate_agent1_to_agent2_handoff(handoff)["ready"] is True
    handoff.write_text(json.dumps({"ready": False, "blockers": ["G01:x"], "signoff_certificate_ref": str(certificate)}), encoding="utf-8")
    with pytest.raises(HandoffValidationError, match="not ready"):
        validate_agent1_to_agent2_handoff(handoff)


def test_handoff_validator_accepts_runtime_relative_certificate_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    session = RuntimeSession(
        RuntimeState(
            run_id="relative-handoff",
            profile="mock_swarm",
            requirement="Design an APB timer peripheral with 32-bit CSRs, interrupt status W1C, 100MHz clock, synchronous reset.",
            project_name="relative",
            output_dir="relative_run",
        )
    )
    result = asyncio.run(session.start())
    assert result.action_required == "PLAN_REVIEW"
    handoff = Path("relative_run") / "contracts" / "agent1_to_agent2.json"
    assert validate_agent1_to_agent2_handoff(handoff)["ready"] is True


def test_studio_agent2_job_rejects_blocked_handoff(tmp_path: Path) -> None:
    certificate = tmp_path / "reports" / "agent1" / "agent1_final_signoff_certificate.json"
    certificate.parent.mkdir(parents=True)
    certificate.write_text(json.dumps({"passed": False, "gate_results": {"G01": "fail"}}), encoding="utf-8")
    handoff = tmp_path / "contracts" / "agent1_to_agent2.json"
    handoff.parent.mkdir(parents=True)
    handoff.write_text(json.dumps({"ready": False, "blockers": ["G01:x"], "signoff_certificate_ref": str(certificate)}), encoding="utf-8")
    service = AgentService(runner=RunnerManager(root=Path.cwd()), event_hub=EventHub())
    job = AgentJob(type="agent2_rtl_draft", output_dir=str(tmp_path), project_name="blocked")
    asyncio.run(service.queue.enqueue(job))
    asyncio.run(service._run_agent2_rtl_draft(job))
    refreshed = asyncio.run(service.queue.get(job.job_id))
    assert refreshed.status == "failed"
    assert "not ready" in str(refreshed.error)


def test_studio_agent2_job_emits_debug_issue_for_missing_handoff(tmp_path: Path) -> None:
    event_hub = EventHub()
    service = AgentService(runner=RunnerManager(root=Path.cwd()), event_hub=event_hub)
    job = AgentJob(type="agent2_rtl_draft", output_dir=str(tmp_path), project_name="missing")
    asyncio.run(service.queue.enqueue(job))
    asyncio.run(service._run_agent2_rtl_draft(job))
    refreshed = asyncio.run(service.queue.get(job.job_id))
    assert refreshed.status == "failed"
    assert any(event.get("code") == "agent2_handoff_not_ready" for event in event_hub.replay)


def test_expert_parser_accepts_json_fallback_and_rejects_secret() -> None:
    findings, risks, assumptions = parse_expert_response('{"findings":["ok"],"risks":["risk"],"assumptions":["assume"]}')
    assert findings == ("ok",)
    assert risks == ("risk",)
    assert assumptions == ("assume",)
    assert parse_expert_response("plain text")[0] == ("model observation: plain text",)
    with pytest.raises(ValueError, match="model_response_secret"):
        parse_expert_response(SECRET_SAMPLE)


class StructuredClient:
    async def complete(self, *, prompt: str, idempotency_key: str) -> ModelResponse:
        text = '{"findings":["structured finding"],"risks":["structured risk"],"assumptions":["structured assumption"]}'
        return ModelResponse(text=text, output_hash=stable_hash(text), prompt_tokens=1, completion_tokens=1)


class SecretClient:
    async def complete(self, *, prompt: str, idempotency_key: str) -> ModelResponse:
        text = SECRET_SAMPLE
        return ModelResponse(text=text, output_hash=stable_hash(text), prompt_tokens=1, completion_tokens=1)


class FlakyTimeoutClient:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, *, prompt: str, idempotency_key: str) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("synthetic timeout")
        text = '{"findings":["retry recovered"],"risks":[],"assumptions":[]}'
        return ModelResponse(text=text, output_hash=stable_hash(text), prompt_tokens=1, completion_tokens=1)


def test_local_llm_structured_response_path_uses_parser(tmp_path: Path) -> None:
    runtime = Agent1SwarmRuntime(event_stream=AsyncEventStream(), model_router=ModelRouter(StructuredClient()))
    result = asyncio.run(
        runtime.run(
            run_id="structured",
            revision_id="rev:0",
            requirement="Design an APB timer peripheral with 32-bit CSRs, interrupt status W1C, 100MHz clock, synchronous reset.",
            project_name="structured",
            planning_mode="normal",
            output_dir=tmp_path,
        )
    )
    assert result.action_required == "PLAN_REVIEW"
    replay = json.loads((tmp_path / "replay" / "replay_bundle.json").read_text(encoding="utf-8"))
    assert replay["schema_version"] == "coreweaver.agent1.replay.v1"


def test_local_llm_timeout_retries_and_recovers(tmp_path: Path) -> None:
    event_stream = AsyncEventStream()
    client = FlakyTimeoutClient()
    runtime = Agent1SwarmRuntime(event_stream=event_stream, model_router=ModelRouter(client))
    result = asyncio.run(
        runtime.run(
            run_id="timeout-retry",
            revision_id="rev:0",
            requirement="Design an APB timer peripheral with 32-bit CSRs, interrupt status W1C, 100MHz clock, synchronous reset.",
            project_name="timeout",
            planning_mode="normal",
            output_dir=tmp_path,
        )
    )
    trace = "\n".join(json.dumps(event.safe_dump(), sort_keys=True) for event in event_stream.history)
    assert result.action_required == "PLAN_REVIEW"
    assert client.calls > 1
    assert "agent1_leaf_expert_retry" in trace


def test_secret_model_response_retries_and_does_not_leak(tmp_path: Path) -> None:
    event_stream = AsyncEventStream()
    runtime = Agent1SwarmRuntime(event_stream=event_stream, model_router=ModelRouter(SecretClient()))
    asyncio.run(
        runtime.run(
            run_id="secret-model",
            revision_id="rev:0",
            requirement="Design an APB timer peripheral with 32-bit CSRs, interrupt status W1C, 100MHz clock, synchronous reset.",
            project_name="secret",
            planning_mode="normal",
            output_dir=tmp_path,
        )
    )
    trace = (tmp_path / "trace" / "events.jsonl").read_text(encoding="utf-8")
    assert SECRET_SAMPLE not in trace
    assert "leaf_expert_failed" in trace


@pytest.mark.parametrize("token, expected", [
    ("BUDGET_BREACH_MUTATION", "budget_exceeded"),
    ("KILL_SWITCH_MUTATION", "kill_switch_tripped"),
    ("CIRCUIT_BREAKER_MUTATION", "circuit_breaker_open"),
    ("CANARY_LEAK_MUTATION", "canary_touched"),
    ("UNAPPROVED_COMMIT_MUTATION", "agent1_proposal_rejected"),
])
def test_safety_mutations_block_handoff(tmp_path: Path, token: str, expected: str) -> None:
    session = RuntimeSession(
        RuntimeState(
            run_id=f"safety-{token.lower()}",
            profile="mock_swarm",
            requirement=f"Design an APB timer peripheral with 32-bit CSRs, interrupt status W1C, 100MHz clock, synchronous reset, and {token}.",
            project_name="safety",
            output_dir=str(tmp_path),
        )
    )
    result = asyncio.run(session.start())
    text = "\n".join(json.dumps(event.safe_dump(), sort_keys=True) for event in session.event_stream.history)
    assert result.action_required == "HITL_REQUIRED"
    assert expected in text
    assert "agent1_handoff_ready" not in text
