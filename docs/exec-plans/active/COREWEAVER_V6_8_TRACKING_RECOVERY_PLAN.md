---
title: CoreWeaver V6.8 Tracking and Recovery Upgrade Plan
status: active
owner: studio-runtime
type: exec-plan
last_reviewed: 2026-05-24
source_of_truth: true
---

# CoreWeaver V6.8 Tracking and Recovery Upgrade Plan

## Summary
V6.8 lay y tuong tot tu AiToEarn ve agent runtime tracking, structured stream events, session manifest, timeout recovery, queue metrics, va debug UI. Khong copy kien truc NestJS/Mongo/Redis/S3 cua AiToEarn. Khong doi decision logic Agent1/Agent2. Khong them runtime provider moi. Muc tieu la lam CoreWeaver de debug hon, ben hon khi refresh/restart, va co dau vet ro tu input den het Agent1/Agent2.

He thong hien tai da co FastAPI Studio, React Studio, `AgentService`, `RunnerManager`, `EventHub`, `InProcessJobQueue`, `model_gateway.py`, Agent1 council tracing, Agent2 RTL artifacts, `scripts/studio_v65_tracking_uat.py`, va `studio/backend/trace_replay.py`. V6.8 se dat lop tracking/recovery/self-check len tren cac thanh phan do, khong thay doi pipeline chip-design core.

## Inspiration From AiToEarn
- Tach service boundary va runtime boundary: service xu ly API/task, runtime giu running task, abort controller, stream chunk, session id, shutdown wait.
- Message schema ro: `init`, `assistant`, `stream_event`, `tool_progress`, `auth_status`, `keep_alive`, `error`.
- Timeout scheduler quet running task qua han.
- Queue metrics: count, active/completed/failed, duration/wait time.
- CoreWeaver chi lay pattern, khong lay domain social/media, credits/refund, S3 session upload, Redis lock, hay Claude SDK runtime y nguyen.

## Non-Goals
- Khong doi thuat toan Agent1 intake/council.
- Khong doi RTL generation/verification logic Agent2.
- Khong them Redis/Mongo/S3.
- Khong dua raw API key, prompt secret, hoac local secret vao response/browser.
- Khong thay doi API cu theo cach breaking.
- Khong bien Real-time Operations Log thanh source of truth; log chi la view. Source of truth la runtime manifest/events/invariants.

## Runtime Artifacts
Moi run ghi them artifacts trong `output_dir/reports/traces/`:

- `runtime_session_manifest.json`: snapshot hien tai cua run/job/agent/node/model-call, overwrite atomic sau moi milestone.
- `runtime_events.jsonl`: append-only event stream, moi dong la mot JSON object schema `studio.runtime_event.v1`.
- `runtime_recovery_report.json`: tao khi watchdog/recovery chay, ghi state truoc/sau va hanh dong da thuc hien.
- `runtime_invariant_report.json`: self-check report cho event/manifest, dung de bat loi tracking som.
- `runtime_replay_report.json`: replay report tu `runtime_events.jsonl`, dung de verify sau run hoac sau bug report.
- `runtime_debug_summary.json`: compact summary cho UI/UAT: run state, active node, loi gan nhat, queue health, token/cost, artifact count.

Tat ca artifact tren nam trong run output, khong commit vao Git.

## Runtime Event Schema
Moi event phai co field toi thieu:

```json
{
  "schema_version": "studio.runtime_event.v1",
  "event_id": "uuid-or-stable-id",
  "correlation_id": "run/job/node/model correlation id",
  "timestamp": "ISO-8601 UTC",
  "run_id": "string",
  "job_id": "string",
  "project_name": "string",
  "agent": "system|agent1|agent2|agent3|agent4|agent5|agent6",
  "phase": "planning|rtl|formal|hitl|dv|physical|signoff|studio",
  "node_id": "string",
  "event_type": "string",
  "status": "queued|running|passed|failed|paused|cancelled|recovered",
  "message": "human-readable short message",
  "duration_ms": 0,
  "artifact_refs": [],
  "metrics": {},
  "error": null
}
```

