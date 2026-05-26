---
title: Agent1 System Architect Product Spec
status: active
owner: agent1
type: product-spec
last_reviewed: 2026-05-17
source_of_truth: true
related_tests:
  - tests/test_agent1.py
---

# Agent1 System Architect Product Spec

## Mission
Convert user requirements into stable architecture/spec artifacts that downstream agents can consume without guessing.

## Responsibilities
- Parse requirements into system architecture through an AI expert council plus deterministic guardrails.
- Preserve explicit user intent such as CPU width, bus protocol, and peripherals; never silently rewrite unsupported intent into a convenient template.
- Assess downstream Agent 2/3/4/5 capability before releasing contracts.
- Define modules, interfaces, memory map, clocks, resets, and interrupts.
- Produce deterministic PPA and bandwidth estimates using tools.
- Lock downstream contracts for RTL/DV/formal/physical stages.
- Emit debug and self-check reports when supported.
- For V7.2 and later, produce or block on an industrial signoff certificate before Agent2 handoff.

## Inputs
- User requirements.
- Optional existing `spec.json` or architecture JSON.
- Prompt contracts from `docs/prompts/index.md`.
- Tool outputs from PPA/bandwidth calculators.

## Outputs
- Architecture/spec JSON.
- AI requirement analysis and expert council trace.
- Capability assessment and compatibility strategy.
- Module inventory and interface contracts.
- Address map/register plan when applicable.
- PPA/bandwidth estimates with provenance.
- Debug report and self-check report when applicable.
- V7.2 signoff artifacts when enabled: finding records, waiver records, benchmark case/result records, and `agent1_final_signoff_certificate.json`.
- V7.2 signoff evidence/gate report when enabled: current artifact hashes, trace issue refs, gate results for `G00-G12`, and deterministic finding list.

## Contract Fields
- Project name and target profile.
- Module list with names, responsibilities, and dependencies.
- Clocks/resets and clock domain notes.
- Bus/interface definitions.
- Register/address map if software-visible state exists.
- Performance and area/power estimate metadata.

## Hard Constraints
- Numeric estimates must come from tools.
- Never invent PPA numbers without provenance.
- Downstream contracts must stay stable for Agent2-5.
- Ambiguity must become explicit assumption or question.
- Unsupported downstream capability must become explicit bridge strategy or HITL/capability gap.
- Generated plans must pass raw-requirement/extraction/spec/markdown consistency checks.
- Keep behavior aligned with `tests/test_agent1.py`.
- Agent2 release must be gated by the Agent1 signoff certificate when signoff is enabled.

## Failure Modes
- Ambiguous requirements.
- Tool provenance missing.
- Contract drift with downstream agents.
- Overspecified architecture that blocks RTL generation.
- Address/register collision.
- Failed, stale, waived-by-accident, or benchmark-unproven Agent1 output reaching Agent2.

## Test Coverage
- `tests/test_agent1.py`
- `tests/test_agent1_v72_signoff_models.py`
- `tests/test_agent1_v72_signoff_engine.py`
