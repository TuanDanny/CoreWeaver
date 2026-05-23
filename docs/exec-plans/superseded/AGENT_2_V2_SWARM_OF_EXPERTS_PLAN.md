---
title: AGENT_2_V2 — Swarm-of-Experts RTL Designer Upgrade Plan
status: superseded
owner: semiconductor-swarm
type: exec-plan
last_reviewed: 2026-05-20
source_of_truth: false
supersedes:
  - docs/exec-plans/superseded/AGENT_2_Upgrade_V1.md
superseded_by: docs/exec-plans/active/AGENT_2_V4_INDUSTRIAL_RTL_SIGNOFF_PLAN.md
related_tests:
  - tests/test_agent2.py
  - tests/test_swarm_graph.py
  - tests/test_prompt_contracts.py
---

# AGENT_2_V2 — Swarm-of-Experts RTL Designer Upgrade Plan

## 1. Version intent

Agent 2 V2 upgrades the current rule-based RTL Designer into a deterministic RTL department made of many narrow specialist subagents.

V2 keeps the public compatibility contract:

- `generate_rtl_files(spec, debug=False)` remains valid.
- Output file entries keep keys: `filename`, `language`, `content`, `line_count`, `dependencies`.
- APB pinout remains locked to Agent 1 `APB_SLAVE_INTERFACE`.
- Existing tests must keep passing during staged rollout.

## 2. Why V2 is needed

Current Agent 2 already has:

- local pattern library
- RAG stub
- RTL self-check
- static/tool linter
- deterministic file generation
- Verilator fallback resilience

Current Agent 2 still concentrates too many roles in one module:

- spec normalization
- interface locking
- block decomposition
- IP writing
- top integration
- style review
- linter/tool handling
- debug report generation

V2 separates these roles into subagents to improve auditability, repair loops, future RAG integration, and semiconductor-grade handoff quality.

## 3. Target architecture

```text
Agent1 Architecture Spec
  |
Agent2 Orchestrator
  |
  +-- Intake subagents
  +-- Planning subagents
  +-- IP writer subagents
  +-- Integration subagents
  +-- Quality gate subagents
  +-- Repair subagents
  +-- Handoff subagents
  |
RTL files + rtl_manifest.json + agent2_subgraph_trace.json + debug report
```

V2 subagents are deterministic Python specialists, not free-form autonomous chat agents. Each subagent owns one narrow concern and returns a typed result.

## 4. Subagent contract

All subagents should return this logical schema:

```python
@dataclass
class Agent2SubAgentResult:
    agent_id: str
    name: str
    version: str
    pass_: bool
    artifacts: dict[str, Any]
    findings: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    needs_repair: bool
    confidence: float
```

Finding schema:

```json
{
  "severity": "error|warning|info",
  "owner": "A2.14 Register File Writer",
  "file": "control_regs.sv",
  "rule": "missing_default_assignment",
  "message": "always_comb path lacks default assignment",
  "suggested_fix": "add default assignments at block entry"
}
```

## 5. Target 56 subagents

### 5.1 Intake agents

| ID | Name | Responsibility |
| --- | --- | --- |
| A2.01 | Spec Normalizer | Normalize Agent 1 spec and identify missing fields. |
| A2.02 | Constraint Extractor | Extract clock, reset, PPA, FPGA/ASIC, area/timing/power constraints. |
| A2.03 | Interface Contract Agent | Lock APB/AXI/FIFO/stream pinout and reject illegal renames. |
| A2.04 | Address Map Agent | Build and validate register/address map. |
| A2.05 | Risk Classifier | Mark risky blocks: CDC, FIFO, DMA, memory, interrupt, accelerator. |

### 5.2 Planning agents

| ID | Name | Responsibility |
| --- | --- | --- |
| A2.06 | Block Decomposer | Convert `ip_blocks` into RTL module plans. |
| A2.07 | Datapath Planner | Plan arithmetic/datapath widths and pipeline points. |
| A2.08 | Control FSM Planner | Plan state machines and transition policy. |
| A2.09 | Register Model Planner | Plan CSRs, reset values, RW/RO/W1C behavior. |
| A2.10 | Memory Map Planner | Plan SRAM/BRAM/register memory behavior. |
| A2.11 | Interrupt Planner | Plan interrupt sources, masks, status, clear policy. |
| A2.12 | Clock/Reset Planner | Plan clock/reset usage and reset assumptions. |