Required event types:

- `run_init`
- `run_hydrated`
- `agent_start`
- `agent_done`
- `node_start`
- `node_done`
- `model_call_start`
- `model_call_done`
- `tool_call_start`
- `tool_call_done`
- `artifact_written`
- `job_queued`
- `job_started`
- `job_done`
- `watchdog_timeout`
- `runtime_recovered`
- `runtime_error`

Correlation id rules:

- Run: `run:{run_id}`
- Job: `job:{job_id}`
- Node: `node:{run_id}:{agent}:{node_id}:{ordinal}`
- Model call: `model:{run_id}:{agent}:{node_id}:{ordinal}`
- Tool call: `tool:{run_id}:{agent}:{node_id}:{tool_name}:{ordinal}`

## Runtime Debug Invariants
Moi run phai tu check de phat hien loi ngay:

- `run_init` phai xuat hien truoc moi event khac cua cung `run_id`.
- `job_started` phai co `job_queued` truoc do, tru khi run hydrate tu manifest cu.
- Moi `agent_done` phai co `agent_start` cung `correlation_id`.
- Moi `node_done` phai co `node_start` cung `correlation_id`.
- Moi `model_call_done` phai co `model_call_start` cung `correlation_id`.
- Moi `tool_call_done` phai co `tool_call_start` cung `correlation_id`.
- Timestamp trong `runtime_events.jsonl` phai monotonic theo append order, cho phep equal timestamp.
- Final run status trong manifest phai khop event ket thuc: `job_done`, `runtime_error`, `watchdog_timeout`, `runtime_recovered`, hoac user stop/cancel.
- `artifact_refs` phai nam trong output sandbox hoac la relative path an toan.
- Metrics token/cost/latency khong duoc am.
- Event/manifest/recovery/debug summary khong duoc chua raw API key, `Authorization`, `Bearer`, hoac pattern `sk-*`.

Invariant checker phai ghi `runtime_invariant_report.json`, va UI phai hien invariant fail o Trace Debug.

## Runtime Manifest Schema
`runtime_session_manifest.json` phai co toi thieu:

```json
{
  "schema_version": "studio.runtime_session_manifest.v1",
  "run_id": "string",
  "job_id": "string",
  "project_name": "string",
  "output_dir": "string",
  "planning_mode": "normal|deep_planning",
  "credential_ref": "owner",
  "status": "idle|starting|running|paused|done|failed|stopped|recovered",
  "active_agent": "agent1",
  "active_node_id": "A1.INTAKE",
  "last_runtime_event_at": "ISO-8601 UTC",
  "recoverable": true,
  "recovery_status": "none|hydrated|timeout_failed|manual_stop|manifest_corrupt",
  "agents": {},
  "nodes": {},
  "model_calls": {},
  "queue": {},
  "metrics": {},
  "artifact_refs": []
}
```

Security rules:

- `credential_ref` duoc phep ghi.
- Raw API key, Authorization header, secret file content, va local secret path khong duoc ghi.
- Prompt full text chi ghi neu da la user requirement/artifact hop le trong output; secret-like content phai duoc redact neu phat hien.

## Phase 0 - Baseline and Contract
### Work
- Tao file plan nay trong `docs/exec-plans/active/`.
- Cap nhat `docs/exec-plans/active/index.md`.
- Cap nhat `PLANS.md`.
- Them hoac cap nhat docs contract neu docs health yeu cau.
- Khong code runtime trong phase nay.

### Expected Results
- Plan co trong active index.
- Docs health pass.
- Implementer khac doc file nay co the lam tiep khong can hoi lai quyet dinh lon.

### Checks
```powershell
python scripts\check_docs_health.py
.venv_dv\Scripts\python.exe -m pytest -q tests\test_docs_health.py
```

