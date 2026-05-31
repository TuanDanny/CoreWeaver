from __future__ import annotations

from coreweaver.orchestration.topology import AgentTopology, TopologyNode

_MANAGERS = (
    ("M01", "interface_protocol_manager"),
    ("M02", "compute_datapath_manager"),
    ("M03", "memory_dataflow_manager"),
    ("M04", "security_safety_manager"),
    ("M05", "formal_dv_intent_manager"),
    ("M06", "ppa_physical_manager"),
    ("M07", "integration_contract_manager"),
)

_LEAVES = (
    ("L01", "axi_apb_expert", "M01"),
    ("L02", "dma_bandwidth_expert", "M01"),
    ("L03", "csr_register_expert", "M01"),
    ("L04", "protocol_error_expert", "M01"),
    ("L05", "microarchitecture_expert", "M02"),
    ("L06", "datapath_mac_expert", "M02"),
    ("L07", "pipeline_control_expert", "M02"),
    ("L08", "accelerator_scheduling_expert", "M02"),
    ("L09", "sram_buffer_expert", "M03"),
    ("L10", "memory_map_expert", "M03"),
    ("L11", "dataflow_tiling_expert", "M03"),
    ("L12", "coherency_ordering_expert", "M03"),
    ("L13", "crypto_expert", "M04"),
    ("L14", "key_protection_expert", "M04"),
    ("L15", "threat_model_expert", "M04"),
    ("L16", "safety_fault_expert", "M04"),
    ("L17", "formal_property_expert", "M05"),
    ("L18", "cocotb_dv_expert", "M05"),
    ("L19", "coverage_signoff_expert", "M05"),
    ("L20", "lint_contract_expert", "M05"),
    ("L21", "timing_expert", "M06"),
    ("L22", "power_expert", "M06"),
    ("L23", "physical_constraint_expert", "M06"),
    ("L24", "handoff_traceability_expert", "M07"),
)


def default_agent1_topology() -> AgentTopology:
    managers = tuple(TopologyNode(node_id=node_id, role=role) for node_id, role in _MANAGERS)
    leaves = tuple(TopologyNode(node_id=node_id, role=role, group_id=manager_id) for node_id, role, manager_id in _LEAVES)
    return AgentTopology(principal_id="P00", managers=managers, leaves=leaves)


def manager_name(manager_id: str) -> str:
    return dict(_MANAGERS).get(manager_id, manager_id)


def leaf_name(leaf_id: str) -> str:
    return {node_id: role for node_id, role, _manager_id in _LEAVES}.get(leaf_id, leaf_id)
