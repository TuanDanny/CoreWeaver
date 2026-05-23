---
title: AGENT_2_V4 — Industrial RTL Signoff Upgrade Plan
status: active
owner: semiconductor-swarm
type: exec-plan
last_reviewed: 2026-05-20
source_of_truth: true
supersedes:
  - docs/exec-plans/superseded/AGENT_2_V3_SEMANTIC_RTL_CLOSURE_PLAN.md
related_tests:
  - tests/test_agent2.py
  - tests/test_swarm_graph.py
  - tests/test_prompt_contracts.py
  - tests/test_real_tool_detection.py
  - tests/test_real_formal_tools.py
  - tests/test_real_dv_tools.py
  - tests/test_swarm_contract_registry.py
---

# AGENT_2_V4 — Industrial RTL Signoff Upgrade Plan

## 0. Critical design corrections from review

This plan incorporates five mandatory corrections before implementation. These corrections override any older wording elsewhere in the document.

1. **CSR auto-generation replaces hand-written CSR RTL.** Agent 2 must not hand-write CSR register modules when Agent 1 provides SystemRDL collateral. Agent 2 must call an open-source generator such as PeakRDL-regblock to produce CSR SystemVerilog from `.rdl`. Agent 2 may only integrate, wrap, and instantiate the generated CSR block. The gate checks generator provenance, generated artifact hashes, interface compatibility, and correct instantiation, not line-by-line hand-written offset recovery as the primary safety mechanism.
2. **Compile order must be derived from actual RTL, not Agent-authored JSON.** `rtl_manifest.json` is advisory metadata only. Compile dependency source of truth must come from tool/AST evidence: Verilator dependency emission (`--MMD` or equivalent), Yosys parse/elaboration evidence, or a SystemVerilog AST scanner. The resolver must build a topological dependency graph from real imports, packages, interfaces, and module instantiations.
3. **Repair loop requires Logic Equivalence Checking (LEC).** Score-based rollback is insufficient for hardware. Any repair patch that can alter logic, timing structure, datapath/control behavior, or synthesis semantics must run Yosys `equiv_make`, `equiv_simple`, and `equiv_status` or an equivalent LEC flow. Non-equivalent patches are rejected even if lint/synthesis scores improve.
4. **UPF/low-power consistency is a real gate.** If low-power intent is present, Agent 2 must emit and validate a UPF consistency report. The gate checks RTL hierarchy paths, clock-gating intent, isolation/retention/level-shifter requirements, and naming/hierarchy alignment between RTL and UPF. This is P1 by default and becomes P0 for designs that enable low-power mode.
5. **Tool provenance must include reproducible environment proof.** Local executable path is not enough. Strict mode requires a container/toolchain rule: Docker image digest or locked toolchain manifest, required environment variables such as `YOSYS_ROOT`, `VERILATOR_ROOT`, and `SBY_ROOT` where applicable, tool versions, executable paths, and report hashes.

## 1. Version intent

Agent 2 V4 upgrades Agent 2 from a strong RTL generation and handoff framework into an industrial RTL signoff engine.

V2 proved deterministic swarm-of-experts orchestration.

V3 added semantic indexing, schema validation, tool adapters, pattern direction, and deeper review.

V4 must close the biggest remaining gap: generated RTL must not receive signoff when real EDA tools fail, are missing in strict mode, or are bypassed by static fallback.

V4 target outcome:

- Agent 2 can still run in demo mode on machines without EDA tools.
- Agent 2 strict mode must fail hard when Verilator, Yosys, or SymbiYosys gates are unavailable or failing.
- Generated RTL must have compile order, lint, synthesis smoke, CSR consistency, protocol contracts, pattern coverage, and downstream handoff evidence.
- All repairs must be finding-driven, traceable, bounded, and revalidated by the exact gate that failed.

## 2. Compatibility contract

V4 keeps existing public compatibility:

```python
generate_rtl_files(spec, debug=False)
```

Public RTL file entries remain compatible:

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

- Do not break Agent 3, Agent 4, or Agent 5 consumers.
- Do not rename Agent 1 APB pinout or violate `APB_SLAVE_INTERFACE`.
- Do not require external EDA tools for default demo/developer mode.
- Do require real EDA tools for strict/nightly signoff modes.
- Do not allow fallback to produce `RTL_SIGNOFF_READY`.
- Keep existing tests green while adding stricter tests.
- Make every new gate produce machine-readable JSON plus reviewer-readable Markdown summary.

