---
title: Test Coverage Index
status: active
owner: docs-governance
type: generated
last_reviewed: 2026-05-20
source_of_truth: false
---

# Test Coverage Index

| Area | Tests | Notes |
|---|---|---|
| Swarm graph | `tests/test_swarm_graph.py` | Pipeline state/routing behavior. |
| Agent pipeline | `tests/test_agent_pipeline.py` | Multi-agent integration behavior. |
| Agent1 | `tests/test_agent1.py` | System architect contract. |
| Agent2 | `tests/test_agent2.py` | RTL generation contract. |
| Agent3 | `tests/test_agent3.py`, `tests/test_real_dv_tools.py` | DV outputs and real tool detection. |
| Agent4 | `tests/test_agent4.py`, `tests/test_real_quartus_tools.py` | FPGA/Quartus outputs and detection. |
| Agent5 | `tests/test_agent5.py`, `tests/test_real_formal_tools.py` | Formal outputs and SymbiYosys/Yosys integration. |
| Prompts | `tests/test_prompt_contracts.py` | Prompt compliance. |
| Tool detection | `tests/test_real_tool_detection.py` | EDA tool availability checks. |
| Docs health | `tests/test_docs_health.py` | Knowledge store integrity. |
| Contract registry | `tests/test_swarm_contract_registry.py` | Versioned handoff schema coverage. |
| Agent6-ready isolation | `tests/test_agent6_ready_contract.py` | Contract isolation and Agent6 handoff readiness. |
