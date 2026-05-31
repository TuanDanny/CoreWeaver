# Harness Review Checklist

Use this before adding agent core logic.

## Architecture
- New module follows `types -> config -> repo -> service -> runtime -> ui`.
- Cross-domain dependency goes through provider/adapter.
- Scope contract names allowed and forbidden paths.
- Core/agent/tool/debug additions are package-shaped, importable, and testable without launching Studio.

## Observability
- Every long-running step emits trace events.
- Failures become `DebugIssue`.
- Replay bundle can reconstruct run state.
- `progress.md` and `session-handoff.md` remain accurate at session boundaries.

## Safety
- Secret scan passes.
- Raw prompts or credentials are not logged.
- Blocker issues prevent handoff.
- `.rules/` changes are deterministic JSON, not executable code.
- New policy uses known predicates/actions or adds tests for any new ones.

## Testing
- Unit tests include negative cases.
- Harness self-check passes.
- `init.sh` or `init.ps1` can run the baseline checks.
- Benchmark case added for new behavior.
