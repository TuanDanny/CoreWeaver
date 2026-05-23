# Agent 1 V4 Modern Debug Upgrade Plan

> Status: DRAFT FOR CHIEF ENGINEER REVIEW  
> Scope: Agent 1 only — System Architect planning, validation, debug, audit, and downstream contract hardening.  
> Baseline: `docs/semiconductor_swarm_ai.md` v3.0, current Agent 1 V3.7 schema/committee implementation.  
> Prime directive: AI operates tools and emits auditable reasoning. AI must not self-calculate PPA, bandwidth, or EDA metrics.

---

## 1. Executive Goal

Upgrade Agent 1 from a working hierarchical architecture planner into a production-grade semiconductor planning agent that is:

- deterministic where it must be deterministic;
- auditable for every LLM/tool/validator decision;
- replayable without LLM access;
- debuggable at node-level granularity;
- hardened against schema drift, hallucinated numeric data, stale repair loops, and downstream contract mismatch;
- ready for modern agentic EDA workflows using traceability, strict typed contracts, fuzzing, and guarded retrieval.

Agent 1 V4 must still preserve all current hard rules:

- Codex architecture reasoning evidence remains mandatory.
- PPA uses only `calculate_ppa()`.
- Bandwidth uses only `calculate_bandwidth()`.
- APB slave pinout is locked.
- Agent 2 cannot rename ports.
- Formal-first remains required.
- HITL remains required when confidence or repair convergence fails.

---

## 2. Planning Prompt For Implementation Mini-Agents

Use this prompt to dispatch mini-agents for design, implementation, and verification.

```markdown
# SYSTEM PROMPT — Agent 1 V4 Upgrade Planner

You are a senior semiconductor EDA platform architect, agentic workflow engineer, and verification lead.

Your job is to upgrade Agent 1 only. Do not modify Agent 2/3/4/5 contracts unless a compatibility shim is added and tests prove no regression.

You must follow `docs/semiconductor_swarm_ai.md` as the source-of-truth system intent:
- AI is a tool operator, not a calculator.
- All numeric PPA and bandwidth values must come from deterministic tools.
- Agent 1 emits strict JSON spec, locked interfaces, memory map, constraints, IP blocks, clock/reset domains, and downstream handoff contracts.
- Human-in-the-loop must be triggered for unsafe convergence, ambiguous architecture, or repeated repair.

Design and implement Agent 1 V4 with these capabilities:

1. Strict typed schema gate
   - Replace shallow manual validation with Pydantic v2 or JSON Schema-backed strict validation.
   - Validate deep semantic constraints: address alignment, range overlap, reset polarity, register access semantics, APB pinout, clock domains, numeric provenance, downstream artifact consistency.
   - Export machine-readable schema to `reports/agent1/agent1_v4_schema.json`.

2. Replayable debug bundle
   - Every Agent 1 run must emit `reports/agent1/replay_bundle.json`.
   - Bundle must include requirement, project name, sanitized project name, config, prompt hash, response hash, tool input/output hashes, spec hash before/after repair, validator decisions, revision history, schema version, git commit if available, and package versions.
   - Add replay mode that can re-run validation/repair/schema checks without calling Codex.

3. OpenTelemetry-style trace JSONL
   - Emit one span per micro-expert, Codex call, tool call, validator, repair, schema gate, HITL decision.
   - Required span fields: `trace_id`, `span_id`, `parent_span_id`, `node`, `event`, `start_ts`, `end_ts`, `duration_ms`, `input_hash`, `output_hash`, `decision`, `severity`, `error`, `artifacts`.
   - Store as `reports/agent1/trace.jsonl`.

4. Immutable tool-call ledger
   - Record all deterministic tool invocations.
   - Required fields: tool name, tool version/hash, input args, input hash, output object, output hash, timestamp, caller node.
   - Schema validation must reject numeric estimates lacking matching ledger entries.

5. Agent 1 debug CLI
   - Add CLI entrypoint:
     `python -m semiconductor_swarm.agents.agent1_planning.debug --requirement "..." --project-name demo --dump-trace`
   - Add replay mode:
     `python -m semiconductor_swarm.agents.agent1_planning.debug --replay reports/agent1/replay_bundle.json`
   - CLI must print graph route, validator decisions, repair diffs, final schema status, and artifact paths.

6. Contract test generator
   - From Agent 1 spec, generate downstream contract tests or contract manifests for Agent 2/3/5.
   - Must include APB port names, memory-map addresses, register access policy, IRQ clear semantics, formal-first property intent, reset behavior.
   - Store `reports/agent1/downstream_contract_manifest.json`.

7. Property-based and metamorphic tests
   - Use Hypothesis or a lightweight internal fuzzer.
   - Fuzz project names, requirement variants, memory maps, register metadata, access policies.
   - Metamorphic invariants: whitespace/case language changes must not break core architecture; adding frequency must only alter frequency-dependent fields; APB pinout must never mutate.

8. Mutation testing for validators
   - Mutate base addresses, sizes, register access, IRQ clear semantics, sensitive register protections, QoS timeout, CDC data.
   - Validators must catch unsafe mutations.

9. Guarded Golden Micro-Patterns RAG V4
   - Optional but design-ready.
   - Retrieval source must be a curated pattern DB only, not raw SV LRM.
   - Agent 1 may attach `pattern_refs` to IP blocks for Agent 2.
   - Missing pattern must not block baseline flow; low-confidence retrieval must trigger HITL or proceed without RAG.

10. Differential review mode
   - Codex proposes architecture reasoning.
   - A separate reviewer model or deterministic critic reviews risk only.
   - Reviewer cannot generate final spec directly.
   - Major disagreement triggers HITL with conflict report.

Deliverables must include docs, tests, and proof commands. Do not claim success unless `python -m pytest -q` passes.
```