## 3. Why V4 is needed

Recent end-to-end review showed Agent 2 can generate a complete RTL package and feed Agent 3, Agent 4, and Agent 5 successfully. However, strict RTL confidence is still limited by real-tool enforcement.

Observed strengths:

- Agent 2 produces 50 RTL artifacts across seven blocks.
- Agent 2 emits manifests, semantic reports, handoff hooks, formal hooks, physical hooks, UPF intent, and release decisions.
- Agent 2 V2/V3 subagent architecture and semantic closure artifacts exist.
- Downstream Agent 3/4/5 handoff works.

Observed gaps V4 must close:

| Gap | Risk | V4 correction |
| --- | --- | --- |
| Verilator environment can fail while static fallback still passes. | False signoff confidence. | Strict mode fails if fallback is used. |
| Compile order is not a first-class signoff artifact. | Tool runs can be inconsistent or brittle. | Generate and validate AST/tool-derived `compile_order.f`; `rtl_manifest.json` is advisory only. |
| Yosys and SymbiYosys reports can be wrapper/static in non-strict mode. | Synthesis/formal confidence unclear. | Add strict EDA reports and provenance. |
| CSR flow can rely on hand-written register RTL and after-the-fact checks. | Register map drift can break firmware and DV. | Replace hand-written CSR modules with PeakRDL/SystemRDL auto-generation and add CSR integration/provenance gate. |
| Pattern coverage is partly token/static. | Generated RTL may look compliant but miss semantics. | Add pattern semantic validators. |
| Repair loop is not yet signoff-grade. | Fixes may be broad, untraceable, non-equivalent, or unproven. | Add finding-driven bounded repair loop with rerun gate and LEC for logic-affecting patches. |
| Handoff lacks all strict tool evidence. | Agent 3/4/5 may consume weak RTL. | Add Agent 2 handoff bundle V2. |

## 4. Target architecture

```text
Agent1 Architecture Contract
  |
Agent2 V4 Orchestrator
  |
  +-- IntakeContractAuditor
  |     +-- schema validation
  |     +-- APB pinout lock
  |     +-- CSR/register map import
  |
  +-- CompileOrderEngineer
  |     +-- RTL dependency graph
  |     +-- compile_order.f
  |     +-- cycle/missing dependency detection
  |
  +-- RTLGenerationLead
  |     +-- deterministic SV generation
  |     +-- package/interface/module/top generation
  |     +-- production style contract
  |
  +-- ProtocolEngineer
  |     +-- APB protocol contracts
  |     +-- interface SVA-lite generation
  |     +-- latency/backpressure expectations
  |
  +-- CSRAuditor
  |     +-- RTL vs RDL vs C header consistency
  |     +-- reset/access/W1C/RO/RW checks
  |
  +-- SemanticLintLead
  |     +-- reset/assignment/width/X-prop checks
  |     +-- APB handshake checks
  |     +-- interrupt and memory side-effect checks
  |
  +-- RealToolRunner
  |     +-- Verilator lint
  |     +-- Yosys syntax/synthesis smoke
  |     +-- SymbiYosys formal smoke
  |
  +-- RepairLead
  |     +-- classify finding
  |     +-- patch bounded diff
  |     +-- rerun exact failing gate
  |     +-- rollback if worse
  |
  +-- HandoffGovernor
  |     +-- Agent2-to-Agent3 bundle
  |     +-- Agent2-to-Agent4 bundle
  |     +-- Agent2-to-Agent5 bundle
  |
  +-- SignoffChair
        +-- quality score
        +-- dashboard
        +-- release decision
```

## 5. Release modes

| Mode | Use case | Fallback allowed | Real tools required | Release label | Required behavior |
| --- | --- | ---: | ---: | --- | --- |
| `demo` | Fast demos and no-tool machines | Yes | No | `DEMO_PASS` | Static fallback allowed but reported. |
| `dev` | Local development | Yes, warned | No | `DEV_PASS_WITH_WARNINGS` | Fallback allowed with risk flag. |
| `strict` | Engineering release | No | Yes | `RTL_SIGNOFF_READY` | Any fallback or unavailable required tool fails. |
| `nightly-real-tools` | CI/signoff hardening | No | Yes | `NIGHTLY_SIGNOFF_READY` | P0 and P1 gates required. |

