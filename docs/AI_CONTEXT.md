# AI Context Contract

This file is the durable context entrypoint for future Codex and AI sessions.
Read it before changing code, then continue with the required files listed in
`AGENTS.md`.

## Current Architecture Baseline
- CoreWeaver is a harness-first semiconductor architecture workflow.
- Project internals live under `src/`; `studio/` remains the UI/backend shell.
- `src/coreweaver/api.py` is the public Core/Studio adapter boundary.
- `RuntimeSession` dispatches `mock_swarm` and `local_llm` into Agent1 true swarm; `local_skeleton` and `ci_no_llm` remain framework-only profiles.
- Agent1 V1.1.0 runs intake, clarification, Principal topology, 7 Middle groups, 24 Leaf experts, blackboard writes, challenge review, read-only verifier, architecture synthesis, G00-G12 signoff, Agent2 handoff gate, trace, replay, and benchmark artifacts.
- Agent2 execution is not part of the current core. Studio Agent2 draft jobs must validate Agent1 handoff readiness before any Agent2 work.
- Public benchmarks live in `benchmarks/cases` and run through deterministic `mock_swarm`.

## Current Active Direction
- Keep the harness and contracts durable enough that future Agent1 quality work is reviewable.
- Improve Agent1 verifier, signoff evidence, handoff readiness, replay, and tracking without bypassing package boundaries.
- Keep `mock_swarm` deterministic and credential-free.
- Keep `local_llm` optional and routed through `ModelRouter`; fake-client tests are the acceptance path unless a task explicitly targets live endpoint evaluation.

## Non-Negotiable Rules
- Do not do feature work on `main`; use `codex/*` branches.
- Do not commit `_private/plans/`, generated benchmark results, Studio build output, credentials, or local settings.
- No raw API keys, bearer tokens, passwords, or secret-like values may appear in trace, debug, replay, or artifacts.
- Every agent output must be typed, traceable, replayable, and gate-checked.
- Agent2 handoff is blocked unless `agent1_to_agent2.json` is ready, has no blockers, and references a passing signoff certificate.
- Keep core, harness, agents, adapters, safety, debug, benchmarks, and tools package-shaped for isolated tests.
- Read `.rules/` before changing harness or agent behavior.

## Required Files To Read Before Work
- `docs/AI_CONTEXT.md`
- `AGENTS.md`
- `ARCHITECTURE.md`
- `docs/HARNESS_ENGINEERING.md`
- `docs/REPO_MAP.md`
- `progress.md`
- `session-handoff.md`
- `.rules/` for harness, safety, trace, handoff, or agent behavior changes.

## Known Gaps
- Live `local_llm` provider quality is not certified beyond fake-client structured-output tests.
- Datasheet-backed private benchmark cases are not in the public corpus.
- Agent2 RTL core execution remains outside the current strict-done scope.
- Resume-from-checkpoint is weaker than replay artifact generation.
- Early pause paths have less replay detail than full signoff/conflict paths.
- Handoff and verifier quality can still be deepened around evidence completeness, schema strictness, and branch-level tracking.
- Benchmark scoring is public-safe and deterministic, but not a substitute for private design-quality review.

## Review Entrypoints
- Public API: `src/coreweaver/api.py`
- Runtime profiles: `src/coreweaver/run_profiles.py`
- Runtime session: `src/coreweaver/runtime/session.py`
- Agent1 runtime: `src/coreweaver/agents/agent1/runtime.py`
- Agent1 verifier/signoff/handoff: `src/coreweaver/agents/agent1/verifier.py`, `src/coreweaver/agents/agent1/signoff.py`, `src/coreweaver/agents/agent1/handoff.py`, `src/coreweaver/contracts/agent1_handoff.py`
- Studio boundary: `studio/backend/agent_service.py`, `src/coreweaver/studio_runner.py`, `src/coreweaver/studio_adapter.py`
- Harness gates: `scripts/harness_check.py`, `.rules/`
- Benchmarks: `scripts/run_benchmarks.py`, `benchmarks/cases/`
- Main regression tests: `tests/`