---

## 3. Current Baseline Observations

Current Agent 1 already has strong foundations:

- hierarchical micro-expert concept;
- V3/V3.5/V3.7 super committee naming;
- mandatory Codex evidence;
- deterministic `generate_architecture_spec()`;
- mandatory `calculate_ppa()` and `calculate_bandwidth()` calls;
- APB pinout lock;
- Mermaid diagrams;
- SystemRDL, C header, driver stub, cocotb register model artifacts;
- semantic validators for memory ranges, safety/security, HWSW, RDL/header, RDL/DV, clock/power, QoS, DFT/IO;
- repair loop fixes for persisted repaired spec, route-back-to-validator, stale reject handling;
- current tests pass.

V4 should not replace this foundation. V4 should wrap it in stronger contracts, traces, replay, and adversarial testing.

---

## 4. Sharp Upgrade Ideas

### 4.1 Pydantic V2 Strict Schema Layer

#### Problem

Manual schema checks catch missing top-level keys but are weaker for deep typed invariants.

#### Upgrade

Create strict models:

- `Agent1SpecV4`
- `RequirementModel`
- `PpaEstimateModel`
- `BandwidthEstimateModel`
- `ToolProvenanceModel`
- `MemoryMapModel`
- `RegisterModel`
- `BusTopologyModel`
- `ClockDomainModel`
- `ApbInterfaceModel`
- `FirmwareContractModel`
- `SafetySecurityModel`
- `DownstreamContractModel`

Recommended checks:

- project name matches RTL-safe regex: `^[a-z_][a-z0-9_]*$`;
- APB protocol fixed to `APB`;
- APB slave signal list exactly equals locked contract;
- base/size parse as positive integers;
- base aligned to 4KB;
- address ranges do not overlap;
- register offsets are aligned to 4 bytes;
- register width is positive and normally one of `1, 8, 16, 32, 64, 128`;
- `irq_status` must use W1C/read_clear and have enable/mask companion;
- sensitive registers require privileged/write_once/lock/zeroize/no-readback policy;
- `formal_first == True`;
- numeric PPA/bandwidth must have ledger and provenance match.

#### Expected Result

Agent 1 V4 rejects malformed specs with exact field paths and actionable errors, before Agent 2 receives anything.

#### Must Achieve

