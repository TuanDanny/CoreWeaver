# AGENTS.md

## Mission
CoreWeaver converts semiconductor requirements into architecture contracts through an agent-first harness. The harness is built before the swarm core.

## Golden Rules
- Harness before core logic.
- Keep `studio/` as the UI/backend shell.
- Keep private plans in `_private/plans/`; never commit them.
- Keep learning/reference material in `document/`.
- Every agent output must be typed, traceable, replayable, and gate-checked.
- Read `.rules/` before changing harness or agent behavior.
- Core, Agent, harness, tools, benchmarks, adapters, and debug features must stay package-shaped for isolated testing/debugging.
- No raw API keys, bearer tokens, passwords, or secrets in trace/debug/artifacts.
- Agent2 handoff is blocked until Agent1 contracts and signoff gates pass.
- Framework-first rule: build/maintain typed messages, async events, hooks, bounded loop, scheduler, adapters, safety, replay, and Studio skeleton before adding Agent1 reasoning.

## Read Map
- Harness architecture: `ARCHITECTURE.md`
- Harness doctrine: `docs/HARNESS_ENGINEERING.md`
- Harness code: `src/coreweaver/harness/`
- Machine-readable rules: `.rules/`
- Core adapter boundary: `src/coreweaver/api.py`
- Studio/Agent1 plug-in contract: `docs/design-docs/studio-agent1-core-contract.md`
- Run profiles: `COREWEAVER_RUN_PROFILE` in `src/coreweaver/run_profiles.py`
- Benchmark skeleton: `benchmarks/`
- Persistent feature state: `feature_list.json`
- Session progress: `progress.md`
- Resume handoff: `session-handoff.md`
- Harness tests: `tests/`
- Stable design docs: `docs/design-docs/index.md`
- Product specs: `docs/product-specs/index.md`
- Generated/manual indexes: `docs/generated/index.md`
- Governance: `docs/governance/harness-review-checklist.md`
- Learning docs: `document/`
- Private plans: `_private/plans/`
- Source root: `src/`; all project internals/core packages live under `src/`.
- Core framework packages: `src/coreweaver/messages`, `src/coreweaver/events`, `src/coreweaver/runtime`, `src/coreweaver/hooks`, `src/coreweaver/models`, `src/coreweaver/tools`, `src/coreweaver/orchestration`, `src/coreweaver/safety`, `src/coreweaver/debug`.

## Commands
```bash
python -m pytest -q tests
python scripts/harness_check.py --json
python scripts/run_benchmarks.py --cases benchmarks/cases --json
powershell -ExecutionPolicy Bypass -File scripts/dev_check.ps1
```

## Conflict Policy
Prefer tests/code behavior, then `ARCHITECTURE.md`, then private plans, then chat history.
