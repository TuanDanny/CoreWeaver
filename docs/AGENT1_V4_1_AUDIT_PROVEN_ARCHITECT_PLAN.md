# Agent 1 V4.1 Audit-Proven Architect Plan

> Status: approved for phased implementation  
> Scope: Agent 1 only. Agent 2/3/4/5 contracts stay backward compatible.  
> Baseline: Agent 1 V4 trace/ledger/replay/schema work.  
> Goal: raise Agent 1 toward 9.8-9.9/10 by adding semiconductor-correctness proofs, stronger provenance, risk scoring, trade-study evidence, and adversarial tests.

## 1. Prime Rules

- AI operates tools; AI does not self-calculate PPA or bandwidth.
- `calculate_ppa()` and `calculate_bandwidth()` remain the only numeric PPA/bandwidth sources.
- APB slave pinout stays locked.
- Agent 2 cannot rename ports.
- Formal-first remains required.
- Human-in-the-loop is required for unresolved HIGH risk, unsafe convergence, repeated repair, or ambiguous architecture.

## 2. V4.1 Upgrade Layers

### 2.1 Semiconductor proof report

Add deterministic proof artifacts for:

- APB address decode disjointness.
- 4KB region alignment and positive ranges.
- register offset alignment, width legality, reset value fit.
- IRQ W1C/read-clear semantics and enable/mask companion.
- sensitive register write-only/no-readback/zeroize/privilege protection.
- CDC/RDC contract consistency.
- formal intent coverage for APB, register side effects, IRQ, DMA, SRAM, accelerator blocks.

Artifact: `agent1_v41_proof_report.json`.

### 2.2 Risk register and confidence gate

Add deterministic risk register:

- PPA/power-budget risk.
- APB contract risk.
- memory-map/register risk.
- CDC/RDC risk.
- security risk.
- verification/formal risk.
- physical/timing risk.
- firmware ambiguity risk.

Artifact: `agent1_v41_risk_register.json`.

Gate:

- any unresolved HIGH risk -> HITL.
- confidence below threshold -> HITL.
- proof failure -> HITL/reject before downstream handoff.

### 2.3 Architecture trade study

Generate deterministic candidate profiles:

- low_power
- balanced
- performance

Each option uses deterministic tool calls only for PPA/bandwidth. Select feasible option via deterministic tie-break.

Artifact: `agent1_v41_trade_study.json`.

### 2.4 Formal intent synthesis

Agent 1 emits property intent, not SVA implementation:

- APB no-overlap/no-spurious-select.
- register reset/RO/W1C semantics.
- IRQ clear/enable behavior.
- DMA bounded completion when present.
- SRAM bounds/no write outside selected region when present.
- accelerator security intent when AES/key material present.

Artifact field: `spec["formal_intent"]`.

### 2.5 V4.1 scorecard

Add machine-readable scorecard and markdown summary covering:

- schema status.
- proof status.
- provenance status.
- trace/replay status.
- downstream contract status.
- risk/HITL status.

Artifact: `agent1_v41_scorecard.md`.

## 3. Implementation Order

1. Add `proofs_v41.py` with deterministic proof functions.
2. Attach `formal_intent`, proof report, risk register, trade study, scorecard to Agent 1 artifacts.
3. Extend V4 schema gate to require V4.1 fields when present and reject malformed proof/risk payloads.
4. Add replay verification for V4.1 proof and risk hashes.
5. Add adversarial tests for mutation catches.
6. Run `python -X utf8 -m pytest tests/test_agent1.py -q`.
7. Run `python -X utf8 -m pytest -q`.

## 4. Acceptance Criteria

- Existing Agent 1 tests remain green.
- New V4.1 tests prove proof report catches address/register/security mutations.
- No Agent 2/3/4/5 contract break.
- V4 audit artifacts still pass.
- Replay still detects spec mutation.
- Agent 1 output includes V4.1 proof/risk/trade-study artifacts.