- `validate_agent1_v4_spec_schema(spec)` gives deterministic errors.
- JSON schema export exists.
- Existing V3.7-compatible specs still pass after adapter/enrichment.

---

### 4.2 Replay Bundle

#### Problem

Agent failures involving LLMs are hard to reproduce. Endpoint, prompt, and model output may change.

#### Upgrade

Emit `reports/agent1/replay_bundle.json`:

```json
{
  "schema_version": "agent1_replay_v1",
  "run_id": "...",
  "trace_id": "...",
  "project_name": "demo",
  "requirement_raw": "...",
  "agent1_config": {"base_url": "http://localhost:20128/v1", "model": "cx/gpt-5.5"},
  "codex": {"prompt_hash": "...", "response_hash": "...", "evidence": {}},
  "tool_ledger_hash": "...",
  "spec_hashes": {"initial": "...", "after_repair": "...", "final": "..."},
  "validator_decisions": [],
  "revision_history": [],
  "artifact_manifest": {},
  "environment": {"python": "...", "platform": "...", "git_commit": "..."}
}
```

#### Expected Result

Any future bug report can attach one JSON file and replay validation/repair without LLM access.

#### Must Achieve

- Replay mode runs validators and schema gate from bundle.
- Replay result says PASS/FAIL and diff from original final state.
- Bundle never stores secrets or API keys.

---

### 4.3 OpenTelemetry-Style Trace JSONL

#### Problem

Current debug evidence is artifact-level, not runtime span-level.

#### Upgrade

Write `reports/agent1/trace.jsonl`, one JSON object per span:

```json
{
  "trace_id": "...",
  "span_id": "...",
  "parent_span_id": "...",
  "node": "Safety_Security_vs_MemoryMap_Validator",
  "event": "validator_decision",
  "start_ts": "2026-05-16T16:00:00Z",
  "end_ts": "2026-05-16T16:00:00Z",
  "duration_ms": 3,
  "input_hash": "...",
  "output_hash": "...",
  "decision": "ACCEPT",
  "severity": "INFO",
  "error": null,
  "artifacts": ["agent1_validation_decisions.json"]
}
```

#### Expected Result

Human can answer: which node failed, what input hash it saw, how long it ran, what it emitted, and where artifacts are.

#### Must Achieve

- Trace exists for every micro-expert/validator/repair/tool call.
- Trace IDs connect all spans in a run.
- Error spans preserve exception class/message without leaking secrets.

---

### 4.4 Immutable Tool-Call Ledger

#### Problem

Existing provenance hashes numeric outputs, but input arguments and tool implementation version are not fully auditable.

#### Upgrade

Emit `reports/agent1/tool_ledger.jsonl`:

```json
{
  "tool": "calculate_ppa",
  "caller": "PPA_Bandwidth_Tool_Expert",
  "tool_version_hash": "...",
  "args": {"tech_node": "28nm", "logic_gates": 250000, "sram_kb": 256, "mac_units": 64, "freq_mhz": 100},
  "input_hash": "...",
  "output": {"power_mw": 4.37, "area_mm2": 0.748, "performance_tops": 0.0128, "tech_node": "28nm"},
  "output_hash": "...",
  "timestamp": "..."
}
```

#### Expected Result

Numeric values are provably tool-derived from known inputs.

#### Must Achieve

- Schema gate rejects numeric estimate if no matching ledger entry.
- Ledger hash appears in replay bundle.
- Tests mutate PPA output and prove mismatch is rejected.

---

### 4.5 Agent 1 Debug CLI

#### Problem

Developers need to debug Agent 1 without running full swarm.

#### Upgrade

Add module:

```text
semiconductor_swarm/agents/agent1_planning/debug.py
```

Commands:

```bash
python -m semiconductor_swarm.agents.agent1_planning.debug --requirement "edge AI camera 100MHz <500mW" --project-name demo --dump-trace
python -m semiconductor_swarm.agents.agent1_planning.debug --replay reports/agent1/replay_bundle.json
python -m semiconductor_swarm.agents.agent1_planning.debug --validate-spec reports/architecture_spec.json
```

