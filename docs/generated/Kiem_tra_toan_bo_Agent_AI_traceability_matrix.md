---
title: Kiem tra toan bo Agent AI traceability matrix
status: generated
owner: docs-governance
type: generated
last_reviewed: 2026-05-17
source_of_truth: false
---

# Kiem tra toan bo Agent AI - Traceability Matrix

| Requirement | Source | Code | Test | Generated artifact | Status | Gap |
|---|---|---|---|---|---|---|
| Agent1 produces architecture spec for downstream agents | `docs/semiconductor_swarm_ai.md`, product specs | `semiconductor_swarm/agents/agent1_planning/` | `tests/test_agent1.py` | spec JSON/state | pass | none found |
| Agent2 produces RTL, packages, interfaces, top module, debug/self-check artifacts | `docs/semiconductor_swarm_ai.md`, Agent2 spec | `semiconductor_swarm/agents/agent2_rtl/rtl_designer.py` | `tests/test_agent2.py` | RTL file dicts / `generated_rtl` style outputs | pass | none found |
| Agent3 produces DV collateral and handles missing tools | `docs/semiconductor_swarm_ai.md`, Agent3 spec | `semiconductor_swarm/agents/agent3_dv/dv_engineer.py` | `tests/test_agent3.py`, `tests/test_real_dv_tools.py` | TB/regression/report dicts | pass | none found |
| Agent4 produces Quartus FPGA collateral and timing/resource decision | `docs/semiconductor_swarm_ai.md`, Agent4 spec | `semiconductor_swarm/agents/agent4_physical/physical_designer.py`, `semiconductor_swarm/tools/quartus_runner.py` | `tests/test_agent4.py`, `tests/test_real_quartus_tools.py` | QSF/SDC/TCL/report dicts | pass | none found |
| Agent5 produces formal SVA/SBY collateral and formal decision | `docs/semiconductor_swarm_ai.md`, Agent5 spec | `semiconductor_swarm/agents/agent5_formal/formal_verifier.py`, `semiconductor_swarm/tools/symbiyosys_runner.py` | `tests/test_agent5.py`, `tests/test_real_formal_tools.py` | SVA/SBY/report dicts | pass | none found |
| Swarm orchestrates Agent1 -> Agent2 -> Agent3 -> Agent4 -> Agent5 | architecture docs | `semiconductor_swarm/swarm_graph.py`, `main.py` | `tests/test_swarm_graph.py`, `tests/test_agent_pipeline.py` | final swarm report/state | pass | none found |
| Prompt contracts stay aligned with canonical prompt | `docs/prompts/canonical-prompts.md`, `docs/prompt_compliance_matrix.yaml` | agent prompt files | `tests/test_prompt_contracts.py` | prompt contract index | pass | none found |
