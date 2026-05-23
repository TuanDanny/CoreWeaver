---
title: SWARM AI STUDIO V5.4 Space Tech UI Polish Plan
status: active
owner: app-ux
type: exec-plan
last_reviewed: 2026-05-22
source_of_truth: false
---

# SWARM AI STUDIO V5.4 Space Tech UI Polish Plan

## Summary
Goal: upgrade the whole desktop app to a polished space-technology cockpit while keeping the existing subprocess runner, JSONL event protocol, API key safety, smart logs, and hard-kill process lifecycle intact.

This plan is UI/UX only. It must not change Agent 1/2/3/4/5 backend behavior, runner semantics, or generated semiconductor artifacts.

Main outcomes:
- No native white Tk menu remains.
- Whole app follows a space-tech mission-control theme.
- Sidebar collapse/expand feels smoother.
- Buttons look modern and consistent.
- Seven-stage progress bar is slimmer and clearer.
- Real-time Operations Log can be resized wider and can take space from Agent Timeline.
- UI fonts are standardized: Segoe UI for controls, Cascadia Code/Consolas for logs and code-like panels.
- Power-user keyboard shortcuts are available for common console/HITL actions.
- Log lines are color-tagged by severity.
- Runtime metrics move to a thin bottom status bar.
- Agent 1 planning mode selector is visible beside START SWARM.

## Requirements

### Visual Theme
- Use a space-tech palette:
  - cosmic black: `#050812`
  - deep space navy: `#0b1020`
  - orbital panel: `#101a2d`
  - card surface: `#121d32`
  - cyan glow: `#35d6ff`
  - plasma blue: `#2f80ff`
  - success green: `#2ee59d`
  - warning amber: `#ffb84d`
  - danger red: `#ff4d5e`
- Keep design dark, technical, and readable.
- Avoid flat default CustomTkinter look where possible by using borders, hover colors, and consistent button states.
- Do not add decorative heavy animations that can make logs or runner UI lag.

### Font Standard
- UI controls, buttons, command bar, sidebar, chips, labels:
  - preferred: `("Segoe UI", 12)`
  - titles: `Segoe UI` bold with larger sizes only where needed.
- Real-time Log, Interactive Console, Plan Preview, Project Requirement textbox:
  - preferred: `("Cascadia Code", 12)`
  - fallback: `("Consolas", 12)`
- No extra font installation is required.
- Font selection must be runtime-detected, not hardcoded blindly:
  - UI fallback order: `Segoe UI` -> `San Francisco` -> `Helvetica` -> `Arial`
  - mono fallback order: `Cascadia Code` -> `Consolas` -> `Courier New` -> `monospace`
  - Use the first installed family reported by Tk when possible.
  - This keeps Windows polished and avoids ugly/broken fonts on Linux EDA workstations.

### Native Menu Removal
- Remove or disable native Tk `Menu` attachment that creates the white menu bar.
- Custom dark command bar becomes the only visible menu/control strip.
- Existing menu actions remain reachable from the command bar:
  - File/New Project
  - View/Theme or Clear Logs where applicable
  - Settings
  - Help/unused actions show `Coming soon`

### Sidebar
- Keep left sidebar.
- Add smooth collapse/expand using `after()` animation with bounded step count.
- Persist collapsed state in `app/settings.json`.
- Collapsed mode should show compact icons or short labels, not empty buttons.
- Sidebar should not jump the whole UI harshly during toggle.
- Sidebar animation must be snappy, not web-style long animation:
  - use only 3-5 frames
  - temporarily disable propagation/reflow where practical during width change
  - never animate every pixel or run a long 60 FPS layout loop

### Buttons
- Add reusable button style helpers:
  - `primary`: START SWARM / launch actions
  - `secondary`: Browse/Open
  - `success`: Approve OK
  - `warning`: Request Change
  - `danger`: STOP
  - `disabled`: Future Wiki / unavailable actions
- Buttons must use Segoe UI and consistent height/padding.
- Hover colors should feel like glow/highlight but remain readable.

### Planning Mode Control
- Add a compact mode selector beside `START SWARM`.
- Supported modes:
  - `Normal`: one hierarchical council pass; intended for faster planning.
  - `Deep Planning`: minimum 3 consensus iterations; intended for higher-quality planning.
- Persist selected mode in `app/settings.json`.
- Pass selected mode to the runner using the existing safe process launch path. If backend CLI support is missing, add a small explicit runner argument rather than encoding mode in free-text requirement.
- Display current mode in UI and bottom status bar.
- Default mode: `Normal`.

### Pipeline Bar
- Replace current tall stage blocks with compact stage pills.
- Height target: about `34-38px`.
- Each stage shows:
  - small status dot
  - stage label
  - compact status text
- Stage states:
  - idle: muted gray
  - running: cyan/blue pulse
  - pass: green
  - fail: red
  - partial/warning: amber
- Existing stage event handling must keep working.