Output must include:

- sanitized project name;
- Codex evidence status;
- tool ledger status;
- graph route;
- validator decisions;
- repair diffs;
- schema gate PASS/FAIL;
- artifact paths;
- HITL reason if any.

#### Expected Result

Agent 1 can be debugged in isolation.

#### Must Achieve

- CLI exit code `0` on pass.
- CLI exit code non-zero on schema/validator failure.
- Replay mode does not call Codex.

---

### 4.6 Downstream Contract Manifest

#### Problem

Agent 2/3/5 correctness depends on Agent 1 spec but contracts are not packaged as a focused test manifest.

#### Upgrade

Generate `reports/agent1/downstream_contract_manifest.json`:

```json
{
  "schema_version": "downstream_contract_v1",
  "project_name": "demo",
  "top_module": "demo_top",
  "interfaces": {"apb_slave": {"signals": []}},
  "memory_map": {},
  "register_access": {},
  "irq_semantics": {},
  "formal_intent": {},
  "dv_intent": {},
  "agent2_forbidden_actions": ["rename_ports", "change_register_offsets", "drop_reset"]
}
```

#### Expected Result

Downstream agents receive a crisp contract and tests can assert no drift.

#### Must Achieve

- Contract manifest generated for every Agent 1 accepted run.
- Agent 2 tests can consume it or compare against it.
- Contract hash appears in final report.

---

### 4.7 Property-Based Fuzzing

#### Problem

Example-based tests do not cover weird project names, malformed memory maps, odd registers, mixed-language requirements.

#### Upgrade

Add tests using Hypothesis or internal generators:

- project name sanitizer fuzz;
- memory map overlap fuzz;
- register access fuzz;
- APB pinout immutability fuzz;
- tool provenance mutation fuzz;
- requirement text variation fuzz.

#### Expected Result

Agent 1 rejects unsafe edge cases and normalizes safe ones.

#### Must Achieve

- `python -m pytest tests/test_agent1_fuzz.py -q` passes reliably.
- Tests are deterministic enough for CI via fixed max examples/seed.

---

### 4.8 Metamorphic Tests

#### Problem

LLM/rule planners can become unstable when wording changes but intent stays same.

#### Upgrade

Define metamorphic relations:

- English/Vietnamese equivalent camera requirement -> same `application_domain`.
- Upper/lowercase/extra spaces -> same core architecture class.
- Adding `100MHz` -> only frequency/bandwidth/PPA-related fields may change.
- Adding `<500mW` -> power constraint field must change, APB pinout must not.
- Project name change -> filenames/top module change, architecture internals remain stable.

#### Expected Result

Agent 1 becomes robust to wording noise.

#### Must Achieve

- `tests/test_agent1_metamorphic.py` exists.
- Failures print semantic diff.

---

### 4.9 Mutation Testing For Validators

#### Problem

Validators may look good but fail to catch dangerous mutations.

#### Upgrade

Create controlled spec mutators:

- overlap two blocks;
- unalign base;
- set size zero;
- drop IRQ clear semantics;
- remove sensitive register protection;
- set QoS timeout below latency;
- add multiple clocks without CDC plan;
- enable JTAG but remove JTAG pins.

Each mutation must be rejected by correct validator.

#### Expected Result

Validation strength is measurable.

#### Must Achieve

- Each validator has at least one mutation test.
- Router resolves repaired stale reject correctly.

---

### 4.10 Guarded Golden Micro-Patterns RAG V4

#### Problem

Raw LRM retrieval creates hallucination and irrelevant context risk.

#### Upgrade

Build curated micro-pattern registry:

```text
docs/patterns/pattern_apb_slave_regfile.sv
docs/patterns/pattern_irq_w1c.sv
docs/patterns/pattern_cdc_2ff_sync.sv
docs/patterns/pattern_async_fifo_gray.sv
docs/patterns/pattern_dma_descriptor_regs.sv
docs/patterns/pattern_aes_key_zeroize_regs.sv
```

Agent 1 attaches pattern refs only:

