# GitHub Publishing Checklist

Use this before pushing the repository to a public or shared remote.

## Must Stay Local

- `codex_api.local.json`
- `studio/settings.json`
- `.env`
- `.swarm/`
- `outputs/`
- `swarm_full_rerun_*/`
- `*.sqlite`
- `studio/frontend/node_modules/`
- `studio/frontend/dist/`
- generated EDA outputs such as `*.sof`, `*.vcd`, `*.fst`, `*.wlf`
- `_private/`
- `PLANS.md`
- `docs/exec-plans/`
- internal plan, upgrade, task, roadmap, and idea documents

## Public Files To Keep

- `codex_api.example.json`
- `studio/settings.example.json`
- `.env.example`
- `studio/frontend/package.json`
- `studio/frontend/package-lock.json`
- source, tests, docs, scripts, and product specs
- public docs only; private implementation plans must stay local

## Pre-Push Audit

Run from the repo root:

```powershell
git add -n .
git status --short --ignored
git ls-files | rg -i '(^PLANS\.md$|^docs/exec-plans/|^docs/.*(PLAN|UPGRADE|TASKS).*\.md$|codex_api\.local|\.env$|outputs/|sqlite|dist/|node_modules/)'
rg -n --hidden -g '!**/.git/**' -g '!**/node_modules/**' -g '!outputs/**' -g '!.swarm/**' -g '!_private/**' -g '!codex_api.local.json' "(api[_-]?key|secret|token|bearer|password|authorization|sk-)"
python -m pytest -q
npm run test --prefix studio\frontend
npm run build --prefix studio\frontend
```

Review `git add -n .` output. It must not include local secrets, generated outputs, SQLite checkpoints, dependency folders, frontend build folders, or private plans.

## Credential Setup For New Clones

Use one of these local-only methods:

```powershell
copy codex_api.example.json codex_api.local.json
python -m studio.backend.secret_admin set-owner-key
```

or set an environment variable:

```powershell
$env:SWARM_CODEX_API_KEY = "local-secret"
```

Never paste real keys into committed files.
