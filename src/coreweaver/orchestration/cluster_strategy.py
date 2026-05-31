from __future__ import annotations

from typing import Protocol

from pydantic import Field

from coreweaver.framework_types import StrictCoreModel


class ClusterAssignment(StrictCoreModel):
    group_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    manager_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    leaf_ids: tuple[str, ...]


class ClusterStrategy(Protocol):
    def assign(self, managers: tuple[str, ...], leaves: tuple[str, ...]) -> tuple[ClusterAssignment, ...]:
        ...


class KMeansLikeClusterStrategy:
    """Deterministic plug point; real semantic clustering comes later."""

    def assign(self, managers: tuple[str, ...], leaves: tuple[str, ...]) -> tuple[ClusterAssignment, ...]:
        if not managers:
            return ()
        buckets = {manager: [] for manager in managers}
        for index, leaf in enumerate(leaves):
            buckets[managers[index % len(managers)]].append(leaf)
        return tuple(
            ClusterAssignment(group_id=f"group:{index + 1}", manager_id=manager, leaf_ids=tuple(items))
            for index, (manager, items) in enumerate(buckets.items())
        )