Mandatory rule: strict/nightly modes must never write `pass=true` if any required real-tool gate used fallback.

## 6. Upgrade work breakdown

| ID | Workstream | Industrial target | Implementation work | Required artifacts | Pass/fail gate | Priority |
| --- | --- | --- | --- | --- | --- | --- |
| A2V4-01 | Strict real-tool gate | No false signoff from fallback | Add mode policy and `AGENT2_STRICT_EDA=1` support | `strict_eda_report.json` | Fail strict if tool unavailable or fallback used | P0 |
| A2V4-02 | Verilator environment hardening | Real lint works on Windows/OSS CAD Suite | Normalize `VERILATOR_ROOT`, include path, waiver path, command capture | `verilator_lint_report.json` | 0 fatal/error; warning budget explicit | P0 |
| A2V4-03 | AST/tool-derived compile order resolver | Deterministic build order from source truth | Generate dependency graph from real RTL using Verilator `--MMD`, Yosys parse/elaboration evidence, or SV AST scanner; treat `rtl_manifest.json` as advisory only | `compile_order.f`, `compile_order_report.json`, `ast_dependency_graph.json` | Fail missing file, duplicate, cycle, unreachable top, or unproven dependency | P0 |
| A2V4-04 | Yosys syntax/synth smoke | Synthesis proof exists | Run read/synth smoke per block and top | `yosys_synth_report.json`, `synth_top.ys` | Fail parse/synth errors in strict | P0 |
| A2V4-05 | SymbiYosys smoke gate | Minimal formal proof exists before handoff | Run reset/protocol smoke subset | `formal_smoke_report.json` | Fail strict if required smoke fails/unavailable | P0 |
| A2V4-06 | CSR auto-generation and integration gate | Firmware-visible map is generated from source of truth | Run PeakRDL-regblock or compatible SystemRDL generator on Agent 1 `.rdl`; forbid hand-written CSR modules except wrappers; validate top-level instantiation and collateral alignment | `csr_codegen_report.json`, `csr_integration_report.json`, `peakrdl_regblock_provenance.json` | Fail generator error, missing provenance, hand-written CSR replacement, or bad instance/wiring | P0 |
| A2V4-07 | Handoff bundle V2 | Downstream gets evidence, not just RTL | Extend Agent2-to-3/4/5 payloads with compile/tool/CSR/protocol evidence | `agent2_handoff_bundle.json` | Schema validation required | P0 |
| A2V4-08 | Pattern Library V2 | Patterns are semantic, not token-only | Activate APB/FIFO/W1C/SRAM/timer/SECDED validators | `pattern_coverage_report.json` | Fail missing required semantic pattern | P1 |
| A2V4-09 | RTL semantic deep checks | Catch common real RTL bugs | Reset, assignment completeness, APB handshake, interrupt, memory side effects | `semantic_deep_report.json` | Fail HIGH severity findings | P1 |
| A2V4-10 | Production RTL style contract | Company-grade coding style | Enforce `default_nettype none`, no latch, no delay, no implicit nets, no forbidden constructs | `rtl_style_report.json` | Fail HIGH severity style violation | P1 |
| A2V4-11 | CDC/RDC early screening | Clock/reset risk visible before physical | Static domain model and reset crossing checks | `cdc_rdc_screen_report.json` | Fail undocumented crossing | P1 |
| A2V4-12 | Protocol contracts | Interfaces have executable expectations | Generate APB and block-level SVA-lite contracts | `interface_contracts.sv`, `protocol_contract_report.json` | Fail missing required contract | P1 |
| A2V4-13 | Repair loop V4 with LEC | Repairs are controlled, proven, and functionally safe | Detect, classify, patch, rerun exact gate, run Yosys `equiv_make`/`equiv_simple`/`equiv_status` for logic-affecting patches, rollback if worse or non-equivalent | `repair_trace.jsonl`, `repair_package.json`, `lec_equivalence_report.json` | Pass only after failing gate reruns clean and LEC passes where required | P1 |
| A2V4-14 | Negative fixture suite | Gates prove they can catch bad RTL | Add known-bad RTL fixtures | `tests/fixtures/bad_rtl/*` | Tests fail for intended reason | P1 |
| A2V4-15 | Golden fixture suite | Gates prove they do not false fail | Add known-good RTL fixtures | `tests/fixtures/golden_rtl/*` | Tests pass without waiver | P1 |
| A2V4-16 | Quality score | Release is measurable | Weighted score over contract/lint/synth/CSR/formal/handoff | `agent2_quality_score.json` | Strict score >= 85 | P2 |
| A2V4-17 | Signoff dashboard | Human reviewer can decide quickly | One-page gate/risk/action summary | `agent2_v4_signoff_dashboard.md` | Required for all strict releases | P2 |
| A2V4-18 | Toolchain reproducibility and provenance | Auditable and portable environment | Record Docker image digest or locked toolchain manifest, env roots, executable path, version, command, env, report hashes | `tool_provenance.json`, `toolchain_reproducibility_report.json` | Required in strict/nightly; fail unknown mutable environment without waiver | P2 |
| A2V4-19 | Deterministic codegen | Reproducible outputs | Stable ordering, metadata isolation, output hash | `rtl_generation_fingerprint.json` | Same input gives same content hash | P2 |
| A2V4-20 | CI profiles | Demo/dev/strict/nightly separated | Add scripts or workflows for each mode | CI logs and profile configs | Strict CI fails on fallback | P2 |

