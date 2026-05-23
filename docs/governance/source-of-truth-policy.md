---
title: Source Of Truth Policy
status: active
owner: docs-governance
type: governance
last_reviewed: 2026-05-17
source_of_truth: true
---

# Source Of Truth Policy

## Canonical Hierarchy
1. Code and tests define executable behavior.
2. Product specs define intended contracts.
3. Exec plans define pending/completed work.
4. Prompt indexes define prompt source paths.
5. Generated indexes summarize, but do not override source docs.

## Source Of Truth Field
- `source_of_truth: true` means doc is authoritative for its scope.
- `source_of_truth: false` means doc is reference, generated summary, or non-binding note.

## Conflict Resolution
If docs conflict:
1. Check tests/code.
2. Check product spec.
3. Check active exec plan.
4. Update stale docs in same change.

## Prompt Rule
Canonical prompt bodies remain at current paths until a migration plan changes runtime loading.