```json
"pattern_refs": [
  {"block": "control_regs", "pattern_id": "pattern_apb_slave_regfile", "confidence": 0.96},
  {"block": "interrupt_ctrl", "pattern_id": "pattern_irq_w1c", "confidence": 0.93}
]
```

#### Expected Result

Agent 2 gets safe pattern anchors without broad hallucination-prone docs.

#### Must Achieve

- Only curated pattern IDs are allowed.
- Missing pattern does not break baseline flow.
- Low confidence triggers HITL or warning.

---

### 4.11 Differential Review Mode

#### Problem

Single LLM reasoning may miss architecture risks.

#### Upgrade

Run separate review pass:

- primary Codex: proposes reasoning;
- reviewer model or deterministic critic: reviews risk only;
- reviewer cannot emit final spec;
- disagreement report goes to HITL.

Conflict examples:

- Codex selects split clock but no CDC plan.
- Codex proposes DMA but no security/privilege policy.
- Codex adds JTAG but no IO pins.

#### Expected Result

Single-model blind spots decrease.

#### Must Achieve

- Conflict report artifact exists.
- HITL triggers on BLOCKER disagreement.
- No final spec accepted solely from reviewer text.

---

## 5. Required Deliverables

### 5.1 Code Deliverables

- `semiconductor_swarm/agents/agent1_planning/schema_v4.py`
- `semiconductor_swarm/agents/agent1_planning/tracing.py`
- `semiconductor_swarm/agents/agent1_planning/replay.py`
- `semiconductor_swarm/agents/agent1_planning/debug.py`
- `semiconductor_swarm/agents/agent1_planning/tool_ledger.py`
- `semiconductor_swarm/agents/agent1_planning/contract_manifest.py`
- optional: `semiconductor_swarm/agents/agent1_planning/pattern_registry.py`

### 5.2 Report Deliverables

- `reports/agent1/trace.jsonl`
- `reports/agent1/tool_ledger.jsonl`
- `reports/agent1/replay_bundle.json`
- `reports/agent1/agent1_v4_schema.json`
- `reports/agent1/downstream_contract_manifest.json`
- `reports/agent1/semantic_diff.json`
- optional: `reports/agent1/differential_review.md`

### 5.3 Test Deliverables

- `tests/test_agent1_schema_v4.py`
- `tests/test_agent1_replay.py`
- `tests/test_agent1_trace.py`
- `tests/test_agent1_tool_ledger.py`
- `tests/test_agent1_contract_manifest.py`
- `tests/test_agent1_fuzz.py`
- `tests/test_agent1_metamorphic.py`
- `tests/test_agent1_validator_mutations.py`

---

## 6. Acceptance Criteria

Agent 1 V4 is accepted only if all criteria below pass.

### Functional Criteria

- Agent 1 still emits existing required spec keys.
- Agent 2/3/4/5 existing tests still pass.
- Codex evidence remains mandatory.
- PPA/bandwidth remain tool-only.
- APB pinout remains exact and immutable.
- Repair loop still persists repaired spec and routes back to rejecting validator.
- Stale reject history does not poison final router decision.

### Debug/Audit Criteria

- Every accepted run emits replay bundle.
- Every accepted run emits trace JSONL.
- Every tool call appears in immutable ledger.
- Every numeric estimate has matching ledger/provenance.
- Replay mode revalidates final spec without Codex.
- Debug CLI prints node-level result and exits correctly.

### Validation Criteria

- Overlapping memory map rejected.
- Unaligned base rejected.
- Invalid size rejected.
- Sensitive register without protection rejected.
- IRQ status without W1C/read_clear rejected.
- Multi-clock without CDC plan rejected.
- QoS latency/timeout contradiction rejected.
- JTAG planned without JTAG pins rejected.

### Test Criteria

Commands must pass:

```bash
python -m pytest tests/test_agent1.py -q
python -m pytest tests/test_prompt_contracts.py -q
python -m pytest tests/test_agent1_schema_v4.py -q
python -m pytest tests/test_agent1_replay.py -q
python -m pytest tests/test_agent1_trace.py -q
python -m pytest tests/test_agent1_tool_ledger.py -q
python -m pytest tests/test_agent1_contract_manifest.py -q
python -m pytest tests/test_agent1_fuzz.py -q
python -m pytest tests/test_agent1_metamorphic.py -q
python -m pytest tests/test_agent1_validator_mutations.py -q
python -m pytest -q
```

