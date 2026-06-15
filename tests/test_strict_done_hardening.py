import asyncio
import json
from pathlib import Path

import pytest

from coreweaver.agents.agent1.expert_parser import parse_expert_response
from coreweaver.agents.agent1.handoff import Agent2HandoffGate
from coreweaver.agents.agent1.models import ArchitecturePlan, ChallengeSeverity, RegisterEntry, SignoffFinding
from coreweaver.agents.agent1.runtime import Agent1SwarmRuntime
from coreweaver.agents.agent1.signoff import IndustrialSignoffEngine
from coreweaver.agents.agent1.verifier import ReadOnlyVerifier
from coreweaver.contracts import HandoffValidationError, validate_agent1_to_agent2_handoff
from coreweaver.events import AsyncEventStream
from coreweaver.framework_types import stable_hash
from coreweaver.messages import Blackboard, CoreMessage, MessageKind, MessageRole
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


def _valid_manager_result(manager_id: str) -> dict[str, object]:
    output_hash = stable_hash(manager_id)
    return {
        "task_id": f"task:{manager_id}",
        "group_id": f"G{manager_id[-2:]}",
        "manager_id": manager_id,
        "expert_id": f"L{manager_id[-2:]}",
        "specialty": "verification",
        "status": "passed",
        "findings": ["evidence-backed finding"],
        "risks": [],
        "assumptions": [],
        "evidence_refs": [f"model:{manager_id}"],
        "model_call_id": f"model:{manager_id}",
        "latency_ms": 1,
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "cost_usd": 0.0,
        "output_hash": output_hash,
    }


def _append_message(board: Blackboard, *, kind: MessageKind, role: MessageRole, payload: dict[str, object], conflict_key: str | None = None, group_id: str | None = None, read_revision: int | None = None) -> None:
    message = CoreMessage.from_payload(
        message_id=f"msg:{stable_hash([kind.value, payload, board.revision])[:16]}",
        run_id=board.run_id,
        revision_id="rev:0",
        role=role,
        kind=kind,
        payload=payload,
    )
    updates: dict[str, object] = {}
    if group_id is not None:
        updates["group_id"] = group_id
    if read_revision is not None:
        updates["read_revision"] = read_revision
    if updates:
        message = message.model_copy(update=updates)
    board.append(message, conflict_key=conflict_key)


def _valid_blackboard() -> Blackboard:
    board = Blackboard("verifier")
    _append_message(board, kind=MessageKind.USER_REQUIREMENT, role=MessageRole.USER, payload={"requirement": "Design APB timer."}, conflict_key="requirement")
    for index in range(7):
        manager_id = f"M{index:02d}"
        _append_message(
            board,
            kind=MessageKind.MANAGER_SUMMARY,
            role=MessageRole.MIDDLE_MANAGER,
            payload={
                "group_id": f"G{index:02d}",
                "manager_id": manager_id,
                "accepted_results": [_valid_manager_result(manager_id)],
                "failed_expert_ids": [],
                "summary": "accepted evidence",
                "output_hash": stable_hash(manager_id),
            },
            conflict_key=f"manager:{manager_id}",
            group_id=f"G{index:02d}",
        )
    return board


def _write_ready_handoff(tmp_path: Path) -> Path:
    plan = _valid_plan()
    certificate = IndustrialSignoffEngine().evaluate(plan)
    plan_path = tmp_path / "reports" / "architecture_plan.md"
    certificate_path = tmp_path / "reports" / "agent1" / "agent1_final_signoff_certificate.json"
    handoff_path = tmp_path / "contracts" / "agent1_to_agent2.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    certificate_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(plan.to_markdown(), encoding="utf-8")
    certificate_path.write_text(json.dumps(certificate.model_dump(mode="json")), encoding="utf-8")
    handoff = Agent2HandoffGate().build(plan=plan, certificate=certificate, plan_ref=str(plan_path), certificate_ref=str(certificate_path))
    handoff_path.write_text(json.dumps(handoff.model_dump(mode="json")), encoding="utf-8")
    return handoff_path


