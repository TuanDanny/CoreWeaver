---
title: Agent5 Formal Verifier Product Spec
status: active
owner: agent5
type: product-spec
last_reviewed: 2026-05-17
source_of_truth: true
related_tests:
  - tests/test_agent5.py
  - tests/test_real_formal_tools.py
---

# Agent5 Formal Verifier Product Spec

## Mission
Generate formal wrappers and SymbiYosys plans that verify RTL contracts with explicit assumptions.

## Responsibilities
- Consume RTL artifacts and architecture constraints.
- Generate SVA wrappers.
- Generate `.sby` files and formal run helpers.
- Prefer formal-first validation for safety/control protocols.
- Report solver/tool availability and failures precisely.

## Inputs
- RTL artifacts from Agent2.
- Architecture constraints from Agent1.
- Interface and reset/clock contracts.
- Tool detection results for Yosys/SymbiYosys.

## Outputs
- SVA wrappers.
- `.sby` files.
- Formal plans/reports.

## Formal Contract Rules
- Assumptions must be explicit.
- Assertions must target contract-visible safety/liveness properties.
- Reset constraints must avoid vacuous proofs.
- Wrapper ports must match RTL ports.
- Tool import failures must be reported as failures/skips, not proof success.

## Hard Constraints
- Formal-first: do not treat simulation as replacement for formal checks.
- Keep assumptions explicit.
- Do not overconstrain design to hide bugs.
- Keep assumptions narrow and documented.
- Keep behavior aligned with `tests/test_agent5.py`.

## Failure Modes
- Unbounded assumptions.
- Overconstraint/vacuous proof.
- Tool import failure.
- Wrapper/RTL port mismatch.
- Reset or clock modeling mismatch.

## Test Coverage
- `tests/test_agent5.py`
- `tests/test_real_formal_tools.py`