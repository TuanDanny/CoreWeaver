---
title: AGENT_2_V3 — Semantic RTL Closure Upgrade Plan
status: superseded
owner: semiconductor-swarm
type: exec-plan
last_reviewed: 2026-05-20
source_of_truth: false
supersedes:
  - docs/exec-plans/superseded/AGENT_2_V2_SWARM_OF_EXPERTS_PLAN.md
superseded_by: docs/exec-plans/active/AGENT_2_V4_INDUSTRIAL_RTL_SIGNOFF_PLAN.md
related_tests:
  - tests/test_agent2.py
  - tests/test_swarm_graph.py
  - tests/test_prompt_contracts.py
  - tests/test_real_tool_detection.py
  - tests/test_real_formal_tools.py
  - tests/test_real_quartus_tools.py
---

# AGENT_2_V3 — Semantic RTL Closure Upgrade Plan

## 1. Version intent

Agent 2 V3 upgrades Agent 2 from a deterministic handoff-grade swarm into a semantic RTL closure swarm.

V2 proved that Agent 2 can orchestrate 56 deterministic specialist subagents, preserve public compatibility, emit traceable handoff artifacts, and keep regression green.

V3 does not add agents for vanity. V3 makes existing Agent 2 deeper:

- generated RTL must be indexed and semantically reviewed;
- tool-available lint/synthesis/formal smoke must become meaningful gates;
- handoff artifacts must be schema-validated;
- repair must be finding-driven and revalidated;
- advanced stubs must move toward implementation-grade tier 1 patterns.

## 2. Compatibility contract

V3 keeps the existing public API:

```python
generate_rtl_files(spec, debug=False)
```

Normal RTL file entries keep the public schema:

```json
{
  "filename": "example.sv",
  "language": "systemverilog",
  "content": "...",
  "line_count": 123,
  "dependencies": []
}
```

Guardrails:

- Do not rename public functions unless wrappers remain.
- Do not break Agent 3, Agent 4, or Agent 5 consumers.
- Do not rename Agent 1 APB pinout or violate `APB_SLAVE_INTERFACE`.
- Do not require external EDA tools to exist on every developer machine.
- When tools are available and healthy, do not silently fallback around real RTL errors.
- Keep existing tests green through staged rollout.

## 3. Why V3 is needed

Agent 2 V2 strengths:

- 56 deterministic subagents from `A2.01` through `A2.56`.
- Ordered trace and manifest artifacts.
- Debug and handoff files for Agent 3/4/5.
- DFT/UPF/macro and advanced reliability/NoC/DSE/HLS/ECO intent artifacts.
- Full regression green at V2 close.

Agent 2 V2 weaknesses V3 must address:

| Weakness | Impact | V3 fix |
| --- | --- | --- |
| Advanced agents are mostly stub/intent. | Users may overestimate production readiness. | Promote selected stubs to implementation-grade tier 1 patterns and label remaining intent clearly. |
| Reviewers are partly token-based. | Semantic bugs can pass. | Add `RTLModuleIndex`, semantic APB/reset/width/X-prop reviewers, and tool-backed reports. |
| Repair loop is simple. | It fixes placeholders more than real RTL defects. | Add finding classification, patch recipes, diff/rollback, and revalidation. |
| Tool fallback can hide real issues. | Healthy Verilator/Yosys failures may be underweighted. | Add hard-gate `ToolHealthMatrix` with normalized severities. |
| Pattern library is small. | Generated RTL stays template-heavy. | Add golden patterns for FIFO, interrupt, timer, SRAM, SECDED, and crossbar. |
| `milestone_a.py` is too large. | Maintainability risk grows. | Refactor subagents by domain without behavior change. |
| Handoff artifact schemas are implicit. | Contract drift can break downstream agents. | Add JSON schema validation for all Agent 2 artifacts. |

## 4. Target architecture

