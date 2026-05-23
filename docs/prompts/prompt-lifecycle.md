---
title: Prompt Lifecycle
status: active
owner: docs-governance
type: prompt
last_reviewed: 2026-05-17
source_of_truth: true
---

# Prompt Lifecycle

## States
- Draft: not used by runtime/tests.
- Candidate: reviewed, not canonical.
- Canonical: source path referenced by `docs/prompts/index.md` and tests.
- Superseded: retained for history with replacement pointer.

## Change Rules
- Update prompt compliance matrix when prompt contract changes.
- Update related product spec if behavior contract changes.
- Run `tests/test_prompt_contracts.py` after prompt changes.
- Do not duplicate full prompt bodies in docs indexes.

## Migration Rules
- Runtime prompt path changes require exec plan.
- Keep compatibility pointer from old path.
- Update `docs/knowledge-map.yaml` in same change.
