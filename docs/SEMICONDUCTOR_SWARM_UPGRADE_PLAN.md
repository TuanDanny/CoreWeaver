# Semiconductor Swarm AI — Advanced Upgrade & Debug Plan

> Baseline source: `semiconductor_swarm_ai.md` v3.0 — Formal-First + HITL Code Overwrite.
> Goal: nâng hệ thống từ deterministic prototype lên engineering-grade semiconductor swarm: ổn định hơn, debug nhanh hơn, signoff rõ hơn, tool-gated hơn.

## 1. Executive Summary

Hệ thống hiện đã có nền tảng tốt:

- Agent 1 tạo architecture spec, khóa APB pinout, dùng tool cho PPA/bandwidth.
- Agent 2 sinh SystemVerilog RTL theo contract.
- Agent 5 chạy formal-first, sinh SVA + SymbiYosys collateral.
- Agent 3 sinh Cocotb/Pytest DV collateral.
- Agent 4 sinh Quartus FPGA backend collateral.
- LangGraph orchestration có HITL pause/resume, checkpoint SQLite, auto-debug loop.

Điểm nâng cấp trọng tâm:

1. Biến generated collateral thành real executable signoff flow.
2. Tăng độ sâu formal, DV, timing debug.
3. Thêm Golden Synthesizable Micro-Patterns DB đúng tinh thần `semiconductor_swarm_ai.md`.
4. Chuẩn hóa contract, manifest, trace, reproducibility.
5. Xây auto-debug thông minh hơn: từ lỗi tool → root cause → patch intent → regression.

## 2. Current State Audit

| Area | Hiện trạng | Đánh giá |
| --- | --- | --- |
| Agent 1 | Deterministic architect, PPA/bandwidth tool-called | Tốt |
| Agent 2 | APB RTL generator, self-check, debug report | Tốt, cần pattern DB |
| Agent 5 | SVA + `.sby`, formal-first gate | Tốt, cần property taxonomy sâu hơn |
| Agent 3 | Cocotb/Pytest collateral | Tốt, nhưng real DV chưa full do thiếu Verilator |
| Agent 4 | Quartus collateral + report parser | Tốt, cần critical path parser nâng cao |
| Orchestrator | LangGraph HITL + debug loop | Tốt, cần event trace + strict signoff |
| Toolchain | Formal OK, Quartus OK, DV thiếu Verilator | Cần hardening |
| Tests | Pipeline + graph pass | Tốt |

Latest known checks:

```bash
python -m pytest tests/test_agent_pipeline.py tests/test_swarm_graph.py -q
# 6 passed
```

```bash
python scripts/check_real_tools.py
# formal: OK
# quartus: OK
# dv: missing verilator
```

## 3. Key Gaps To Fix

### Technical Review Notes — corrections after re-check

The plan is technically sound overall, but several details need tightening before implementation:

- **Quartus detection must include `quartus_sta`, not only `quartus_sh`.** Current real compile path calls both `quartus_sh --flow compile` and `quartus_sta`; strict tool detection should mark Quartus group incomplete if STA runner is missing.
- **DV runner should not hard-code only Verilator.** Verilator remains default for CI, but design should support a simulator enum/fallback (`verilator`, `icarus`, `questa/modelsim`) and report unsupported feature limits. Icarus can be smoke-only because SystemVerilog/cocotb support is narrower than Verilator/Questa.
- **Waiver model should cover all real-tool gates, not only Quartus.** Strict signoff should allow explicit approved waivers for formal, DV, or Quartus when tool access is unavailable; every waiver must carry risk, owner, scope, expiry, and block `SIGNOFF_READY` if expired.
- **JSON Schema adds dependency risk.** If using `jsonschema`, add it to project requirements/CI setup; otherwise implement lightweight in-repo validators to avoid hidden dependency failures.
- **Pattern DB should be “approved source for risky/reusable RTL constructs,” not “only source for all RTL.”** Agent 2 still needs deterministic glue/top-level generation. Enforce patterns for APB register files, CDC, FIFO, DMA FSM, interrupt sticky/clear, SRAM wait-state, and timing pipelines.
- **Formal liveness/deadlock claims need assumptions and bounded depth.** Avoid overclaiming unbounded liveness with SymbiYosys smoke flow; use bounded response properties plus clear fairness/environment assumptions.
- **Coverage extraction depends on simulator support.** Verilator coverage requires compile flags and `verilator_coverage`; ModelSim/Questa coverage uses different commands. Report coverage as unavailable unless tool-specific evidence exists.
- **Critical path parsing should target Quartus TimeQuest report sections.** Generic regex for `Setup Slack` is not enough; parse source node, destination node, launch/capture clocks, data delay, logic/routing split, and slack where present.
- **Auto patching timing by adding generic pipeline can break latency-visible protocols.** Patch intent must include allowed latency changes, APB read latency policy, and regression/formal checks before accepting any timing fix.
- **Generated artifacts should include source-role hash.** Hash content plus role (`rtl`, `tb`, `formal`, `fpga`) and origin agent to prevent same filename/content ambiguity across directories.

