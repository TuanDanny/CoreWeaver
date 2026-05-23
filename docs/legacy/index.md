---
title: Legacy Docs Index
status: active
owner: docs-governance
type: legacy-index
last_reviewed: 2026-05-17
source_of_truth: true
---

# Legacy Docs Index

Legacy docs remain reachable until explicit migration/removal plan exists.

| Path | Status | Notes |
|---|---|---|
| `docs/AGENT1_V3_SUPER_COMMITTEE_PLAN.md` | historical | Agent1 legacy planning context. |
| `docs/AGENT1_V3_6_REPAIR_LOOP_UPGRADE_PLAN.md` | historical | Agent1 repair-loop upgrade context. |
| `docs/AGENT1_V4_MODERN_DEBUG_UPGRADE_PLAN.md` | deferred | Agent1 V4 work paused until knowledge store foundation complete. |
| `semiconductor_swarm_ai.md` | compatibility | Root copy exists; canonical docs path remains `docs/semiconductor_swarm_ai.md` when present. |
| Generated artifact folders `generated_*` | active-output | Runtime/generated outputs, not docs source of truth. |
| Run artifact folders `runs/`, `swarm_*`, `tmp_smoke/` | historical-output | Execution history and smoke outputs. |

## Status Meanings
- active: current source of truth.
- deferred: planned but paused.
- historical: retained for context.
- compatibility: retained to avoid broken workflows.
- active-output: generated output used by tests/runtime.
- historical-output: old generated/run output.
