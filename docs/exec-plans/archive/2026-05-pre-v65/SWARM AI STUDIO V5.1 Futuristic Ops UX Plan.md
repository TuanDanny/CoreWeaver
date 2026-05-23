---
title: SWARM AI STUDIO V5.1 Futuristic Ops UX Plan
status: active
owner: app-ux
type: exec-plan
last_reviewed: 2026-05-21
source_of_truth: true
---

# SWARM AI STUDIO V5.1 Futuristic Ops UX Plan

## Summary
Upgrade the existing `app/` desktop studio from a functional runner UI into a richer operations cockpit for the semiconductor swarm.

Goals:
- Show detailed Agent 1-5 operational activity.
- Show evidence-based collaboration and handoffs between agents.
- Make the UI feel more futuristic, polished, and smooth.
- Keep the current robust subprocess runner model: UI stays responsive, STOP kills the process tree, pipeline state comes from JSONL events, not log regex.
- Keep the app stable under heavy EDA output: no huge report bodies over stdout, no unbounded Textbox growth, and no forced auto-scroll while the user is reading older logs.
- Add Windows desktop polish: crisp DPI-aware text, no stray CMD popups, monospace technical panes, and safe shutdown of active runners.

Non-goals:
- Do not rewrite the app in PyQt6 for V5.1.
- Do not change RTL/DV/signoff logic.
- Do not invent fake agent chat. Collaboration messages must be derived from real events, reports, contracts, and artifacts.
- Do not stream full EDA reports such as `.sta.rpt`, Quartus logs, Verilator logs, or waveform metadata into JSONL. The UI receives paths, summaries, and capped tails only.

## Current State
- `app/main_window.py` already provides CustomTkinter desktop UI, top menu, inputs, pipeline bar, real-time log box, plan preview, interactive console, subprocess launch, STOP, resume, and output opening.
- `app/swarm_runner.py` already runs the graph in a subprocess and emits JSONL events: `stage`, `pause`, `log`, `artifact`, `done`, `error`.
- Backend status is currently mostly written through `status.log`, then tailed as plain log text.
- UI currently lacks first-class agent cards, agent-to-agent handoff visualization, evidence-linked collaboration board, richer metrics, log filtering, and future-styled controls.

## Product Result
After V5.1, the user should see a studio-like workflow:
- Agent cards for Agent 1, Agent 2, Agent 3, Agent 4, and Agent 5.
- Each card shows current status, latest action, evidence count, and last artifact.
- Reserve an `Agent 6 / Signoff Ready` card slot in the timeline layout. It stays disabled/placeholder in V5.1, but prevents a future Agent 6 UI integration from breaking the 3-area layout.
- A Collaboration Board shows real handoffs:
  - Agent 1 -> Agent 2: architecture/spec contract ready.
  - Agent 2 -> Agent 5: RTL/formal hooks ready.
  - Agent 5 -> Agent 3: formal-first collateral status.
  - Agent 2 -> Agent 3: RTL compile order and DV hooks ready.
  - Agent 3 -> Agent 4: DV decision and simulation evidence.
  - Agent 4 -> Signoff: timing/resource/signoff readiness.
- Real-time logs remain available, but are no longer the only operational view.
- Logs stay bounded and smooth even under long Quartus/Verilator output.
- Pipeline remains stable because it still reads only structured events.
- Plan Review remains embedded with `architecture_plan.md` preview and approve/change actions.

## Performance And Safety Guardrails
These are mandatory implementation constraints, not polish tasks.

### JSONL Payload Limits
- Runner must never emit complete large files or report bodies on stdout.
- Any single JSONL event must stay below `64 KiB`.
- Any text field in an event must be capped:
  - `message`: max 4 KiB.
  - `summary`: max 2 KiB.
  - `traceback_tail`: max 8 KiB.
  - report/log tails: max 200 lines or 16 KiB, whichever is smaller.
- Large artifacts must be emitted by path:
  - `artifact.path`
  - `artifact.kind`
  - `artifact.bytes`
  - optional `artifact.preview_tail`
- If a payload would exceed the cap, runner writes full content to file and emits a short event with `truncated=true` and `full_path`.

