# Security Policy

## Supported Branch

Security fixes target `main`. Active feature work should happen on `codex/*` branches and merge through review.

## Reporting

If you find a vulnerability, avoid posting secrets or exploit details in public issues. Use GitHub private vulnerability reporting if it is enabled for the repository. If it is not available, open a minimal issue that says a private security report is needed, without including sensitive details.

## Secret Handling

CoreWeaver must never commit or publish:
- API keys, bearer tokens, passwords, or credential files.
- `codex_api.local.json`, `.env`, `.env.*` except `.env.example`.
- `_private/`, `.swarm/`, `outputs/`, `runs/`, SQLite checkpoints, or generated debug bundles.

Trace, replay, benchmark, and evidence artifacts must stay redacted and safe to review.

## Security Gates

Before publishing changes, run:

```powershell
python scripts/harness_check.py --json
python -m pytest -q tests
```

The harness secret scan and machine-readable `.rules/` checks are blocking gates for release-quality work.