### 5.3 IP writer agents

| ID | Name | Responsibility |
| --- | --- | --- |
| A2.13 | APB Slave Writer | Generate APB access skeleton. |
| A2.14 | Register File Writer | Generate CSR RTL. |
| A2.15 | FIFO Writer | Generate synchronous FIFO RTL. |
| A2.16 | DMA Writer | Generate DMA skeleton/state machine. |
| A2.17 | SRAM Controller Writer | Generate SRAM controller skeleton. |
| A2.18 | Timer/Counter Writer | Generate timer/counter RTL. |
| A2.19 | Interrupt Controller Writer | Generate IRQ aggregation/control RTL. |
| A2.20 | MAC/Accelerator Writer | Generate MAC/accelerator datapath RTL. |
| A2.21 | Generic Glue Logic Writer | Generate mux/decoder/tieoff logic. |

### 5.4 Integration agents

| ID | Name | Responsibility |
| --- | --- | --- |
| A2.22 | Package Writer | Generate `*_pkg.sv`, typedefs, params. |
| A2.23 | Interface Writer | Generate `*_intf.sv` where required. |
| A2.24 | Top-Level Integrator | Instantiate blocks and wire APB/IRQ/reset. |
| A2.25 | Dependency Order Agent | Order compile files deterministically. |
| A2.26 | Naming Convention Agent | Enforce module/instance/signal naming. |

### 5.5 Quality gate agents

| ID | Name | Responsibility |
| --- | --- | --- |
| A2.27 | Static RTL Style Reviewer | Check forbidden tokens, TODOs, legacy `reg/wire`, prompt style rules. |
| A2.28 | Synthesizability Reviewer | Check always_ff/always_comb style, latch risk, full assignments. |
| A2.29 | Width/Type Reviewer | Check width mismatch, truncation, signed/unsigned risks. |
| A2.30 | Tool Lint Agent | Run tool-health-aware Verilator/Yosys/static lint. |
| A2.31 | Formal Hook Agent | Generate SVA suggestions/assumptions for Agent 5. |
| A2.32 | DV Hook Agent | Generate coverpoints and scenario hints for Agent 3. |

### 5.6 Repair/finalization agents

| ID | Name | Responsibility |
| --- | --- | --- |
| A2.33 | Diagnostic Agent | Aggregate review/lint findings. |
| A2.34 | Repair Planner | Choose owner subagent and repair strategy. |
| A2.35 | Patch Agent | Apply small local patches without rewriting whole design. |
| A2.36 | Release/Handoff Agent | Package RTL, manifest, trace, and debug report. |

### 5.7 Advanced signoff and governance agents

| ID | Name | Responsibility |
| --- | --- | --- |
| A2.37 | Protocol Compliance Agent | Check APB setup/access sequencing, selected response behavior, ready/error semantics, and protocol-specific illegal states. |
| A2.38 | Reset Safety Agent | Check reset values, reset polarity, reset fanout assumptions, X-safe reset behavior, and unreset-state policy. |
| A2.39 | CDC/RDC Agent | Detect clock/reset domain crossings and require 2-flop sync, sync FIFO, handshake, or explicit waiver policy. |
| A2.40 | X-Propagation Agent | Check unknown-safe defaults, mux defaults, unreachable-state handling, and no unintended X leakage. |
| A2.41 | Low-Power Intent Agent | Convert power constraints into RTL policy: clock enables, idle gating hints, and reduced toggle defaults. |
| A2.42 | Security/Safety Agent | Check CSR access safety, illegal address response, privilege hooks, safe tieoffs, and fail-closed defaults. |
| A2.43 | Parameterization Agent | Check width/depth/lane parameters and remove hard-coded values where spec requires configurability. |
| A2.44 | Lint Waiver Governance Agent | Track lint warnings, approved waivers, waiver owner, expiration, and audit trail. |
| A2.45 | Synthesis Semantics Agent | Check RTL against synthesizable subsets for Quartus, Yosys, and Verilator compatibility. |
| A2.46 | Timing Closure Prep Agent | Recommend/register pipeline cuts, avoid long mux chains, and prepare Agent 4 timing repair hooks. |
| A2.47 | Coverage Intent Agent | Generate coverage intent for Agent 3: registers, FSM states, interrupts, FIFO boundaries, and error paths. |
| A2.48 | Documentation/Traceability Agent | Link requirement -> spec field -> RTL module/file -> DV hook -> formal hook -> signoff evidence. |