## Phase 1 - Structured Runtime Event Writer
### Work
- Them backend helper de ghi runtime event append-only vao `runtime_events.jsonl`.
- Helper phai support atomic-ish append, UTF-8, one JSON object per line.
- Helper phai publish event qua `EventHub` de UI nhan realtime.
- Gan event vao Studio run start/stop/resume, job queue state, Agent1 start/done, Agent2 draft/run start/done.
- Event cu van giu backward compatible; event moi them field, khong xoa field cu.
- Moi event writer phai goi redaction helper truoc khi ghi file/publish.
- Them correlation id factory theo rules trong plan.

### Expected Results
- Khi Start run, co `run_init`, `job_started`, `agent_start`, `node_start`.
- Khi Agent1 model call, co `model_call_start` va `model_call_done`.
- Khi artifact duoc tao, co `artifact_written`.
- UI/log van chay voi event cu.
- Trace Debug co correlation tree: event -> node -> model call/tool -> artifact.

### Checks
```powershell
.venv_dv\Scripts\python.exe -m pytest -q tests\test_studio_backend.py tests\test_studio_jobs.py
```

## Phase 2 - Runtime Session Manifest
### Work
- Them manifest writer/reader cho `runtime_session_manifest.json`.
- Manifest update sau moi runtime event quan trong.
- Manifest update bang ghi file tam roi replace de tranh corrupt.
- Sau moi manifest update, ghi `runtime_debug_summary.json` compact cho UI.
- Them hydration path:
  - `GET /api/runs/{run_id}/runtime`
  - optional runtime fields trong current state/job responses.
- `GET /api/runs/current_state` hydrate duoc run state tu manifest neu process state trong memory rong nhung output_dir/run_id co manifest hop le.
- Neu manifest corrupt:
  - khong crash backend
  - emit `runtime_error`
  - tao recovery report voi `reason=manifest_corrupt`
  - UI hien "manifest corrupt" va van cho user Start fresh/clear output

### Expected Results
- Refresh browser giua Agent1 van hien dung run/job/agent/node state.
- Backend restart xong van doc duoc last run manifest.
- Manifest khong co raw API key.
- Trace Debug co data nguon ro thay vi parse log text.
- Corrupt manifest duoc bao ro, khong lam web trang.

### API Additions
- `GET /api/runs/{run_id}/runtime`
  - Return:
    - `manifest`
    - `recentEvents`
    - `recoveryReport`
    - `invariantReport`
    - `replayReport`
    - `debugSummary`
  - Neu run khong ton tai: `404`.
  - Neu artifact path vuot sandbox: `403`.

### Checks
```powershell
.venv_dv\Scripts\python.exe -m pytest -q tests\test_studio_backend.py
```

## Phase 3 - Watchdog and Recovery
### Work
- Them watchdog task trong Studio backend lifespan.
- Watchdog check moi 10 giay.
- Default stale timeout: 30 phut khong co runtime progress event.
- Runtime progress event gom: `node_start`, `node_done`, `model_call_done`, `artifact_written`, `job_started`, `job_done`.
- Neu run/job stale:
  - emit `watchdog_timeout`
  - mark job failed neu running/starting
  - mark stopped neu stale trong stopping
  - write `runtime_recovery_report.json`
  - update manifest `recovery_status`
- Stop/cancel cua user uu tien hon watchdog.
- Watchdog co dry-run test mode de UAT co the ep timeout nhanh ma khong doi default production.
- Watchdog phai phan biet:
  - model call stale
  - subprocess stale
  - queue job stale
  - websocket disconnect only, not backend stale

### Expected Results
- Khong con UI running mai khi backend/subprocess ket.
- Timeout co ly do ro trong UI va output artifact.
- Watchdog khong tao spam event; moi stale incident chi tao mot timeout event.
- Debug report noi ro ket o model, subprocess, queue, hay UI connection.

### Checks
```powershell
.venv_dv\Scripts\python.exe -m pytest -q tests\test_studio_backend.py tests\test_studio_jobs.py
```

