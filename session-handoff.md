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
- Goal: harden harness evidence gates and workflow checks, then make the WIP branch easy to clone from another machine without committing local secrets.
- Branch: `codex/agent1-evidence-markdown-report`.
- Files changed: `.github/workflows/harness.yml`, `.env.example`, `feature_list.json`, `src/coreweaver/harness/persistent_state.py`, `scripts/harness_check.py`, `scripts/gemini_smoke_test.py`, `src/coreweaver/debug/trace_validator.py`, `src/coreweaver/debug/replay_resume.py`, `src/coreweaver/debug/__init__.py`, `src/coreweaver/runtime/session.py`, `src/coreweaver/studio_runner.py`, `studio/backend/runner.py`, `src/coreweaver/agents/agent1/runtime.py`, `src/coreweaver/agents/agent1/evidence_report.py`, `scripts/run_benchmarks.py`, `scripts/finish_codex_task.ps1`, `tests/test_harness_lifecycle_state.py`, `tests/test_harness_trace_gates_replay.py`, `tests/test_agent1_evidence_report.py`, `tests/test_benchmark_skeleton.py`, `tests/test_strict_done_hardening.py`, `tests/test_studio_core_adapter.py`, `docs/AI_CONTEXT.md`, `docs/REPO_MAP.md`, `progress.md`, `session-handoff.md`.
- Tests run: `python -m pytest -q tests/test_strict_done_hardening.py`; `python -m pytest -q tests/test_studio_core_adapter.py`; `python -m pytest -q tests/test_core_skeleton.py tests/test_contracts_and_profiles.py`; `python -m pytest -q tests/test_agent1_evidence_report.py`; `python -m pytest -q tests/test_harness_trace_gates_replay.py`; `python -m pytest -q tests/test_harness_lifecycle_state.py`; `python -m pytest -q tests/test_harness_rules.py tests/test_harness_knowledge_observability_eval.py`; `python -m pytest -q tests/test_benchmark_skeleton.py`; `python -m pytest -q tests/test_benchmark_skeleton.py tests/test_strict_done_hardening.py`; `python -m pytest -q tests/test_harness_lifecycle_state.py tests/test_benchmark_skeleton.py`; PowerShell parser check for `scripts/finish_codex_task.ps1`; `python -m pytest -q tests`; `python scripts/harness_check.py --json`; `python scripts/run_benchmarks.py --cases benchmarks/cases --results %TEMP%/coreweaver-benchmark-ci-gate-report.json --json`; `python scripts/run_benchmarks.py --cases benchmarks/cases --results $env:TEMP/coreweaver-sync-benchmarks --json`; `npm run test --prefix studio/frontend`; `npm run build --prefix studio/frontend`.
- Risks: persistent-state validation intentionally supports the schema subset used by `feature_list.schema.json`; trace validation intentionally treats `span_id` as an event-unique identifier for replay ordering; executable resume currently covers safe pause continuations (`PLAN_REVIEW` approval and clarification rerun), not arbitrary mid-run restore.
- Reviewer notes: `harness_check.py --json` now reports `checks.persistent_state_schema`; Agent1 evidence reports now include `trace_validation` and `replay_resume`, and `ready` is blocked by trace/replay event-count/order mismatches, duplicate spans, orphan parent spans, missing terminal events, unpaired group/tool lifecycles, stale/missing replay resume state, or `agent1_handoff_ready` before a traced G12 pass. Replay bundles include checkpoint refs/hashes plus a typed `resume` block with latest stage, action required, event/checkpoint counts, and blackboard revision where available. `RuntimeSession.resume()` validates that state before execution, emits `agent1_rollback_point_restored`, approves `PLAN_REVIEW` to `run_end`, reruns Agent1 when a clarification answer is provided, and blocks tampered replay with a debug issue/HITL. Studio resume now preserves the original requirement when launching the core runner. Benchmark pass/fail now requires exact runtime status plus evidence-policy success for every case: `PLAN_REVIEW` cases must be evidence `ready` with readiness/debug scores at 100, while blocked/clarification/non-design cases must remain evidence `not_ready`. Benchmark cases clean their output directories before each run to prevent stale artifacts from affecting evidence results. GitHub CI and `finish_codex_task.ps1` both run benchmarks with temporary result directories so generated benchmark output is not staged by default. `finish_codex_task.ps1` now refuses to continue if known untracked mirror/scratch paths such as `src/coreweaver/agents/harness/`, `src/coreweaver/agents/agents/`, or `kiemtra*.txt` would be swept up by `git add -A`. Clone-on-another-machine setup is documented with placeholder-only `.env.example`; real Gemini keys remain local/ignored.