### 5.8 DFT, power format, and technology abstraction agents

| ID | Name | Responsibility |
| --- | --- | --- |
| A2.49 | DFT Stitching Integrator | Add DFT-ready RTL hooks: `scan_enable`, `test_mode`, scan placeholder ports, clock/reset bypass mux policy, safe tieoffs, and `dft_hooks.json`; do not insert foundry scan cells directly. |
| A2.50 | UPF Generator | Generate IEEE 1801 Unified Power Format (`.upf`) skeleton and `upf_manifest.json` from Agent 1 power intent; support ASIC-ready handoff and FPGA-safe stub mode. |
| A2.51 | Tech-Specific Macro Wrapper | Generate platform-independent SRAM/PLL/macro wrappers with behavioral sim/formal fallback and mapping stubs for Quartus IP or ASIC macros. |

### 5.9 Reliability, scalability, exploration, HLS, and ECO agents

| ID | Name | Responsibility |
| --- | --- | --- |
| A2.52 | Fault Tolerance & Radiation Hardening Injector | Add selective safety hardening from Agent 1 policy: TMR for critical FSM/registers, SECDED ECC wrappers for SRAM/FIFO, fault-injection hooks, and formal/DV handoff evidence. |
| A2.53 | Advanced NoC & Coherency Generator | Generate NoC/router/crossbar skeletons, AXI4/TileLink/CHI intent hooks, routing tables, and coherency manifests; do not claim full coherency proof without downstream DV/formal closure. |
| A2.54 | Micro-Architecture DSE Engine | Generate multiple RTL variants for datapath/accelerator blocks, run available lint/synthesis/PPA probes or heuristic fallback, score tradeoffs, and select preferred variant. |
| A2.55 | HLS Bridge | Tool-gated bridge for C/C++ algorithm blocks through Bambu/XLS-style HLS flows, plus APB/AXI wrapper generation and deterministic fallback stubs when tools are unavailable. |
| A2.56 | ECO Intent & Surgical Patch Planner | Classify late bugs for ECO feasibility, emit `eco_intent.json`, affected-cone analysis, patch script skeletons, and required LEC/STA/DFT checks; do not auto-apply unsafe netlist mutations. |

### 5.10 Required technical upgrades for existing agents

| Agent | Upgrade |
| --- | --- |
| A2.03 Interface Contract Agent | Add protocol family registry and semantic checks, not only pin-name locking. |
| A2.04 Address Map Agent | Add overlap checks, alignment checks, decode exclusivity, reserved-region policy, and default error policy. |
| A2.07 Datapath Planner | Add bit-growth, saturation, rounding, truncation, and pipeline-depth policy. |
| A2.09 Register Model Planner | Support `RW`, `RO`, `W1C`, `W0C`, `RC`, `RS`, side-effect reads, side-effect writes, and reset-value proof. |
| A2.11 Interrupt Planner | Add raw/sticky/masked/status/clear hierarchy and lost-interrupt prevention rules. |
| A2.12 Clock/Reset Planner | Separate clock-domain and reset-domain rules; record synchronous/asynchronous reset policy. |
| A2.24 Top-Level Integrator | Add decode exclusivity, one-hot select proof, default slave response, and no-floating-output rules. |
| A2.28 Synthesizability Reviewer | Add latch proof, incomplete assignment detection, and synthesis-safe process templates. |
| A2.29 Width/Type Reviewer | Add enum width, cast, packed struct, sign-extension, and truncation checks. |
| A2.30 Tool Lint Agent | Add tool health matrix for Verilator/Yosys/Quartus, severity normalization, and fallback provenance. |
| A2.31 Formal Hook Agent | Generate protocol, register, FSM, reset, and illegal-access property targets. |
| A2.32 DV Hook Agent | Focus on scenario generation; coverage responsibility moves to A2.47. |
| A2.35 Patch Agent | Add patch granularity limits, before/after diff, rollback record, and no-whole-file-rewrite policy. |
| A2.36 Release/Handoff Agent | Add release manifest, reproducibility hash, compile-order hash, and signoff summary. |
| A2.41 Low-Power Intent Agent | Feed A2.50 with power-domain, isolation, retention, level-shifter, and target-flow metadata. |
| A2.45 Synthesis Semantics Agent | Check A2.51 wrapper portability across Quartus/Yosys/Verilator and ASIC substitution flow. |
| A2.46 Timing Closure Prep Agent | Coordinate with A2.49 so clock/reset bypass muxes do not create untracked timing exceptions. |
| A2.05 Risk Classifier | Tag radiation, safety, multicore, HLS, DSE, and ECO risk classes to activate A2.52-A2.56 only when justified. |
| A2.07 Datapath Planner | Feed A2.54 variant generation with width, pipeline, latency, and arithmetic tradeoff knobs. |
| A2.10 Memory Map Planner | Feed A2.53 routing-map and NoC address-region generation for multi-master/multi-slave designs. |
| A2.17 SRAM Controller Writer | Coordinate with A2.52 SECDED ECC insertion and A2.51 macro wrappers. |
| A2.20 MAC/Accelerator Writer | Support A2.54 DSE and A2.55 HLS-generated accelerator blocks. |

