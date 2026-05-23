---
title: Repository Layout
status: active
owner: docs-governance
type: repo-map
last_reviewed: 2026-05-23
source_of_truth: true
---

# Repository Layout

Use this map when preparing commits or reviewing pull requests.

## Stable Source Areas

| Area | Path | Commit together when changing |
|---|---|---|
| Core swarm graph | `main.py`, `semiconductor_swarm/swarm_graph.py`, `semiconductor_swarm/contracts/` | graph behavior, checkpoint contracts, HITL routing |
| Agent 1 planning | `semiconductor_swarm/agents/agent1_planning/` | intake, council, tracing, architecture planning |
| Agent 2 RTL | `semiconductor_swarm/agents/agent2_rtl/`, `patterns/` | RTL generation, pattern library, lint/repair |
| Agent 3 DV | `semiconductor_swarm/agents/agent3_dv/` | cocotb/pytest collateral |
| Agent 4 physical | `semiconductor_swarm/agents/agent4_physical/` | Quartus/FPGA collateral |
| Agent 5 formal | `semiconductor_swarm/agents/agent5_formal/` | SVA/SymbiYosys collateral |
| Studio web | `studio/backend/`, `studio/frontend/src/` | FastAPI, WebSocket, React cockpit, tracking UI |
| Tests | `tests/` | regression coverage matching source changes |

## Isolated Or Legacy Areas

| Area | Path | Rule |
|---|---|---|
| Legacy desktop cockpit | `app/` | keep working, but new UX belongs in `studio/` |
| Historical plans | `docs/exec-plans/archive/` and `docs/exec-plans/superseded/` | do not edit except for archive hygiene |
| Generated docs indexes | `docs/generated/` | update only with docs/governance intent |
| Debug helpers | `debug_runners/`, `scripts/` | keep separate from core runtime changes |

## Local-Only Areas

These must not be committed:

- `codex_api.local.json`
- `studio/settings.json`
- `app/settings.json`
- `.env`
- `.swarm/`
- `outputs/`
- `swarm_full_rerun_*/`
- `*.sqlite`
- `studio/frontend/node_modules/`
- `studio/frontend/dist/`

## Suggested Commit Slices

1. Repo hygiene: `.gitignore`, examples, CI, publishing docs.
2. Core engine changes: `semiconductor_swarm/` plus focused tests.
3. Studio backend changes: `studio/backend/` plus `tests/test_studio_backend.py`.
4. Studio frontend changes: `studio/frontend/src/` plus `studio/frontend/scripts/smoke.mjs`.
5. Docs-only changes: `docs/`, `README.md`, `ARCHITECTURE.md`, `PLANS.md`.
