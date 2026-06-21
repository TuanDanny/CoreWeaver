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
- Extend resume beyond safe pause continuations into arbitrary mid-run resume-from-checkpoint.
- Add more datasheet-backed benchmark cases when source material exists.
- Improve Studio visualizations for new `agent1_*` event types if needed.

## Clone-On-Another-Machine Handoff
- GitHub remote: `https://github.com/TuanDanny/CoreWeaver.git`.
- Continuation branch: `codex/agent1-evidence-markdown-report`.
- Clone flow:
  ```bash
  git clone https://github.com/TuanDanny/CoreWeaver.git
  cd CoreWeaver
  git checkout codex/agent1-evidence-markdown-report
  ```
- Local secrets stay outside Git. Set `GEMINI_API_KEY` in the shell or create ignored `codex_api.local.json` locally; use `.env.example` only as a placeholder template.
- Gemini smoke test after setting the key:
  ```bash
  python scripts/gemini_smoke_test.py
  ```
- Studio start:
  ```powershell
  studio\run_studio.bat
  ```
  Backend defaults to `http://127.0.0.1:8000`; frontend defaults to `http://127.0.0.1:5173`.

## Latest Task
- Goal: Upgrade Agent 1 reasoning engine to eliminate fallback regex and introduce structured LLM-as-a-judge for signoff gates.
- Branch: `codex/agent1-reasoning-upgrade`.
- Files changed: `experts.py`, `reasoning.py`, `signoff.py`, `verifier.py`, `openai_compatible.py`, and test files.
- Tests run: `python -m pytest -q tests` (57/57 passed); `python scripts/harness_check.py --json` (Clean). E2E live test executed using `studio_test_apb_timer_3` but paused gracefully due to Google API `RESOURCE_EXHAUSTED` (code 429) rate limit on `gemini-3.5-flash` after successful cluster assignment. E2E handles parsing correctly and `agent1_canary_touched` functions correctly.
- Risks: The system no longer falls back to hardcoded regex strings for AXI/AES components; if the model fails to output valid JSON conforming to the schema, it will retry and ultimately fail via `signoff` instead of passing with hallucinated data.
- Reviewer notes: `_domain_findings` and `_synthesize_fallback` hardcoded mocks have been entirely removed. The system is completely dynamic and structured output bound. Ready to be merged once reviewed.