## 6. Deterministic DAG

```text
Stage 1 Intake:
  A2.01 -> A2.02 -> A2.03 -> A2.04 -> A2.05

Stage 2 Planning:
  A2.06 -> [A2.07, A2.08, A2.09, A2.10, A2.11, A2.12, A2.53, A2.54, A2.55]

Stage 3 Generation:
  [A2.13..A2.24, A2.51, A2.52, A2.53, A2.54, A2.55] by block and capability

Stage 4 Integration:
  A2.25 -> A2.26

Stage 5 Review:
  [A2.27, A2.28, A2.29, A2.30, A2.31, A2.32, A2.37, A2.38, A2.39, A2.40, A2.41, A2.42, A2.43, A2.44, A2.45, A2.46, A2.47, A2.48, A2.49, A2.50, A2.52, A2.53, A2.54, A2.55]

Stage 6 Repair Loop:
  A2.33 -> A2.34 -> A2.35 -> Stage 5, max 3 iterations

Stage 7 Handoff:
  A2.36 -> A2.56
```

## 7. Milestone roadmap

### 7.1 AGENT_2_V2.0_MA — skeleton swarm

Implement 12 first subagents while keeping existing output compatible:

- A2.01 Spec Normalizer
- A2.03 Interface Contract Agent
- A2.04 Address Map Agent
- A2.06 Block Decomposer
- A2.09 Register Model Planner
- A2.13 APB Slave Writer
- A2.14 Register File Writer
- A2.24 Top-Level Integrator
- A2.25 Dependency Order Agent
- A2.27 Static RTL Style Reviewer
- A2.30 Tool Lint Agent
- A2.36 Release/Handoff Agent

Definition of Done:

- [ ] `semiconductor_swarm/agents/agent2_rtl/contracts.py` exists.
- [ ] `semiconductor_swarm/agents/agent2_rtl/state.py` exists.
- [ ] `semiconductor_swarm/agents/agent2_rtl/orchestrator.py` exists.
- [ ] `semiconductor_swarm/agents/agent2_rtl/subagents/` exists.
- [ ] 12 Milestone A subagents exist and return `Agent2SubAgentResult`.
- [ ] `generate_rtl_files()` can delegate to orchestrator without changing public schema.
- [ ] `debug=True` emits `rtl_manifest.json` and `agent2_subgraph_trace.json`.
- [ ] Existing tests pass.
- [ ] New tests validate subagent trace and manifest.

### 7.2 AGENT_2_V2.1_MB — review and repair swarm

Add review/repair agents:

- A2.28 Synthesizability Reviewer
- A2.29 Width/Type Reviewer
- A2.31 Formal Hook Agent
- A2.32 DV Hook Agent
- A2.33 Diagnostic Agent
- A2.34 Repair Planner
- A2.35 Patch Agent

Definition of Done:

- [ ] Review stage aggregates findings from all reviewers.
- [ ] Repair loop supports max 3 deterministic iterations.
- [ ] `repair_trace.json` emitted when repairs occur.
- [ ] Tool-health pass with bad RTL fails when tool is healthy.
- [ ] Broken/missing tool still falls back safely.

