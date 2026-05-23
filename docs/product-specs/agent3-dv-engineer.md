---
title: Agent3 DV Engineer Product Spec
status: active
owner: agent3
type: product-spec
last_reviewed: 2026-05-17
source_of_truth: true
related_tests:
  - tests/test_agent3.py
  - tests/test_real_dv_tools.py
---

# Agent3 DV Engineer Product Spec

## Mission
Generate deterministic DV collateral for RTL using cocotb/SystemVerilog testbench patterns without UVM.

## Responsibilities
- Consume RTL artifacts and architecture constraints.
- Generate testbench files and simulation helpers.
- Provide smoke tests for module interfaces.
- Keep stimulus deterministic via explicit seeds when randomized.
- Report simulator/tool availability clearly.

## Inputs
- RTL artifacts from Agent2.
- Formal and architecture constraints when available.
- Tool detection results.

## Outputs
- Testbench collateral.
- Simulation helpers/reports when applicable.

## DV Contract Rules
- No UVM.
- Testbench ports must match RTL ports.
- Clock/reset sequencing must match architecture.
- Stimulus must be deterministic or seed-controlled.
- Scoreboards/checks must target contract-visible behavior.

## Hard Constraints
- No UVM.
- Keep tests deterministic and contract-driven.
- Do not treat DV as formal replacement.
- Do not hide missing simulator as pass.
- Keep behavior aligned with `tests/test_agent3.py`.

## Failure Modes
- Testbench mismatches RTL ports.
- Simulation tool unavailable.
- Non-deterministic stimulus without seed control.
- Assertions/checkers inconsistent with architecture.
- Generated script has wrong paths.

## Test Coverage
- `tests/test_agent3.py`
- `tests/test_real_dv_tools.py`