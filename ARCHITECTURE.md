---
title: Semiconductor Swarm Architecture
status: active
owner: swarm-graph
type: architecture
last_reviewed: 2026-05-17
source_of_truth: true
related_code:
  - main.py
  - semiconductor_swarm/swarm_graph.py
related_tests:
  - tests/test_swarm_graph.py
  - tests/test_agent_pipeline.py
---

# Semiconductor Swarm Architecture

## Purpose
Map system structure for agents and humans. Keep details in linked docs.

## Pipeline
```text
Requirements -> Agent1 Architect -> Agent2 RTL -> Agent5 Formal -> Agent3 DV -> Agent4 Physical -> Reports/HITL
```

## Core Components
- `main.py`: user entrypoint.
- `semiconductor_swarm/swarm_graph.py`: orchestration and checkpoint flow.
- `semiconductor_swarm/agents/`: agent implementations and prompts.
- `semiconductor_swarm/tools/`: deterministic calculators and EDA runners.
- `tests/`: source of executable behavior.
- `docs/`: repository knowledge store.

## Artifact Flow
- Agent1 emits architecture/spec outputs.
- Agent2 emits RTL packages, interfaces, and modules.
- Agent5 emits SVA/SBY formal collateral.
- Agent3 emits DV/testbench collateral.
- Agent4 emits FPGA/QSF/SDC/backend collateral.

## Tool Boundaries
LLMs may propose structure. Deterministic tools must produce numeric PPA/bandwidth and EDA execution results.

## Human Gates
HITL is required when repeated debug/validation failures persist or when tool availability blocks signoff.

## Deeper Docs
- Knowledge store design: `docs/design-docs/repo-knowledge-store.md`
- Product specs: `docs/product-specs/index.md`
- Active plans: `PLANS.md`