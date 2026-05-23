---
title: Semiconductor Swarm Product Spec
status: active
owner: swarm-graph
type: product-spec
last_reviewed: 2026-05-17
source_of_truth: true
related_tests:
  - tests/test_swarm_graph.py
---

# Semiconductor Swarm Product Spec

## Mission
Coordinate semiconductor mini-agents to produce architecture, RTL, DV, physical, and formal collateral with formal-first validation and deterministic artifacts.

## Responsibilities
- Route work across Agent1-5.
- Preserve contracts between stages.
- Store checkpoints and reports.
- Surface tool availability as explicit state.
- Keep generated artifacts reproducible where possible.

## Inputs
- User requirements.
- Existing spec JSON or architecture artifacts.
- Agent outputs from previous stages.
- Stable contracts from `docs/design-docs/`.
- Prompt contracts from `docs/prompts/index.md`.

## Outputs
- Architecture/spec artifacts.
- RTL packages, interfaces, and modules.
- Formal SVA wrappers and `.sby` plans.
- DV testbenches and simulation helpers.
- FPGA/physical scripts and constraints.
- Debug reports, self-checks, and status logs.

## State Model
- Requirement ingestion starts flow.
- Agent1 creates architecture contract.
- Agent2 consumes architecture and emits RTL contract.
- Agent5 can validate RTL formally.
- Agent3 builds DV collateral from RTL/contract.
- Agent4 builds backend collateral from RTL/top/device constraints.
- Final reports summarize outputs and unresolved issues.

## Hard Constraints
- Follow `AGENTS.md` routing.
- Do not override stable design docs silently.
- Preserve locked downstream contracts.
- Record tool missing/failing states instead of pretending success.
- Keep behavior aligned with related tests.

## Human-In-The-Loop Points
- Ambiguous user requirements.
- Contract-breaking architecture changes.
- Missing EDA tool where real execution is requested.
- Formal failure needing assumption/design decision.

## Failure Modes
- Missing upstream artifacts.
- Contract drift between docs, code, and tests.
- Tool unavailable or non-deterministic output.
- Generated artifact path mismatch.
- Agent produces plausible but unverified numbers.

## Test Coverage
- `tests/test_swarm_graph.py`
- `tests/test_agent_pipeline.py`