```text
Agent1 Architecture Spec
  |
Agent2 V3 Orchestrator
  |
  +-- V2 56-agent deterministic swarm
  |
  +-- Semantic RTL Index Layer
  |     +-- module/port/param/dependency index
  |     +-- process/assignment/reset scan
  |
  +-- Tool Health and EDA Adapters
  |     +-- Verilator adapter when healthy
  |     +-- Yosys adapter when healthy
  |     +-- SymbiYosys/formal-smoke adapter when healthy
  |
  +-- Semantic Review Layer
  |     +-- APB protocol review
  |     +-- reset safety review
  |     +-- width/type review
  |     +-- X-propagation review
  |
  +-- Schema Validation Layer
  |     +-- manifest schemas
  |     +-- handoff schemas
  |
  +-- Repair V3 Loop
  |     +-- classify finding
  |     +-- choose deterministic patch recipe
  |     +-- apply bounded diff
  |     +-- revalidate
  |     +-- rollback if worse
  |
  +-- Release Gate
        +-- pass
        +-- pass_with_waivers
        +-- fail
        +-- degraded_tooling
```

## 5. New technical components

### 5.1 Semantic RTL module index

Proposed files:

```text
semiconductor_swarm/agents/agent2_rtl/semantic/
  __init__.py
  module_index.py
  findings.py
  validators.py
  apb_protocol.py
  width_reset.py
```

Target data model:

```python
@dataclass
class RTLModuleIndexEntry:
    module_name: str
    filename: str
    parameters: list[dict[str, Any]]
    ports: list[dict[str, Any]]
    instances: list[dict[str, Any]]
    always_blocks: list[dict[str, Any]]
    assigns: list[dict[str, Any]]
```

Index must extract:

- modules;
- parameters;
- ports, directions, and widths;
- simple instantiations;
- always blocks;
- continuous assignments;
- dependency edges.

Initial parser can be deterministic lightweight regex/state-machine. V3 does not require building a full SystemVerilog compiler.

### 5.2 Normalized findings

```python
@dataclass
class SemanticFinding:
    severity: str  # info|warning|error|fatal
    source: str    # static|semantic|verilator|yosys|formal|schema
    owner: str
    file: str | None
    module: str | None
    rule: str
    message: str
    suggested_fix: str | None
    evidence: dict[str, Any]
```

All reviewers and tool adapters should produce this format.

### 5.3 Tool health matrix

Proposed files:

```text
semiconductor_swarm/agents/agent2_rtl/tools/
  __init__.py
  tool_health_matrix.py
  verilator_adapter.py
  yosys_adapter.py
  symbiyosys_adapter.py
```

Tool statuses:

```text
missing
healthy
broken
degraded
```

Policy:

- `missing`: fallback allowed, record provenance.
- `healthy`: RTL errors are hard failures.
- `broken`: do not pass silently; mark `degraded_tooling`.
- `degraded`: continue only if severity policy allows.

Artifacts:

- `tool_health_matrix.json`
- `semantic_lint_report.json`
- `synthesis_smoke_report.json`
- `formal_smoke_report.json`

### 5.4 Semantic reviewers

Semantic reviewers should use `RTLModuleIndex` plus optional tool reports.

Required reviewers:

- APB protocol semantic reviewer:
  - required APB signal set;
  - direction correctness;
  - setup/access phase intent;
  - ready/error default behavior;
  - illegal address default error response.
- Reset semantic reviewer:
  - state/control registers reset coverage;
  - reset polarity consistency;
  - unreset register waiver policy.
- Width/type reviewer:
  - param width propagation;
  - obvious truncation/extension risk;
  - enum/packed struct width risk where detectable.
- X-propagation reviewer:
  - always_comb default assignment scan;
  - default case policy;
  - unsafe `'x` assignment detection.

Artifact:

- `semantic_review_report.json`

### 5.5 Schema validation

Proposed files:

```text
semiconductor_swarm/agents/agent2_rtl/schemas/
  validator.py
  rtl_manifest.schema.json
  subgraph_trace.schema.json
  formal_hooks.schema.json
  dv_hooks.schema.json
  ppa_handoff.schema.json
  dft_hooks.schema.json
  upf_manifest.schema.json
  macro_wrappers.schema.json
  fault_tolerance_manifest.schema.json
  noc_coherency_manifest.schema.json
  dse_manifest.schema.json
  hls_bridge_manifest.schema.json
  eco_intent.schema.json
```

Validation policy:

- If `jsonschema` is installed, use it.
- If not installed, use local fallback validator for required keys and basic types.
- Bad debug artifact blocks release when `debug=True`.

