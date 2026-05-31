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
- Goal: add Agent1 evidence report generation for proof/debug review.
- Branch: `codex/agent1-evidence-report`.
- Base note: branch includes local commit `Upgrade Agent1 verifier and replay` from `codex/upgrade-agent1-verifier`; keep evidence-report changes as the next focused commit.
- Files changed: `src/coreweaver/agents/agent1/evidence_report.py`, `scripts/generate_agent1_evidence_report.py`, `scripts/run_benchmarks.py`, `tests/test_agent1_evidence_report.py`, `session-handoff.md`.
- Tests run: `python -m pytest -q tests/test_agent1_evidence_report.py`; `python -m pytest -q tests`; `python scripts/harness_check.py --json`; `python scripts/run_benchmarks.py --cases benchmarks/cases --json`.
- Risks: report verdict is intentionally strict; non-design, clarification, HITL, conflict, missing trace/replay, failed signoff, incomplete gates, and invalid ready handoff all produce `not_ready`.
- Reviewer notes: report reads real trace/replay/signoff/handoff artifacts, writes `artifacts/agent1_artifact_index.json` and `artifacts/agent1_evidence_report.json`, and benchmark results now include evidence report path plus debug/readiness scores.
