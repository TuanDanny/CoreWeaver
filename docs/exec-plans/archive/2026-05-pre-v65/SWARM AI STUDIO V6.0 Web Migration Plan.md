---
title: SWARM AI STUDIO V6.0 Web Migration Plan
status: active
owner: app-ux
type: exec-plan
last_reviewed: 2026-05-22
source_of_truth: false
---

# SWARM AI STUDIO V6.0 Web Migration Plan

## Summary
Goal: replace the Python CustomTkinter desktop shell with a modern local web cockpit while keeping the semiconductor backend stable.

Architecture decision:
- Keep `semiconductor_swarm/` unchanged as the core engine.
- Keep `app/swarm_runner.py` as the first execution bridge because it already emits structured JSONL, sanitizes payloads, owns graph execution, and supports subprocess lifecycle.
- Add a new `studio/` workspace:
  - `studio/backend/`: FastAPI local server.
  - `studio/frontend/`: React + Vite + TypeScript + Tailwind CSS + shadcn/ui/Radix + lucide-react.
- React talks to FastAPI over HTTP and WebSocket.
- FastAPI runs/controls the Python runner and streams JSON events to the browser.

Expected end result:
- User opens a browser-based local Studio UI at `http://127.0.0.1:<port>`.
- UI looks like a real space-tech/cyberpunk operations cockpit, not a Tkinter form.
- START/STOP/RESUME/PLAN REVIEW/SETTINGS work through FastAPI.
- Realtime logs, agent timeline, pipeline, token metrics, plan preview, and console update via WebSocket.
- STOP kills the full subprocess tree.
- API key remains local and redacted.
- Existing Python app remains as fallback during migration.
- All useful V5.4 visual/UX requirements are carried forward into the web UI, upgraded for React rather than copied as Tk constraints.

## Key Changes

### Backend: FastAPI Local Server
- Add `studio/backend/server.py` and supporting modules.
- Local-only bind by default: `127.0.0.1`.
- Use FastAPI WebSocket to broadcast JSON events to frontend clients.
- Use the existing `app/swarm_runner.py` subprocess as the execution unit for V6.0.
- Maintain one active run initially; multi-run support can be added later after V6.0 is stable.
- Keep current JSONL event schema:
  - `log`
  - `stage`
  - `agent_action`
  - `agent_handoff`
  - `agent_discussion`
  - `metric`
  - `artifact`
  - `pause`
  - `done`
  - `error`
  - `process_start`
  - `process_exit`
- Add backend-side event replay buffer for recently connected/reconnected frontend clients.
- Enforce event size limits and no whole-file streaming through WebSocket.
- Add `CORSMiddleware` for local dev origins:
  - `http://localhost:5173`
  - `http://127.0.0.1:5173`
  - WebSocket origin handling must match the same local-only policy.
  - WebSocket connections from non-local or unknown origins must be rejected.
- Do not block the FastAPI event loop with long-running runner/process reads.
- Add bounded backend event queues so a slow or disconnected frontend cannot block runner stdout consumption.
- When queues are under pressure, prefer coalescing/dropping low-value log events over blocking critical events such as `stage`, `pause`, `error`, and `done`.

### Backend API
- `GET /api/health`
  - returns server health, active run state, and runner availability.
- `GET /api/settings`
  - returns endpoint/model/checkpoint/output defaults and masked API-key state.
- `POST /api/settings`
  - saves endpoint/model/API key to `codex_api.local.json` and UI-safe settings separately.
  - empty/masked API key preserves existing key.
- `POST /api/settings/test-connection`
  - tests Codex endpoint without blocking frontend.
  - fails truthfully if key missing.
- `POST /api/runs/start`
  - body includes `requirement`, `project_name`, `output_dir`, `planning_mode`, `checkpoint_db`.
  - launches `app/swarm_runner.py start`.
- `POST /api/runs/{run_id}/resume`
  - supports `ok` and `change` flow.
- `POST /api/runs/{run_id}/stop`
  - hard-kills runner process tree.
- `GET /api/runs/{run_id}`
  - returns current run state.
- `GET /api/runs/current_state`
  - returns the current hydrated UI state before frontend opens WebSocket.
  - includes active run id, run status, stage states, agent card states, latest metrics, pause state, current plan path, output directory, process pid, selected planning mode, and websocket replay cursor if used.