### Log Storage And Rendering Limits
- UI must maintain an in-memory ring buffer, not an unbounded Textbox.
- Default retained log entries: `10_000`.
- Default rendered Textbox lines: `2_000`.
- When the active filter changes, re-render from the ring buffer up to the render cap.
- Store full operational logs on disk through existing output artifacts/status files, not in widget memory.
- Never insert 100,000 lines into a Tkinter Textbox.
- Queue draining must be batched and bounded:
  - Each `.after()` UI drain cycle reads at most `100` queued events.
  - If backlog remains, schedule the next drain quickly instead of blocking the Tk event loop.
  - Never use an infinite queue-drain loop on the UI thread.

### Fonts And Readability
- All log, console, code, and markdown preview widgets must use monospace font.
- Preferred font order:
  - `Cascadia Code`
  - `Consolas`
  - `Courier New`
- Log and console font size: `12 px`.
- Plan preview/code preview font size: `13 px`.
- Hex addresses, register maps, paths, and command lines must align cleanly in the UI.

### Windows Native Polish
- `app/main_window.py` must enable DPI awareness before creating the Tk root window.
- Preferred Windows call:
  - `ctypes.windll.shcore.SetProcessDpiAwareness(1)` or stronger equivalent when available.
- All `subprocess.Popen(...)` calls launched by the UI must use `creationflags=subprocess.CREATE_NO_WINDOW` on Windows.
- No black CMD window should flash when the runner starts, resumes, opens helper commands, or performs app-managed subprocess actions.

### Auto-scroll Policy
- Auto-scroll is enabled only when the user is already near the bottom.
- If the user scrolls upward, UI enters `scroll_locked=true`.
- While locked:
  - New logs increment a `new log count` chip.
  - Textbox does not jump to bottom.
  - A `Jump to latest` button appears.
- Clicking `Jump to latest` unlocks auto-scroll and scrolls to bottom.

### Process Lifecycle Safety
- Closing the window with an active runner must not orphan subprocesses.
- The app must register a `WM_DELETE_WINDOW` handler.
- If a runner is active when the user presses the window `[X]`, show a confirmation dialog before quitting.
- After confirmation, `on_exit()` must call the same hard process-tree kill path as STOP before destroying the window.
- On Windows, use `taskkill /T /F /PID <pid>` first.
- Fallback sequence:
  - `proc.terminate()`
  - wait up to 2 seconds
  - `proc.kill()`
- UI must display `Stopping runner...` and wait for `process_exit` or timeout before final destroy.
- If kill fails, show a blocking error dialog with PID and command to terminate manually.

## Event Protocol
Keep existing JSONL events compatible and add these event types.

### `agent_action`
Emitted when an agent starts, finishes, blocks, or records important evidence.

Required fields:
- `type`: `agent_action`
- `agent`: `agent1`, `agent2`, `agent3`, `agent4`, `agent5`, or reserved `agent6`
- `label`: human label such as `Agent 1 Architect`
- `phase`: `planning`, `rtl`, `formal`, `dv`, `physical`, or `signoff`
- `action`: short action phrase
- `status`: `running`, `pass`, `fail`, `paused`, or `info`
- `summary`: one-line detail

Optional fields:
- `artifact`
- `evidence_path`
- `metric`
- `severity`
- `truncated`
- `full_path`

### `agent_handoff`
Emitted when one agent produces a contract or artifact for another agent.

Required fields:
- `type`: `agent_handoff`
- `from_agent`
- `to_agent`
- `contract`
- `status`
- `summary`

Optional fields:
- `artifact`
- `evidence_path`
- `truncated`

### `agent_discussion`
Evidence-based commentary shown in the Collaboration Board.

Required fields:
- `type`: `agent_discussion`
- `speaker`
- `audience`
- `message`
- `severity`: `info`, `warning`, `error`, or `success`

Optional fields:
- `evidence`
- `artifact`
- `truncated`

### `metric`
Small operational metric for UI chips and dashboard rows.

Required fields:
- `type`: `metric`
- `name`
- `value`
- `status`

Optional fields:
- `unit`
- `agent`
- `artifact`