### G1 — Real DV not fully ready

`cocotb` and `make` exist, but `verilator` may be missing from PATH. Generated tests exist, but full automatic real simulation gate should not claim pass until simulator run succeeds or an approved DV waiver exists.

### G2 — Strict signoff needs stronger gating

Current packaging can produce reports without mandatory real DV/formal/Quartus result depending on flags. Strict mode should require:

- real formal pass,
- real DV pass,
- Quartus compile,
- explicit approved waiver for any unavailable real-tool gate,
- artifact hashes,
- tool versions,
- reproducible command log.

### G3 — Formal depth and property classes need expansion

Current formal collateral is sanity-oriented. Need classified properties:

- reset convergence,
- APB protocol compliance,
- no X propagation assumptions,
- liveness/deadlock freedom,
- bounded response,
- register write/read consistency,
- FIFO/DMA ordering,
- interrupt sticky/clear behavior,
- low-power clock/reset assumptions.

### G4 — Timing closure intelligence too shallow

Quartus parser extracts high-level metrics. Need critical path intelligence:

- from/to registers,
- hierarchy block,
- logic levels,
- fanout,
- routing delay vs logic delay,
- setup/hold split,
- suggested fix intent.

### G5 — Auto-debug loop rule-based

Need root-cause classifier that maps evidence to patch intent:

- formal counterexample → missing reset/default/handshake guard,
- DV failure → APB protocol/data mismatch/latency issue,
- timing failure → pipeline/retime/fanout split/register duplication,
- synthesis failure → unsupported SV/package/import/width mismatch.

### G6 — Golden Micro-Patterns DB missing

`semiconductor_swarm_ai.md` explicitly bans raw SV LRM RAG and requires curated synthesizable patterns. Need `patterns/` with reviewed `.sv` templates and metadata.

### G7 — Observability missing

Need trace for each run:

- agent start/end,
- input hashes,
- output hashes,
- tool commands,
- return codes,
- parsed metrics,
- HITL decisions,
- debug iterations.

## 4. Upgrade Tracks

## Track A — Toolchain Hardening

### Actions

- Add `scripts/install_verilator_windows.md` or scripted detection guide.
- Extend `scripts/check_real_tools.py` to detect simulator alternatives: Verilator, Icarus, Questa/ModelSim.
- Extend Quartus detection to require both `quartus_sh` and `quartus_sta` for real compile+STA signoff.
- Add `semiconductor_swarm/tools/dv_runner.py`:
  - writes RTL/TB to run dir,
  - runs selected simulator command, default `make SIM=verilator`,
  - captures logs,
  - captures wave paths,
  - parses pass/fail.
- Add tests with mocked subprocess.

### Target files

- `semiconductor_swarm/tools/tool_detection.py`
- `semiconductor_swarm/tools/dv_runner.py`
- `scripts/check_real_tools.py`
- `tests/test_real_dv_tools.py`

### Acceptance

```bash
python scripts/check_real_tools.py
python -m pytest tests/test_real_dv_tools.py
```

## Track B — Golden Synthesizable Micro-Patterns DB

### Actions

Create curated pattern library:

```text
patterns/
  README.md
  pattern_apb_slave_register_file.sv
  pattern_apb_ready_error.sv
  pattern_fsm_3process.sv
  pattern_sync_reset_pipeline.sv
  pattern_cdc_2ff_sync.sv
  pattern_async_fifo_gray.sv
  pattern_dma_descriptor_fsm.sv
  pattern_interrupt_sticky_clear.sv
  pattern_sram_controller_waitstate.sv
  pattern_mac_array_pipeline.sv
  metadata.json
```

Add pattern validator:

- no `initial`, `#delay`, `$display` in RTL patterns,
- uses `logic`, `always_ff`, `always_comb`,
- includes reset policy,
- includes short design note,
- distinguishes synthesizable RTL patterns from simulation/formal-only helper patterns.

### Target files

- `patterns/*`
- `semiconductor_swarm/tools/pattern_loader.py`
- `tests/test_patterns.py`

### Acceptance

```bash
python -m pytest tests/test_patterns.py tests/test_agent2.py
```

## Track C — Agent Contract Strengthening

### Actions

- Add JSON Schema contracts for handoffs.
- Add dependency plan for `jsonschema` or use in-repo lightweight validators.
- Validate all agent outputs before next agent runs.
- Fail fast with actionable error messages.

Proposed files:

```text
contracts/
  architecture_spec.schema.json
  rtl_files.schema.json
  formal_files.schema.json
  dv_files.schema.json
  physical_files.schema.json
```

Add validator:

```text
semiconductor_swarm/tools/contract_validator.py
```

### Acceptance

```bash
python -m pytest tests/test_prompt_contracts.py tests/test_agent_pipeline.py
```

## Track D — Real DV Enablement

### Actions

- Generate executable Makefile per block plus top-level regression Makefile.
- Add APB bus functional model helper.
- Add latency-tolerant scoreboards.
- Add simulator-specific coverage extraction summary only when coverage tool evidence exists.
- Save `results.xml` or JSON pass/fail.

Advanced ideas:

- randomized APB wait-state injection,
- back-to-back transfer stress,
- reset during transaction,
- invalid address/error response tests,
- DMA/memory ordering tests,
- interrupt clear/sticky tests.

### Target files

- `semiconductor_swarm/agents/agent3_dv/dv_engineer.py`
- `semiconductor_swarm/tools/dv_runner.py`
- `tests/test_agent3.py`
- `tests/test_real_dv_tools.py`

### Acceptance

```bash
python -m pytest tests/test_agent3.py tests/test_real_dv_tools.py
```

## Track E — Formal Verification Upgrade

### Actions

- Add property taxonomy generator.
- Add formal coverage intent file.
- Add bounded proof depth policy per block.
- Parse failing assertions into structured root cause.
- Mark liveness/deadlock properties as bounded unless fairness assumptions and proof depth are explicit.

Property classes:

| Class | Example |
| --- | --- |
| Reset | outputs known after reset |
| APB safety | `pready_o` stable rules |
| Register consistency | write then read same value |
| Liveness | request eventually completes |
| Deadlock | FSM cannot stay stuck in busy forever |
| X safety | no unknown control outputs under assumptions |
| Ordering | DMA descriptors retire in order |

### Target files

- `semiconductor_swarm/agents/agent5_formal/formal_verifier.py`
- `semiconductor_swarm/tools/symbiyosys_runner.py`
- `semiconductor_swarm/tools/formal_property_classifier.py`
- `tests/test_agent5.py`

### Acceptance

```bash
python -m pytest tests/test_agent5.py tests/test_real_formal_tools.py
```

## Track F — Quartus Timing Closure Intelligence

### Actions

- Extract detailed critical path from `.sta.rpt`.
- Parse TimeQuest details where present: source node, destination node, clocks, logic delay, routing delay, data arrival/required time, slack.
- Classify timing failure:
  - setup slack,
  - hold slack,
  - fanout,
  - routing dominated,
  - logic depth dominated,
  - unconstrained path.
- Convert classification to Agent 2 patch intent:
  - add pipeline stage,
  - split combinational mux,
  - register outputs,
  - duplicate high-fanout enable,
  - add false/multicycle path only with explicit rule.
- Reject auto pipeline patches unless latency/protocol impact is declared safe and regression gates pass.

### Target files

- `semiconductor_swarm/tools/quartus_runner.py`
- `semiconductor_swarm/agents/agent4_physical/physical_designer.py`
- `semiconductor_swarm/swarm_graph.py`
- `tests/test_agent4.py`

### Acceptance

```bash
python -m pytest tests/test_agent4.py tests/test_swarm_graph.py
```

## Track G — Advanced Auto-Debug Loop

### Actions

Add `semiconductor_swarm/debug/root_cause_classifier.py`.

Input evidence:

- formal report,
- DV log,
- Quartus timing report,
- synthesis errors,
- current RTL hash,
- iteration count.

Output patch intent:

```json
{
  "category": "TIMING_SETUP",
  "confidence": 0.92,
  "target_block": "mac_array",
  "fix_type": "PIPELINE_CRITICAL_PATH",
  "evidence": ["setup_slack_ns=-0.42", "critical_path=mac_array reg0_q -> prdata_o"],
  "allowed_actions": ["add_stage_1_pipeline", "register_prdata_o"],
  "forbidden_actions": ["rename_ports", "change_apb_pinout"]
}
```

Rules:

- never rename APB ports,
- never remove assertions to pass formal,
- never weaken tests silently,
- after 5 iterations pause HITL,
- if slack < -1.0ns pause HITL.

### Acceptance

```bash
python -m pytest tests/test_swarm_graph.py
```

## Track H — HITL UX Upgrade

### Actions

- Add concise review bundle:
  - changed files,
  - failure root cause,
  - suggested patch,
  - exact resume command.
- Add `reports/hitl_review.md`.
- Add `reports/debug_iteration_N.md`.
- Add stale context clearing confirmation after human overwrite.

### Acceptance

Human can open one file and decide:

- approve,
- reject,
- patch manually,
- resume from human files.

## Track I — CI, Regression, Strict Signoff

### Actions

Add regression levels:

| Level | Command | Purpose |
| --- | --- | --- |
| L0 | `pytest tests/test_agent*.py` | fast unit |
| L1 | `pytest tests/test_agent_pipeline.py tests/test_swarm_graph.py` | graph/pipeline |
| L2 | real formal smoke | SBY/Yosys/Z3 |
| L3 | real DV smoke | Cocotb/Verilator |
| L4 | Quartus compile | FPGA backend |

Add signoff scorecard:

```text
reports/signoff_scorecard.md
reports/signoff_manifest.json
reports/tool_versions.json
reports/artifact_hashes.json
reports/run_trace.jsonl
```

Strict signoff rule:

```text
SIGNOFF_READY only if:
  architecture_valid == true
  rtl_self_check.pass == true
  formal_real.pass == true or waiver.formal.approved == true
  dv_real.pass == true or waiver.dv.approved == true
  quartus.pass == true or waiver.quartus.approved == true
  all waivers are unexpired and include owner/risk/scope
  hitl_approved == true
```

## Track J — Long-Term ASIC/OpenROAD Path

### Actions

- Keep Quartus as FPGA-first backend.
- Add OpenROAD only after FPGA path stable.
- Add ASIC collateral later:
  - SDC,
  - floorplan Tcl,
  - liberty selection,
  - power intent skeleton,
  - CDC/RDC checks.

Do not start ASIC path until Tracks A-I stable.

## 5. Priority Matrix

| Priority | Item | Impact | Difficulty |
| --- | --- | --- | --- |
| P0 | Install/detect Verilator + real DV runner | Very high | Medium |
| P0 | Strict signoff manifest | Very high | Medium |
| P0 | Event trace JSONL | High | Low |
| P1 | Formal property taxonomy | Very high | Medium |
| P1 | Quartus critical path parser | Very high | Medium |
| P1 | Root-cause classifier | Very high | Medium |
| P2 | Golden Micro-Patterns DB | Very high | High |
| P2 | HITL review bundle | High | Low |
| P3 | Dashboard | Medium | Medium |
| P4 | OpenROAD path | High | High |

## 6. Concrete Implementation Phases

### Phase 0 — Freeze Baseline

- [ ] Run full tests.
- [ ] Save current known-good tool report.
- [ ] Save current generated artifact hashes.
- [ ] Add baseline note to `reports/`.

Commands:

```bash
python -m pytest tests
python scripts/check_real_tools.py
```

### Phase 1 — Make DV Real

- [ ] Install Verilator or add supported simulator fallback.
- [ ] Add `dv_runner.py`.
- [ ] Add mocked tests.
- [ ] Add real smoke command.
- [ ] Add DV result into manifest.

### Phase 2 — Strengthen Signoff

- [ ] Add `signoff_scorecard.md`.
- [ ] Add `tool_versions.json`.
- [ ] Add `artifact_hashes.json`.
- [ ] Add `run_trace.jsonl`.
- [ ] Enforce strict signoff gate.

### Phase 3 — Deep Formal

- [ ] Add property taxonomy.
- [ ] Increase per-block proof policy.
- [ ] Add structured counterexample parser.
- [ ] Add formal root-cause mapping.

### Phase 4 — Timing Closure Intelligence

