---
title: Canonical Prompts
status: active
owner: docs-governance
type: prompt
last_reviewed: 2026-05-20
source_of_truth: true
---

# Canonical Prompts

| Prompt | Canonical Path | Status | Notes |
|---|---|---|---|
| Semiconductor Swarm master | `docs/semiconductor_swarm_ai.md` | canonical | User-required standard prompt. |
| Agent1 runtime prompt | `semiconductor_swarm/agents/agent1_planning/agent1_prompt.py` | runtime canonical | Python prompt source. |
| Agent2 runtime prompt | `semiconductor_swarm/agents/agent2_rtl/agent2_prompt.py` | runtime canonical | Python prompt source. |
| Agent3 runtime prompt | `semiconductor_swarm/agents/agent3_dv/agent3_prompt.py` | runtime canonical | Python prompt source. |
| Agent4 runtime prompt | `semiconductor_swarm/agents/agent4_physical/agent4_prompt.py` | runtime canonical | Python prompt source. |
| Agent5 runtime prompt | `semiconductor_swarm/agents/agent5_formal/agent5_prompt.py` | runtime canonical | Python prompt source. |

## Rule
This file points to canonical paths. It does not duplicate prompt bodies.