### `log`
Existing `log` event remains supported, but V5.1 adds hard caps.

Required behavior:
- `message` is capped to 4 KiB.
- Full logs are persisted to disk when available.
- If capped, include `truncated=true`.
- If full text exists in a file, include `full_path`.

## UX Layout
Use CustomTkinter. Keep one executable desktop window.

### Header
- Replace plain title area with a compact tech header:
  - Product name: `SWARM AI STUDIO V5.1`
  - Run status chip: `Idle`, `Running`, `Paused`, `Done`, `Failed`
- PID chip when runner active
- Output directory quick action
- New-log count chip when auto-scroll is locked

### Input Panel
- Keep requirement textbox, project name, output directory, Browse.
- Add compact run options row:
  - Demo mode locked for V5.1 default.
  - Checkpoint DB display from settings.
  - `Auto-open plan on pause` toggle, default on.

### Action Buttons
Buttons must look more polished and readable:
- `START SWARM`: primary cyan, prominent.
- `STOP`: red danger.
- `APPROVE OK`: green.
- `REQUEST CHANGE`: amber.
- `OPEN OUTPUT`: neutral.
- `OPEN PLAN`: neutral.
- `OPEN WIKI DASHBOARD`: disabled placeholder for future Agent 6 dashboard integration.

Button states:
- Start disabled while runner active.
- Stop enabled only while runner active.
- Approve/Request Change enabled only on pause.
- Open Plan enabled only when plan path exists.
- Open Wiki Dashboard remains disabled in V5.1.

### Pipeline Stepper
Replace label-only pipeline with stepper-style status items:
- Planning
- RTL
- Formal
- HITL
- DV
- Physical
- Signoff

Each step shows:
- label
- status dot
- subtle running pulse by periodic color toggle
- status text: idle/running/paused/pass/fail

### Main Workspace
Use a 3-area layout:
- Left: Agent Timeline.
- Center: Real-time Logs and Ops Details tabs.
- Right: Plan Preview and Interactive Console.

Agent Timeline:
- One visible card per Agent 1-5.
- One reserved placeholder card for Agent 6 / Signoff Ready.
- Fields: latest action, status, last evidence/artifact, handoff count.
- Cards update only from `agent_action` and `agent_handoff`.
- Agent 6 placeholder is disabled in V5.1 and marked `Reserved`.

Ops Details:
- Tabs or segmented buttons:
  - Logs
  - Collaboration
  - Artifacts
  - Metrics
  - Errors
- If tabs are too heavy for CustomTkinter, use segmented control plus a single textbox/list area.

Collaboration Board:
- Append `agent_discussion` and `agent_handoff` entries.
- Prefix entries with speaker and audience.
- Include evidence path if present.
- Do not fabricate conversations from raw log text.

Real-time Logs:
- Keep chronological log stream.
- Use monospace font at `12 px`.
- Backed by bounded ring buffer and capped rendering.
- Auto-scroll locks when user scrolls upward.
- Show `Jump to latest` when locked.
- Add filter controls:
  - All
  - Agent1
  - Agent2
  - Agent3
  - Agent4
  - Agent5
  - Agent6
  - Errors
- Filtering can be in-memory for current session only.

Plan Preview:
- Keep current markdown text preview.
- Use monospace font at `13 px` for markdown, code fences, register maps, and path snippets.
- Add buttons:
  - Approve OK
  - Request Change
  - Open Plan File
  - Open Output Folder

Interactive Console:
- Use monospace font at `12 px`.
- Keep existing commands:
  - `ok`
  - `change <text>`
  - `stop`
  - `clear`
  - `help`
  - `open output`
- Add commands:
  - `open plan`
  - `filter all`
  - `filter agent1`
  - `filter agent2`
  - `filter agent3`
  - `filter agent4`
  - `filter agent5`
  - `filter agent6`
  - `filter errors`
  - `jump latest`

## Runner Behavior
Enhance `app/swarm_runner.py` without changing graph semantics.

Global runner constraints:
- Wrap every emitted event with a payload sanitizer before JSON serialization.
- Sanitizer applies field caps and adds `truncated=true` when needed.
- For large reports, emit artifact path and capped summary only.
- Never print raw report bodies or whole stack traces outside capped JSONL events.

