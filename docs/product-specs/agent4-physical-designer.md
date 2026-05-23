---
title: Agent4 Physical Designer Product Spec
status: active
owner: agent4
type: product-spec
last_reviewed: 2026-05-17
source_of_truth: true
related_tests:
  - tests/test_agent4.py
  - tests/test_real_quartus_tools.py
---

# Agent4 Physical Designer Product Spec

## Mission
Generate FPGA/physical collateral for backend handoff while tracking real EDA tool availability explicitly.

## Responsibilities
- Consume RTL/top-level artifacts.
- Generate QSF/SDC/backend scripts.
- Preserve top module, clock, reset, and device intent.
- Provide physical signoff plan/report artifacts.
- Report Quartus/tool status without pretending success.

## Inputs
- RTL artifacts.
- Target device constraints.
- Clock/reset/timing intent from architecture.
- Tool detection results.

## Outputs
- QSF/SDC/backend scripts.
- Physical signoff plan/report artifacts.

## Physical Contract Rules
- Top-level name must match RTL.
- Clocks and resets must match architecture.
- Device/family must be explicit when required.
- Tool missing state must be represented as skipped/unavailable, not pass.
- Timing constraints must be conservative and readable.

## Hard Constraints
- Preserve top-level names and clock/reset intent.
- Treat external EDA tool availability as explicit state.
- Do not require Quartus for dry-run generation tests.
- Keep behavior aligned with `tests/test_agent4.py`.

## Failure Modes
- Missing target device.
- Invalid constraints.
- EDA tool unavailable.
- Top module mismatch.
- Timing clock missing or duplicated.

## Test Coverage
- `tests/test_agent4.py`
- `tests/test_real_quartus_tools.py`