### Resizable Operations Layout
- Replace fixed three-column main grid with a resizable splitter/paned layout.
- Use native `tkinter.PanedWindow` styled with dark background (`bg="#050812"` or theme equivalent) as the preferred splitter.
- Do not invent a continuous custom mouse-drag splitter with `<B1-Motion>` reflow unless it is debounced and layout recomputes only on button release.
- Panes:
  - Agent Timeline
  - Real-time Operations Log
  - Plan Preview / Interactive Console
- User can drag pane handles so the Real-time Operations Log expands left and reduces Agent Timeline width.
- Save and restore pane widths in `app/settings.json`.
- If pane restore fails due to screen size, fallback to sane defaults.

### Textbox Performance
- Real-time Operations Log must keep `wrap="none"`.
- Plan Preview should keep `wrap="none"` for code/register map alignment.
- Interactive Console input/history must not force expensive wrap recalculation.
- Add horizontal scrollbars where needed for log/plan panels.
- Do not render huge file contents into UI; keep existing JSONL payload limits and ring buffer policy.

### Interactive Console UX
- Console should look like a terminal, not a generic form field.
- Add a static prompt prefix such as `root@swarm:~$` or `swarm@studio:~$` in cyan.
- User input text should be green or amber to separate commands from placeholder/log text.
- Use monospace font.
- Cursor should be block-style where Tk supports it; acceptable fallback is wider cyan/amber insertion cursor if CTkEntry cannot expose true block cursor cleanly.
- Keyboard shortcuts:
  - `Enter` in console sends the command immediately.
  - `Ctrl+Enter` triggers `Approve OK`.
  - `Esc` clears the console input.
  - Shortcuts must work without mouse focus fights and must not trigger duplicate command sends.

### Log Severity Highlighting
- Use text tags in the underlying textbox for severity colors.
- Tag policy:
  - `[INFO]` / info events: plasma blue
  - `[ERROR]`, `[FAIL]`, error/fail events: danger red
  - `[WARNING]`, warning events: amber
  - metrics/events: cyan or green accent
- Severity tagging must apply during append, not by rescanning all 2000 retained lines on every update.
- Ring buffer trimming must preserve color tags for retained lines.

### Bottom Status Bar
- Add a thin VS Code-style bottom status bar, about `24-26px` tall.
- Move runtime metrics from crowded header area to bottom bar:
  - engine state
  - PID
  - token count / estimated cost / burn rate
  - new log count
  - selected planning mode
- Header should focus on product identity and main actions.
- Status bar must update from existing app state and structured metric events.

### Existing Safety Must Stay
- No API key in logs, command-line args, JSONL events, or `app/settings.json`.
- Test Connection remains non-blocking.
- Ring buffer remains limited to 2000 rendered log lines.
- Smart auto-scroll remains: only auto-scroll when user is at bottom.
- STOP and window close still hard-kill subprocess tree.
- `Coming soon` behavior remains for unused actions.

## Roadmap

### Phase 0 - Baseline Audit
- Inspect current `app/main_window.py` structure.
- Identify native menu attachment, sidebar toggle, pipeline renderer, and main-area layout.
- Record start in `history.md`.
- Acceptance:
  - No code behavior changed yet except history entry and plan approval flow.

### Phase 1 - Theme And Font Foundation
- Add centralized constants for palette and fonts.
- Add runtime font resolver with Windows-first and Linux-safe fallbacks.
- Apply resolved UI font to UI elements.
- Apply resolved mono font to log, console, plan, and requirement text areas.
- Add reusable helpers for CTk fonts and button styles.
- Acceptance:
  - Tests can inspect expected font families on representative widgets.
  - App remains importable and starts.

### Phase 2 - Remove Native Menu And Polish Command Bar
- Stop attaching native Tk menu.
- Keep custom dark command bar as the menu surface.
- Update command bar colors to space-tech palette.
- Ensure unused command actions log `Coming soon`.
- Acceptance:
  - No white menu bar appears.
  - Command bar still exposes File/View/Settings-related actions.

### Phase 3 - Sidebar Animation
- Replace instant sidebar width jump with bounded animation.
- Persist collapsed state in `app/settings.json`.
- Render collapsed labels/icons clearly.
- Limit animation to 3-5 snappy frames and avoid continuous whole-window reflow.
- Acceptance:
  - Collapse/expand does not crash.
  - Collapsed state survives app restart/settings reload.

### Phase 4 - Button And Panel Restyle
- Apply style helpers to main actions, plan actions, header chips, sidebar buttons, and secondary controls.
- Update panel backgrounds/borders to mission-control theme.
- Add `Normal` / `Deep Planning` selector beside `START SWARM`.
- Save selected mode and pass it through runner launch.
- Acceptance:
  - START/STOP/Approve/Change/Open have distinct semantic colors.
  - Disabled Future Wiki remains visibly disabled.
  - Selected planning mode is visible and persists.

### Phase 4.5 - Bottom Status Bar
- Add thin bottom status bar.
- Move PID, engine state, token/cost/burn rate, new log count, and mode display from header chips into the bottom bar.
- Acceptance:
  - Header is less crowded.
  - Metrics still update from existing event handling.

