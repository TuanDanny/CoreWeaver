---
title: Repo Knowledge Store
status: active
owner: docs-governance
type: design-doc
last_reviewed: 2026-05-17
source_of_truth: true
related_tests: []
---

# Repo Knowledge Store

## Purpose
Apply Harness Engineering pattern: give agents a map, not a 1,000-page instruction manual.

## Structure
- `AGENTS.md`: short map.
- `ARCHITECTURE.md`: system overview.
- `PLANS.md`: plan index.
- `docs/design-docs/`: stable invariants.
- `docs/product-specs/`: agent/tool contracts.
- `docs/exec-plans/`: active/completed/deferred plans.
- `docs/prompts/`: prompt source index.
- `docs/references/`: external/non-binding references.
- `docs/governance/`: maintenance and review policy.
- `docs/generated/`: manual or generated indexes.

## Rules
- Keep `AGENTS.md` concise.
- Do not move/delete legacy docs in v0.1.
- Prefer Markdown with YAML frontmatter.
- Product specs stay concise first.
- Do not add `docs/knowledge-map.yaml` until routing needs are proven.
- Keep prompt canonical paths unchanged in v0.1; point to them from `docs/prompts/index.md`.

## Conflict Policy
Prefer tests/code behavior, then stable design docs, then product specs, then prompt sources, then generated/manual indexes, then active plans, then references, then chat.