# Repository Map

This file maps the current public repo shape for future AI/Codex sessions.

## Major Directories
- `.rules/`: machine-readable harness, security, trace, architecture, and handoff rules.
- `.github/workflows/`: CI workflows for harness and regression checks.
- `benchmarks/`: public benchmark schemas, cases, runner outputs, and benchmark docs.
- `docs/`: durable architecture, design, governance, product, generated, ADR, and context documentation.
- `document/`: local learning/reference material.
- `scripts/`: developer checks, benchmark runner, harness checker, and Codex task workflow scripts.
- `src/coreweaver/`: package-shaped core framework, Agent1 runtime, contracts, adapters, safety, debug, and orchestration code.
- `studio/`: React/FastAPI shell and backend job/runtime tracking layer.
- `tests/`: Python regression and harness tests.
- `_private/plans/`: local-only private plans; ignored by Git.

## Key Entrypoints
- `AGENTS.md`: repo instructions, required context loading, and mandatory Git workflow.
- `docs/AI_CONTEXT.md`: durable AI context contract.
- `ARCHITECTURE.md`: current architecture baseline and layer rule.
- `docs/HARNESS_ENGINEERING.md`: harness doctrine and done definition.
- `progress.md`: persistent project state.
- `session-handoff.md`: task-level resume handoff.
- `src/coreweaver/api.py`: public CoreWeaver runtime adapter.
- `src/coreweaver/run_profiles.py`: runtime profile definitions.
- `src/coreweaver/runtime/session.py`: profile dispatch into skeleton or Agent1 swarm runtime.
- `src/coreweaver/agents/agent1/runtime.py`: Agent1 true swarm flow.
- `src/coreweaver/agents/agent1/signoff.py`: deterministic G00-G12 signoff.
- `src/coreweaver/contracts/agent1_handoff.py`: consumer-side Agent1-to-Agent2 handoff validator.
- `studio/backend/agent_service.py`: Studio job service and Agent2 draft gate.
- `scripts/harness_check.py`: deterministic harness/rule/secret check.
- `scripts/run_benchmarks.py`: public benchmark runner.
- `scripts/start_codex_task.ps1` and `scripts/finish_codex_task.ps1`: branch, check, commit, push, and PR workflow.

## Runtime, Data, And Control Flow
- Public callers use `CoreWeaverRuntime.start()` with a `CoreRequest`.
- `local_skeleton` and `ci_no_llm` run framework skeleton behavior only.
- `mock_swarm` and `local_llm` create a `RuntimeSession`, emit `run_start`, and dispatch to `Agent1SwarmRuntime`.
- Agent1 intake classifies requirements into non-design, ambiguous, or design-ready paths.
- Design-ready paths run safety preflight, blackboard append, topology load, cluster assignment, canary check, manager/leaf expert work, challenge review, read-only verifier, architecture synthesis, proposal tracking, signoff, artifact writing, handoff readiness, trace, replay, and final HITL pause.
- `mock_swarm` uses deterministic mock model behavior through `ModelRouter`.
- `local_llm` uses an OpenAI-compatible client through `ModelRouter`; live endpoint credentials remain optional.
- Agent1 artifacts are written under output directories such as `reports/`, `contracts/`, `trace/`, `replay/`, `blackboard/`, and `checkpoints/`.
- Studio maps core events into UI/runtime tracking events and blocks Agent2 draft jobs unless handoff validation passes.

## Test Coverage Map
- Harness rules, scope, trace, replay, and lifecycle: `tests/test_harness_rules.py`, `tests/test_harness_scope_architecture.py`, `tests/test_harness_trace_gates_replay.py`, `tests/test_harness_lifecycle_state.py`.
- Framework packages and event/model contracts: `tests/test_framework_first_core.py`, `tests/test_harness_models.py`.
- Public API, runtime profiles, and Studio adapter: `tests/test_core_skeleton.py`, `tests/test_contracts_and_profiles.py`, `tests/test_studio_core_adapter.py`.
- Agent1 true swarm happy and negative flows: `tests/test_agent1_true_swarm.py`.
- Strict-done signoff, safety, handoff, local LLM fake client, and replay hardening: `tests/test_strict_done_hardening.py`.
- Benchmark runner and cases: `tests/test_benchmark_skeleton.py`, `scripts/run_benchmarks.py`, `benchmarks/cases/`.
- Package/source layout: `tests/test_packaging_rule.py`.
- Harness knowledge and observability evals: `tests/test_harness_knowledge_observability_eval.py`.

## Known Gaps
- Live `local_llm` quality is not certified by default gates.
- Agent2 RTL execution is not implemented in the current CoreWeaver package.
- Resume-from-checkpoint needs stronger end-to-end coverage.
- Replay depth is strongest for full signoff/conflict paths and thinner for early pause paths.
- Agent1 verifier and handoff schema strictness can be improved further.
- Benchmark scoring is deterministic and public-safe, but private datasheet-backed review remains future work.
- Studio visualization for newer `agent1_*` tracking events may need polish as flows deepen.
