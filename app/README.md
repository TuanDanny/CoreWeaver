# SWARM AI STUDIO V5.0

Desktop UI for the Semiconductor Swarm AI workflow.

This Tk/CustomTkinter app is kept as the legacy desktop cockpit. New UX work lives in `studio/`.

## Run

From repo root:

```bat
app\run_app.bat
```

Or manually:

```bat
.venv_dv\Scripts\python.exe -m pip install -r app\requirements.txt
.venv_dv\Scripts\python.exe app\main_window.py
```

## Default Run Mode

V5.0 starts in demo-safe mode:

- `run_real_tools=False`
- `strict_signoff=False`
- checkpoint DB: `.swarm/app_checkpoints.sqlite`
- output root: `outputs/app_runs/<project_name>`
- local settings: copy `app/settings.example.json` to `app/settings.json` if needed; do not commit machine-local settings.

## Console Commands

- `ok`: resume current HITL pause.
- `change <text>`: resume Plan Review with a requested change.
- `stop`: kill active runner process tree.
- `clear`: clear logs.
- `help`: show command list.
- `open output`: open selected output directory.

## Runner Protocol

`app/swarm_runner.py` emits JSONL events on stdout. The UI updates the Pipeline Bar only from `stage` events. Human-readable logs never drive control state.

## Smoke Checks

```bat
.venv_dv\Scripts\python.exe -m py_compile app\main_window.py app\swarm_runner.py
.venv_dv\Scripts\python.exe app\swarm_runner.py --help
```
