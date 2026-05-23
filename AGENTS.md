# AGENTS.md

## Mission
Semiconductor Swarm converts chip requirements into architecture, RTL, formal, DV, and FPGA collateral using a formal-first multi-agent workflow.

## Golden Rules
- Formal before simulation.
- Numeric PPA/bandwidth estimates only from deterministic tools.
- APB slave pinout is immutable once locked by architecture.
- Agent2 must not rename locked ports.
- No UVM; use cocotb plus SystemVerilog/SVA.
- HITL required after persistent debug failures.
- Keep repository knowledge in `docs/`; keep this file as a map, not an encyclopedia.

## Read Map
- System architecture: `ARCHITECTURE.md`
- Work plans: `PLANS.md`
- Stable design contracts: `docs/design-docs/index.md`
- Product specs: `docs/product-specs/index.md`
- Prompt sources: `docs/prompts/index.md`
- Generated/manual indexes: `docs/generated/index.md`
- Governance: `docs/governance/index.md`

## Task Routing
| Task | Read first |
|---|---|
| repo/docs/governance | `docs/design-docs/repo-knowledge-store.md`, `docs/governance/change-review-checklist.md` |
| architecture/swarm graph | `ARCHITECTURE.md`, `docs/product-specs/semiconductor-swarm.md` |
| agent1 architecture | `docs/product-specs/agent1-system-architect.md`, `docs/prompts/index.md` |
| RTL/APB | `docs/product-specs/agent2-rtl-designer.md` |
| DV | `docs/product-specs/agent3-dv-engineer.md` |
| physical/FPGA | `docs/product-specs/agent4-physical-designer.md` |
| formal | `docs/product-specs/agent5-formal-verifier.md` |

## Commands
```bash
python -m pytest -q
```

## Conflict Policy
Prefer tests/code behavior, then stable design docs, then product specs, then prompt sources, then generated/manual indexes, then active exec plans, then references, then chat history.

If generated docs become machine-generated, trust them above manual docs except tests/code.