- `GET /api/artifacts/preview?path=...`
  - returns safe text preview for plan/report files with max-size cap.
  - must enforce an output sandbox jail:
    - resolve absolute path with symlink-aware semantics where available.
    - allow only files inside the repository `outputs/` directory or the active run output directory.
    - reject any path escaping the sandbox with `403 Forbidden`.
    - never read arbitrary absolute paths supplied by the browser.
  - allow preview only for text-like extensions:
    - `.md`, `.txt`, `.log`, `.json`, `.rpt`, `.sv`, `.v`, `.py`, `.f`, `.yaml`, `.yml`, `.toml`, `.csv`
  - reject binary/unknown extensions with a safe non-preview response.
- `WebSocket /ws/runs/{run_id}`
  - streams events.
  - sends replay buffer first, then live events.
  - sends heartbeat events at a fixed interval while connected.

### Process Lifecycle
- Start must not block FastAPI's asyncio event loop.
- Preferred implementation: `asyncio.create_subprocess_exec`.
- Acceptable fallback: isolate blocking subprocess work inside a dedicated background worker/thread executor and communicate through an async-safe queue.
- Do not call blocking `subprocess.Popen`/pipe reads directly inside request handlers or WebSocket handlers.
- On Windows, creation flags should hide console windows where compatible with the async subprocess path.
- STOP:
  - Windows: `taskkill /T /F /PID <pid>`.
  - Linux/macOS: create process group and kill group.
- Server shutdown kills active runner before exit.
- Runner stdout JSONL is parsed and broadcast.
- Runner stderr becomes structured `error` or `log` events.
- Malformed stdout lines are wrapped as `log` events.
- Dev startup scripts must clean stale local server processes/ports before launching.
- Windows script must check ports `8000` and `5173`; if occupied by prior Studio/Uvicorn/Node process, terminate them before start or print a clear safe warning.

### Frontend: React + Vite
- Create `studio/frontend` with:
  - React
  - TypeScript
  - Vite
  - Tailwind CSS
  - shadcn/ui or Radix primitives
  - lucide-react icons
- UI theme:
  - space-tech/cyberpunk dark mode
  - glassmorphism panels
  - glow buttons
  - animated but restrained pipeline
  - readable code/log typography
- V6.0 must carry forward V5.4 UI intent:
  - cosmic/space-tech palette
  - left sidebar
  - top command bar
  - bottom VS Code-style status bar
  - compact seven-stage pipeline
  - semantic button colors
  - terminal-style console
  - severity-highlighted logs
  - Normal/Deep Planning mode selector beside START
- Required views:
  - Project launch panel
  - Agent timeline
  - Collaboration board
  - Realtime operations log
  - Architecture plan preview
  - Interactive console
  - Settings
  - Bottom status bar
- Normal/Deep Planning selector sits next to START.
- Future Wiki button remains disabled/Coming Soon.

### Frontend Performance
- Use log virtualization for large streams.
- Keep rendered log rows bounded.
- Do not render large artifacts directly into DOM.
- Use WebSocket event reducer/state store.
- Do not call React `setState` for every raw log line under high-rate streams.
- Batch log updates on a fixed interval, target about 100-250 ms.
- Acceptable approaches:
  - external log store plus `useSyncExternalStore`
  - throttled reducer updates
  - virtualized list fed by batched chunks
  - direct DOM append inside an isolated log component only if capped, tested, and not mixed with normal React state ownership
- React state may hold aggregate run state; high-volume log rows must be isolated from full-app rerenders.
- Reconnect with backoff and replay recent events from backend.
- State hydration is mandatory:
  - on page load or browser refresh, frontend calls `GET /api/runs/current_state` before opening WebSocket.
  - UI initializes pipeline, agent cards, metrics, pause state, plan preview pointer, and run status from current state.
  - replayed WebSocket events then append/update on top of hydrated state.
- Replay buffer alone is not enough for page refresh recovery.
- Severity colors:
  - info blue
  - warning amber
  - error/fail red
  - metrics cyan/green
- Hotkeys:
  - Enter in console sends command.
  - Ctrl+Enter approves Plan Review.
  - Esc clears command input.
