# Session Handoff

Use this file when ending or resuming a long task.

## Last Known Good Checks
```bash
python -m pytest -q tests
python scripts/harness_check.py --json
python scripts/run_benchmarks.py --cases benchmarks/cases --json
npm run test --prefix studio/frontend
npm run build --prefix studio/frontend
powershell -ExecutionPolicy Bypass -File scripts/dev_check.ps1
```

## Latest UAT Smoke
- Hard NPU: `PLAN_REVIEW`, 7 group sessions start/done, plan + signoff + Agent2 handoff artifacts written.
- Ambiguous input: `REQUIREMENT_CLARIFICATION`, no plan artifact.
- Non-design chat: `NON_DESIGN_CONVERSATION`, no swarm run.
- Forced M06/M07 conflict: exactly 3 Principal reviews, `CONFLICT_REQUIRED`, no Agent2 handoff.
- Safety/signoff mutations: budget breach, kill switch, circuit breaker, canary leak, unapproved commit, missing reset/formal, wrong bus width, fake PPA all block handoff.
- Agent2 draft: blocked unless `agent1_to_agent2.json` is ready, blocker-free, and backed by a passing signoff certificate.

## Resume Checklist
- Read `AGENTS.md`.
- Read `.rules/`.
- Read `progress.md`.
- Confirm private plans remain ignored.
- Keep all new core internals under `src/coreweaver/`.

## Open Work
- Strengthen live-endpoint `local_llm` evaluation beyond fake-client structured-output tests.
- Add more datasheet-backed benchmark cases when source material exists.
- Improve Studio visualizations for new `agent1_*` event types if needed.

## Latest Task
- Goal: upgrade Agent1 verifier and replay completeness.
- Branch: `codex/upgrade-agent1-verifier`.
- Files changed: `src/coreweaver/agents/agent1/verifier.py`, `src/coreweaver/agents/agent1/models.py`, `src/coreweaver/agents/agent1/handoff.py`, `src/coreweaver/contracts/agent1_handoff.py`, `src/coreweaver/agents/agent1/runtime.py`, `tests/test_strict_done_hardening.py`, `session-handoff.md`.
- Tests run: `python -m pytest -q tests/test_strict_done_hardening.py`; `python -m pytest -q tests`; `python scripts/harness_check.py --json`; `python scripts/run_benchmarks.py --cases benchmarks/cases --json`; `powershell -ExecutionPolicy Bypass -File scripts/dev_check.ps1`.
- Risks: handoff schema is stricter and intentionally rejects partial legacy handoff/certificate JSON; Agent2 execution remains out of scope.
- Reviewer notes: verifier blockers now cover missing/duplicate manager summaries, unresolved blackboard conflicts, and missing accepted expert evidence; early terminal Agent1 paths now write replay bundles.