## 7. Gate hierarchy

### 7.1 P0 gates — mandatory for V4 Phase 1

| Gate | Required condition | Release impact |
| --- | --- | --- |
| Contract gate | Agent 1 contract valid and APB pinout locked | Blocks Agent 2 generation |
| Compile order gate | Complete AST/tool-derived ordered filelist, no cycles, top reachable, manifest mismatch reported | Blocks tool runs |
| Verilator gate | Real Verilator runs in strict mode and returns no fatal/error | Blocks `RTL_SIGNOFF_READY` |
| Yosys gate | Real Yosys reads and synthesizes blocks/top in strict mode | Blocks `RTL_SIGNOFF_READY` |
| CSR gate | CSR RTL generated from Agent 1 SystemRDL using PeakRDL/SystemRDL tooling; generated block is integrated and provenance is recorded | Blocks handoff |
| Formal smoke gate | Required reset/protocol smoke proofs pass or explicit waiver is approved | Blocks strict release |
| Handoff gate | Agent2-to-Agent3/4/5 bundles schema-validate and include tool evidence | Blocks downstream flow |

### 7.2 P1 gates — mandatory for V4 Phase 2/nightly

| Gate | Required condition | Release impact |
| --- | --- | --- |
| Pattern semantic gate | Required block patterns pass semantic validators | Blocks nightly signoff |
| Semantic deep gate | No HIGH severity reset/APB/assignment/interrupt/memory findings | Blocks nightly signoff |
| Style gate | No latch, implicit net, delay, incomplete assignment, forbidden construct | Blocks nightly signoff |
| CDC/RDC screen | No undocumented crossing or reset hazard | Blocks nightly signoff |
| Repair gate | Every repair has trace, diff, rerun result, LEC evidence for logic-affecting patches, rollback evidence if needed | Blocks repaired release |
| UPF/low-power gate | UPF paths, clock-gating intent, isolation, retention, level shifters, and RTL hierarchy agree when low-power intent exists | Blocks nightly signoff; blocks strict when low-power mode is enabled |
| Fixture gate | Bad RTL fails and golden RTL passes | Blocks V4 completion |

### 7.3 P2 gates — scale and governance

| Gate | Required condition | Release impact |
| --- | --- | --- |
| Dashboard gate | Reviewer-readable dashboard exists and links all reports | Blocks formal review |
| Quality score gate | Strict score >= 85, nightly score >= 90 | Blocks quality label |
| Provenance gate | Docker image digest or locked toolchain manifest, env roots, tool versions, paths, commands, environment, hashes recorded | Blocks audit label |
| Determinism gate | Same input produces same hash excluding metadata | Blocks reproducibility label |

## 8. Artifact contract

V4 must create this artifact structure under the RTL output directory.