- WebSocket heartbeat:
  - backend sends `{"type":"ping","ts":...}` every 10 seconds while a client is connected.
  - frontend records connection health and can reply with `pong` or update last-seen timestamp depending on implementation.
  - heartbeat events are not shown as normal log rows unless debug mode is enabled.
- Connection UX:
  - bottom status bar shows `Connected`, `Reconnecting`, or `Disconnected`.
  - reconnect attempts use backoff.
  - user-visible run state must remain hydrated while reconnecting.

### V5.4 UI Requirements Carried Into V6.0
- Visual palette:
  - cosmic black: `#050812`
  - deep space navy: `#0b1020`
  - orbital panel: `#101a2d`
  - card surface: `#121d32`
  - cyan glow: `#35d6ff`
  - plasma blue: `#2f80ff`
  - success green: `#2ee59d`
  - warning amber: `#ffb84d`
  - danger red: `#ff4d5e`
- Typography:
  - UI font fallback: `Segoe UI`, `Inter`, `San Francisco`, `Helvetica`, `Arial`, `sans-serif`.
  - Code/log font fallback: `Cascadia Code`, `Consolas`, `JetBrains Mono`, `Courier New`, `monospace`.
  - Log, console, artifact preview, and register-map-like content must use monospace.
- Layout:
  - collapsible left sidebar with icons and labels.
  - top command bar for app actions, not dense metrics.
  - bottom status bar for engine state, PID, token/cost burn rate, new log count, active run, selected planning mode, and websocket state.
  - resizable main layout using browser-native splitter library or CSS grid splitter, not heavy continuous reflow; drag must be debounced or handled by a proven React splitter component.
- Pipeline:
  - seven stages: Planning, RTL, Formal, HITL, DV, Physical, Signoff.
  - compact pills with dot/status, not tall cards.
  - stage state comes only from `stage` events, not regex log parsing.
- Buttons:
  - primary launch button with cyan glow.
  - danger STOP button.
  - success Approve OK.
  - amber Request Change.
  - secondary Open/Settings/Browse actions.
  - disabled Future Wiki/Coming Soon state.
- Logs:
  - virtualized log list with horizontal overflow, not word-wrap.
  - no full-file report streaming.
  - severity colors mirror V5.4.
  - user scroll lock: auto-scroll only if already at bottom; otherwise show `Jump to latest` and new-count.
  - high-rate log streams must be batched/throttled to prevent React render storms.
- Console:
  - terminal prompt such as `root@swarm:~$`.
  - command text in green or amber.
  - hotkeys from V5.4 retained.
- Plan Review:
  - markdown preview of `architecture_plan.md`.
  - Approve OK, Request Change, Open Output, Open Plan File.
  - large file preview must be capped and show truncation state.
- Settings:
  - endpoint/model/API key/checkpoint/output defaults.
  - API key masked and never exposed after save.
  - Test Connection cannot claim success without key.
- Responsive targets:
  - desktop 1440p cockpit first.
  - usable at 1280x720.
  - not required to be mobile-first for V6.0.

### Settings And Secrets
- API key stored only in `codex_api.local.json`.
- Frontend only sees:
  - `apiKeySaved: true/false`
  - never raw key.
- Settings save must not log key.
- Test Connection must fail if no key is available.
- Backend must redact `Authorization`, `api_key`, and token-like values from events/logs.

## Roadmap

### Phase 0 - Migration Safety Baseline
- Record current V5.4 app status in `history.md`.
- Confirm full pytest baseline before web migration.
- Keep Python app untouched except shared runner-compatible changes if strictly needed.
- Acceptance:
  - existing tests pass before V6.0 implementation.
  - V5.4 remains runnable.

### Phase 1 - FastAPI Backend Skeleton
- Add backend package under `studio/backend`.
- Add health/settings endpoints.
- Add run state model.
- Add local config read/write helpers.
- Add strict local dev CORS middleware for Vite origins.
- Acceptance:
  - server starts.
  - `GET /api/health` passes.
  - settings API preserves API key rules.
  - CORS preflight from `localhost:5173` succeeds.

### Phase 2 - Runner Process Manager
- Wrap `app/swarm_runner.py` as subprocess.
- Use `asyncio.create_subprocess_exec` or explicit background worker isolation.
- Implement start/resume/stop.
- Parse stdout JSONL into normalized events.
- Convert stderr to events.
- Hard-kill process tree.
- Acceptance:
  - fake long-running runner can be killed.
  - malformed lines do not crash backend.
  - one active run guard works.
  - health/settings endpoints remain responsive while fake runner is active.

