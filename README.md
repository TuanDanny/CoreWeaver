# CoreWeaver

[![Harness](https://github.com/TuanDanny/CoreWeaver/actions/workflows/harness.yml/badge.svg)](https://github.com/TuanDanny/CoreWeaver/actions/workflows/harness.yml)

CoreWeaver is an agent-first semiconductor architecture harness. It converts hardware requirements into typed, traceable, replayable architecture contracts before any downstream RTL generation is allowed to proceed.

The project is built around a harness-first rule: contracts, gates, traces, replay bundles, safety checks, and Studio integration come before swarm depth.

## What It Does

- Runs Agent1 architecture planning through deterministic `mock_swarm` and optional `local_llm` profiles.
- Produces architecture plans, signoff evidence, replay bundles, trace validation, and Agent1-to-Agent2 handoff contracts.
- Blocks Agent2 draft work unless Agent1 handoff is ready, blocker-free, and backed by passing signoff evidence.
- Provides a local Studio shell with FastAPI backend and Vite React frontend.
- Keeps private plans, local API keys, generated outputs, and run artifacts out of Git.

## Current Status

CoreWeaver is in active harness and Agent1 hardening. Public benchmark cases are deterministic and credential-free. Live LLM quality is intentionally optional and is not required for the main regression gates.

Implemented:
- Framework-first runtime rails and package boundaries.
- Agent1 true-swarm flow behind `mock_swarm` and `local_llm`.
- G00-G12 signoff, safety blockers, replay bundles, evidence reports, and benchmark evidence gates.
- Studio job/runtime shell and Agent1 handoff validation.

Not implemented yet:
- Agent2 RTL execution after handoff.
- Datasheet-backed private benchmark suite.
- Arbitrary mid-run resume-from-checkpoint.

## Quick Start

```powershell
git clone https://github.com/TuanDanny/CoreWeaver.git
cd CoreWeaver
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pytest pydantic fastapi httpx python-multipart
python -m pytest -q tests
```

Run the full public harness gates:

```powershell
python -m pytest -q tests
python scripts/harness_check.py --json
python scripts/run_benchmarks.py --cases benchmarks/cases --json
```

Run Studio locally:

```powershell
studio\run_studio.bat
```

Studio defaults:
- Backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5173`

## Optional Gemini Setup

CoreWeaver does not require live LLM credentials for normal tests. For local live-provider experiments, keep secrets outside Git.

```powershell
$env:GEMINI_API_KEY=""
$env:COREWEAVER_MODEL_ENDPOINT="https://generativelanguage.googleapis.com/v1beta/openai"
$env:COREWEAVER_MODEL="gemini-flash-latest"
python scripts/gemini_smoke_test.py
```

`codex_api.local.json`, `.env`, `.swarm/`, `outputs/`, and `_private/` are intentionally ignored.

## Repository Map

- `src/coreweaver/`: core framework, Agent1 runtime, contracts, adapters, safety, debug, and orchestration.
- `studio/`: local web shell and backend job/runtime tracking.
- `benchmarks/`: public deterministic benchmark cases.
- `tests/`: harness, runtime, Studio, benchmark, replay, signoff, and safety regression tests.
- `docs/`: architecture, design, governance, and durable AI context.
- `.rules/`: machine-readable harness and safety rules.
- `_private/plans/`: local-only private plans, ignored by Git.

Start with:
- `AGENTS.md`
- `docs/AI_CONTEXT.md`
- `ARCHITECTURE.md`
- `docs/HARNESS_ENGINEERING.md`
- `docs/REPO_MAP.md`

## Development Rules

- Do not work directly on `main`; use a `codex/*` branch.
- Do not commit private plans, credentials, generated outputs, Studio build output, or local settings.
- Keep all project internals under `src/`.
- Keep model and tool calls behind adapters.
- Run pytest, harness check, and benchmark gates before publishing changes.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for branch, test, review, and safety expectations.

## Security

See [SECURITY.md](SECURITY.md). Never include API keys, bearer tokens, passwords, or secret-like values in traces, debug bundles, replay artifacts, benchmark results, issues, or pull requests.

## License

No public license has been selected yet. All rights are reserved until the repository owner adds a license.
