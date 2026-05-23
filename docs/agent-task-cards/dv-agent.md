---
title: DV Agent Task Card
status: active
owner: agent3
type: agent-task-card
last_reviewed: 2026-05-17
source_of_truth: true
---

# DV Agent Task Card

## Read First
- `docs/product-specs/agent3-dv-engineer.md`
- `tests/test_agent3.py`
- `tests/test_real_dv_tools.py`

## Job
Generate deterministic cocotb/SystemVerilog DV collateral without UVM.

## Edit Rules
- Match RTL ports exactly.
- Seed any random stimulus.
- Do not treat simulator missing as pass.
