---
title: SWARM AI STUDIO V5.0 UXUI
status: approved-for-implementation
owner: app-uxui
type: exec-plan
last_reviewed: 2026-05-21
source_of_truth: true
---

# SWARM AI STUDIO V5.0 UXUI - Subprocess Runner Upgrade

## Summary
Build a local desktop Studio in `app/` for Semiconductor Swarm AI. The UI uses CustomTkinter. Heavy swarm execution runs in a child process, not in the UI process, so STOP can kill the process tree and the UI stays responsive.

Primary goals:
- UI does not freeze during swarm execution.
- STOP kills active runner and child EDA/tool processes.
- Pipeline Bar uses structured JSONL stage events, not regex log parsing.
- Plan Review shows `architecture_plan.md` inside the Studio.
- All Studio code lives under `app/`.

## Expected Output
Implementation creates:
- `app/main_window.py`: CustomTkinter desktop UI.
- `app/swarm_runner.py`: subprocess runner for start/resume.
- `app/requirements.txt`: app dependencies.
- `app/run_app.bat`: Windows launcher that installs deps into `.venv_dv` and starts the UI.
- `app/README.md`: run, debug, and HITL workflow notes.

User-visible result:
- Top menu: File, View, Settings.
- Input panel: requirement, project name, output directory, Browse.
- Main action: `START SWARM`.
- Pipeline: Planning -> RTL -> Formal -> HITL -> DV -> Physical -> Signoff.
- Realtime log console.
- Interactive console with `ok`, `change <text>`, `stop`, `clear`, `help`, `open output`.
- Architecture Plan Preview panel for Plan Review.
- Output artifacts written to selected output directory.

## Architecture
- `main_window.py` owns only UI, process management, pipe readers, plan preview, and settings.
- `swarm_runner.py` owns swarm graph execution.
- UI starts runner with `subprocess.Popen`.
- UI reads stdout/stderr with lightweight reader threads.
- Runner emits one JSON object per stdout line.
- STOP uses Windows `taskkill /T /F /PID <pid>`, with `terminate()` and `kill()` fallback.
- No core `semiconductor_swarm/` changes unless implementation proves impossible without a small wrapper.

## JSONL Event Protocol
Runner stdout is machine-readable JSONL:

- `{"type":"stage","stage":"planning","status":"running"}`
- `{"type":"stage","stage":"rtl","status":"pass"}`
- `{"type":"pause","action_required":"PLAN_REVIEW","plan_path":"...","payload":{...}}`
- `{"type":"log","level":"info","message":"..."}`
- `{"type":"artifact","output_dir":"...","path":"..."}`
- `{"type":"done","status":"SIGNOFF_READY","output_dir":"..."}`
- `{"type":"error","message":"...","traceback_tail":"..."}`

Pipeline Bar consumes only `stage` events. Log text never drives control state.

## Roadmap
### Phase 0 - Plan Approval
- Write this plan.
- Wait for human approval.

Acceptance:
- Plan exists in `docs/exec-plans/active/`.
- Plan describes outputs, architecture, JSONL events, STOP behavior, and Plan Preview.

### Phase 1 - App Skeleton
- Create `app/`.
- Add UI, runner, launcher, dependencies, README.
- App opens without running swarm.

Acceptance:
- `python app/main_window.py` opens `SWARM AI STUDIO V5.0`.
- Missing CustomTkinter produces a clear dependency message.

### Phase 2 - UI Layout
- Add menus, input panel, pipeline bar, log console, interactive console, plan preview panel.
- Add Browse, Open Output, Clear Logs, Theme Toggle.

Acceptance:
- UI resizes cleanly on desktop.
- Text does not overlap.
- Theme and log clearing work.

### Phase 3 - Subprocess Manager
- Launch `swarm_runner.py` with `Popen`.
- Read JSONL stdout and stderr.
- Implement STOP hard kill.

Acceptance:
- START creates a runner process.
- JSONL log events render live.
- STOP kills active process tree and re-enables START.

### Phase 4 - Swarm Start/Resume
- Runner supports `start` and `resume`.
- Runner calls `persistent_swarm_graph()`.
- Runner uses `Command(resume=...)`.
- Runner calls `write_outputs()` after final done.

Acceptance:
- Start run reaches Plan Review pause.
- `ok` resumes from checkpoint.
- Human Review resume works.
- Final output directory receives artifacts.

### Phase 5 - Plan Preview And HITL UX
- On `PLAN_REVIEW`, UI loads `architecture_plan.md` from event `plan_path`.
- Add Approve OK and Request Change actions.
- Add Open Plan File and Open Output Folder.

Acceptance:
- User can review plan without File Explorer.
- Request Change sends text to resume flow.
- Bad/missing plan path shows a clear message.

### Phase 6 - Polish And Smoke Checks
- Add settings persistence in `app/settings.json`.
- Add README examples.
- Add smoke checks for runner help/compile.

Acceptance:
- `app/run_app.bat` works from repo root.
- `python -m py_compile app/main_window.py app/swarm_runner.py` passes.
- Runner `--help` works without importing LangGraph.

## Test Plan
- Startup:
  - `.venv_dv\Scripts\python.exe app\main_window.py`
  - Window opens without crash in a desktop session.
- Subprocess:
  - START creates runner PID.
  - STOP kills runner process tree.
  - UI stays responsive.
- Pipeline:
  - Stage JSONL events change node colors.
  - Changing log wording does not affect pipeline.
- Plan Review:
  - Demo run pauses at `PLAN_REVIEW`.
  - UI displays `architecture_plan.md`.
  - Approve OK resumes.
  - Request Change resumes with change text.
- Failure:
  - Runner exception emits `error`.
  - UI remains alive.
  - START is enabled after failure.
- Output:
  - Done run writes artifacts using `write_outputs()`.

## Assumptions
- CustomTkinter remains selected.
- V5.0 defaults to demo safe: `run_real_tools=False`, `strict_signoff=False`.
- Strict/ModelSim/Quartus mode is deferred to V5.1, but subprocess kill support is ready.
- Threading is allowed only for pipe reading and UI queue polling, not for heavy swarm execution.
- Regex log parsing is forbidden for pipeline/control state.