---

## 7. Implementation Order

### Phase 1 — Safe Audit Infrastructure

1. Add stable hashing helpers.
2. Add tool ledger around `calculate_ppa()` and `calculate_bandwidth()` usage.
3. Add trace JSONL writer.
4. Add replay bundle writer.
5. Add tests proving artifacts exist and contain no secrets.

Expected result: no architecture behavior change, only better evidence.

### Phase 2 — Strict Schema V4

1. Add Pydantic/JSON Schema models.
2. Add adapter from current V3.7 spec to V4 model.
3. Add deep semantic validators.
4. Export JSON schema.
5. Add mutation tests.

Expected result: unsafe specs fail with exact error paths.

### Phase 3 — Debug CLI + Replay

1. Add debug CLI.
2. Add replay mode.
3. Add semantic diff output.
4. Add tests for exit codes.

Expected result: Agent 1 can be debugged without full swarm.

### Phase 4 — Downstream Contract Manifest

1. Generate manifest from accepted spec.
2. Add contract hash to report.
3. Add tests comparing APB pins/registers/IRQ semantics.

Expected result: downstream drift becomes test-detectable.

### Phase 5 — Adversarial Testing

1. Add property-based fuzz tests.
2. Add metamorphic tests.
3. Add validator mutation tests.
4. Tune examples/seed for stable CI.

Expected result: edge-case bugs surface before production use.

### Phase 6 — Optional RAG/Differential Review

1. Add curated pattern registry.
2. Add pattern refs to spec.
3. Add low-confidence HITL.
4. Add differential review conflict report.

Expected result: better architecture guidance without unsafe raw-document RAG.

---

## 8. Risk Controls

### Risk: Scope creep breaks downstream agents

Control:

- Keep existing spec fields.
- Add new fields optional or adapter-backed.
- Run full regression after each phase.

### Risk: Pydantic dependency unavailable

Control:

- Prefer existing dependency if present.
- If not, use `jsonschema` or internal validator first.
- Do not block V4 plan on dependency if project policy avoids installs.

### Risk: Trace/replay leaks secrets

Control:

- Never store API keys.
- Hash prompts/responses when needed.
- Store endpoint/model only, not credentials.

### Risk: Fuzz tests flaky

Control:

- Fixed seed.
- Bounded examples.
- No network calls.
- No Codex calls.

### Risk: RAG adds hallucination risk

Control:

- Curated patterns only.
- Pattern IDs only in spec.
- Low confidence HITL.
- No raw LRM retrieval.

---

## 9. Definition Of Done

Agent 1 V4 is done when:

1. Full regression passes.
2. Accepted Agent 1 run emits:
   - spec;
   - plan markdown;
   - trace JSONL;
   - tool ledger;
   - replay bundle;
   - JSON schema;
   - downstream contract manifest.
3. Replay mode validates accepted run without Codex.
4. Debug CLI isolates Agent 1 failures.
5. Mutation tests prove validators catch unsafe memory/security/clock/QoS/DFT cases.
6. Fuzz/metamorphic tests prove stability under noisy inputs.
7. No numeric estimate can enter final spec without deterministic tool ledger proof.
8. No downstream agent receives ambiguous or unlocked interface names.

---

## 10. Expected End State

After this upgrade, Agent 1 becomes a modern EDA planning front-end:

- It plans architecture with LLM assistance.
- It computes numbers only through deterministic tools.
- It validates every handoff with strict typed contracts.
- It self-repairs known semantic issues.
- It escalates unsafe ambiguity to HITL.
- It records enough evidence to replay and debug any failure.
- It gives downstream agents testable contracts instead of loose prose.

Target statement:

```text
Agent 1 V4 can generate, validate, repair, trace, replay, and prove a semiconductor architecture spec before any RTL is generated.
```