```text
rtl/
  *.sv
  *_pkg.sv
  *_intf.sv
  rtl_manifest.json
  compile_order.f
  compile_order_report.json
  ast_dependency_graph.json
  agent2_v4_signoff_dashboard.md
  agent2_quality_score.json
  agent2_release_decision.json

rtl/reports/
  strict_eda_report.json
  verilator_lint_report.json
  yosys_synth_report.json
  formal_smoke_report.json
  csr_codegen_report.json
  csr_integration_report.json
  peakrdl_regblock_provenance.json
  semantic_deep_report.json
  pattern_coverage_report.json
  cdc_rdc_screen_report.json
  rtl_style_report.json
  protocol_contract_report.json
  tool_provenance.json
  toolchain_reproducibility_report.json
  upf_consistency_report.json
  rtl_generation_fingerprint.json

rtl/contracts/
  interface_contracts.sv
  agent2_handoff_bundle.json
  agent2_to_agent3.json
  agent2_to_agent4.json
  agent2_to_agent5.json

rtl/repair/
  repair_trace.jsonl
  repair_package.json
  lec_equivalence_report.json
  failed_gate_snapshots/
```

## 9. Quality scorecard

| Category | Weight | Strict target | Evidence |
| --- | ---: | ---: | --- |
| Contract completeness | 10 | >= 9 | Contract audit and schema validation |
| RTL style | 10 | >= 9 | Style report |
| Compile/lint | 20 | >= 18 | Compile order and Verilator report |
| Synthesis smoke | 15 | >= 13 | Yosys report |
| CSR correctness | 15 | >= 14 | CSR codegen, integration, and provenance reports |
| Protocol correctness | 10 | >= 8 | Interface contracts and protocol report |
| Formal smoke | 10 | >= 8 | SymbiYosys smoke report |
| Handoff readiness | 5 | 5 | Agent2 handoff bundle V2 |
| Trace/repair audit | 5 | >= 4 | Repair trace, LEC report where required, and provenance |

Release thresholds:

- `DEMO_PASS`: score >= 70, fallback allowed.
- `DEV_PASS_WITH_WARNINGS`: score >= 75, fallback allowed with explicit warnings.
- `RTL_SIGNOFF_READY`: score >= 85, P0 all pass, no fallback.
- `NIGHTLY_SIGNOFF_READY`: score >= 90, P0/P1 all pass, no fallback.

## 10. Roadmap phases

### Phase 0 — Baseline lock and safety net

Goal: freeze current behavior and establish measurement before strict changes.

| Task | Output | Success criteria |
| --- | --- | --- |
| Capture current Agent 2 reports | Baseline run directory and report index | Existing full regression stays green. |
| Add V4 plan to docs index if required | Documentation link | Plan discoverable by docs health checks. |
| Define modes in config constants | Mode enum or constants | `demo`, `dev`, `strict`, `nightly-real-tools` names consistent. |
| Add tests for fallback policy expectations | Initial strict policy tests | Tests describe desired fail/pass behavior before implementation. |

Exit criteria:

- Current behavior documented.
- No public API break.
- Tests can distinguish demo/dev from strict intent.

### Phase 1 — P0 strict EDA hardening

Goal: Agent 2 cannot claim strict signoff without real tools.

| Task | Output | Success criteria |
| --- | --- | --- |
| Implement strict mode policy | `strict_eda_report.json` | Strict mode fails if any required tool is unavailable or fallback is used. |
| Fix Verilator adapter environment handling | `verilator_lint_report.json` | Verilator command, include paths, waiver paths, version, stdout/stderr captured. |
| Add AST/tool-derived compile order resolver | `compile_order.f`, `compile_order_report.json`, `ast_dependency_graph.json` | All packages/interfaces/modules/top sorted from real RTL evidence; no missing/cycle/duplicate/unproven dependency. |
| Add Yosys syntax/synth smoke gate | `yosys_synth_report.json` | Top and blocks read/synth in strict mode or fail with actionable error. |
| Add formal smoke gate policy | `formal_smoke_report.json` | Required reset/protocol smoke either passes or blocks strict release. |
| Add CSR auto-generation and integration gate | `csr_codegen_report.json`, `csr_integration_report.json`, `peakrdl_regblock_provenance.json` | PeakRDL/SystemRDL-generated CSR RTL matches Agent 1 `.rdl`; only wrappers/integration are hand-authored. |
| Add handoff bundle V2 | `agent2_handoff_bundle.json` | Agent 3/4/5 bundles include compile order and tool evidence. |

