from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import Field

from coreweaver.framework_types import StrictCoreModel
from coreweaver.orchestration.plan_dag import PlanDag

from .executors import ExecutorPolicy

TaskFactory = Callable[[str], Awaitable[Any]]


class SchedulerResult(StrictCoreModel):
    completed: tuple[str, ...]
    failed: tuple[str, ...] = ()
    results: dict[str, Any] = Field(default_factory=dict)


class Scheduler:
    def __init__(self, executor_policy: ExecutorPolicy | None = None) -> None:
        self.executor_policy = executor_policy or ExecutorPolicy()

    async def run(self, dag: PlanDag, task_factory: TaskFactory) -> SchedulerResult:
        completed: set[str] = set()
        failed: list[str] = []
        results: dict[str, Any] = {}
        while len(completed) + len(failed) < len(dag.nodes):
            ready = [node for node in dag.ready_nodes(completed) if node.node_id not in failed]
            if not ready:
                break
            sequential = [node for node in ready if node.lane != "concurrent"]
            concurrent = [node for node in ready if node.lane == "concurrent"]
            for node in sequential:
                try:
                    results[node.node_id] = await task_factory(node.node_id)
                    completed.add(node.node_id)
                except Exception:
                    failed.append(node.node_id)
            if concurrent:
                call_results = await asyncio.gather(
                    *(task_factory(node.node_id) for node in concurrent),
                    return_exceptions=True,
                )
                for node, result in zip(concurrent, call_results, strict=True):
                    if isinstance(result, Exception):
                        failed.append(node.node_id)
                    else:
                        results[node.node_id] = result
                        completed.add(node.node_id)
        return SchedulerResult(completed=tuple(sorted(completed)), failed=tuple(failed), results=results)