## Phase 4 - Queue and Runtime Metrics
### Work
- Mo rong `InProcessJobQueue.health()`:
  - `queued`
  - `running`
  - `completed`
  - `failed`
  - `cancelled`
  - `averageWaitMs`
  - `averageDurationMs`
  - `activeJobId`
  - `lastFailure`
- Them model-call metrics aggregation:
  - call count
  - prompt/completion/total tokens
  - estimated cost
  - latency avg/max
  - failure count
- Expose metrics qua `/api/health`, `/api/jobs`, `/api/runs/{run_id}/runtime`, va WebSocket.
- Them metrics provenance:
  - `source=runtime_event`
  - `source=runner_state`
  - `source=queue`
  - `source=manifest_hydrate`
- Neu metrics bi thieu, UI hien `unknown`, khong hien `0` gia.

### Expected Results
- Status bar/debug panel biet queue nghen o dau.
- Model-call cost/latency xem duoc theo Agent1/Agent2.
- API cu khong break; old fields van ton tai.
- Metrics khong gay hieu nham giua `unknown` va gia tri zero that.

### Checks
```powershell
.venv_dv\Scripts\python.exe -m pytest -q tests\test_studio_jobs.py
```

## Phase 5 - Studio Trace Debug UI
### Work
- Nang `Trace Debug` panel thanh UI debug chinh:
  - Run Session Summary
  - Agent1/Agent2 node timeline
  - Model-call metrics table
  - Queue/runtime health cards
  - Recovery report panel
  - Invariant/replay/secret-scan panel
- Render state moi:
  - `recovered`
  - `stale`
  - `watchdog timeout`
  - `manifest corrupt`
  - `failed with reason`
- Real-time Operations Log giu nguyen workflow, chi them rich rendering neu event co runtime fields.
- UI khong duoc overflow 1365x768 va 1920x1080.
- Them debug affordances thuc dung:
  - filter theo agent/node/status
  - copy correlation id
  - copy artifact path
  - jump tu model-call row sang related log/event
  - badge invariant pass/fail
  - badge secret-scan pass/fail
- Khi UI nhan event loi, auto-pin loi gan nhat trong Trace Debug, nhung khong scroll log neu user dang doc doan cu.

### Expected Results
- Nguoi dung thay Agent1/Agent2 dang o node nao.
- Loi model/tool/artifact hien ro.
- Debug khong can mo file output truoc.
- Refresh browser van hydrate Trace Debug tu manifest.
- Mot loi bat ky co duong dan debug ro: event -> node -> model call/tool -> artifact.

### Checks
```powershell
npm run test --prefix studio\frontend
npm run build --prefix studio\frontend
```

## Phase 6 - Automated Debug Harness and Invariant Replay
### Work
- Tao script UAT moi: `scripts/studio_v68_runtime_tracking_uat.py`.
- Ke thua y tuong tu `scripts/studio_v65_tracking_uat.py`, nhung them runtime artifacts/invariants.
- Script dung fake OpenAI-compatible endpoint de test khong ton token va khong dung API key that.
- Script phai chay backend/frontend tren port tam khi CI/local khong co Studio dang mo.
- Khi user dang mo `127.0.0.1:5173`, browser UAT thu cong van dung port do.
- Them runtime replay verifier:
  - reuse `studio/backend/trace_replay.py` cho old trace health
  - them runtime replay doc/test cho `runtime_events.jsonl`
  - output `runtime_replay_report.json`
- Them failure injection cases:
  - fake model 401
  - fake model timeout
  - fake model malformed JSON
  - subprocess nonzero exit
  - corrupt manifest
  - missing artifact ref
  - stale running run
  - double Stop
  - browser refresh during Agent1
- Them secret scan trong UAT:
  - scan runtime events/manifest/recovery/debug summary
  - fail neu co raw key, `Bearer`, `Authorization`, `sk-*`, hoac known fake key string.