Artifact:

- `schema_validation_report.json`

### 5.6 Repair loop V3

Proposed files:

```text
semiconductor_swarm/agents/agent2_rtl/repair/
  __init__.py
  classifier.py
  recipes.py
  patcher.py
  rollback.py
```

Flow:

```text
SemanticFinding
  -> classify owner/rule
  -> choose deterministic recipe
  -> bounded patch
  -> emit before/after diff
  -> re-run affected checks
  -> rollback if worse
```

Initial patch recipes:

- missing always_comb default assignment;
- missing reset assignment for state/control register;
- missing APB illegal-address error default;
- missing metadata dependency entry;
- stale manifest field.

Patch guardrails:

- no whole-file rewrite by default;
- max changed lines per repair;
- max 3 repair iterations;
- rollback record if revalidation worsens;
- repair trace must include finding ID, recipe ID, diff, and validation result.

### 5.7 Pattern library expansion

New patterns:

```text
patterns/apb_register_file_w1c.sv
patterns/sync_fifo_verified.sv
patterns/interrupt_controller_w1c_sticky.sv
patterns/apb_timer_counter.sv
patterns/sram_controller_latency_ready.sv
patterns/secded_39_32_encoder_decoder.sv
patterns/simple_apb_crossbar_1m_ns.sv
```

Each pattern must have manifest metadata:

```yaml
id: sync_fifo_verified
version: 1.0
owners:
  - A2.15 FIFO Writer
  - A2.28 Synthesizability Reviewer
  - A2.31 Formal Hook Agent
parameters:
  - WIDTH
  - DEPTH
interfaces:
  - clock_reset
  - push_pop
lint_status: required
formal_smoke: required
```

### 5.8 Advanced tier 1 implementation upgrades

V3 should upgrade selected advanced features from stub-only to implementation-grade tier 1.

| Agent | V2 state | V3 tier 1 target |
| --- | --- | --- |
| A2.52 Fault Tolerance | ECC/TMR manifests and stubs | 32-bit SECDED encoder/decoder wrapper with syndrome/correct/detect signals. |
| A2.53 NoC/Coherency | Router/crossbar skeleton intent | Simple 1-master N-slave APB crossbar with exclusive decode and default error slave. |
| A2.54 DSE | Heuristic manifest | Optional Yosys area estimate when healthy, heuristic fallback with provenance. |
| A2.55 HLS Bridge | Tool-gated wrapper/intent | Tool-present path records real command result; unavailable path remains explicit stub. |
| A2.56 ECO Planner | Intent/checklist | Affected module/file analysis from dependency graph; no netlist mutation. |

## 6. Refactor plan

Current risk: `semiconductor_swarm/agents/agent2_rtl/subagents/milestone_a.py` contains too many responsibilities.

Target layout:

```text
semiconductor_swarm/agents/agent2_rtl/subagents/
  __init__.py
  intake.py
  planning.py
  writers.py
  review.py
  repair.py
  signoff.py
  manufacturing.py
  advanced.py
  registry.py
```

Backward compatibility:

- Keep existing imports working through wrappers.
- Preserve registry functions.
- Compare canonical output before/after refactor.
- No behavior change in V3.1.

## 7. Milestone roadmap

### 7.1 AGENT_2_V3.0_MA — V2 closure and V3 plan approval

Status: proposed.

Definition of Done:

- [ ] V2 plan marked completed or moved to completed folder after owner approval.
- [ ] This V3 plan is reviewed and approved by user.
- [ ] No implementation code changed before approval.
- [ ] Existing regression remains green after documentation-only changes if tests are run.

### 7.2 AGENT_2_V3.1_MB — Refactor subagents, no behavior change

Definition of Done:

- [ ] Split `milestone_a.py` into domain modules.
- [ ] Keep compatibility wrapper for old imports.
- [ ] Preserve `get_milestone_*_registry()` behavior.
- [ ] Canonical `generate_rtl_files()` output unchanged except permitted trace provenance.
- [ ] Existing tests pass.
- [ ] Add import-boundary tests.

### 7.3 AGENT_2_V3.2_MC — Semantic RTL module index