Exit criteria:

- `demo` still works on no-tool machines.
- `strict` fails on no-tool/fallback machines.
- `strict` passes only when required tools really pass.
- P0 reports are generated and schema-checkable.

### Phase 2 — Semantic and pattern depth

Goal: Move from surface/token checks to block-specific semantic confidence.

| Task | Output | Success criteria |
| --- | --- | --- |
| Activate Pattern Library V2 | `pattern_coverage_report.json` | APB/FIFO/W1C/SRAM/timer/SECDED pattern requirements mapped to blocks. |
| Add semantic deep validators | `semantic_deep_report.json` | Reset, APB handshake, assignment completeness, interrupt, memory side effects checked. |
| Add production RTL style gate | `rtl_style_report.json` | No HIGH severity style violations in generated RTL. |
| Add protocol contract generation | `interface_contracts.sv`, `protocol_contract_report.json` | APB and relevant block interfaces have SVA-lite contracts. |
| Add CDC/RDC early screen | `cdc_rdc_screen_report.json` | Clock/reset domains identified; undocumented crossings fail. |
| Add UPF/low-power consistency gate | `upf_consistency_report.json` | RTL hierarchy and UPF low-power intent agree when low-power intent exists. |

Exit criteria:

- Nightly mode blocks semantic HIGH severity issues.
- Pattern checks are semantic enough to reject bad examples, not just missing tokens.
- Protocol contracts are consumable by Agent 5.

### Phase 3 — Repair loop V4

Goal: Repairs become deterministic, auditable, and gate-proven.

| Task | Output | Success criteria |
| --- | --- | --- |
| Implement finding classifier | Classified findings | Every failing gate maps to owner/rule/severity/suggested fix. |
| Implement bounded patch recipes | Patch records | Patch scope limited to affected files and rules. |
| Implement exact gate rerun | Updated gate report | Same failing gate reruns after patch and must pass. |
| Implement LEC for logic-affecting repairs | `lec_equivalence_report.json` | Yosys equivalence flow passes before any logic-affecting repair can release. |
| Implement rollback-if-worse-or-non-equivalent | Rollback record | If score worsens, new P0 fail appears, or LEC fails, patch is reverted. |
| Implement HITL escalation | HITL package | More than 5 failed repair attempts creates review package. |

Exit criteria:

- `repair_trace.jsonl` explains every repair attempt.
- No repaired RTL can release without rerunning failing gate.
- Manual review package is actionable.

### Phase 4 — Fixtures, CI, and release governance

Goal: Prove gates catch bad RTL and scale the flow into repeatable CI.

| Task | Output | Success criteria |
| --- | --- | --- |
| Add negative RTL fixtures | `tests/fixtures/bad_rtl/*` | Known bad latch/APB/reset/CSR cases fail expected gates. |
| Add golden RTL fixtures | `tests/fixtures/golden_rtl/*` | Good APB/FIFO/W1C/SRAM/timer/SECDED cases pass. |
| Add mode-specific tests | `tests/test_agent2_v4_*.py` | Demo/dev/strict/nightly behavior covered. |
| Add quality score calculator | `agent2_quality_score.json` | Release labels match score thresholds. |
| Add signoff dashboard | `agent2_v4_signoff_dashboard.md` | Reviewer can see status, risk, artifacts, and next action within 2 minutes. |
| Add reproducible toolchain provenance capture | `tool_provenance.json`, `toolchain_reproducibility_report.json` | Docker image digest or locked toolchain manifest, env roots, tool paths, versions, commands, environment, report hashes captured. |
| Add deterministic fingerprint | `rtl_generation_fingerprint.json` | Same input yields same content hash excluding metadata. |

Exit criteria:

- Bad fixtures fail for intended reasons.
- Golden fixtures pass without waiver.
- CI can run demo/dev always and strict/nightly where real tools exist.
- Reviewer dashboard is complete.

### Phase 5 — Industrial completion and feedback loop

Goal: Agent 2 participates in full chip-style closure feedback, not isolated RTL generation.

