---
title: RTL Agent Task Card
status: active
owner: agent2
type: agent-task-card
last_reviewed: 2026-05-17
source_of_truth: true
---

# RTL Agent Task Card

## Read First
- `docs/product-specs/agent2-rtl-designer.md`
- `tests/test_agent2.py`
- Agent1 output spec.

## Job
Generate SystemVerilog modules, packages, interfaces, and top wiring.

## Edit Rules
- Do not rename locked ports.
- Keep package/interface dependencies valid.
- Preserve generated file naming expected by tests.