Definition of Done:

- [ ] `RTLModuleIndex` extracts modules, parameters, ports, directions, widths, instances, always blocks, and assigns.
- [ ] Detect duplicate modules.
- [ ] Detect unresolved instantiations.
- [ ] Detect missing top module.
- [ ] Emit `rtl_module_index.json` when `debug=True`.
- [ ] Tests cover simple, multi-module, generated, and malformed RTL.

### 7.4 AGENT_2_V3.3_MD — Tool health hard-gate matrix

Definition of Done:

- [ ] Emit `tool_health_matrix.json`.
- [ ] Add Verilator adapter with normalized findings.
- [ ] Add Yosys adapter with read/synth smoke findings.
- [ ] Add optional SymbiYosys/formal-smoke adapter.
- [ ] Missing tools produce fallback provenance, not false pass.
- [ ] Healthy tools with real RTL errors produce blocking failure.
- [ ] Broken tools produce `degraded_tooling` release state.

### 7.5 AGENT_2_V3.4_ME — Semantic APB/reset/width/X reviewers

Definition of Done:

- [ ] APB semantic reviewer validates required APB signal set and directions.
- [ ] APB reviewer emits SVA protocol targets for setup/access/ready/error behavior.
- [ ] Reset reviewer identifies required state/control registers and reset coverage.
- [ ] Width reviewer detects obvious width mismatch/truncation patterns.
- [ ] X-propagation reviewer detects incomplete default assignment risk.
- [ ] Emit `semantic_review_report.json`.

### 7.6 AGENT_2_V3.5_MF — JSON schema validation for artifacts

Definition of Done:

- [ ] Add schema files for all Agent 2 manifests and handoff artifacts.
- [ ] Validate every debug artifact before release.
- [ ] Bad artifact blocks release when `debug=True`.
- [ ] Add tests for missing required keys and type mismatch.
- [ ] Emit `schema_validation_report.json`.

### 7.7 AGENT_2_V3.6_MG — Golden pattern library expansion

Definition of Done:

- [ ] Add verified sync FIFO pattern with formal hooks.
- [ ] Add W1C sticky interrupt controller pattern.
- [ ] Add APB timer/counter pattern.
- [ ] Add SRAM controller with latency/ready semantics.
- [ ] Add SECDED 39/32 encode/decode pattern.
- [ ] Add simple APB crossbar 1-master N-slave pattern.
- [ ] Update `patterns/pattern_manifest.yaml` with lint/formal ownership metadata.
- [ ] Writers choose patterns deterministically.

### 7.8 AGENT_2_V3.7_MH — Advanced agents implementation-grade tier 1

Definition of Done:

- [ ] A2.52 emits real 32-bit SECDED wrapper with syndrome/correct/detect signals.
- [ ] A2.53 emits simple APB crossbar/router with exclusive decode and default error response.
- [ ] A2.54 records real Yosys score when Yosys is healthy, otherwise heuristic fallback with provenance.
- [ ] A2.55 tool-present path records actual HLS command result and generated wrapper policy.
- [ ] A2.56 lists affected modules/files from dependency graph and still avoids netlist mutation.

### 7.9 AGENT_2_V3.8_MI — Repair loop V3

Definition of Done:

- [ ] Findings classify by owner subagent and rule.
- [ ] Patch recipes exist for initial semantic findings.
- [ ] Before/after diff emitted.
- [ ] Rollback occurs if revalidation worsens.
- [ ] Max patch budget enforced.
- [ ] `repair_trace.json` includes classification, recipe, diff, and validation result.

### 7.10 AGENT_2_V3.9_MJ — Semantic closure release gate

Definition of Done:

- [ ] Emit `agent2_release_decision.json`.
- [ ] Decision enum: `pass`, `pass_with_waivers`, `fail`, `degraded_tooling`.
- [ ] Blocking criteria documented.
- [ ] Waiver governance validates owner, reason, expiry, and exact warning signature.
- [ ] Full regression passes.

## 8. Proposed test plan

Add tests incrementally:

```text
tests/test_agent2_v3_refactor.py
tests/test_agent2_semantic_index.py
tests/test_agent2_tool_health_matrix.py
tests/test_agent2_semantic_review.py
tests/test_agent2_schema_validation.py
tests/test_agent2_patterns.py
tests/test_agent2_v3_repair.py
tests/test_agent2_release_gate.py
```

