# Harness Engineering

## Purpose
CoreWeaver uses harness-first development: build the environment that makes agents effective before adding the agent core. This file is the public system record for the clean rebuild.

## Required Harness Parts
- Repo-local knowledge map: `AGENTS.md`, `ARCHITECTURE.md`, and `docs/`.
- Persistent state: `feature_list.json`, `progress.md`, and `session-handoff.md`.
- Strict boundaries: layer checks and scope contracts.
- Observable runtime: JSONL trace, raw issues, metrics, replay bundles.
- Review loop: gates, benchmark cases, negative tests, and HITL blocks.
- Entropy control: secret scan, ignored private plans, no generated clutter in source.
- Machine-readable policy: `.rules/*.rule` JSON files run through the deterministic rule engine.
- Skeleton-first core: config, adapter boundary, artifact layout, registry, mock LLM, and benchmark runner existed before Agent1 logic.
- True-swarm core: Agent1 runtime now runs behind `mock_swarm` and `local_llm` profiles while preserving adapter and trace gates.
- Package-first layout: every core capability must live behind package boundaries with local tests and public adapter exports.
- Source-root layout: project internals and core packages live under `src/` so the public repo root stays clean.
- ADR 0001 records package-first as a permanent design decision.

## Reference Doctrine vs CoreWeaver Customization
Reference documents are doctrine inputs, not implementation blueprints to copy literally.
CoreWeaver follows their harness, tool, eval, safety, and production lessons, then builds its own semiconductor architecture workflow.
CoreWeaver-specific strategies must stay pluggable behind package boundaries.
Examples include `cluster_strategy`, `reasoning_loop`, `challenge_policy`, `signoff_gate`, and future Agent1 council policies.
Custom clustering ideas may guide swarm routing, but they must remain replaceable modules instead of hardwired behavior.

## Framework-First Core Contract
Message-first runtime is mandatory before Agent1 reasoning.
Every model/tool call must go through adapters.
No real Principal/Middle/Leaf reasoning may be implemented before the framework gate passes.
The framework gate requires typed messages, async event stream, hook chain, bounded loop, scheduler, adapters, safety skeleton, replay, and Studio skeleton smoke.
AgentScope is a reference pattern only; CoreWeaver must not depend on AgentScope or copy its domain logic.

## Agent1 True Swarm Contract
Agent1 true swarm must keep Principal, Middle Manager, and Leaf Expert work behind package boundaries.
Default Studio execution uses `mock_swarm` for deterministic no-secret UAT; `local_llm` uses an OpenAI-compatible adapter.
All expert work goes through `ModelRouter`; no expert may call provider APIs directly.
Blackboard writes remain append-only, challenge rounds are capped, unresolved blockers require HITL, and Agent2 handoff is blocked unless signoff passes.
Benchmark cases must include hard inputs, ambiguity, non-design chat, conflict hard caps, security mutations, safety mutations, and handoff-blocker mutations.
Agent2 handoff consumers must validate `ready`, empty blockers, and a passing signoff certificate; file existence alone is never sufficient.
`local_llm` must remain behind `ModelRouter`; fake-client structured-output tests are the credential-free acceptance gate, while live endpoint quality is optional follow-up work.

## Done Means
- `python -m pytest -q tests` passes.
- `python scripts/harness_check.py --json` passes.
- `python scripts/run_benchmarks.py --cases benchmarks/cases --json` passes.
- New agent code has typed contracts, trace events, replay support, and tests.
- Debug artifacts never include raw secrets.
- New harness policy has a `.rule` file and unit coverage.
- Public smoke/mutation benchmarks pass at or above 90%; datasheet-backed private cases can be added later without public plan leakage.
- New core capability is rejected if it cannot be tested/debugged as a package-level unit.