### Phase 5 - Compact Pipeline
- Rebuild seven-stage pipeline as compact pills.
- Keep same `stage_widgets`/stage update contract or provide compatible wrapper.
- Acceptance:
  - Existing structured `stage` events still update UI correctly.
  - Pipeline consumes less vertical space.

### Phase 6 - Resizable Ops Layout
- Introduce native dark-styled `tkinter.PanedWindow` splitter for Agent Timeline, Logs, and Plan/Console.
- Persist pane widths.
- Ensure log panel can expand leftward over Agent Timeline space.
- Keep log and plan text widgets unwrapped and add horizontal scrolling where needed.
- Acceptance:
  - User can resize panes.
  - Saved widths restore on next app load.
  - Layout does not break when sidebar is collapsed.

### Phase 6.5 - Console Terminal Polish
- Replace plain console input presentation with terminal-style prompt row.
- Keep command handling behavior unchanged.
- Add prompt prefix, monospace command input, colored typed text, and block/wide cursor best effort.
- Bind power-user hotkeys: `Enter`, `Ctrl+Enter`, and `Esc`.
- Acceptance:
  - Commands `ok`, `change <text>`, `stop`, `clear`, `help`, `open output`, `open plan`, and filters still work.
  - Console visually reads as a terminal command line.
  - Keyboard shortcuts work without mouse use.

### Phase 6.6 - Log Severity Highlighting
- Configure text tags for info, warning, error/fail, metric, and neutral log lines.
- Apply tags when appending each log event.
- Avoid full-buffer recoloring on every append.
- Acceptance:
  - ERROR/FAIL lines are visibly red.
  - WARNING lines are amber.
  - INFO lines are blue.
  - Ring buffer still caps rendered logs at 2000 lines.

### Phase 7 - Verification And Smoke
- Run static compile, UI unit tests, targeted Agent 1 V5.1 regression, and full pytest when practical.
- Run app startup smoke.
- Record results in `history.md`.
- Acceptance:
  - No syntax errors.
  - App opens without crash.
  - Existing app safety tests remain green.

## Test Plan

Required commands:
```powershell
.venv_dv\Scripts\python.exe -m py_compile app\main_window.py app\swarm_runner.py tests\test_app_codex_ui.py
.venv_dv\Scripts\python.exe -m pytest -q tests\test_app_codex_ui.py
.venv_dv\Scripts\python.exe -m pytest -q tests\test_agent1_v51_deep_council.py
.venv_dv\Scripts\python.exe -m pytest -q
```

New/updated UI tests:
- Native menu is not attached.
- UI button/menu/label samples use resolved UI font from the approved fallback list.
- Log, console, plan, and requirement text widgets use resolved mono font from the approved fallback list.
- Sidebar collapse persists.
- Sidebar animation step count is bounded and does not run pixel-by-pixel.
- Coming Soon action logs expected message.
- Pipeline widgets are compact and still update from `stage` events.
- Resizable pane container uses native `tkinter.PanedWindow` or a debounced release-only fallback.
- Log/plan widgets use `wrap="none"` and horizontal scrollbar wiring exists.
- Console prompt prefix exists and command handling still works.
- Console `Enter`, `Ctrl+Enter`, and `Esc` shortcuts route to expected handlers.
- Log severity tags are configured and applied to new lines.
- Bottom status bar exists and shows engine state, PID, token/cost, new log count, and planning mode.
- Planning mode selector persists and is sent to runner args.
- Existing API key masking and async connection tests still pass.

Manual UAT:
- Launch app with:
```powershell
.venv_dv\Scripts\python.exe app\main_window.py
```
- Confirm:
  - no white menu bar
  - space-tech theme is applied across the whole app
  - sidebar collapse/expand is smoother
  - buttons look polished and semantic
  - progress bar is compact
  - Real-time Operations Log can be dragged wider
  - resizing does not spike CPU or stutter noticeably
  - log/console/plan fonts are monospace and aligned
  - long log lines scroll horizontally instead of wrapping
  - console prompt looks terminal-like
  - Enter sends console command, Ctrl+Enter approves, Esc clears input
  - warning/error/fail logs are easy to spot by color
  - bottom status bar shows PID/token/state/mode without crowding header
  - Normal/Deep Planning selector sits beside START SWARM

## Out Of Scope
- No Agent 1/2/3/4/5 backend changes.
- No JSONL runner protocol changes.
- No new API key storage model.
- No custom Windows title bar replacement.
- No Agent 6 implementation.
- No change to Agent 1 planning algorithms beyond exposing existing normal/deep mode selection through the app.

## Assumptions
- CustomTkinter remains the UI framework.
- Windows is primary target.
- `Segoe UI` exists on Windows.
- Linux EDA workstations are future targets, so font fallback must be runtime-resolved.
- `Cascadia Code` is preferred; `Consolas` or another mono fallback is accepted.
- Existing app safety behavior is more important than decorative animation.
- If backend runner does not yet expose a planning-mode CLI arg, V5.4 may add only the minimal explicit arg required for app selection, without changing Agent 1 decision logic.
