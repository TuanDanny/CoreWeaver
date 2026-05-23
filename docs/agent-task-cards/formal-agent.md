---
title: Formal Agent Task Card
status: active
owner: agent5
type: agent-task-card
last_reviewed: 2026-05-17
source_of_truth: true
---

# Formal Agent Task Card

## Read First
- `docs/product-specs/agent5-formal-verifier.md`
- `tests/test_agent5.py`
- `tests/test_real_formal_tools.py`

## Job
Generate formal wrappers, `.sby` plans, and formal run helpers.

## Edit Rules
- Keep assumptions explicit and narrow.
- Report tool failures as failures/skips, not proof success.
- Avoid vacuous proofs.