def _assert_replay_bundle(output_dir: Path, *, run_id: str) -> dict[str, object]:
    replay_path = output_dir / "replay" / "replay_bundle.json"
    assert replay_path.exists()
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    assert replay["schema_version"] == "coreweaver.agent1.replay.v1"
    assert replay["run_id"] == run_id
    assert isinstance(replay["events"], list)
    assert isinstance(replay["checkpoints"], list)
    assert "blackboard_snapshot" in replay
    assert "signoff" in replay
    assert "handoff" in replay
    assert "resume" in replay
    assert replay["resume"]["run_id"] == run_id
    assert replay["resume"]["latest_checkpoint_ref"] == "checkpoints/latest.json"
    assert replay["resume"]["reconstructable"] is True
    return replay


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


def test_verifier_accepts_complete_manager_evidence() -> None:
    findings = ReadOnlyVerifier().verify(_valid_blackboard().snapshot())
    assert not [finding for finding in findings if finding.severity == ChallengeSeverity.BLOCKER]


def test_verifier_empty_blackboard_blocks() -> None:
    findings = ReadOnlyVerifier().verify(Blackboard("empty").snapshot())
    assert any(finding.code == "empty_blackboard" and finding.severity == ChallengeSeverity.BLOCKER for finding in findings)


def test_verifier_blocks_missing_manager_summary() -> None:
    board = _valid_blackboard()
    findings = ReadOnlyVerifier(expected_manager_count=8).verify(board.snapshot())
    assert any(finding.code == "manager_summary_count_invalid" for finding in findings)


def test_verifier_blocks_duplicate_manager_summary() -> None:
    board = _valid_blackboard()
    manager_id = "M00"
    _append_message(
        board,
        kind=MessageKind.MANAGER_SUMMARY,
        role=MessageRole.MIDDLE_MANAGER,
        payload={
            "group_id": "G99",
            "manager_id": manager_id,
            "accepted_results": [_valid_manager_result(manager_id)],
            "failed_expert_ids": [],
            "summary": "duplicate evidence",
            "output_hash": stable_hash("duplicate"),
        },
        conflict_key="manager:duplicate",
        group_id="G99",
    )
    findings = ReadOnlyVerifier(expected_manager_count=8).verify(board.snapshot())
    assert any(finding.code == "duplicate_manager_summary" for finding in findings)


def test_verifier_blocks_manager_without_accepted_evidence() -> None:
    board = _valid_blackboard()
    _append_message(
        board,
        kind=MessageKind.MANAGER_SUMMARY,
        role=MessageRole.MIDDLE_MANAGER,
        payload={"group_id": "GX", "manager_id": "MX", "accepted_results": [], "failed_expert_ids": [], "summary": "empty", "output_hash": stable_hash("empty")},
        conflict_key="manager:MX",
        group_id="GX",
    )
    findings = ReadOnlyVerifier(expected_manager_count=8).verify(board.snapshot())
    assert any(finding.code == "manager_summary_without_accepted_evidence" for finding in findings)


def test_verifier_blocks_missing_expert_evidence_fields() -> None:
    board = _valid_blackboard()
    bad_result = _valid_manager_result("M99")
    bad_result.pop("model_call_id")
    _append_message(
        board,
        kind=MessageKind.MANAGER_SUMMARY,
        role=MessageRole.MIDDLE_MANAGER,
        payload={"group_id": "G99", "manager_id": "M99", "accepted_results": [bad_result], "failed_expert_ids": [], "summary": "bad", "output_hash": stable_hash("bad")},
        conflict_key="manager:M99",
        group_id="G99",
    )
    findings = ReadOnlyVerifier(expected_manager_count=8).verify(board.snapshot())
    assert any(finding.code == "expert_result_missing_evidence" for finding in findings)


def test_verifier_blocks_blackboard_conflict() -> None:
    board = _valid_blackboard()
    _append_message(
        board,
        kind=MessageKind.USER_REQUIREMENT,
        role=MessageRole.USER,
        payload={"requirement": "Conflicting requirement."},
        conflict_key="requirement",
        read_revision=0,
    )
    findings = ReadOnlyVerifier().verify(board.snapshot())
    assert any(finding.code == "blackboard_conflict_unresolved" for finding in findings)


def test_handoff_validator_requires_ready_contract_and_passing_certificate(tmp_path: Path) -> None:
    handoff = _write_ready_handoff(tmp_path)
    assert validate_agent1_to_agent2_handoff(handoff)["ready"] is True
    payload = json.loads(handoff.read_text(encoding="utf-8"))
    payload.update({"ready": False, "blockers": ["G01:x"]})
    handoff.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HandoffValidationError, match="not ready"):
        validate_agent1_to_agent2_handoff(handoff)


