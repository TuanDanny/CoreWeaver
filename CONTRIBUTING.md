# Contributing

Thanks for helping make CoreWeaver sturdier. This repo is harness-first: preserve contracts, traceability, replayability, and safety gates before adding new agent behavior.

## Workflow

1. Create a branch named `codex/<short-topic>`.
2. Read the required context files listed in `AGENTS.md`.
3. Keep private plans in `_private/plans/` and never commit them.
4. Keep project internals under `src/`.
5. Update `session-handoff.md` with goal, branch, files changed, tests run, risks, and reviewer notes.
6. Open a pull request; do not merge unless a human explicitly asks.

## Required Checks

Run these before publishing a branch:

```powershell
python -m pytest -q tests
python scripts/harness_check.py --json
python scripts/run_benchmarks.py --cases benchmarks/cases --json
```

For Studio/frontend changes, also run:

```powershell
npm run test --prefix studio/frontend
npm run build --prefix studio/frontend
```

## Safety Rules

- No raw API keys, bearer tokens, passwords, or secret-like values in code, traces, debug bundles, replay artifacts, benchmark output, issues, or PRs.
- Do not commit `codex_api.local.json`, `.env`, `.swarm/`, `outputs/`, `runs/`, or `_private/`.
- Do not bypass Agent1 signoff or Agent2 handoff gates.
- Do not add direct provider calls inside agents; route model/tool access through adapters.

## Review Expectations

Pull requests should state:
- What changed.
- Which gates were run.
- Any known risks or intentionally deferred work.
- Whether behavior affects harness contracts, Studio, Agent1, benchmarks, or local-only tooling.
