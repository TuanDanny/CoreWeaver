import asyncio

import pytest
from pydantic import ValidationError

from coreweaver.agents.agent1 import Agent1PlaceholderWorker, default_agent1_topology
from coreweaver.debug import ContextSummary, ReplayBundle, invariant_check_context_summary
from coreweaver.events import AsyncEventStream, CoreEvent, CoreEventType, map_core_event_to_studio
from coreweaver.framework_types import make_idempotency_key, stable_hash
from coreweaver.hooks import HookChain, HookContext, HookPoint, HookResult, HookStatus, secret_scan_hook
from coreweaver.messages import Blackboard, CoreMessage, MessageKind, MessageRole
from coreweaver.models import MockModelClient, ModelRouter
from coreweaver.orchestration import DependencyEdge, KMeansLikeClusterStrategy, PlanDag, PlanNode
from coreweaver.runtime import AgentLoop, AgentLoopConfig, ExecutorPolicy, Scheduler, StopReason
from coreweaver.safety import BudgetDecision, CanaryFinding, CircuitBreakerState, CostBudget, CostUsage, KillSwitchState, ProposalCommitRecord
from coreweaver.tools import PermissionDecision, PermissionStatus, ToolRegistry, ToolSchema


def _hash(value: object) -> str:
    return stable_hash(value)


def cpu_sum(limit: int) -> int:
    return sum(range(limit))


def make_message(kind: MessageKind = MessageKind.USER_REQUIREMENT, *, message_id: str = "m1", payload: object = "hello", read_revision: int | None = None) -> CoreMessage:
    return CoreMessage.from_payload(
        message_id=message_id,
        run_id="run1",
        revision_id="rev1",
        role=MessageRole.USER,
        kind=kind,
        payload=payload,
        replayable=kind in {MessageKind.EXPERT_TASK, MessageKind.HANDOFF_CANDIDATE},
        idempotency_key=make_idempotency_key("run1", message_id) if kind in {MessageKind.EXPERT_TASK, MessageKind.HANDOFF_CANDIDATE} else None,
    ).model_copy(update={"read_revision": read_revision})


def test_message_contract_requires_idempotency_and_redacts() -> None:
    with pytest.raises(ValidationError):
        CoreMessage(
            message_id="m2",
            run_id="run1",
            revision_id="rev1",
            role=MessageRole.LEAF_EXPERT,
            kind=MessageKind.EXPERT_TASK,
            blocks=make_message().blocks,
            input_hash=_hash("in"),
            output_hash=_hash("out"),
        )
    with pytest.raises(ValidationError):
        make_message(payload={"token": "sk-" + "abcdefghijklmnopqrstuvwxyz123456"})
    message = make_message(payload={"api_key": "placeholder"})
    assert message.safe_dump()["blocks"][0]["content"]["api_key"] == "<redacted>"


def test_blackboard_append_only_and_conflict_detection() -> None:
    board = Blackboard("run1")
    first = make_message(message_id="m1", payload={"freq": "500MHz"}, read_revision=0)
    first_result = board.append(first, conflict_key="freq")
    second = make_message(message_id="m2", payload={"freq": "250MHz"}, read_revision=0)
    second_result = board.append(second, conflict_key="freq")
    assert first_result.conflict is None
    assert second_result.conflict is not None
    assert second_result.conflict_message is not None
    assert not hasattr(board, "update")
    assert board.snapshot().revision == 2


async def _collect_one(stream: AsyncEventStream):
    async for event in stream:
        return event
    return None


def test_async_event_stream_and_studio_mapping() -> None:
    async def scenario():
        stream = AsyncEventStream()
        event = CoreEvent(
            event_type=CoreEventType.HITL_REQUIRED,
            run_id="run1",
            revision_id="rev1",
            span_id="span1",
            parent_span_id=None,
            payload={"action_required": "CORE_SKELETON_READY", "message": "ready"},
        )
        task = asyncio.create_task(_collect_one(stream))
        await stream.emit(event)
        seen = await task
        await stream.close()
        return seen

    seen = asyncio.run(scenario())
    assert seen is not None
    mapped = map_core_event_to_studio(seen)
    assert mapped["type"] == "pause"
    assert mapped["action_required"] == "CORE_SKELETON_READY"
    with pytest.raises(ValidationError):
        CoreEvent(event_type=CoreEventType.MODEL_CALL_START, run_id="run1", revision_id="rev1", span_id="s", parent_span_id=None)


def test_hook_chain_short_circuits_before_later_hook() -> None:
    calls: list[str] = []

    class LaterHook:
        name = "later"

        async def __call__(self, context: HookContext) -> HookResult:
            calls.append("later")
            return HookResult.continue_("later")

    context = HookContext(run_id="run1", revision_id="rev1", span_id="s", hook_point=HookPoint.ON_MODEL_CALL, payload="Bearer " + "abcdefghijklmnopqrstuvwxyz")
    results = asyncio.run(HookChain([secret_scan_hook, LaterHook()]).run(context))
    assert results[0].status == HookStatus.BLOCK
    assert calls == []


