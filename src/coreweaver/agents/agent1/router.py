from __future__ import annotations

from coreweaver.orchestration.cluster_strategy import ClusterAssignment

from .topology_contract import default_agent1_topology


class Agent1ClusterRouter:
    """Config-shaped cluster router. Topology can be replaced without rewriting runtime."""

    def assign(self) -> tuple[ClusterAssignment, ...]:
        topology = default_agent1_topology()
        assignments: list[ClusterAssignment] = []
        for manager in topology.managers:
            leaf_ids = tuple(leaf.node_id for leaf in topology.leaves if leaf.group_id == manager.node_id)
            assignments.append(ClusterAssignment(group_id=f"group:{manager.node_id}", manager_id=manager.node_id, leaf_ids=leaf_ids))
        return tuple(assignments)
