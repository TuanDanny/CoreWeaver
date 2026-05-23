"""Versioned contract package for Semiconductor Swarm agent boundaries."""

from .constants import (
    AGENT1_TO_AGENT2_V1,
    AGENT2_TO_AGENT3_V1,
    AGENT2_TO_AGENT4_V1,
    AGENT2_TO_AGENT5_V1,
    AGENT3_RESULT_V1,
    AGENT4_RESULT_V1,
    AGENT5_RESULT_V1,
    SWARM_ARTIFACT_INDEX_V1,
    SWARM_TO_DOCS_AGENT_V1,
    PLANNED_V1_CONTRACTS,
)
from .common import APB_SLAVE_INTERFACE
from .envelope import ContractEnvelope
from .registry import ContractValidationError, get_contract_schema, list_contracts, validate_contract
from .validators import build_agent1_to_agent2_contract, validate_agent1_to_agent2_contract, agent1_to_agent2_spec

__all__ = [
    "AGENT1_TO_AGENT2_V1",
    "AGENT2_TO_AGENT3_V1",
    "AGENT2_TO_AGENT4_V1",
    "AGENT2_TO_AGENT5_V1",
    "AGENT3_RESULT_V1",
    "AGENT4_RESULT_V1",
    "AGENT5_RESULT_V1",
    "SWARM_ARTIFACT_INDEX_V1",
    "SWARM_TO_DOCS_AGENT_V1",
    "PLANNED_V1_CONTRACTS",
    "APB_SLAVE_INTERFACE",
    "ContractEnvelope",
    "ContractValidationError",
    "get_contract_schema",
    "list_contracts",
    "validate_contract",
    "build_agent1_to_agent2_contract",
    "validate_agent1_to_agent2_contract",
    "agent1_to_agent2_spec",
]