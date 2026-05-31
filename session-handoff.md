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
- Goal: add human-readable Agent1 evidence Markdown reports next to existing JSON evidence reports.
- Branch: `codex/agent1-evidence-markdown-report`.
- Files changed: `src/coreweaver/agents/agent1/evidence_report.py`, `scripts/generate_agent1_evidence_report.py`, `scripts/run_benchmarks.py`, `tests/test_agent1_evidence_report.py`, `tests/test_benchmark_skeleton.py`, `docs/REPO_MAP.md`, `session-handoff.md`.
- Tests run: `python -m pytest -q tests/test_agent1_evidence_report.py`; `python -m pytest -q tests/test_benchmark_skeleton.py`.
- Risks: Markdown is a rendered view of the JSON evidence report only; runtime reasoning, signoff, and handoff behavior are intentionally unchanged.
- Reviewer notes: Markdown output is `artifacts/agent1_evidence_report.md`; CLI non-JSON mode prints verdict plus JSON and Markdown paths; benchmark results include `evidence_markdown_report`.
