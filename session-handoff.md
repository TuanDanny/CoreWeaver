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
- Goal: polish GitHub repository presentation and collaboration settings without changing harness behavior.
- Branch: `codex/repo-professional-profile`.
- Files changed: `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `.github/CODEOWNERS`, `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/config.yml`, `.github/ISSUE_TEMPLATE/bug_report.yml`, `.github/ISSUE_TEMPLATE/feature_request.yml`, `session-handoff.md`.
- Tests run: `python -m pytest -q tests`; `python scripts/harness_check.py --json`; `python scripts/run_benchmarks.py --cases benchmarks/cases --results $env:TEMP/coreweaver-repo-polish-benchmarks --json`.
- Risks: no public license is added because license selection is a repository-owner/legal decision; branch protection is intentionally admin-bypassable.
- Reviewer notes: GitHub repo metadata was updated with a clearer description, professional topics, disabled Wiki/Projects, enabled delete-branch-on-merge, and lightweight `main` protection requiring the `harness` check plus conversation resolution.