### Phase 3 - WebSocket Event Plane
- Add WebSocket manager.
- Broadcast runner events to all clients.
- Add bounded replay buffer.
- Add event sanitizer/redaction at server boundary.
- Add current-state aggregation model fed by incoming events.
- Add `GET /api/runs/current_state`.
- Add heartbeat ping every 10 seconds per connected client.
- Add bounded per-client queues and backpressure policy.
- Add WebSocket origin rejection for non-local origins.
- Acceptance:
  - test client receives `stage`, `log`, `metric`, and `done`.
  - reconnect receives replay.
  - oversized payload is capped.
  - browser-refresh hydration reconstructs pipeline/agents/metrics without needing to replay all logs.
  - idle connection remains alive during a simulated 10-minute no-log runner.
  - non-local WebSocket origin is rejected.
  - slow client does not block runner stdout consumption.

### Phase 4 - React Shell
- Create Vite React TypeScript frontend.
- Add Tailwind and shadcn/Radix base components.
- Build layout:
  - top command bar
  - left sidebar
  - main ops grid
  - bottom status bar
- Apply V5.4-carried space-tech palette, font stacks, semantic buttons, compact pipeline, terminal console styling, and sidebar behavior from the start.
- Use mock events first.
- Acceptance:
  - `npm run build` passes.
  - UI renders space-tech cockpit without backend.

### Phase 5 - Realtime UI Integration
- Connect frontend to WebSocket.
- Implement event reducer for stages, agents, metrics, logs, pause, artifacts.
- Fetch `GET /api/runs/current_state` before WebSocket connect.
- Add virtualized log panel.
- Add severity highlighting.
- Add scroll-lock and Jump to Latest behavior.
- Keep long technical lines horizontal; do not wrap by default.
- Add batched/throttled log ingestion so high-rate event bursts do not rerender the whole app.
- Keep heartbeat events out of normal log view.
- Add connection state UX in bottom status bar.
- Acceptance:
  - mock stream with 100k log events does not freeze.
  - mock stream at 100 logs/second does not trigger 100 full React renders/second.
  - stage/agent/status/metric cards update from events, not regex.
  - simulated F5 refresh restores active run state before new events arrive.
  - disconnect/reconnect updates status bar clearly without losing hydrated state.

### Phase 6 - Project Run UX
- Wire START, STOP, RESUME, REQUEST CHANGE to HTTP API.
- Add Normal/Deep Planning mode selector.
- Add plan preview from artifact path.
- Add console command handling and hotkeys.
- Add markdown plan preview and capped artifact preview behavior.
- Artifact preview must request only backend-approved output artifacts; backend remains the security boundary.
- Artifact preview UI must handle binary/unknown file responses cleanly instead of showing broken text.
- Acceptance:
  - start launches runner.
  - stop hard-kills runner.
  - pause loads architecture plan preview.
  - approve resumes.

### Phase 7 - Settings UX
- Build settings modal/page.
- Save endpoint/model/API key.
- Test Connection non-blocking.
- Show masked key state only.
- Acceptance:
  - no key leak in frontend state, logs, network responses, or artifacts.
  - missing key test fails truthfully.

### Phase 8 - Dev Runner Scripts
- Add `studio/run_studio.bat`.
- Add backend requirements.
- Add frontend package scripts.
- Add README for V6.0 run flow.
- Add Windows port cleanup for `8000` and `5173` before launch, limited to local Studio/Uvicorn/Node matches where possible.
- Port cleanup must be conservative:
  - kill only processes whose command line clearly matches Studio/Uvicorn/FastAPI backend or Vite/Node frontend launched from this repo.
  - if ownership is ambiguous, do not kill automatically; print PID, port, command line, and manual cleanup instructions.
- Acceptance:
  - one command starts backend and frontend dev servers.
  - user can open the URL and operate demo flow.
  - stale port/process from previous run does not block startup.
  - unrelated service on the same port is not killed silently.

