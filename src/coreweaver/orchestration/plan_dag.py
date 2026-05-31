from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator, model_validator

from coreweaver.framework_types import StrictCoreModel, validate_id_text


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class FailurePolicy(str, Enum):
    RETRY = "retry"
    REPLAN = "replan"
    HITL = "hitl"
    BLOCK = "block"
    DEGRADE = "degrade"


class RetryPolicy(StrictCoreModel):
    max_attempts: int = 1
    backoff_ms: int = 0


class PlanNode(StrictCoreModel):
    node_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    lane: str = "sequential"
    status: NodeStatus = NodeStatus.PENDING
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    failure_policy: FailurePolicy = FailurePolicy.BLOCK

    @field_validator("node_id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        return validate_id_text(value, "node_id")


class DependencyEdge(StrictCoreModel):
    source: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    target: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")


class PlanDag(StrictCoreModel):
    nodes: tuple[PlanNode, ...]
    edges: tuple[DependencyEdge, ...] = ()

    @model_validator(mode="after")
    def _validate_graph(self) -> "PlanDag":
        ids = [node.node_id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("PlanDag node ids must be unique")
        id_set = set(ids)
        for edge in self.edges:
            if edge.source not in id_set or edge.target not in id_set:
                raise ValueError("PlanDag edge references missing node")
        self._assert_acyclic(ids)
        return self

    def ready_nodes(self, completed: set[str]) -> tuple[PlanNode, ...]:
        ready: list[PlanNode] = []
        for node in self.nodes:
            if node.node_id in completed:
                continue
            deps = {edge.source for edge in self.edges if edge.target == node.node_id}
            if deps <= completed:
                ready.append(node)
        return tuple(ready)

    def _assert_acyclic(self, ids: list[str]) -> None:
        graph = {node_id: [edge.target for edge in self.edges if edge.source == node_id] for node_id in ids}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError("PlanDag cannot contain cycles")
            if node_id in visited:
                return
            visiting.add(node_id)
            for child in graph[node_id]:
                visit(child)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in ids:
            visit(node_id)
