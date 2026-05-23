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

## Public Files To Keep

- `codex_api.example.json`
- `studio/settings.example.json`
- `.env.example`
- `studio/frontend/package.json`
- `studio/frontend/package-lock.json`
- source, tests, docs, scripts, and product specs

## Pre-Push Audit

Run from the repo root:

```powershell
git add -n .
git status --short --ignored
rg -n --hidden -g '!**/.git/**' -g '!**/node_modules/**' -g '!outputs/**' -g '!.swarm/**' -g '!codex_api.local.json' "(api[_-]?key|secret|token|bearer|password|authorization)"
python -m pytest -q
npm run test --prefix studio\frontend
npm run build --prefix studio\frontend
```

Review `git add -n .` output. It must not include local secrets, generated outputs, SQLite checkpoints, dependency folders, or frontend build folders.

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
