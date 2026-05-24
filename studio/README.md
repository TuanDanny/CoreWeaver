# SWARM AI STUDIO V6.5

Local web cockpit for Semiconductor Swarm.

## Run

```powershell
studio\run_studio.bat
```

Backend:
- FastAPI on `http://127.0.0.1:8000`
- WebSocket on `ws://127.0.0.1:8000/ws/runs/current`
- Job API on `http://127.0.0.1:8000/api/jobs`

Frontend:
- Vite React on `http://127.0.0.1:5173`

## Safety
- Core `semiconductor_swarm/` stays unchanged.
- Runner remains `app/swarm_runner.py`.
- API key stays in `codex_api.local.json` and is never returned raw.
- `studio/settings.json` is local-only. Use `studio/settings.example.json` as the public template.
- Web Settings only selects credential refs. Rotate the owner key locally with:

```powershell
.venv_dv\Scripts\python.exe -m studio.backend.secret_admin set-owner-key
```

- Artifact preview is sandboxed to `outputs/` or the active output directory.
- WebSocket uses heartbeat ping and local-origin checks.
- Logs are batched and rendered with a capped UI store.

## Job Queue
- `POST /api/jobs` creates queue-backed jobs.
- Supported V1 job types: `agent1_plan_draft`, `agent2_rtl_draft`, `full_swarm_run`, `debug_bundle`.
- Queue backend is Python in-process for V1.
- Redis/BullMQ remains future adapter work; the API shape is already isolated.
- Run APIs still work for normal Start, Stop, Approve, and Resume.

## GitHub Hygiene
- Commit `package.json` and `package-lock.json`.
- Do not commit `node_modules/`, `dist/`, `.swarm/`, `outputs/`, SQLite checkpoints, or local API settings.
- Run `npm run test --prefix studio\frontend` before publishing UI changes.
