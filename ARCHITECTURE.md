---
title: Semiconductor Swarm Architecture
status: active
owner: swarm-graph
type: architecture
last_reviewed: 2026-05-23
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
- `studio/backend/agent_service.py`: Studio service boundary for job validation, queue dispatch, cancellation, and runner coordination.
- `studio/backend/job_queue.py`: Python-native in-process queue with a Redis/BullMQ-compatible adapter shape for future migration.
- `studio/backend/model_gateway.py`: provider registry boundary; V1 enables OpenAI-compatible chat completions only.
- `studio/frontend/src/`: React mission-control UI, WebSocket logs/traces, and job queue panel.
- `tests/`: source of executable behavior.
- `docs/`: repository knowledge store.

## Studio Web Boundary
```text
React Studio / CLI
  -> Agent Controller API
  -> Agent Service
  -> In-process Job Queue
  -> Runner / Draft Workers
  -> semiconductor_swarm agents
  -> Model Gateway
  -> OpenAI-compatible endpoint
```

- Existing run APIs stay compatible: `/api/runs/start`, `/api/runs/{run_id}/resume`, `/api/runs/{run_id}/stop`.
- Job APIs are additive: `/api/jobs`, `/api/jobs/{job_id}`, `/api/jobs/{job_id}/cancel`.
- `job_id` links UI actions, queue records, runner events, traces, artifacts, and replay logs.
- Browser never receives raw API keys; it only sends credential refs.

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
