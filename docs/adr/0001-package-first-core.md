# ADR 0001: Package-First Core

## Status
Accepted

## Context
CoreWeaver will rebuild the Agent core over many sessions. Long context windows, compaction, and agent handoff can cause implementation intent to be forgotten. If the package boundary only lives in chat, future work can drift into tangled modules that are hard to debug.

## Decision
All core capabilities must be package-shaped before they contain substantial logic.

Required pattern:

- Put each capability behind a package/module boundary.
- Expose a small public adapter or registry entry.
- Keep Studio as a caller, not an owner of core internals.
- Add local tests for each capability.
- Add trace/debug/replay hooks when the capability affects runtime behavior.
- Add or update `.rules/` when the capability introduces policy.

Disallowed pattern:

- Mixing Agent logic into Studio UI/backend internals.
- Hiding cross-domain behavior in one large file.
- Adding runtime behavior without tests or debug path.
- Depending on chat context as the only source of design intent.

## Consequences
This costs more upfront files and small adapters, but it makes future Agent1, Agent2, benchmark, debug, and signoff work easier to test and replace. If Codex forgets context, `AGENTS.md`, `.rules/`, and this ADR restore the intent.