def test_handoff_validator_rejects_weak_certificate_and_incomplete_handoff(tmp_path: Path) -> None:
    handoff = _write_ready_handoff(tmp_path)
    payload = json.loads(handoff.read_text(encoding="utf-8"))
    payload.pop("locked_memory_map")
    handoff.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HandoffValidationError, match="schema"):
        validate_agent1_to_agent2_handoff(handoff)

    handoff = _write_ready_handoff(tmp_path)
    payload = json.loads(handoff.read_text(encoding="utf-8"))
    certificate = Path(payload["signoff_certificate_ref"])
    certificate.write_text(json.dumps({"passed": True, "gate_results": {"G00": "pass"}}), encoding="utf-8")
    with pytest.raises(HandoffValidationError, match="certificate"):
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


@pytest.mark.parametrize(
    ("requirement", "run_id", "expected"),
    [
        ("Báº¡n lÃ  ai?", "non-design-replay", "NON_DESIGN_CONVERSATION"),
        ("Design an AI chip.", "ambiguous-replay", "REQUIREMENT_CLARIFICATION"),
    ],
)
def test_early_pause_paths_write_replay_bundle(tmp_path: Path, requirement: str, run_id: str, expected: str) -> None:
    session = RuntimeSession(RuntimeState(run_id=run_id, profile="mock_swarm", requirement=requirement, project_name=run_id, output_dir=str(tmp_path)))
    result = asyncio.run(session.start())
    assert result.action_required == expected
    replay = _assert_replay_bundle(tmp_path, run_id=run_id)
    assert replay["blackboard_snapshot"] is None
    assert replay["signoff"] is None
    assert replay["handoff"] is None
    assert replay["resume"]["action_required"] == expected
    if expected == "NON_DESIGN_CONVERSATION":
        assert replay["resume"]["latest_stage"] == "pause_non_design"
    else:
        assert replay["resume"]["latest_stage"] == "clarification"


def test_resume_plan_review_approval_writes_resume_result(tmp_path: Path) -> None:
    session = RuntimeSession(
        RuntimeState(
            run_id="resume-plan-review",
            profile="mock_swarm",
            requirement="Design an APB timer peripheral with 32-bit CSRs, interrupt status W1C, 100MHz clock, synchronous reset.",
            project_name="resume-plan",
            output_dir=str(tmp_path),
        )
    )
    assert asyncio.run(session.start()).action_required == "PLAN_REVIEW"

    resume = RuntimeSession(
        RuntimeState(
            run_id="resume-plan-review",
            profile="mock_swarm",
            requirement="Design an APB timer peripheral with 32-bit CSRs, interrupt status W1C, 100MHz clock, synchronous reset.",
            project_name="resume-plan",
            output_dir=str(tmp_path),
        )
    )
    result = asyncio.run(resume.resume(resume_action="APPROVE"))
    resume_result = json.loads((tmp_path / "replay" / "resume_result.json").read_text(encoding="utf-8"))

    assert result.action_required is None
    assert result.stop_reason.value == "finished"
    assert resume_result["status"] == "done"
    assert any(event["event_type"] == "agent1_rollback_point_restored" for event in resume_result["events"])
    assert any(event["event_type"] == "run_end" for event in resume_result["events"])


def test_resume_clarification_reruns_with_user_detail(tmp_path: Path) -> None:
    start = RuntimeSession(
        RuntimeState(
            run_id="resume-clarification",
            profile="mock_swarm",
            requirement="Design an AI chip.",
            project_name="resume-clarification",
            output_dir=str(tmp_path),
        )
    )
    assert asyncio.run(start.start()).action_required == "REQUIREMENT_CLARIFICATION"

    resume = RuntimeSession(
        RuntimeState(
            run_id="resume-clarification",
            profile="mock_swarm",
            requirement="Design an AI chip.",
            project_name="resume-clarification",
            planning_mode="deep_planning",
            output_dir=str(tmp_path),
        )
    )
    result = asyncio.run(
        resume.resume(
            resume_action="REQUIREMENT_CLARIFICATION",
            notes="Use a 64-bit AXI4 image DMA, 32-bit APB CSRs, 64KB SRAM, AES-256 key lock, 500MHz clock, synchronous reset, and <2W budget.",
        )
    )
    replay = _assert_replay_bundle(tmp_path, run_id="resume-clarification")
    trace_text = (tmp_path / "trace" / "events.jsonl").read_text(encoding="utf-8")

    assert result.action_required == "PLAN_REVIEW"
    assert replay["resume"]["action_required"] == "PLAN_REVIEW"
    assert "agent1_rollback_point_restored" in trace_text
    assert (tmp_path / "reports" / "architecture_plan.md").exists()


