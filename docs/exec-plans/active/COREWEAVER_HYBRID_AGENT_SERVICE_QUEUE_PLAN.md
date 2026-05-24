---
title: CoreWeaver Hybrid Agent Service Queue Plan
status: implemented-pending-user-review
owner: studio-backend
type: exec-plan
last_reviewed: 2026-05-23
source_of_truth: false
---

# CoreWeaver Hybrid Agent Service Queue Plan

## Summary

Goal: combine useful ideas from the supplied service diagram with current CoreWeaver strengths.

Diagram strengths to borrow:
- Agent Controller initiates work.
- Agent Service is the orchestration boundary.
- Sub-agents are explicit worker units.
- Queue decouples request from execution.
- Draft Generation Service handles long AI/model work.
- AI Models are behind an integration boundary.

Current repo strengths to preserve:
- Python/FastAPI Studio backend already works.
- React Studio already streams logs and traces.
- `semiconductor_swarm/` has real Agent 1/2/3/4/5 logic.
- Agent 1 tracking, trace health, and secret redaction already exist.
- Credential refs isolate local API keys from the browser.
- Tests and UAT harness are already strong.

Decision: V1 is Studio-first and Python-native. Add a queue/service boundary now, keep the interface compatible with BullMQ/Redis later, and do not rewrite the core swarm.

## Target Architecture

```text
React Studio / CLI
  -> Agent Controller API
  -> Agent Service
  -> Job Queue abstraction
  -> Agent Worker / Draft Worker
  -> semiconductor_swarm core agents
  -> Model Gateway
  -> OpenAI-compatible endpoint
  -> traces, artifacts, websocket events
```

Component mapping:
- Agent Controller: existing Studio UI plus API routes.
- Agent Service: new backend service layer that owns job creation, validation, cancellation, and status.
- Queue: Python in-process queue in V1; adapter shape ready for Redis/BullMQ later.
- Sub-Agents: existing Agent 1 intake/council, Agent 2 subagents, Agent 3 DV, Agent 4 physical, Agent 5 formal.
- Draft Generation Service: worker job types for plan drafts, RTL drafts, and debug bundles.
- AI Module Core: `semiconductor_swarm/` plus trace/contracts.
- AI Models: current OpenAI-compatible endpoint through credential refs.

## Phases And Expected Results

Phase rule:
- Do not move to the next phase until the current phase commands/tests pass.
- If a phase introduces a regression, fix inside that phase before continuing.
- Each phase must preserve secret isolation: no raw API key in browser payloads, logs, traces, artifacts, Git, or command-line arguments.
- Each phase must keep existing Studio run APIs usable unless that phase explicitly adds a compatible wrapper.

### Phase 0 - Baseline Gate

Work:
- Record current green baseline.
- Run repo health before any code changes.
- Confirm ignored files and secret safety still hold.

Commands:
- `python -m pytest -q`
- `npm run test --prefix studio\frontend`
- `npm run build --prefix studio\frontend`
- `python scripts\studio_v65_tracking_uat.py`
- staged/HEAD secret scan for `sk-*`, `Bearer`, GitHub token, AWS key.

Expected result:
- All tests pass.
- No secret appears in tracked files, traces, UI payloads, or artifacts.
- Current `main` remains deployable before architectural work starts.

Done gate:
- Baseline command output is recorded in the implementation report.
- Dirty working tree is understood before code changes begin.

### Phase 1 - Agent Job Contract

Work:
- Define a stable `AgentJob` contract.
- Add job statuses: `queued`, `running`, `paused`, `completed`, `failed`, `cancelled`.
- Add job event types: `job_queued`, `job_started`, `job_progress`, `job_completed`, `job_failed`, `job_cancelled`.
- Keep `run_id` and existing trace IDs; add `job_id` everywhere new job events are emitted.

Minimum fields:
- `job_id`
- `run_id`
- `type`
- `status`
- `project_name`
- `requirement`
- `planning_mode`
- `output_dir`
- `credential_ref`
- `created_at`
- `started_at`
- `ended_at`
- `error`
- `artifact_refs`

Expected result:
- Backend has one canonical job schema.
- Existing run state can be mapped to job state without breaking current UI.
- No raw API key exists in job payloads or events.

Done gate:
- Unit tests prove schema serialization, status transitions, and secret absence.
- Existing run IDs and trace IDs still appear in current event flow.

### Phase 2 - Queue Abstraction

Work:
- Add Python-native queue interface.
- Implement V1 with in-process async queue.
- Keep adapter boundary compatible with future Redis/BullMQ.
- Add bounded queue size and visible rejection error when full.

Interface:
- `enqueue(job) -> job_id`
- `cancel(job_id) -> status`
- `get(job_id) -> AgentJob`
- `list() -> list[AgentJob]`
- `subscribe_events() -> async stream`

