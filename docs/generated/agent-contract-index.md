---
title: Agent Contract Index
status: active
owner: docs-governance
type: generated
last_reviewed: 2026-05-20
source_of_truth: false
---

# Agent Contract Index

Manual generated-style index for quick agent routing.

| Agent | Product Spec | Prompt Source | Primary Tests | Main Code |
|---|---|---|---|---|
| Agent1 System Architect | `docs/product-specs/agent1-system-architect.md` | `semiconductor_swarm/agents/agent1_planning/agent1_prompt.py` | `tests/test_agent1.py` | `semiconductor_swarm/agents/agent1_planning/architect.py`, `semiconductor_swarm/agents/agent1_planning/agent1_subgraph.py` |
| Agent2 RTL Designer | `docs/product-specs/agent2-rtl-designer.md` | `semiconductor_swarm/agents/agent2_rtl/agent2_prompt.py` | `tests/test_agent2.py` | `semiconductor_swarm/agents/agent2_rtl/rtl_designer.py`, `semiconductor_swarm/agents/agent2_rtl/orchestrator.py` |
| Agent3 DV Engineer | `docs/product-specs/agent3-dv-engineer.md` | `semiconductor_swarm/agents/agent3_dv/agent3_prompt.py` | `tests/test_agent3.py`, `tests/test_real_dv_tools.py` | `semiconductor_swarm/agents/agent3_dv/dv_engineer.py` |
| Agent4 Physical Designer | `docs/product-specs/agent4-physical-designer.md` | `semiconductor_swarm/agents/agent4_physical/agent4_prompt.py` | `tests/test_agent4.py`, `tests/test_real_quartus_tools.py` | `semiconductor_swarm/agents/agent4_physical/physical_designer.py` |
| Agent5 Formal Verifier | `docs/product-specs/agent5-formal-verifier.md` | `semiconductor_swarm/agents/agent5_formal/agent5_prompt.py` | `tests/test_agent5.py`, `tests/test_real_formal_tools.py` | `semiconductor_swarm/agents/agent5_formal/formal_verifier.py` |

## Contract Rule
Product specs are source-of-truth for intended behavior. Tests/code define executable behavior.