- [ ] Parse detailed Quartus STA report.
- [ ] Classify critical path.
- [ ] Generate patch intent.
- [ ] Feed Agent 2 pipeline/fanout fix safely.

### Phase 5 — Golden Patterns

- [ ] Add curated `patterns/` library.
- [ ] Add pattern metadata.
- [ ] Add pattern lint checks.
- [ ] Make Agent 2 use patterns as allowed source.

### Phase 6 — Advanced Debug Orchestration

- [ ] Add root-cause classifier.
- [ ] Add debug iteration reports.
- [ ] Add HITL overwrite resume from ground-truth files.
- [ ] Add stale context invalidation.

### Phase 7 — UX + Dashboard

- [ ] Add single HTML or Markdown dashboard.
- [ ] Add timeline view.
- [ ] Add pass/fail badges.
- [ ] Add exact rerun commands per failure.

## 7. Special High-End Ideas

### Idea 1 — Evidence-Driven Debug Memory

Store every failed run as evidence, not chat history:

```json
{
  "run_id": "...",
  "artifact_hash": "...",
  "failure_class": "FORMAL_APB_STABILITY",
  "tool_log_hash": "...",
  "fix_applied": "register_pready_o",
  "result_after_fix": "PASS"
}
```

Benefit: avoids AI stale context, enables deterministic learning from tool evidence.

### Idea 2 — Hardware Safety Policy Engine

Add hard deny rules:

- cannot delete failing assertions,
- cannot weaken coverage targets,
- cannot rename public ports,
- cannot change clock/reset semantics without HITL,
- cannot mark signoff ready with missing tool result.

### Idea 3 — Multi-Simulator DV Abstraction

Support:

- Verilator for fast open-source CI,
- Icarus for simple smoke,
- Questa/ModelSim GUI for waveform debug.

### Idea 4 — Formal + Simulation Cross-Link

When formal finds counterexample, auto-generate a Cocotb reproducer seed.

When Cocotb finds bug, auto-generate formal cover/assertion candidate.

### Idea 5 — Timing-Aware RTL Templates

Patterns include timing variants:

- area-optimized,
- speed-optimized,
- low-power,
- FPGA-friendly.

Agent 2 chooses variant based on Agent 4 feedback.

### Idea 6 — Signoff Waiver System

If Quartus cannot run or target board unavailable, require waiver:

```json
{
  "waiver_id": "QRT-001",
  "scope": "quartus_compile",
  "reason": "license unavailable",
  "risk": "timing not proven",
  "owner": "human",
  "expires": "2026-06-01"
}
```

No silent pass.

## 8. Final Master Plan

Recommended order:

1. **Fix real DV gap**: install/detect Verilator, add `dv_runner.py`.
2. **Make signoff honest**: strict manifest, tool versions, hashes, trace.
3. **Improve formal**: property taxonomy + structured failure classification.
4. **Improve timing closure**: parse critical path + generate safe patch intents.
5. **Build Golden Micro-Patterns DB**: force Agent 2 to use reviewed RTL patterns.
6. **Upgrade auto-debug**: root-cause classifier + safety policy engine.
7. **Improve HITL UX**: review bundle, debug reports, stale context clearing.
8. **Add CI levels**: L0-L4 regression gates.
9. **Only then expand ASIC/OpenROAD**.

## 9. Definition Of Done

System considered upgraded when:

- [ ] `python -m pytest tests` passes.
- [ ] `python scripts/check_real_tools.py` shows DV/Formal/Quartus groups available or documented approved waiver.
- [ ] Real formal smoke passes.
- [ ] Real DV smoke passes.
- [ ] Quartus compile produces parsed timing/resource result.
- [ ] `SIGNOFF_READY` impossible without required gates.
- [ ] Every generated artifact has hash, role, and origin agent.
- [ ] Every failure has root-cause category and next action.
- [ ] HITL review can resume from human-edited source safely.
- [ ] Agent 2 uses approved synthesizable patterns for risky/reusable constructs while deterministic glue/top-level code remains contract-validated.

## 10. Immediate Next Actions

- [ ] Create `semiconductor_swarm/tools/dv_runner.py`.
- [ ] Extend `scripts/check_real_tools.py` for simulator fallback detail.
- [ ] Add `reports/signoff_scorecard.md` generation.
- [ ] Add `run_trace.jsonl` events in `swarm_graph.py`.
- [ ] Add `patterns/` starter database.
- [ ] Add `root_cause_classifier.py`.
- [ ] Add focused tests for each upgrade.