Expected result:
- Job creation is decoupled from execution.
- Start request returns quickly with job identity.
- Future Redis/BullMQ integration will not require changing Studio UI contracts.

Done gate:
- Queue tests cover enqueue, FIFO order, cancellation, full queue rejection, and event subscription.
- Queue implementation uses async-safe primitives; no blocking worker loop inside FastAPI request handlers.

### Phase 3 - Agent Service Layer

Work:
- Add service layer between FastAPI routes and `RunnerManager`.
- Move start/resume/stop validation into this layer.
- Preserve existing `/api/runs/start`, `/api/runs/{run_id}/resume`, and `/api/runs/{run_id}/stop`.
- Internally route `/api/runs/start` to a `full_swarm_run` job.

New API:
- `POST /api/jobs`
- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/cancel`

Expected result:
- Current Studio flow still works.
- New queue/job API exists for future UI panels.
- Duplicate output policy and credential preflight still block early.
- Failed jobs never get mislabeled as stopped or completed.

Done gate:
- `/api/runs/start`, `/api/runs/{run_id}/resume`, and `/api/runs/{run_id}/stop` pass current regression tests.
- New `/api/jobs*` routes pass API tests.
- Invalid credentials and duplicate output both fail before worker spawn.

### Phase 4 - Draft Worker

Work:
- Add worker job types:
  - `agent1_plan_draft`
  - `agent2_rtl_draft`
  - `full_swarm_run`
  - `debug_bundle`
- `agent1_plan_draft` runs Agent 1 intake/council to plan review only.
- `agent2_rtl_draft` consumes locked architecture artifact and produces RTL draft artifacts.
- `debug_bundle` collects traces, health reports, conflict matrix, plan, and relevant artifacts.

Expected result:
- User can request drafts without forcing full downstream flow.
- Agent 1 debug visibility improves.
- Draft outputs reuse current trace/artifact structure.

Done gate:
- Agent 1 draft pauses at plan review or clarification without launching Agent 2/3/4/5.
- Debug bundle contains traces, health report, input summary, node decisions, artifacts index, and redaction report.

### Phase 5 - Model Gateway Boundary

Work:
- Add provider registry abstraction.
- Enable only `openai_compatible` provider in V1.
- Keep current endpoint/model/credential ref behavior.
- Do not add raw API key input to web.
- Add future provider placeholders for `openai`, `gemini`, `grok`, disabled by default.

Expected result:
- Current 9Router/OpenAI-compatible flow still works.
- Adding Grok/Gemini later becomes config/provider work, not Agent 1 rewrite.
- Browser never sees raw secrets.

Done gate:
- Provider tests use mocked OpenAI-compatible responses.
- Unauthorized provider responses update credential health without exposing secret.
- Disabled provider placeholders cannot be selected by normal UI.

### Phase 6 - Studio UI Integration

Work:
- Add practical Job Queue panel.
- Show queued/running/paused/completed/failed/cancelled jobs.
- Link each job to Agent Timeline, Real-time Log, Trace Debug, Plan Preview, and artifacts.
- Add draft controls:
  - Create Agent 1 Plan Draft
  - Create Agent 2 RTL Draft
  - Export Debug Bundle
- Keep current Start/Stop/Approve flow compatible.

Expected result:
- UI shows long-running work as jobs, not only process state.
- User can debug by job, run, trace file, and agent node.
- No visual regression in current Studio layout.

Done gate:
- Frontend tests cover job list, job status transitions, draft actions, cancel action, and trace filter by job ID.
- Browser smoke proves Start, Stop, Approve, draft, and log replay still work.

### Phase 7 - Tracking And Observability

Work:
- Emit job-level trace events.
- Add job_id to relevant trace events.
- Add queue health summary.
- Extend UAT to cover:
  - queued job
  - cancelled job
  - failed job
  - agent1 draft
  - full run
  - reconnect/replay
  - no secret leak

Expected result:
- Every user action from click to artifact can be followed.
- Trace Debug can answer: who started work, which job ran, which agent node produced output, why it paused/failed.
- Trace health score remains >= 95 in UAT.

Done gate:
- Tracking UAT includes happy path, weak input, bad credential, cancellation, refresh/reconnect, and artifact scan.
- Every UAT case emits a machine-readable pass/fail summary.

### Phase 8 - Compatibility And Cleanup

Work:
- Keep legacy `app/` untouched except docs if needed.
- Keep existing CLI flow working.
- Update architecture docs and repo layout.
- Add migration notes for future BullMQ/Redis adapter.
- Keep no Redis dependency in V1.

Expected result:
- Existing users keep working.
- New architecture is documented.
- Repo remains clean for GitHub and CI.

Done gate:
- Architecture docs, repo layout docs, and active plan index are updated.
- Full backend/frontend/UAT regression is green.
- `git status --short` only shows intended implementation files.

## Final Expected Product

After all phases are complete:
- CoreWeaver Studio has a practical Agent Job Queue panel, not a decorative sidebar item.
- Start/Stop/Approve remain compatible with current user workflow.
- Agent 1 can run as a draft/intake job before full downstream execution.
- Long AI work is represented as jobs with status, cancellation, replayable events, and artifacts.
- Trace Debug can follow input -> job -> queue -> worker -> Agent 1 node -> model call -> artifact -> pause/result.
- Model/provider access remains server-side through credential refs only.
- Repo is still safe for GitHub: no local secrets, no generated output noise, no accidental dependency dump.

## Public API And Interface Changes

Additive only in V1:
- New job API routes.
- New job event types.
- New job schema.
- Existing run APIs remain compatible.
- Existing trace schema remains valid; new events add `job_id`.

No change:
- No raw API key browser input.
- No command-line secret passing.
- No forced Redis/BullMQ.
- No rewrite of `semiconductor_swarm`.
- No removal of legacy desktop app.

## Test Plan

Backend tests:
- Create job returns `job_id`.
- Queue preserves FIFO order for same priority.
- Cancel queued job marks `cancelled`.
- Cancel running job stops process/worker safely.
- Failed job preserves `failed`.
- `/api/runs/start` still works.
- Credential invalid blocks before queue execution.
- Output conflict blocks before credential probe.
- Settings response never contains raw secret.

Frontend tests:
- Job Queue panel renders all statuses.
- Start creates visible job.
- Cancel updates log and status bar.
- Draft buttons create expected job types.
- Trace Debug filters by job/run/node.
- Existing Start/Stop/Approve UI still works.

Tracking UAT:
- `pure_hi` -> clarification job.
- `identity_question` -> clarification job.
- `bus_contradiction` -> clarification job.
- `minimum_cpu_apb_uart` -> Agent 1 draft and plan review.
- `full_swarm_run` -> current end-to-end flow.
- failed credential -> no worker spawn.
- cancelled run -> clean cancellation.
- artifact scan -> `secret_hit_count = 0`.

Regression commands:
- `python -m pytest -q`
- `npm run test --prefix studio\frontend`
- `npm run build --prefix studio\frontend`
- `python scripts\studio_v65_tracking_uat.py`

## Acceptance Criteria

- Existing Studio can still start, stop, approve, resume, and stream logs.
- Queue panel shows real jobs.
- Agent 1 draft can be generated without full flow.
- Full swarm run still reaches current expected pause/signoff states.
- All job events are replayable after browser refresh.
- No API key or secret appears in UI payloads, logs, traces, artifacts, Git, or command line.
- Full regression remains green.

## Assumptions

- V1 is Python-native queue, not BullMQ/Redis.
- BullMQ/Redis is future adapter, not current dependency.
- V1 model gateway enables OpenAI-compatible only.
- Grok/Gemini/OpenAI named providers are placeholders until separately approved.
- `semiconductor_swarm/` remains the source of real agent behavior.
- `studio/` is the only place for new service/UI architecture.
- `app/` remains legacy.

## Implementation Report

Implemented on 2026-05-23:
- Added `AgentJob` schema and job event contract.
- Added Python in-process async queue with bounded capacity, FIFO claim, cancellation, event subscription, and queue health.
- Added Studio Agent Service layer for start/resume/stop, credential preflight, output conflict guard, runner dispatch, and job status updates.
- Added additive `/api/jobs`, `/api/jobs/{job_id}`, and `/api/jobs/{job_id}/cancel` routes.
- Added draft worker paths for `agent1_plan_draft`, `agent2_rtl_draft`, `full_swarm_run`, and `debug_bundle`.
- `agent2_rtl_draft` now consumes the locked `agent1_to_agent2` contract and writes real RTL draft artifacts under `rtl/`.
- Added model gateway provider registry with only `openai_compatible` enabled in V1.
- Added React Job Queue panel with draft controls, job status cards, cancellation, and queue health summary.
- Added `job_id` propagation through run state, live events, replay events, Trace Debug job entries, and tracking UAT.
- Updated architecture docs, repository layout docs, Studio README, and active plan index.

Verification:
- Phase 0 baseline: `336 passed, 1 skipped`; frontend smoke/build passed; UAT passed; secret scan clean.
- Backend/job regression: `51 passed`.
- Frontend smoke/build: passed.
- Tracking UAT: passed, including `debug_bundle_job` completed, `agent2_draft_existing_plan_completed` produced RTL artifacts, and `agent2_draft_missing_plan_fails` failed clearly.
- Full regression: `342 passed, 1 skipped`.
- Secret scan for API keys/tokens: no matches.
- Browser smoke: Job Queue panel and draft controls render; debug bundle job completed in local browser.