| Task | Output | Success criteria |
| --- | --- | --- |
| Feed Agent 4 timing/resource data back into Agent 2 | RTL/physical feedback report | RTL bottlenecks visible to Agent 2. |
| Feed Agent 3 coverage holes back into Agent 2 | DV feedback report | Missing observability/control hooks become RTL actions. |
| Feed Agent 5 proof failures back into Agent 2 | Formal feedback report | Assertion failures map to RTL owners. |
| Add waiver governance | `agent2_waivers.json` | Waivers require owner, reason, expiry, affected gate, risk. |
| Create V4 completion report | Completion report | All P0/P1 gates pass; score >= 90 in nightly environment. |

Exit criteria:

- Agent 2 has closed-loop feedback from DV, formal, and physical.
- Waivers are explicit and expiring.
- V4 can be marked active/completed with evidence.

## 11. Required tests

| Test file | Purpose | Minimum assertions |
| --- | --- | --- |
| `tests/test_agent2_v4_strict_eda.py` | Strict fallback policy | Strict fails on fallback; demo allows fallback. |
| `tests/test_agent2_v4_compile_order.py` | AST/tool-derived compile order resolver | Packages before users; cycles fail; manifest-only dependency claims are ignored or flagged. |
| `tests/test_agent2_v4_verilator_gate.py` | Verilator report handling | Tool unavailable/fatal/error/warning parsed correctly. |
| `tests/test_agent2_v4_yosys_gate.py` | Yosys smoke gate | Parse/synth pass/fail normalized. |
| `tests/test_agent2_v4_csr_codegen.py` | CSR code generation and integration | PeakRDL/SystemRDL generator provenance exists; hand-written CSR replacement fails; wrapper integration is valid. |
| `tests/test_agent2_v4_pattern_semantics.py` | Pattern semantic validators | Missing semantic requirement fails. |
| `tests/test_agent2_v4_handoff_bundle.py` | Downstream contract evidence | Agent2-to-3/4/5 include tool and compile evidence. |
| `tests/test_agent2_v4_negative_fixtures.py` | Gate sensitivity | Bad RTL fixtures fail intended gates. |
| `tests/test_agent2_v4_quality_score.py` | Score thresholds | Labels match threshold and P0 status. |
| `tests/test_agent2_v4_repair_trace.py` | Repair audit | Patch/rerun/rollback/HITL trace exists. |
| `tests/test_agent2_v4_lec_repair.py` | Repair equivalence | Logic-affecting repairs require passing LEC; non-equivalent repair is rejected. |
| `tests/test_agent2_v4_upf_consistency.py` | Low-power consistency | UPF hierarchy or isolation/retention mismatch fails when low-power intent exists. |
| `tests/test_agent2_v4_toolchain_reproducibility.py` | Toolchain provenance | Strict mode requires Docker digest or locked toolchain manifest plus env roots and report hashes. |

## 12. Definition of Done

Agent 2 V4 is complete only when all items below are true:

1. Default `demo` and `dev` modes keep current developer friendliness.
2. `strict` mode cannot pass if required EDA tools are missing, unhealthy, or bypassed by fallback.
3. Verilator lint runs for real in strict/nightly modes and records command, version, stdout, stderr, and parsed result.
4. Yosys syntax/synthesis smoke runs for real in strict/nightly modes.
5. SymbiYosys formal smoke either passes or creates a blocking waiver-backed failure.
6. Compile order is generated once from AST/tool evidence, not `rtl_manifest.json`, and reused by tool gates and downstream handoff.
7. CSR RTL is generated from Agent 1 SystemRDL collateral by PeakRDL/SystemRDL tooling, provenance is recorded, and integration passes.
8. Pattern Library V2 semantic validators cover APB, FIFO, W1C interrupt, SRAM latency, timer, SECDED, and crossbar where applicable.
9. Protocol contracts are generated and included in Agent 5 handoff.
10. Agent 3, Agent 4, and Agent 5 handoff bundles include strict evidence when strict mode is used.
11. Repair loop writes trace, reruns exact failing gate, runs LEC for logic-affecting patches, and rolls back worse or non-equivalent patches.
12. Negative fixtures fail and golden fixtures pass.
13. Quality score is at least 85 for `RTL_SIGNOFF_READY` and at least 90 for `NIGHTLY_SIGNOFF_READY`.
14. UPF/low-power consistency passes when low-power intent exists.
15. Tool provenance includes Docker image digest or locked toolchain manifest, env roots, tool paths, versions, commands, and report hashes.
16. Signoff dashboard gives status, risks, waivers, artifact links, and next action.
17. All existing regression tests plus V4 tests pass.