Start flow:
- Emit `agent_action(agent1, running)` before graph invoke.
- Emit `stage(planning, running)`.
- On Plan Review pause:
  - Emit `agent_action(agent1, paused/pass)`.
  - Emit `agent_discussion` from Agent 1 to user: plan is ready for review.
  - Emit `artifact` for `architecture_plan.md`.
  - Emit current `pause` event unchanged.

Resume after Plan Review:
- Emit Agent 1 approval discussion.
- Emit `agent_handoff agent1 -> agent2` with `agent1_to_agent2`.
- Emit Agent 2 running action.
- Emit Agent 5 running action after Agent 2.
- On Human Review pause:
  - Emit Agent 2 pass action with RTL count if available.
  - Emit Agent 5 pass action with formal file count if available.
  - Emit `agent_handoff agent2 -> agent5`.
  - Emit `agent_handoff agent2 -> agent3`.
  - Emit current `pause` event unchanged.

Resume after Human Review:
- Emit HITL pass.
- Emit Agent 3 running action.
- Emit Agent 3 pass/fail action from `agent3_release_decision` if available.
- Emit Agent 4 running action.
- Emit Agent 4 pass/fail action from physical report.
- Emit final signoff discussion from collected evidence.

Done:
- Emit final `metric` events:
  - generated file count
  - stage status
  - DV decision label if present
  - signoff readiness if present
- Emit current `done` event unchanged.

Errors:
- Emit `agent_action(..., fail)` for active agent if known.
- Emit `error` event unchanged.
- Cap `traceback_tail` to 8 KiB.
- If full traceback is needed, write it to an error artifact and include `full_path`.

## Implementation Roadmap

### Phase 0 - Plan Approval
Deliver this plan file and wait for approval.

Acceptance:
- Plan file exists under `docs/exec-plans/active/`.
- Active index and `PLANS.md` reference the plan.
- No app implementation changes yet.

### Phase 1 - Event Protocol Foundation
Add runner helpers for `agent_action`, `agent_handoff`, `agent_discussion`, and `metric`. Add the global JSONL payload sanitizer.

Acceptance:
- `python app/swarm_runner.py --help` still works.
- Existing UI can still run because old events are preserved.
- Unit/smoke command can parse emitted JSONL events.
- A synthetic 1 MiB message is truncated before emission and the JSONL line stays below `64 KiB`.
- UI subprocess launches use `CREATE_NO_WINDOW` on Windows, with a no-op fallback on non-Windows.

### Phase 2 - Evidence-Based Agent Events
Emit structured events around start/resume/pause/done transitions.

Acceptance:
- Plan Review pause includes Agent 1 action/discussion/artifact.
- Human Review pause includes Agent 2 and Agent 5 handoff events.
- Done includes Agent 3/4/signoff summaries if reports exist.
- No UI state depends on log text.

### Phase 3 - Futuristic UI Shell
Upgrade header, input panel, buttons, status chips, and pipeline stepper.

Acceptance:
- Window opens without crash.
- Buttons have correct enabled/disabled state.
- Pipeline still reacts to `stage` events.
- STOP still kills process tree.
- Window close with an active runner uses the same process-tree kill path and does not orphan the subprocess.
- DPI awareness is enabled before Tk root creation.
- Log, console, and preview panes use monospace fonts.
- `OPEN WIKI DASHBOARD` button is visible but disabled for the reserved Agent 6 integration.

### Phase 4 - Agent Timeline And Collaboration Board
Add Agent 1-5 cards, reserved Agent 6 placeholder, and collaboration board.

Acceptance:
- Agent cards update from `agent_action`.
- Handoff entries update from `agent_handoff`.
- Collaboration entries update from `agent_discussion`.
- Evidence paths display in readable form.
- Agent 6 placeholder is visible but disabled/reserved.

### Phase 5 - Ops Details, Filters, And Console Upgrades
Add logs/collaboration/artifacts/metrics/errors view switching, log filters, bounded log rendering, and smart auto-scroll.