### Phase 9 - UAT And Legacy Fallback
- Run backend tests, frontend build, integration smoke.
- Keep `app/main_window.py` as legacy fallback.
- Mark V6.0 as UAT-ready only when browser flow covers V5.4 features.
- Acceptance:
  - V6.0 reaches feature parity for Start/Stop/Plan Review/Logs/Settings.
  - V5.4 still passes existing tests.

## Test Plan

Backend tests:
- health endpoint.
- CORS preflight accepts Vite local origins and rejects non-local origins.
- WebSocket accepts local origins and rejects non-local origins.
- settings save/load preserves existing API key.
- missing API key test connection fails without network call.
- start rejects second active run.
- stop kills fake child process tree.
- stdout JSONL bridge broadcasts events.
- stderr and malformed JSON become safe log/error events.
- WebSocket replay buffer works.
- current-state hydration returns pipeline/agent/metric/pause/process state.
- APIs remain responsive while fake long-running runner is active.
- event redaction removes secrets.
- artifact preview rejects `..`, arbitrary absolute paths, symlink escapes, and paths outside `outputs/` with `403`.
- artifact preview allows valid files inside active output directory and caps preview size.
- artifact preview rejects binary/unknown extensions safely.
- WebSocket heartbeat emits ping during idle/no-log periods.
- slow WebSocket client/backpressure test proves runner reader is not blocked.

Frontend tests:
- build passes.
- layout renders without backend.
- WebSocket mock updates stages, agents, metrics, and logs.
- initial `current_state` response hydrates UI before WebSocket events.
- 100k log event stress stays responsive through virtualization.
- high-rate log stream is batched/throttled and does not rerender the whole app per line.
- heartbeat ping updates connection status without polluting user logs.
- reconnect/disconnect status bar states render correctly.
- hotkeys work.
- settings modal masks key.
- plan preview handles missing/large files safely.
- visual contract tests or component snapshots cover:
  - sidebar collapsed/expanded state
  - compact pipeline
  - bottom status bar metrics
  - severity-colored log rows
  - terminal console prompt
  - Normal/Deep Planning selector

Integration smoke:
- start FastAPI.
- start frontend.
- run mock runner stream.
- run real `app/swarm_runner.py` demo.
- refresh browser during active run and verify state is retained.
- simulate idle runner with no logs for several minutes and verify WebSocket health stays connected.
- verify:
  - START creates run.
  - logs stream live.
  - STOP kills process.
  - PLAN_REVIEW pause loads plan.
  - APPROVE resumes.
  - status bar updates.
  - UI remains responsive under a large mocked log stream.
  - stale ports are cleaned or reported clearly before startup.
  - artifact preview cannot read outside output sandbox.
  - unrelated process on watched port is reported, not killed blindly.

Required commands after implementation:
```powershell
.venv_dv\Scripts\python.exe -m pytest -q tests\test_app_codex_ui.py
.venv_dv\Scripts\python.exe -m pytest -q
cd studio\frontend; npm run build
```

## Expected Outputs
- `studio/backend/` FastAPI server.
- `studio/frontend/` React/Vite UI.
- `studio/run_studio.bat`.
- local port cleanup logic for Windows dev run.
- `studio/README.md`.
- Backend tests for process/WebSocket/settings.
- Backend tests for CORS, event-loop responsiveness, and current-state hydration.
- Backend tests for artifact path sandbox and WebSocket heartbeat.
- Backend tests for artifact extension allowlist, WebSocket origin rejection, and backpressure.
- Frontend build and mock-event tests.
- Frontend stress test proving batched log ingestion.
- Updated `history.md`.
- Updated plan indexes.
- V6.0 visual parity checklist proving V5.4 UI requirements were carried forward.

## Assumptions
- V6.0 uses React + Vite, not Next.js, for a local cockpit.
- shadcn/ui/Radix is preferred for polished components.
- Browser-first local app is the next step; Tauri/Electron packaging is deferred.
- Existing Python app remains available until V6.0 passes UAT.
- FastAPI server remains local-only by default.
- No backend core rewrite in `semiconductor_swarm/`.
- V6.0 should improve V5.4 visuals using web-native capabilities; it must not regress V5.4 core workflows.
- FastAPI route handlers must remain non-blocking during long EDA/runner tasks.
- Browser-supplied paths are untrusted input and must never bypass server-side sandbox checks.
- Log rendering performance is a first-class requirement, not a visual polish item.
- Startup convenience must not silently kill unrelated user processes.
