---
title: Kiem tra toan bo Agent AI file inventory
status: generated
owner: docs-governance
type: generated
last_reviewed: 2026-05-17
source_of_truth: false
---

# Kiem tra toan bo Agent AI - File Inventory

| Path | Type | Owner | Source-of-truth role | Tests | Status | Notes |
|---|---|---|---|---|---|---|
| `docs/semiconductor_swarm_ai.md` | prompt | Prompt Auditor | canonical master prompt | `tests/test_prompt_contracts.py` | active | baseline source |
| `semiconductor_swarm/agents/agent1_planning/` | code | Agent Auditor | Agent1 runtime | `tests/test_agent1.py` | active | planning/schema/replay |
| `semiconductor_swarm/agents/agent2_rtl/` | code | Agent Auditor | Agent2 runtime | `tests/test_agent2.py` | active | RTL generator |
| `semiconductor_swarm/agents/agent3_dv/` | code | Agent Auditor | Agent3 runtime | `tests/test_agent3.py` | active | DV collateral |
| `semiconductor_swarm/agents/agent4_physical/` | code | Agent Auditor | Agent4 runtime | `tests/test_agent4.py` | active | Quartus collateral |
| `semiconductor_swarm/agents/agent5_formal/` | code | Agent Auditor | Agent5 runtime | `tests/test_agent5.py` | active | formal collateral |
| `semiconductor_swarm/tools/` | code | Tool Auditor | EDA/tool wrapper layer | real-tool tests | active | detection/runners/calculators |
| `semiconductor_swarm/swarm_graph.py` | code | Graph Auditor | orchestration | `tests/test_swarm_graph.py` | active | state handoffs |
| `main.py` | code | Graph Auditor | CLI entrypoint | `tests/test_agent_pipeline.py` | active | pipeline launcher |
| `tests/` | tests | Test Auditor | verification suite | `python -m pytest tests -q` | active | 75 passed |
| `docs/generated/` | docs | Docs Auditor | generated audit indices | docs health | active | includes this audit output |
| `generated_rtl/`, `generated_formal/`, `generated_fpga/`, `runs/`, `swarm_out/` | generated | Repo Auditor | run outputs only | not primary oracle | generated | stale artifact risk monitored |
