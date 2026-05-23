---
title: Agent2 RTL Designer Product Spec
status: active
owner: agent2
type: product-spec
last_reviewed: 2026-05-17
source_of_truth: true
related_tests:
  - tests/test_agent2.py
---

# Agent2 RTL Designer Product Spec

## Mission
Generate SystemVerilog RTL, packages, and interfaces that implement Agent1 architecture contracts without port drift.

## Responsibilities
- Consume Agent1 architecture/spec artifacts.
- Emit SystemVerilog modules.
- Emit packages and interfaces for shared types/constants.
- Preserve locked module names, ports, widths, resets, and clocks.
- Emit debug and self-check reports when supported.

## Inputs
- Agent1 architecture/spec artifacts.
- Stable interface contracts.
- Existing RTL constraints if repair mode is used.

## Outputs
- RTL modules under generated output path.
- `*_pkg.sv` package files where needed.
- `*_intf.sv` interface files where needed.
- Top module wiring.
- Debug/self-check artifacts.

## RTL Contract Rules
- Do not rename locked ports.
- Do not change bit widths without architecture change.
- Use consistent reset polarity and clock naming.
- Keep APB-style contracts stable once emitted by architecture.
- Packages must be importable by dependent modules.
- Interfaces must match module usage.

## Hard Constraints
- Do not rename locked ports.
- Preserve APB-style contract once emitted by architecture.
- SystemVerilog must be syntactically valid enough for downstream tools/tests.
- No hidden dependency on unavailable proprietary tools for generation.
- Preserve file naming conventions used by tests.
- Keep behavior aligned with `tests/test_agent2.py`.

## Failure Modes
- Port drift.
- Invalid SystemVerilog.
- Missing package/interface dependency.
- Top-level wiring mismatch.
- Reset behavior inconsistent with contract.

## Test Coverage
- `tests/test_agent2.py`