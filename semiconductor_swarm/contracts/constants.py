"""Canonical v1 contract names for swarm boundaries."""

SWARM_MODE_DEMO = "demo"
SWARM_MODE_DEV = "dev"
SWARM_MODE_STRICT = "strict"
SWARM_MODE_NIGHTLY_REAL_TOOLS = "nightly-real-tools"

SWARM_RUN_MODES = (
    SWARM_MODE_DEMO,
    SWARM_MODE_DEV,
    SWARM_MODE_STRICT,
    SWARM_MODE_NIGHTLY_REAL_TOOLS,
)

SWARM_FALLBACK_POLICIES = {
    SWARM_MODE_DEMO: "fallback_allowed_with_explicit_provenance_no_silent_pass",
    SWARM_MODE_DEV: "fallback_allowed_with_explicit_provenance_no_silent_pass",
    SWARM_MODE_STRICT: "fallback_forbidden_missing_or_broken_real_tools_block_signoff",
    SWARM_MODE_NIGHTLY_REAL_TOOLS: "fallback_forbidden_real_tools_required_for_regression",
}

SWARM_MODE_REQUIRES_REAL_TOOLS = {
    SWARM_MODE_DEMO: False,
    SWARM_MODE_DEV: False,
    SWARM_MODE_STRICT: True,
    SWARM_MODE_NIGHTLY_REAL_TOOLS: True,
}

AGENT1_TO_AGENT2_V1 = "agent1_to_agent2/v1"
AGENT2_TO_AGENT3_V1 = "agent2_to_agent3/v1"
AGENT2_TO_AGENT4_V1 = "agent2_to_agent4/v1"
AGENT2_TO_AGENT5_V1 = "agent2_to_agent5/v1"
AGENT3_RESULT_V1 = "agent3_result/v1"
AGENT4_RESULT_V1 = "agent4_result/v1"
AGENT5_RESULT_V1 = "agent5_result/v1"
SWARM_ARTIFACT_INDEX_V1 = "swarm_artifact_index/v1"
SWARM_TO_DOCS_AGENT_V1 = "swarm_to_docs_agent/v1"

PLANNED_V1_CONTRACTS = (
    AGENT1_TO_AGENT2_V1,
    AGENT2_TO_AGENT3_V1,
    AGENT2_TO_AGENT4_V1,
    AGENT2_TO_AGENT5_V1,
    AGENT3_RESULT_V1,
    AGENT4_RESULT_V1,
    AGENT5_RESULT_V1,
    SWARM_ARTIFACT_INDEX_V1,
    SWARM_TO_DOCS_AGENT_V1,
)