## 13. Expected end state

After V4, Agent 2 should be rated differently:

| Review angle | Current estimated score | V4 target score |
| --- | ---: | ---: |
| RTL generation framework | 8.3 | 9.0 |
| Real-tool confidence | 6.5 | 8.8 |
| Engineering signoff readiness | 6.2 | 8.5 |
| Downstream handoff confidence | 8.7 | 9.2 |
| CI/reproducibility | 6.8 | 8.6 |
| Overall Agent 2 score | 7.5 | 8.8 |

V4 does not claim tapeout signoff. V4 claims industrial-grade RTL signoff readiness for generated RTL packages in an open-source EDA environment, with honest separation between demo fallback and strict real-tool evidence.

## 14. First implementation recommendation

Implement Phase 1 first, in this order:

1. Add mode policy and strict fallback failure.
2. Fix Verilator adapter path/provenance/reporting.
3. Add AST/tool-derived compile order resolver.
4. Add Yosys smoke gate.
5. Add CSR auto-generation and integration gate.
6. Add handoff bundle V2.

Do not start Pattern Library V2 or repair loop V4 until strict mode proves that fallback cannot create a false `RTL_SIGNOFF_READY` result.

## 15. Phase carryover — unfinished items from 2026-05-20 session

This section records work that was not completed in this phase, so the next session can continue without losing context.

### 15.1 Completed during this phase

- Agent 2 V4 score path was exercised with generated IoT camera RTL.
- `semiconductor_swarm/agents/agent2_rtl/tools/verilator_adapter.py` was updated so Verilator lint materializes generated SystemVerilog into a temporary working directory before invoking the tool.
- Broken local Verilator install is now reported with explicit `provenance: degraded_tool_install` instead of silently looking like clean real-tool signoff.
- Targeted V4 regression passed: `12 passed`.
- Full regression passed: `165 passed`.

### 15.2 Not completed / must continue next phase

- [ ] Repair or reinstall OSS CAD Suite Verilator on Windows.
  - Current executable: `D:\APP\oss-cad-suite\bin\verilator_bin.exe`.
  - Current failure:
    - `Cannot find verilated_std_waiver.vlt`
    - `Cannot find verilated_std.sv`
  - Required result: Verilator lint must run for real without degraded fallback in strict/nightly mode.
- [ ] Add strict/nightly regression proving degraded Verilator blocks signoff.
  - Demo/dev may keep `degraded_tool_install` as explicit non-silent fallback.
  - `requires_real_tools=true`, `strict`, or `nightly-real-tools` must fail if Verilator is degraded, unavailable, or fallback-backed.
- [ ] Align tool health fields in `verilator_lint_report.json`.
  - Observed mismatch: `environment.status: healthy` while lint provenance is `degraded_tool_install`.
  - Required result: environment/tool/report statuses must not imply healthy real lint when include path is broken.
- [ ] Add regression for temp RTL materialization.
  - Test should prove `run_verilator_lint()` writes all in-memory SV artifacts into temp cwd and invokes Verilator from that cwd.
  - Test should cover compile order files that do not exist on disk before lint invocation.
- [ ] Re-run real-tool diagnostics after Verilator repair.
  - Command: `python scripts/check_real_tools.py`.
  - Capture tool paths, versions, env roots, and failures into plan or generated report.
- [ ] Re-run strict Agent 2 profile on clean machine/toolchain.
  - Command candidate: `python scripts/run_agent2_profile.py --strict` or equivalent supported profile.
  - Required result: no fallback can produce `RTL_SIGNOFF_READY`.
- [ ] Re-run full regression after strict/toolchain fixes.
  - Command: `pytest -q`.
  - Last known result before carryover: `165 passed in 46.82s`.

### 15.3 Known risk left open

Agent 2 can currently demonstrate `agent2_quality_score.json` with `score: 100` in demo path while local Verilator is degraded by broken include files. This is acceptable only because provenance is explicit and default mode is demo-friendly. It is not acceptable as strict/nightly real-tool signoff until the open items above are closed.