### Expected Results
- Script UAT tu dong tao evidence dir voi:
  - backend log
  - frontend log
  - start/resume/stop responses
  - runtime artifacts
  - runtime invariant report
  - runtime replay report
  - screenshots neu browser headless co san
- Bat loi schema, state mismatch, secret leak, artifact path leak, stale state ngay trong UAT.
- Co the chay lai bug user report bang mot command va lay evidence ro.

### Checks
```powershell
.venv_dv\Scripts\python.exe scripts\studio_v68_runtime_tracking_uat.py
.venv_dv\Scripts\python.exe -m pytest -q tests\test_studio_backend.py tests\test_studio_jobs.py
```

## Phase 7 - End-to-End UAT
### Work
- Chay local Studio tai port hien co.
- Test cac scenario:
  - Start run binh thuong voi requirement chip hop le.
  - Refresh giua Agent1.
  - Stop giua run.
  - Resume sau pause Agent1.
  - Simulate stale run de watchdog kich hoat.
  - Chay den Agent2 draft/run neu input du dieu kien.
  - Mo output dir kiem `runtime_session_manifest.json`, `runtime_events.jsonl`, `runtime_recovery_report.json`, `runtime_invariant_report.json`, `runtime_replay_report.json`.
- Chay them automated debug harness Phase 6.
- Neu UAT fail, debug theo thu tu:
  1. `runtime_invariant_report.json`
  2. `runtime_replay_report.json`
  3. `runtime_recovery_report.json`
  4. `runtime_debug_summary.json`
  5. `runtime_events.jsonl`
  6. Real-time Operations Log

### Expected Results
- Input -> Agent1 -> Agent2 co trace lien tuc.
- Runtime events va manifest khop UI.
- Stop/resume/refresh khong tao state sai.
- Watchdog timeout hien dung UI va artifact.
- Khong co secret/API key trong runtime files.
- Khi co loi, evidence chi ra phase/node/correlation id gay loi trong vong 1 phut review.

### Full Commands
```powershell
python scripts\check_docs_health.py
npm run test --prefix studio\frontend
npm run build --prefix studio\frontend
.venv_dv\Scripts\python.exe -m pytest -q tests\test_studio_backend.py tests\test_studio_jobs.py
.venv_dv\Scripts\python.exe scripts\studio_v68_runtime_tracking_uat.py
.venv_dv\Scripts\python.exe -m pytest -q
```

## Acceptance Criteria
- Docs:
  - Plan active index co V6.8.
  - Docs health pass.
- Backend:
  - Runtime event writer co tests.
  - Manifest writer/reader co tests.
  - Watchdog co tests.
  - Queue metrics backward compatible.
  - Runtime invariant/replay verifier co tests.
  - No secret leak tests pass.
- Frontend:
  - Trace Debug render runtime summary/timeline/metrics/recovery.
  - Trace Debug render invariant/replay/secret-scan badges.
  - Browser refresh hydrate state.
  - No overflow desktop 1365x768/1920x1080.
- E2E:
  - UAT pass tu input den Agent1/Agent2.
  - Failure injection UAT pass.
  - Output artifacts ton tai va hop le.
  - Full regression pass.

## Risk Controls
- Runtime tracking is additive only.
- Manifest write failures must emit warning, not crash chip-design flow, unless output dir is unusable.
- Watchdog must not override explicit user stop/cancel.
- Runtime API must use existing output sandbox rules.
- All secret-like fields are redacted before writing manifest/events.
- Invariant fail must fail debug harness, but must not crash user run unless invariant exposes unsafe state or secret leak.
- Recovery/hydration must prefer manifest over stale WebSocket replay when `run_id` differs.

## Implementation Order
1. Phase 0 docs/index.
2. Phase 1 event writer.
3. Phase 2 manifest + runtime API.
4. Phase 3 watchdog/recovery.
5. Phase 4 metrics.
6. Phase 5 UI.
7. Phase 6 automated debug harness/invariant replay.
8. Phase 7 UAT/regression.

Do not move to next phase until tests/checks for current phase pass.
