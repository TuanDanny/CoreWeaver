---
title: Harness Engineering Knowledge Store
status: active
owner: docs-governance
type: exec-plan
last_reviewed: 2026-05-17
source_of_truth: true
related_tests: []
---

# Harness Engineering Knowledge Store

## Goal
Adopt OpenAI Harness Engineering style repository knowledge store: concise map files plus structured docs as system of record.

## Non-Goals
- Do not implement Agent1 V4 Phase 1/2 in this plan.
- Do not rename or delete legacy docs in v0.1.
- Do not change runtime prompt loading in v0.1.
- Do not add machine-readable `docs/knowledge-map.yaml` in v0.1.

## Decisions So Far
1. V4 Phase 1/2 paused.
2. Harness Engineering foundation prioritized before more Agent1 V4 work.
3. Use Markdown with YAML frontmatter.
4. `AGENTS.md` is a short map, not an encyclopedia.
5. Migration is additive-first; no destructive moves in v0.1.
6. Product specs stay concise first.
7. No `docs/knowledge-map.yaml` in v0.1.
8. Prompt canonical paths remain unchanged in v0.1; `docs/prompts/index.md` points to them.
9. Save current discussion and decisions in this active plan.

## Proposed v0.1 Structure
- Top-level: `AGENTS.md`, `ARCHITECTURE.md`, `PLANS.md`.
- Core docs: `docs/design-docs/`, `docs/product-specs/`, `docs/exec-plans/`.
- Supporting docs: `docs/prompts/`, `docs/references/`, `docs/generated/`, `docs/governance/`.

## Migration Plan
### v0.1 Additive Foundation
Add skeleton and concise docs only.

### v0.2 Health Checks
Add docs existence/link/frontmatter checks.

### v0.3 Contract Indexes
Add manual or generated contract/test/prompt indexes.

### v0.4 Controlled Migration
Only then consider moving/copying old docs with compatibility pointers.

### v0.5 Machine Routing
Add optional `docs/knowledge-map.yaml` if needed.

## Risk Matrix
| Risk | Mitigation |
|---|---|
| Docs bloat | Keep specs concise and `AGENTS.md` under 150 lines. |
| Broken paths | Additive-only, no move/delete in v0.1. |
| Duplicate prompt drift | Do not copy full prompts in v0.1. |
| Agent confusion | Use clear read map and task routing. |
| YAML complexity | Defer machine routing. |
| V4 scope leak | Keep V4 deferred. |

## Acceptance Criteria
- Map files exist.
- v0.1 docs tree exists.
- This file records discussion decisions.
- Prompt index points to existing prompt paths.
- No agent code behavior changes.

## Test Commands
```bash
python -m pytest -q
```

## Open Questions
- When to promote generated/manual indexes into machine-generated artifacts.
- When to add `docs/knowledge-map.yaml`.
- When to migrate legacy prompt paths.

## 2026-05-17 Continuation
User requested full completion according to OpenAI Harness Engineering reference and required all plans/work logs to be saved in `docs/`.

Authoritative completion records:
- `docs/exec-plans/completed/harness-engineering-100-percent-plan.md`
- `docs/exec-plans/completed/openai-harness-full-compliance-plan.md`

Updated direction:
- `docs/knowledge-map.yaml` is now in scope for 100% completion.
- Docs health script/test are required.
- Generated/manual indexes are required.
- Agent task cards are required.
- Legacy docs index is required.
- Completion record must be saved under `docs/exec-plans/completed/`.