def test_agent_loop_hard_cap_and_framework_placeholder() -> None:
    async def never_finishes(_: int):
        return None

    capped = asyncio.run(AgentLoop(config=AgentLoopConfig(max_iters=3, run_profile="local_llm")).run(run_id="run1", revision_id="rev1", step=never_finishes))
    assert capped.stop_reason == StopReason.MAX_ITERS
    assert capped.iterations == 3
    skeleton = asyncio.run(AgentLoop(config=AgentLoopConfig(run_profile="local_skeleton")).run(run_id="run2", revision_id="rev1"))
    assert skeleton.action_required == "CORE_SKELETON_READY"


def test_plan_dag_scheduler_and_cluster_strategy() -> None:
    dag = PlanDag(
        nodes=(PlanNode(node_id="a"), PlanNode(node_id="b", lane="concurrent"), PlanNode(node_id="c", lane="concurrent")),
        edges=(DependencyEdge(source="a", target="b"), DependencyEdge(source="a", target="c")),
    )

    async def task(node_id: str) -> str:
        return f"done:{node_id}"

    result = asyncio.run(Scheduler().run(dag, task))
    assert result.completed == ("a", "b", "c")
    with pytest.raises(ValidationError):
        PlanDag(nodes=(PlanNode(node_id="a"), PlanNode(node_id="b")), edges=(DependencyEdge(source="a", target="b"), DependencyEdge(source="b", target="a")))
    assignments = KMeansLikeClusterStrategy().assign(("M01", "M02"), ("L01", "L02", "L03"))
    assert assignments[0].leaf_ids == ("L01", "L03")


def test_cpu_executor_keeps_event_loop_responsive() -> None:
    async def scenario() -> tuple[str, int]:
        executor = ExecutorPolicy(max_cpu_workers=1)
        try:
            cpu_task = asyncio.create_task(executor.run_cpu(cpu_sum, 10000))
            await asyncio.sleep(0)
            marker = "responsive"
            return marker, await cpu_task
        finally:
            executor.shutdown()

    marker, result = asyncio.run(scenario())
    assert marker == "responsive"
    assert result == sum(range(10000))


def test_model_and_tool_adapters_are_mocked_and_idempotent() -> None:
    async def scenario():
        router = ModelRouter(MockModelClient())
        first = await router.complete(prompt="hello", idempotency_key="key1")
        second = await router.complete(prompt="hello changed", idempotency_key="key1")
        registry = ToolRegistry()
        registry.register(
            ToolSchema(name="echo", input_schema={"type": "object", "required": ["value"], "properties": {"value": {"type": "string"}}, "additionalProperties": False}),
            lambda payload: {"echo": payload["value"]},
            PermissionDecision(status=PermissionStatus.ALLOW, reason="test"),
        )
        tool_first = await registry.call("echo", {"value": "x"}, idempotency_key="tool-key")
        tool_second = await registry.call("echo", {"value": "y"}, idempotency_key="tool-key")
        return first, second, tool_first, tool_second

    first, second, tool_first, tool_second = asyncio.run(scenario())
    assert first == second
    assert tool_first == tool_second


def test_safety_and_context_compression_contracts() -> None:
    assert CostBudget(max_tokens=10, max_cost_usd=1.0).decide(CostUsage(tokens=9, cost_usd=0.1)) == BudgetDecision.WARN
    KillSwitchState(enabled=True, controlled_by_agent=False).assert_valid()
    with pytest.raises(ValueError):
        KillSwitchState(enabled=True, controlled_by_agent=True).assert_valid()
    assert CircuitBreakerState(failure_count=3).tripped is True
    assert CanaryFinding.from_touch("canary1", True).quarantine_required is True
    with pytest.raises(PermissionError):
        ProposalCommitRecord(proposal_id="p1", action="write", risk="high").commit()
    summary = ContextSummary(task_overview="x", unresolved_challenges=("c1",), next_actions=())
    assert "unresolved_challenges_need_next_actions" in invariant_check_context_summary(summary)
    blocked = ContextSummary(task_overview="x", signoff_blockers=("b1",), pending_hitl=())
    assert "signoff_blockers_need_pending_hitl" in invariant_check_context_summary(blocked)
    pending = ContextSummary(task_overview="x", open_risks=("pending replayable work",))
    assert "pending_replayable_work_needs_idempotency_keys" in invariant_check_context_summary(pending)
    with pytest.raises(ValidationError):
        ContextSummary(task_overview="sk-" + "abcdefghijklmnopqrstuvwxyz123456")


def test_agent1_placeholder_topology_and_replay_bundle() -> None:
    topology = default_agent1_topology()
    assert len(topology.managers) == 7
    assert len(topology.leaves) == 24
    message = make_message()
    result = asyncio.run(Agent1PlaceholderWorker().run(message))
    assert result.kind == MessageKind.MANAGER_SUMMARY
    event = CoreEvent(event_type=CoreEventType.MESSAGE_PUBLISHED, run_id="run1", revision_id="rev1", span_id="s", parent_span_id=None)
    bundle = ReplayBundle(run_id="run1", messages=(message, result), events=(event,))
    assert bundle.event_order() == ("s",)
    assert bundle.context_summary.task_overview == "framework skeleton"