def test_resume_blocks_tampered_replay_state(tmp_path: Path) -> None:
    start = RuntimeSession(
        RuntimeState(
            run_id="resume-tampered",
            profile="mock_swarm",
            requirement="Design an APB timer peripheral with 32-bit CSRs, interrupt status W1C, 100MHz clock, synchronous reset.",
            project_name="resume-tampered",
            output_dir=str(tmp_path),
        )
    )
    assert asyncio.run(start.start()).action_required == "PLAN_REVIEW"
    replay_path = tmp_path / "replay" / "replay_bundle.json"
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    replay["resume"]["latest_checkpoint_hash"] = "0" * 64
    replay_path.write_text(json.dumps(replay), encoding="utf-8")

    resume = RuntimeSession(
        RuntimeState(
            run_id="resume-tampered",
            profile="mock_swarm",
            requirement="Design an APB timer peripheral with 32-bit CSRs, interrupt status W1C, 100MHz clock, synchronous reset.",
            project_name="resume-tampered",
            output_dir=str(tmp_path),
        )
    )
    result = asyncio.run(resume.resume(resume_action="APPROVE"))
    resume_result = json.loads((tmp_path / "replay" / "resume_result.json").read_text(encoding="utf-8"))

    assert result.action_required == "HITL_REQUIRED"
    assert resume_result["status"] == "blocked"
    assert any(event["event_type"] == "debug_issue" and event["payload"]["code"] == "replay_resume_invalid" for event in resume_result["events"])


def test_conflict_and_signoff_block_paths_write_replay_bundle(tmp_path: Path) -> None:
    conflict_dir = tmp_path / "conflict"
    conflict = RuntimeSession(
        RuntimeState(
            run_id="conflict-replay",
            profile="mock_swarm",
            requirement="Design an AXI4/APB secure accelerator with 64KB SRAM, 300MHz clock, reset policy, AES key protection, and FORCE_M06_M07_CONFLICT.",
            project_name="conflict",
            output_dir=str(conflict_dir),
        )
    )
    assert asyncio.run(conflict.start()).action_required == "CONFLICT_REQUIRED"
    conflict_replay = _assert_replay_bundle(conflict_dir, run_id="conflict-replay")
    assert conflict_replay["blackboard_snapshot"] is not None
    assert conflict_replay["handoff"] is None

    blocked_dir = tmp_path / "blocked"
    blocked = RuntimeSession(
        RuntimeState(
            run_id="signoff-blocked-replay",
            profile="mock_swarm",
            requirement="Design an APB timer peripheral with 32-bit CSRs, interrupt status W1C, 100MHz clock, synchronous reset, and NO_RESET_POLICY_MUTATION.",
            project_name="blocked",
            output_dir=str(blocked_dir),
        )
    )
    assert asyncio.run(blocked.start()).action_required == "HITL_REQUIRED"
    blocked_replay = _assert_replay_bundle(blocked_dir, run_id="signoff-blocked-replay")
    assert blocked_replay["signoff"] is not None
    assert blocked_replay["handoff"] is not None


def test_studio_agent2_job_rejects_blocked_handoff(tmp_path: Path) -> None:
    handoff = _write_ready_handoff(tmp_path)
    payload = json.loads(handoff.read_text(encoding="utf-8"))
    payload.update({"ready": False, "blockers": ["G01:x"]})
    handoff.write_text(json.dumps(payload), encoding="utf-8")
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
    replay = _assert_replay_bundle(tmp_path, run_id=f"safety-{token.lower()}")
    if token in {"BUDGET_BREACH_MUTATION", "KILL_SWITCH_MUTATION", "CIRCUIT_BREAKER_MUTATION"}:
        assert replay["blackboard_snapshot"] is None
