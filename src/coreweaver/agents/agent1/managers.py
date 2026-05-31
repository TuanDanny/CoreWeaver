from __future__ import annotations

import asyncio

from coreweaver.events import AsyncEventStream, CoreEvent, CoreEventType
from coreweaver.framework_types import stable_hash
from coreweaver.models import ModelRouter
from coreweaver.orchestration.cluster_strategy import ClusterAssignment

from .experts import LeafExpertWorker, build_expert_task
from .models import ExpertResult, ManagerSummary, RequirementPack
from .topology_contract import manager_name


class MiddleManagerRunner:
    def __init__(self, model_router: ModelRouter, event_stream: AsyncEventStream, *, max_concurrency: int = 4, max_attempts: int = 2) -> None:
        self.model_router = model_router
        self.event_stream = event_stream
        self.max_concurrency = max_concurrency
        self.max_attempts = max_attempts

    async def run_group(self, *, pack: RequirementPack, assignment: ClusterAssignment, run_id: str, revision_id: str, iteration: int = 1) -> ManagerSummary:
        await self.event_stream.emit(
            CoreEvent(
                event_type=CoreEventType.AGENT1_GROUP_SESSION_START,
                run_id=run_id,
                revision_id=revision_id,
                span_id=f"group:{assignment.manager_id}:start",
                parent_span_id="agent1:cluster",
                payload={
                    "group_id": assignment.group_id,
                    "manager_id": assignment.manager_id,
                    "leaf_ids": assignment.leaf_ids,
                    "iteration": iteration,
                    "manager_name": manager_name(assignment.manager_id),
                },
            )
        )
        semaphore = asyncio.Semaphore(self.max_concurrency)
        results = await asyncio.gather(
            *(self._run_leaf(pack, assignment, leaf_id, run_id, revision_id, iteration, semaphore) for leaf_id in assignment.leaf_ids),
            return_exceptions=True,
        )
        accepted: list[ExpertResult] = []
        failed: list[str] = []
        for leaf_id, result in zip(assignment.leaf_ids, results, strict=True):
            if isinstance(result, Exception):
                failed.append(leaf_id)
            else:
                accepted.append(result)
        status = "passed" if not failed else "degraded"
        summary_text = f"{manager_name(assignment.manager_id)} accepted {len(accepted)} expert results; failed {len(failed)}."
        summary = ManagerSummary(
            group_id=assignment.group_id,
            manager_id=assignment.manager_id,
            accepted_results=tuple(accepted),
            failed_expert_ids=tuple(failed),
            summary=summary_text,
            output_hash=stable_hash([summary_text, [result.output_hash for result in accepted], failed]),
        )
        await self.event_stream.emit(
            CoreEvent(
                event_type=CoreEventType.AGENT1_GROUP_SESSION_DONE if status == "passed" else CoreEventType.AGENT1_GROUP_SESSION_FAILED,
                run_id=run_id,
                revision_id=revision_id,
                span_id=f"group:{assignment.manager_id}:done",
                parent_span_id=f"group:{assignment.manager_id}:start",
                payload={
                    "group_id": assignment.group_id,
                    "manager_id": assignment.manager_id,
                    "status": status,
                    "accepted": len(accepted),
                    "failed_expert_ids": tuple(failed),
                },
            )
        )
        return summary

    async def _run_leaf(
        self,
        pack: RequirementPack,
        assignment: ClusterAssignment,
        leaf_id: str,
        run_id: str,
        revision_id: str,
        iteration: int,
        semaphore: asyncio.Semaphore,
    ) -> ExpertResult:
        async with semaphore:
            task = build_expert_task(pack, group_id=assignment.group_id, manager_id=assignment.manager_id, expert_id=leaf_id, iteration=iteration)
            worker = LeafExpertWorker(self.model_router)
            last_error: Exception | None = None
            for attempt in range(1, self.max_attempts + 1):
                await self.event_stream.emit(
                    CoreEvent(
                        event_type=CoreEventType.AGENT1_LEAF_EXPERT_START,
                        run_id=run_id,
                        revision_id=revision_id,
                        span_id=f"leaf:{leaf_id}:attempt:{attempt}",
                        parent_span_id=f"group:{assignment.manager_id}:start",
                        idempotency_key=task.idempotency_key,
                        payload={
                            "group_id": assignment.group_id,
                            "manager_id": assignment.manager_id,
                            "expert_id": leaf_id,
                            "attempt": attempt,
                            "task_id": task.task_id,
                        },
                    )
                )
                try:
                    await self.event_stream.emit(
                        CoreEvent(
                            event_type=CoreEventType.AGENT1_MODEL_ROUTE_SELECTED,
                            run_id=run_id,
                            revision_id=revision_id,
                            span_id=f"leaf:{leaf_id}:route:{attempt}",
                            parent_span_id=f"leaf:{leaf_id}:attempt:{attempt}",
                            idempotency_key=task.idempotency_key,
                            payload={
                                "group_id": assignment.group_id,
                                "manager_id": assignment.manager_id,
                                "expert_id": leaf_id,
                                "route": "agent1-leaf",
                            },
                        )
                    )
                    result = await worker.run(task, pack)
                    await self.event_stream.emit(
                        CoreEvent(
                            event_type=CoreEventType.AGENT1_LEAF_EXPERT_DONE,
                            run_id=run_id,
                            revision_id=revision_id,
                            span_id=f"leaf:{leaf_id}:done:{attempt}",
                            parent_span_id=f"leaf:{leaf_id}:attempt:{attempt}",
                            model_call_id=result.model_call_id,
                            idempotency_key=task.idempotency_key,
                            latency_ms=result.latency_ms,
                            prompt_tokens=result.prompt_tokens,
                            completion_tokens=result.completion_tokens,
                            cost_usd=result.cost_usd,
                            payload={
                                "group_id": assignment.group_id,
                                "manager_id": assignment.manager_id,
                                "expert_id": leaf_id,
                                "status": result.status,
                                "model_call_id": result.model_call_id,
                            },
                        )
                    )
                    return result
                except Exception as exc:  # noqa: PERF203 - explicit retry trace matters here.
                    last_error = exc
                    event_type = CoreEventType.AGENT1_LEAF_EXPERT_RETRY if attempt < self.max_attempts else CoreEventType.AGENT1_LEAF_EXPERT_FAILED
                    await self.event_stream.emit(
                        CoreEvent(
                            event_type=event_type,
                            run_id=run_id,
                            revision_id=revision_id,
                            span_id=f"leaf:{leaf_id}:failed:{attempt}",
                            parent_span_id=f"leaf:{leaf_id}:attempt:{attempt}",
                            idempotency_key=task.idempotency_key,
                            retry_count=attempt,
                            payload={
                                "group_id": assignment.group_id,
                                "manager_id": assignment.manager_id,
                                "expert_id": leaf_id,
                                "attempt": attempt,
                                "error": exc.__class__.__name__,
                            },
                        )
                    )
                    if attempt >= self.max_attempts:
                        await self.event_stream.emit(
                            CoreEvent(
                                event_type=CoreEventType.DEBUG_ISSUE,
                                run_id=run_id,
                                revision_id=revision_id,
                                span_id=f"issue:leaf:{leaf_id}:failed",
                                parent_span_id=f"leaf:{leaf_id}:failed:{attempt}",
                                payload={
                                    "severity": "error",
                                    "source": "agent1.leaf",
                                    "code": "leaf_expert_failed",
                                    "message": f"Leaf expert {leaf_id} failed after retry budget.",
                                    "group_id": assignment.group_id,
                                    "manager_id": assignment.manager_id,
                                    "expert_id": leaf_id,
                                },
                            )
                        )
                    if attempt < self.max_attempts:
                        await asyncio.sleep(0.01 * attempt)
            assert last_error is not None
            raise last_error