Regression command:

```bash
python -X utf8 -m pytest -q
```

Expected rollout:

- existing tests remain green at every milestone;
- new milestone tests are added only when corresponding milestone implementation begins;
- real-tool tests remain skip/fallback-safe when tools are missing.

## 9. Scoring target

Agent 2 V2 close score: 8.4 / 10.

Agent 2 V3 target score: 9.1 / 10.

| Category | V2 close | V3 target |
| --- | ---: | ---: |
| Architecture | 9.2 | 9.3 |
| Determinism | 9.0 | 9.2 |
| RTL semantic validation | 6.8 | 8.7 |
| Tool integration | 7.2 | 8.8 |
| Pattern/IP depth | 6.9 | 8.4 |
| Repair loop | 7.0 | 8.5 |
| Handoff schema | 8.5 | 9.4 |
| Maintainability | 8.1 | 9.0 |

## 10. Non-goals

V3 will not:

- build a full commercial SystemVerilog compiler;
- claim full AXI4/TileLink/CHI coherency proof;
- auto-apply destructive gate-level ECO;
- insert foundry scan cells directly;
- require proprietary EDA tools;
- break public API compatibility;
- claim production-grade signoff without downstream DV/formal/physical closure.

## 11. Execution order after approval

1. Mark V2 completed after user approval.
2. Keep this V3 plan as active source of truth.
3. Implement V3.1 refactor with no behavior change.
4. Implement semantic index.
5. Implement tool health hard-gate matrix.
6. Implement semantic reviewers.
7. Implement schema validation.
8. Expand golden pattern library.
9. Upgrade advanced agents to tier 1.
10. Upgrade repair loop.
11. Add release gate.
12. Run full regression.
13. Update docs and generated indexes if required.

## 12. Final Acceptance Criteria

Agent 2 V3 is complete only when all items below are true.

### 12.1 Compatibility results

- [ ] Public API remains stable: `generate_rtl_files(spec, debug=False)`.
- [ ] Normal RTL file entry schema remains stable: `filename`, `language`, `content`, `line_count`, `dependencies`.
- [ ] Agent 3, Agent 4, and Agent 5 handoff compatibility is preserved.
- [ ] Existing prompt-contract expectations remain valid.
- [ ] Existing regression passes with:

```bash
python -X utf8 -m pytest -q
```

### 12.2 Semantic RTL closure results

- [ ] `rtl_module_index.json` is emitted when `debug=True`.
- [ ] Module index reports modules, ports, parameters, instances, always blocks, assigns, and dependency edges.
- [ ] Duplicate modules are detected.
- [ ] Missing top module is detected.
- [ ] Unresolved instantiations are detected where deterministic static analysis can identify them.
- [ ] `semantic_review_report.json` is emitted when `debug=True`.
- [ ] APB semantic reviewer detects missing/wrong-direction APB signals in tests.
- [ ] Reset reviewer detects missing reset coverage for required state/control registers in tests.
- [ ] Width reviewer detects obvious truncation or width mismatch patterns in tests.
- [ ] X-propagation reviewer detects incomplete default assignment risk in tests.

### 12.3 Tool-backed closure results

- [ ] `tool_health_matrix.json` is emitted when `debug=True`.
- [ ] Tool status is one of: `missing`, `healthy`, `broken`, `degraded`.
- [ ] Missing tools produce explicit fallback provenance, not silent pass.
- [ ] Healthy Verilator/Yosys RTL errors produce blocking findings.
- [ ] Broken tools produce `degraded_tooling` release decision unless waived by policy.
- [ ] `semantic_lint_report.json` is emitted when lint path runs or fallback path is recorded.
- [ ] `synthesis_smoke_report.json` is emitted when synthesis-smoke path runs or fallback path is recorded.
- [ ] `formal_smoke_report.json` is emitted when formal-smoke path runs or fallback path is recorded.

### 12.4 Artifact schema results

