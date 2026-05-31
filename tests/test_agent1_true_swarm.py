import asyncio
from pathlib import Path

from coreweaver.agents.agent1.runtime import Agent1SwarmRuntime
from coreweaver.events import AsyncEventStream
from coreweaver.framework_types import stable_hash
from coreweaver.models import ModelResponse, ModelRouter
from coreweaver.runtime import RuntimeSession, RuntimeState


SECURE_NPU = (
    "Design a Secure Edge AI Vision NPU. It requires a 64-bit AXI4 interface for high-speed image data DMA, "
    "and a 32-bit APB interface for firmware configuration. The NPU contains a MAC array and a 64KB SRAM buffer. "
    "The neural network weights must be decrypted on-the-fly using an AES-256 core. The AES Secret Key must be "
    "software-programmable but strictly hardware-protected (Write-Only, locked after boot, no readback). "
    "Target frequency: 500MHz. Power budget: < 2W."
)


class FailingExpertsClient:
    async def complete(self, *, prompt: str, idempotency_key: str) -> ModelResponse:
        if any(name in prompt for name in ("axi_apb_expert", "crypto_expert", "timing_expert")):
            raise TimeoutError("mock timeout")
        text = f"ok:{stable_hash(prompt)[:8]}"
        return ModelResponse(text=text, output_hash=stable_hash(text), prompt_tokens=len(prompt.split()), completion_tokens=1)


def test_secure_npu_true_swarm_generates_plan_and_handoff(tmp_path: Path) -> None:
    session = RuntimeSession(
        RuntimeState(
            run_id="swarm-npu",
            profile="mock_swarm",
            requirement=SECURE_NPU,
            project_name="secure_npu",
            planning_mode="deep_planning",
            output_dir=str(tmp_path),
        )
    )
    result = asyncio.run(session.start())
    assert result.action_required == "PLAN_REVIEW"
    plan = (tmp_path / "reports" / "architecture_plan.md").read_text(encoding="utf-8")
    assert "AXI4" in plan
    assert "APB" in plan
    assert "AES-256" in plan
    assert "WO" in plan
    assert "lock-after-boot" in plan
    assert "500MHz" in plan
    assert (tmp_path / "contracts" / "agent1_to_agent2.json").exists()
    assert (tmp_path / "trace" / "events.jsonl").exists()
    assert any(event.event_type.value == "agent1_handoff_ready" for event in session.event_stream.history)


def test_non_design_and_ambiguous_inputs_pause_without_swarm(tmp_path: Path) -> None:
    async def scenario(requirement: str, run_id: str):
        session = RuntimeSession(
            RuntimeState(run_id=run_id, profile="mock_swarm", requirement=requirement, project_name=run_id, output_dir=str(tmp_path / run_id))
        )
        result = await session.start()
        return result, tuple(event.safe_dump() for event in session.event_stream.history)

    non_design_result, non_design = asyncio.run(scenario("Bạn là ai?", "non-design"))
    ambiguous_result, ambiguous = asyncio.run(scenario("Design an AI chip.", "ambiguous"))
    assert non_design_result.action_required == "NON_DESIGN_CONVERSATION"
    assert ambiguous_result.action_required == "REQUIREMENT_CLARIFICATION"
    assert "NON_DESIGN_CONVERSATION" in str(non_design)
    assert "REQUIREMENT_CLARIFICATION" in str(ambiguous)
    assert not (tmp_path / "non-design" / "reports" / "architecture_plan.md").exists()


def test_conflict_hard_cap_reaches_hitl(tmp_path: Path) -> None:
    requirement = "Design an AXI4/APB secure accelerator with 64KB SRAM, 300MHz clock, reset policy, AES key protection, and FORCE_M06_M07_CONFLICT."
    session = RuntimeSession(RuntimeState(run_id="conflict", profile="mock_swarm", requirement=requirement, project_name="conflict", output_dir=str(tmp_path)))
    result = asyncio.run(session.start())
    reviews = [event for event in session.event_stream.history if event.event_type.value == "agent1_principal_group_review"]
    assert len(reviews) == 3
    assert result.action_required == "CONFLICT_REQUIRED"
    assert "CONFLICT_REQUIRED" in str([event.safe_dump() for event in session.event_stream.history])
    assert not (tmp_path / "contracts" / "agent1_to_agent2.json").exists()


def test_partial_expert_failures_retry_and_do_not_crash(tmp_path: Path) -> None:
    event_stream = AsyncEventStream()
    runtime = Agent1SwarmRuntime(event_stream=event_stream, model_router=ModelRouter(FailingExpertsClient()))
    asyncio.run(
        runtime.run(
            run_id="partial-fail",
            revision_id="rev:0",
            requirement=SECURE_NPU,
            project_name="partial_fail",
            planning_mode="deep_planning",
            output_dir=tmp_path,
        )
    )
    text = "\n".join(event.event_type.value + " " + str(event.payload) for event in event_stream.history)
    assert "agent1_leaf_expert_retry" in text
    assert "agent1_leaf_expert_failed" in text
    assert "leaf_expert_failed" in text
    assert "agent1_group_session_failed" in text
    assert (tmp_path / "reports" / "architecture_plan.md").exists()