### 7.3 AGENT_2_V2.2_MC — full IP specialist swarm

Add remaining IP specialist agents:

- A2.02 Constraint Extractor
- A2.05 Risk Classifier
- A2.07 Datapath Planner
- A2.08 Control FSM Planner
- A2.10 Memory Map Planner
- A2.11 Interrupt Planner
- A2.12 Clock/Reset Planner
- A2.15 FIFO Writer
- A2.16 DMA Writer
- A2.17 SRAM Controller Writer
- A2.18 Timer/Counter Writer
- A2.19 Interrupt Controller Writer
- A2.20 MAC/Accelerator Writer
- A2.21 Generic Glue Logic Writer
- A2.22 Package Writer
- A2.23 Interface Writer
- A2.26 Naming Convention Agent

Definition of Done:

- [ ] Full 36-agent registry exists.
- [ ] Orchestrator can skip unavailable capabilities deterministically.
- [ ] Pattern selection uses `patterns/pattern_manifest.yaml` as source of truth.
- [ ] Generated RTL manifest records which writer owned each file section.

### 7.4 AGENT_2_V2.3_MD — PPA/formal/DV-aware handoff

Add richer cross-agent handoff:

- `rtl_manifest.json` with clocks, resets, ports, modules, dependencies, address map, interrupts.
- `formal_hooks.json` for Agent 5.
- `dv_hooks.json` for Agent 3.
- rough PPA hints for Agent 4.

Definition of Done:

- [ ] Agent 3 can consume DV hints without guessing block behavior.
- [ ] Agent 5 can consume formal assumptions/assertion targets.
- [ ] Agent 4 receives compile order and top module info.

### 7.5 AGENT_2_V2.4_ME — semiconductor-grade signoff swarm

Add advanced signoff and governance agents:

- A2.37 Protocol Compliance Agent
- A2.38 Reset Safety Agent
- A2.39 CDC/RDC Agent
- A2.40 X-Propagation Agent
- A2.41 Low-Power Intent Agent
- A2.42 Security/Safety Agent
- A2.43 Parameterization Agent
- A2.44 Lint Waiver Governance Agent
- A2.45 Synthesis Semantics Agent
- A2.46 Timing Closure Prep Agent
- A2.47 Coverage Intent Agent
- A2.48 Documentation/Traceability Agent

Definition of Done:

- [ ] Full 48-agent registry exists.
- [ ] Protocol compliance checks APB setup/access response semantics.
- [ ] Reset safety checks reset polarity, reset values, and X-safe behavior.
- [ ] CDC/RDC checker either proves single-domain design or records synchronizer requirements.
- [ ] X-propagation checker verifies default assignment and illegal-state policy.
- [ ] Low-power intent produces RTL clock-enable/toggle-reduction hints from power constraints.
- [ ] Security/safety checker verifies illegal address behavior and fail-closed defaults.
- [ ] Parameterization checker flags hard-coded widths where spec requires configurable widths.
- [ ] Lint waivers require owner, reason, expiration, and exact warning signature.
- [ ] Synthesis semantics checker records Quartus/Yosys/Verilator subset compatibility.
- [ ] Timing closure prep emits pipeline suggestions and Agent 4 repair handoff hooks.
- [ ] Coverage intent emits Agent 3 coverage goals.
- [ ] Traceability links spec requirement -> RTL file/module -> DV/formal/signoff evidence.

### 7.6 AGENT_2_V2.5_MF — DFT, UPF, and macro abstraction handoff

Add manufacturing, power-format, and technology-portability agents:

- A2.49 DFT Stitching Integrator
- A2.50 UPF Generator
- A2.51 Tech-Specific Macro Wrapper

Definition of Done:

- [ ] Full 51-agent registry exists.
- [ ] DFT disabled mode ties off `scan_enable`, `test_mode`, scan placeholders, and bypass controls safely.
- [ ] DFT enabled mode emits DFT-ready ports/hooks and `dft_hooks.json` without inserting foundry scan cells directly.
- [ ] Clock/reset bypass mux policy is explicit and reviewed by reset/timing agents.
- [ ] Agent 1 power intent generates `power_intent.upf` when target flow includes ASIC.
- [ ] Missing/partial power intent emits deterministic single-domain UPF stub plus warnings.
- [ ] `upf_manifest.json` records power domains, supply nets, isolation, retention, level-shifter hints, and target flow.
- [ ] SRAM wrapper generation produces platform-independent module, behavioral sim/formal model, and backend mapping stub.
- [ ] PLL wrapper generation produces platform-independent module, lock/reset semantics, sim fallback, and backend mapping stub.
- [ ] Macro wrappers expose latency, polarity, initialization, clocking, and synthesis black-box policy in manifest.
- [ ] Agent 4 receives DFT hooks, UPF files, macro mapping manifests, and timing exception hints.

### 7.7 AGENT_2_V2.6_MG — Reliability, NoC, DSE, HLS, and ECO handoff

Status: implemented with deterministic stubs/manifests and strict DoD regression coverage.

Add high-end silicon agents:

- A2.52 Fault Tolerance & Radiation Hardening Injector
- A2.53 Advanced NoC & Coherency Generator
- A2.54 Micro-Architecture DSE Engine
- A2.55 HLS Bridge
- A2.56 ECO Intent & Surgical Patch Planner

Definition of Done:

- [x] Full 56-agent registry exists.
- [x] Radiation hardening activates only from explicit Agent 1 policy (`none`, `selective`, `full`) and protected block tags.
- [x] Selective TMR applies only to critical FSM/register sets and emits area/power impact warnings.
- [x] SECDED ECC wrappers exist for selected SRAM/FIFO memories and emit syndrome/correction/detection hooks.
- [x] Fault-injection hooks are handed to Agent 3 and ECC/TMR properties are handed to Agent 5.
- [x] NoC mode emits router/crossbar skeletons, routing tables, endpoint manifests, and protocol intent.
- [x] AXI4/TileLink/CHI support is clearly marked as skeleton/intent unless proven by downstream DV/formal closure.
- [x] DSE engine emits at least two deterministic RTL variants when tradeoff knobs exist.
- [x] DSE selection records PPA score, tool availability, heuristic fallback, and chosen variant reason.
- [x] HLS bridge detects Bambu/XLS-style tool availability before invocation.
- [x] HLS unavailable mode emits wrapper stub, integration plan, and explicit warning instead of failing silently.
- [x] HLS generated blocks receive APB/AXI wrapper policy and manifest entries.
- [x] ECO planner emits `eco_intent.json`, affected cone notes, patch script skeleton, and signoff checklist.
- [x] ECO planner never auto-applies destructive gate-level netlist patches.
- [x] ECO handoff requires LEC/formal equivalence, STA, DFT retest, and owner approval.

## 8. Proposed file layout

```text
semiconductor_swarm/agents/agent2_rtl/
  contracts.py
  state.py
  orchestrator.py
  subagents/
    __init__.py
    spec_normalizer.py
    interface_contract.py
    address_map.py
    block_decomposer.py
    register_model_planner.py
    apb_slave_writer.py
    register_file_writer.py
    top_integrator.py
    dependency_order.py
    static_style_reviewer.py
    tool_lint_agent.py
    release_handoff.py
    protocol_compliance.py
    reset_safety.py
    cdc_rdc_agent.py
    x_propagation.py
    low_power_intent.py
    security_safety.py
    parameterization.py
    lint_waiver_governance.py
    synthesis_semantics.py
    timing_closure_prep.py
    coverage_intent.py
    documentation_traceability.py
    dft_stitching_integrator.py
    upf_generator.py
    tech_macro_wrapper.py
    fault_tolerance_radiation_hardening.py
    advanced_noc_coherency.py
    micro_arch_dse.py
    hls_bridge.py
    eco_intent_patch_planner.py
```

Later V2.1/V2.2 adds remaining files in same folder.

## 9. Compatibility guardrails

- Do not rename existing public functions unless wrappers remain.
- Do not change generated file dictionary schema for normal RTL files.
- Keep `agent2_debug_report.json` for existing debug tests.
- Add extra debug artifacts only when `debug=True`.
- Keep `APB_SLAVE_INTERFACE` as source of truth for APB pinout.
- Keep full pytest green after each milestone.

## 10. Test plan

Milestone A tests:

- Subagent registry contains 12 required agents.
- `generate_rtl_files(debug=True)` includes:
  - `agent2_debug_report.json`
  - `rtl_manifest.json`
  - `agent2_subgraph_trace.json`
- Trace includes ordered agent IDs.
- Manifest includes project, top module, blocks, files, dependencies, APB signals.
- Normal `generate_rtl_files(debug=False)` output remains unchanged except internal generation path.
- Full regression:

```bash
python -X utf8 -m pytest -q
```

Milestone E tests:

- Registry contains A2.01 through A2.48.
- Protocol compliance rejects malformed APB setup/access sequence templates.
- Reset safety rejects missing reset on required state/control registers.
- CDC/RDC agent marks multi-clock specs and requires synchronizer policy.
- X-propagation agent rejects incomplete default assignments.
- Low-power intent emits clock-enable/toggle-reduction hints when power constraints exist.
- Security/safety agent verifies illegal address response and fail-closed behavior.
- Parameterization agent flags hard-coded widths where spec exposes configurable width.
- Lint waiver governance rejects waiver without owner, reason, expiration, and signature.
- Synthesis semantics records Quartus/Yosys/Verilator compatibility status.
- Timing closure prep emits pipeline recommendations for wide mux/datapath risks.
- Coverage intent produces Agent 3 coverage goals.
- Documentation/traceability emits requirement-to-RTL-to-signoff matrix.

Milestone F tests:

- Registry contains A2.01 through A2.51.
- DFT disabled mode produces safe tieoffs and no floating test signals.
- DFT enabled mode emits `dft_hooks.json` and scan/test placeholder ports according to policy.
- Clock/reset bypass mux policy is visible to reset safety and timing closure prep artifacts.
- Agent 1 ASIC power intent generates `power_intent.upf` and `upf_manifest.json`.
- FPGA-only flow emits UPF stub or skips UPF with explicit reason.
- SRAM block emits platform-independent wrapper plus sim/formal behavioral fallback.
- PLL requirement emits platform-independent wrapper plus lock/reset behavioral fallback.
- Macro wrapper manifest records backend mapping targets for Quartus and ASIC.

Milestone G tests:

- Registry contains A2.01 through A2.56.
- Radiation-hardening disabled mode leaves RTL unchanged except explicit manifest note.
- Selective hardening mode applies TMR only to tagged critical FSM/register blocks.
- ECC mode emits SECDED wrapper for selected SRAM/FIFO blocks and syndrome hooks.
- Fault-injection hooks appear in DV/formal handoff manifests.
- NoC mode emits deterministic router/crossbar skeleton and routing manifest.
- Coherency mode emits intent manifest and requires DV/formal closure before signoff.
- DSE mode emits multiple RTL variants and records chosen variant reason.
- Tool-missing DSE mode uses heuristic score with provenance.
- HLS tool-missing mode emits integration stub and warning.
- HLS tool-present mode records tool command, generated RTL wrapper, and manifest entry.
- ECO planner emits `eco_intent.json` and does not mutate netlist by default.
- ECO checklist includes LEC/formal equivalence, STA, DFT retest, and approval gate.

## 11. Execution order for AGENT_2_V2.0_MA

1. Add `contracts.py` and `state.py`.
2. Add `subagents/` with 12 skeleton subagents.
3. Add `orchestrator.py` to run deterministic DAG.
4. Move existing helper generation through subagent calls with minimal code movement.
5. Add manifest/trace debug artifact generation.
6. Update `rtl_designer.py` wrapper to call orchestrator.
7. Add tests for subagent trace and manifest.
8. Run target tests.
9. Run full pytest.
10. Update plan status/checklist.

## 12. Version log

- V1: Pattern/RAG/linter upgrade plan.
- V2.0_MA: Skeleton Swarm-of-Experts with 12 deterministic subagents.
- V2.1_MB: Review and repair swarm.
- V2.2_MC: Full 36-agent specialist registry.
- V2.3_MD: PPA/formal/DV-aware handoff enrichment.
- V2.4_ME: Full 48-agent semiconductor-grade signoff and governance swarm.
- V2.5_MF: Full 51-agent DFT, UPF, and technology macro abstraction handoff.
- V2.6_MG: Full 56-agent reliability, NoC, DSE, HLS, and ECO handoff expansion.
