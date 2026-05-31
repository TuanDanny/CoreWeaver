from __future__ import annotations

from pydantic import Field, model_validator

from coreweaver.framework_types import StrictCoreModel


class TopologyNode(StrictCoreModel):
    node_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    role: str
    group_id: str | None = None


class AgentTopology(StrictCoreModel):
    principal_id: str
    managers: tuple[TopologyNode, ...]
    leaves: tuple[TopologyNode, ...]

    @model_validator(mode="after")
    def _topology_valid(self) -> "AgentTopology":
        ids = [self.principal_id, *[node.node_id for node in self.managers], *[node.node_id for node in self.leaves]]
        if len(ids) != len(set(ids)):
            raise ValueError("topology node ids must be unique")
        return self
