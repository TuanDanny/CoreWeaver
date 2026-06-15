# Progress

Persistent session state for future Codex runs.

## Current State
- Framework-first gate is complete and still green.
- Agent1 True Swarm V1.1.0 strict-done hardening is active behind `mock_swarm` and `local_llm`.
- Default Studio runner profile is `mock_swarm`, so Studio now runs full Agent1 flow without credentials.
- `local_skeleton` and `ci_no_llm` remain available for framework-only tests.
- `local_llm` uses `OpenAICompatibleModelClient` through `ModelRouter`; structured expert-response parsing is covered with fake-client tests and live endpoint remains optional.
- Agent1 flow includes intake, clarification, Principal topology, 7 Middle groups, 24 Leaf experts, model adapter calls, blackboard writes, challenge hard cap, read-only verifier, architecture plan synthesis, signoff gates, Agent2 handoff gate, trace/replay artifacts, and benchmark cases.
- Public benchmark corpus has 20 smoke/mutation cases with schema validation, per-case output cleanup, hard evidence-policy gating, and pass-rate reporting.
- CI and Codex finish workflow run pytest, harness_check, and benchmark evidence gates.
- Codex finish workflow blocks known untracked mirror/scratch paths before `git add -A`.
- `RuntimeSession.start()` now returns the actual Agent1 pause action (`PLAN_REVIEW`, `REQUIREMENT_CLARIFICATION`, `NON_DESIGN_CONVERSATION`, or `CONFLICT_REQUIRED`) instead of a hardcoded `PLAN_REVIEW`.
- `CoreWeaverRuntime.start()` now dispatches `mock_swarm` and `local_llm` profiles into `RuntimeSession`, while skeleton profiles remain framework-only.
- Studio Agent2 draft jobs validate Agent1 handoff readiness (`ready`, no blockers, passing signoff certificate) before any Agent2 draft work.
- Deterministic signoff now covers G00-G12, safety mutations block handoff, and Agent1 replay bundles include events, blackboard snapshot, checkpoints, signoff, handoff, and debug issues.
- Agent1 replay bundles now include a typed `resume` state with latest checkpoint ref/hash, terminal action, blackboard revision, and evidence-report validation.
- Agent1 resume now validates replay resume state before execution, can approve `PLAN_REVIEW` to done, and can rerun a clarified requirement after `REQUIREMENT_CLARIFICATION`.
- Final UAT smoke passed for hard NPU, ambiguous input, non-design chat, and forced M06/M07 conflict hard cap.

## Last Known Good Checks
```bash
python -m pytest -q tests
python scripts/harness_check.py --json
python scripts/run_benchmarks.py --cases benchmarks/cases --json
npm run test --prefix studio/frontend
npm run build --prefix studio/frontend
powershell -ExecutionPolicy Bypass -File scripts/dev_check.ps1
```

## Next Session
- Read `AGENTS.md`.
- Read `.rules/`.
- Read `docs/adr/0001-package-first-core.md`.
- Run `powershell -ExecutionPolicy Bypass -File scripts/dev_check.ps1`.
- If improving Agent1 quality, work inside `src/coreweaver/agents/agent1/` and keep model/tool calls behind adapters.
- Next quality frontier is arbitrary mid-run resume-from-checkpoint or deeper live `local_llm` structured output evaluation with a configured endpoint; current acceptance is fake-client and deterministic.