- [ ] `schema_validation_report.json` is emitted when `debug=True`.
- [ ] All Agent 2 debug/handoff artifacts have schema coverage or explicit schema-deferred entry.
- [ ] Missing required artifact keys fail schema validation tests.
- [ ] Wrong artifact field types fail schema validation tests.
- [ ] Schema failure blocks release when `debug=True`.

### 12.5 Repair-loop results

- [ ] `repair_trace.json` is emitted when repair loop runs.
- [ ] Each repair item includes finding ID, owner, rule, recipe ID, before/after diff, and revalidation result.
- [ ] Repair loop uses bounded patches, not default whole-file rewrite.
- [ ] Repair loop rolls back when revalidation gets worse.
- [ ] Repair loop enforces max iteration and max patch budget.

### 12.6 Pattern and advanced-agent results

- [ ] New golden patterns exist for FIFO, interrupt controller, APB timer, SRAM controller, SECDED, and APB crossbar.
- [ ] `patterns/pattern_manifest.yaml` records owner, parameters, interfaces, lint requirement, and formal-smoke requirement for each new pattern.
- [ ] Writers select patterns deterministically.
- [ ] A2.52 emits real 32-bit SECDED wrapper evidence.
- [ ] A2.53 emits simple APB crossbar/router evidence.
- [ ] A2.54 emits DSE score with real Yosys provenance when healthy, or explicit heuristic fallback when unavailable.
- [ ] A2.55 records real HLS command result when tool is healthy, or explicit unavailable-tool provenance.
- [ ] A2.56 emits affected module/file analysis from dependency graph.

### 12.7 Release decision results

- [ ] `agent2_release_decision.json` is always emitted when `debug=True`.
- [ ] Release decision is exactly one of: `pass`, `pass_with_waivers`, `fail`, `degraded_tooling`.
- [ ] Blocking criteria are recorded in release decision artifact.
- [ ] Waivers include owner, reason, expiry, and exact warning/error signature.
- [ ] V3 final score is documented against rubric and reaches target 9.1 / 10, or gap is explicitly recorded.

## 13. Evidence Matrix

| Required result | Evidence artifact/file | Primary test target | Blocking when absent? |
| --- | --- | --- | --- |
| Public API compatibility | `generate_rtl_files(spec, debug=False)` unchanged | `tests/test_agent2.py` | Yes |
| Agent 3/4/5 compatibility | Existing handoff artifacts remain consumable | `tests/test_agent_pipeline.py`, `tests/test_swarm_graph.py` | Yes |
| Semantic module index | `rtl_module_index.json` | `tests/test_agent2_semantic_index.py` | Yes when `debug=True` |
| APB/reset/width/X semantic review | `semantic_review_report.json` | `tests/test_agent2_semantic_review.py` | Yes for error severity |
| Tool health policy | `tool_health_matrix.json` | `tests/test_agent2_tool_health_matrix.py` | Yes when `debug=True` |
| Lint evidence | `semantic_lint_report.json` | `tests/test_agent2_tool_health_matrix.py` | Yes if tool healthy and errors exist |
| Synthesis-smoke evidence | `synthesis_smoke_report.json` | `tests/test_agent2_tool_health_matrix.py` | Yes if tool healthy and errors exist |
| Formal-smoke evidence | `formal_smoke_report.json` | `tests/test_agent2_tool_health_matrix.py` | No if tool missing; yes if healthy and fatal |
| Artifact schema validation | `schema_validation_report.json` | `tests/test_agent2_schema_validation.py` | Yes when `debug=True` |
| Golden pattern expansion | `patterns/*.sv`, `patterns/pattern_manifest.yaml` | `tests/test_agent2_patterns.py` | Yes for V3.6 completion |
| Advanced tier 1 evidence | A2.52-A2.56 manifests and generated modules | `tests/test_agent2_patterns.py`, `tests/test_agent2.py` | Yes for V3.7 completion |
| Repair traceability | `repair_trace.json` | `tests/test_agent2_v3_repair.py` | Yes when repair runs |
| Release gate | `agent2_release_decision.json` | `tests/test_agent2_release_gate.py` | Yes when `debug=True` |
| Full regression | pytest output | `python -X utf8 -m pytest -q` | Yes |

## 14. Approval gate

This plan is currently proposed.

No implementation work should start until the user approves this plan.