Acceptance:
- Existing logs still stream.
- User can filter by agent or errors.
- Console supports `open plan` and `filter ...`.
- Clear logs does not clear pipeline or agent states.
- Log ring buffer keeps at most `10_000` entries by default.
- Textbox renders at most `2_000` lines by default.
- Queue drain reads at most `100` events per UI cycle.
- When user scrolls up, new logs do not force-scroll; `Jump to latest` restores auto-scroll.

### Phase 6 - Smoke And Flow Validation
Run app/runner smoke checks and a demo flow.

Acceptance:
- `python -m py_compile app/main_window.py app/swarm_runner.py` passes.
- `python app/swarm_runner.py --help` passes.
- Demo flow reaches Plan Review and loads plan preview.
- Resume reaches Human Review and shows Agent2/Agent5 handoff events.
- Final resume writes outputs and shows done/signoff event.
- Close-window during an active mocked long run kills the runner process tree.
- Synthetic large report path event does not freeze UI and does not inject full report text into Textbox.

## Test Plan
Required checks after implementation:

```bat
.venv_dv\Scripts\python.exe -m py_compile app\main_window.py app\swarm_runner.py
.venv_dv\Scripts\python.exe app\swarm_runner.py --help
.venv_dv\Scripts\python.exe -m pytest -q tests\test_swarm_graph.py tests\test_agent_pipeline.py
.venv_dv\Scripts\python.exe -m pytest -q tests\test_docs_health.py tests\test_prompt_contracts.py
```

Manual Studio checks:
- Open app with `app\run_app.bat`.
- Verify text stays crisp at Windows display scaling `125%` and `150%`.
- Verify no black CMD popup appears during start/resume/stop helper subprocess actions.
- Verify log, console, and plan preview use monospace fonts and register-map hex columns align.
- Start demo run.
- Verify UI does not freeze.
- Verify Agent Timeline updates Agent 1 during planning.
- Verify Plan Preview opens on Plan Review.
- Approve OK.
- Verify Agent 2 and Agent 5 cards update.
- Verify Collaboration Board shows handoffs.
- Approve Human Review.
- Verify Agent 3, Agent 4, Signoff summaries appear.
- Verify STOP still works during a long-running subprocess.
- Start a long-running/mocked runner, close with the window `[X]`, and verify no child process remains.
- Scroll log upward during streaming; verify new logs do not pull view to bottom until `Jump to latest`.
- Send a large synthetic artifact/report event; verify UI shows path/summary only.

## Risks And Controls
- Risk: UI becomes too visually busy.
  - Control: use compact cards, restrained colors, and clear grouping.
- Risk: Collaboration board becomes fake chat.
  - Control: only use structured events derived from graph state/reports/contracts.
- Risk: event protocol breaks old UI behavior.
  - Control: keep existing events unchanged and add new event types only.
- Risk: log volume slows UI.
  - Control: ring buffer, render cap, event batching, and no full-report stdout payloads.
- Risk: stdout pipe blocks on huge JSONL events.
  - Control: event sanitizer, 64 KiB line cap, artifact-by-path for large files.
- Risk: active EDA subprocess survives window close.
  - Control: `on_exit()` must call process-tree kill and wait before destroy.
- Risk: user cannot inspect older log lines because auto-scroll fights them.
  - Control: scroll lock plus `Jump to latest`.
- Risk: Agent 6 later breaks layout.
  - Control: reserve disabled Agent 6 card/slot now.
- Risk: Windows scaling makes text blurry or subprocess launches flash CMD windows.
  - Control: enable DPI awareness and use `CREATE_NO_WINDOW` for UI-managed subprocesses.
- Risk: queue processing blocks Tk under heavy log bursts.
  - Control: bounded queue drain of at most `100` events per UI cycle and capped Textbox rendering.

## Assumptions
- CustomTkinter remains the V5.1 UI toolkit.
- V5.1 does not alter core agent algorithms.
- Demo mode remains default.
- `history.md` must be updated at implementation start, after major changes, after test results, and at completion.
- Agent 6 logic is not implemented in V5.1, but the UI reserves an Agent 6 / Signoff Ready slot for future integration.
