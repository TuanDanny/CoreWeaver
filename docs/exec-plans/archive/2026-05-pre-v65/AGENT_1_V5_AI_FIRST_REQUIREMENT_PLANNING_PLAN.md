---
title: Agent 1 V5 AI-First Requirement Planning Plan
status: active
owner: agent1-platform
type: exec-plan
last_reviewed: 2026-05-21
source_of_truth: true
---

# Agent 1 V5 AI-First Requirement Planning Plan

## Summary
Muc tieu: sua tan goc loi Agent 1 dang "AI hieu dung nhung deterministic template ghi de sai". Agent 1 V5 phai hanh xu nhu mot nhom kien truc su chip dung AI: boc tach Project Requirement, phan cong nhieu chuyen gia, tong hop nhieu output, chon architecture phu hop, kiem tra kha nang downstream, roi moi sinh `architecture_plan.md` va contract cho Agent 2/3/4/5.

Bug bang chung tu run `outputs/app_runs/cpu_soc`:
- User requirement: `Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral`.
- `agent1_codex_response.md` hieu dung: `64-bit CPU`, `AMBA AHB`, `SPI`.
- `architecture_plan.md` lai ghi `64-bit APB fabric`, `APB master`, va acceptance criteria thua ve `UART`/`I2C`.
- `agent1_plan_quality_report.json` van pass, vi quality gate chi check UART/I2C khi duoc detect, chua check bus drift, negative tokens, va stale template text.

Ket qua mong muon:
- Agent 1 dung AI de boc tach requirement va tao plan, khong dung template APB co dinh lam su that.
- Deterministic code chi lam guardrail, schema, capability check, va consistency gate.
- Neu downstream chua support day du AHB, Agent 1 phai noi ro capability gap/bridge strategy, khong duoc silently doi AHB thanh APB.
- Kien truc phai mo de sau nay them RAG/context provider ma khong pha pipeline.

## Technical Direction
Agent 1 V5 gom 4 lop ro rang:

1. AI Requirement Intelligence Layer
   - Goi Codex nhieu lan theo vai tro chuyen gia.
   - Moi expert tra ve JSON co schema, citation tu raw requirement, confidence, assumptions, open questions.
   - Khong cho expert tu tinh PPA/bandwidth numeric; numeric van do tool deterministic tinh.

2. Principal Architect Synthesis Layer
   - Tong hop output tu cac expert.
   - Chon architecture cuoi cung.
   - Neu expert bat dong, phai ghi tradeoff va ly do chon.
   - Tao `agent1_ai_requirement_analysis.json` lam source trung gian giua requirement va spec.

3. Capability And Compatibility Layer
   - Doc capability registry cua downstream Agent 2/3/4/5.
   - Biet protocol/IP nao dang support end-to-end.
   - Neu requirement can capability chua support, phai chon bridge/adapter strategy hoac HITL/capability gap.

4. Deterministic Guardrail Layer
   - Validate extraction vs raw requirement.
   - Validate selected architecture vs generated spec.
   - Validate generated spec vs markdown plan.
   - Reject plan neu co stale/hardcoded noi dung khong lien quan.

## Key Artifacts
Them artifact Agent 1:

- `agent1_ai_requirement_analysis.json`
  - `schema_version: agent1.ai_requirement_analysis.v1`
  - raw requirement
  - extracted intents: CPU, bus, peripherals, clock, power, node, constraints
  - expert outputs
  - selected architecture
  - rejected alternatives
  - assumptions/open questions
  - citations
  - confidence

- `agent1_expert_council_trace.jsonl`
  - Mot record moi expert call.
  - Khong ghi full prompt neu qua lon; prompt/response hash, model, latency, token usage.
  - Khong leak API key.

- `agent1_capability_assessment.json`
  - Requested capabilities.
  - Supported downstream capabilities.
  - Unsupported/partial capabilities.
  - Bridge strategy hoac HITL reason.

- `agent1_requirement_consistency_report.json`
  - Raw requirement vs AI extraction.
  - AI extraction vs spec.
  - Spec vs markdown plan.
  - Negative token/stale text gate.

- `agent1_plan_quality_report.json`
  - Nang cap tu V1 len V2.
  - Giu backward-compatible fields neu tests hien co can.
  - Them bus/protocol/peripheral/negative-token checks.

## Expert Council Design
Moi expert la mot Codex call rieng, co prompt ngan va structured output:

- Requirement Intake Expert
  - Extract exact user intent.
  - Phan biet explicit requirement, inferred assumption, unknown.
  - Example: `AHB` la explicit, khong duoc thay bang `APB`.

- Protocol And Interconnect Expert
  - Phan tich AHB/APB/AXI/Wishbone/native bus.
  - De xuat bus topology, bridge, arbitration, error response.
  - Neu downstream chua support full protocol, ghi bridge/capability gap.

- CPU And Memory Expert
  - CPU width, ISA proposal, reset vector, memory hierarchy, boot memory, SRAM/ROM/cache assumptions.
  - Khong duoc default `rv32` khi requirement la `64-bit CPU`.

- Peripheral And Register Expert
  - SPI/UART/I2C/GPIO/register map theo peripheral duoc yeu cau.
  - Khong them UART/I2C acceptance criteria cho SPI-only requirement.

- Verification And Formal Expert
  - Acceptance criteria theo dung protocol/IP da chon.
  - AHB plan thi formal/DV criteria phai noi AHB hoac bridge boundary, khong noi APB-only.

- Downstream Compatibility Expert
  - Doc capability registry.
  - Danh gia Agent 2/3/5 co generate/prove/test duoc khong.
  - Dua ra route: supported, bridge-supported, unsupported-HITL.

- Principal Architect
  - Tong hop tat ca expert.
  - Tao selected architecture.
  - Neu dung bridge, ghi ro "AHB primary system bus, APB peripheral sub-bus behind AHB-to-APB bridge".
  - Neu pure unsupported, fail/pause truoc Plan Review.

## Capability Registry
Them registry local, sau nay thay bang RAG/context provider ma khong doi interface:

- Interface toi thieu:
  - `get_agent_capabilities(agent_id) -> dict`
  - `assess_requirement_capability(requirement_analysis) -> dict`

- Noi dung ban dau:
  - Agent 2: APB RTL generation supported; AHB full RTL not supported; bridge-boundary collateral partially supported.
  - Agent 3: APB cocotb/scoreboard supported; AHB full DV not supported.
  - Agent 5: APB formal collateral supported; AHB full property set not supported.
  - Agent 4: mostly protocol-agnostic collateral, but depends on generated RTL.

- Policy:
  - Requirement `APB`: normal APB path.
  - Requirement `AHB`: default practical strategy la AHB primary bus + AHB-to-APB peripheral bridge, neu user khong cam bridge.
  - Requirement `pure AHB/no APB bridge`: HITL/capability gap until Agent 2/3/5 AHB upgrade.
  - Requirement protocol unknown: Agent1 hoi clarification thay vi chon silent default neu design depends on it.

## Spec And Plan Contract Changes
Mo rong Agent 1 spec:

- `requirements.extracted_intents`
  - `cpu_width_bits`
  - `requested_bus_protocol`
  - `external_peripherals`
  - `explicit_constraints`
  - `unknowns`

- `bus_architecture`
  - `primary_protocol`
  - `peripheral_protocol`
  - `bridges`
  - `masters`
  - `slaves`
  - `error_response`
  - `ordering_model`

- `compatibility_strategy`
  - `mode`: `native_supported`, `bridge_supported`, `unsupported_hitl`
  - `reason`
  - `downstream_impacts`

- `capability_gaps`
  - list of unsupported requested capabilities.

Backward compatibility:
- Keep existing `bus_topology` for current Agent 2/3/5 consumers.
- If bridge strategy selected:
  - `bus_topology.protocol` can remain the downstream generation protocol for Agent2 APB-side collateral.
  - `bus_architecture.primary_protocol` must be `AHB`.
  - `architecture_plan.md` must make boundary explicit.
- No downstream agent may infer that `bus_topology.protocol=APB` means user requested APB when `bus_architecture.primary_protocol=AHB`.

## Plan Generation Rules
`architecture_plan.md` phai sinh tu selected architecture, khong tu text template co dinh.

Required sections:
- Executive Summary
- Raw Requirement
- Requirement Extraction Table
- AI Expert Council Summary
- Selected Architecture
- Rejected Alternatives
- CPU Subsystem
- Bus/Interconnect Architecture
- Bridge/Adapter Strategy, neu co
- Peripheral/Register Plan
- Downstream Capability Assessment
- Assumptions And Open Questions
- Downstream Acceptance Criteria

Forbidden stale behavior:
- Khong ghi `APB fabric` neu selected primary bus la AHB, tru khi dang noi `APB peripheral sub-bus behind bridge`.
- Khong ghi `APB master` cho CPU neu CPU la AHB master.
- Khong ghi `rv32` khi CPU width la 64.
- Khong ghi UART/I2C register/acceptance criteria neu requirement chi co SPI.
- Khong ghi acceptance criteria ve protocol/IP khong nam trong selected architecture.

## Validation Gates
Them `agent1_requirement_consistency_report.json` voi checks:

- `raw_requirement_extracted`
  - CPU width, bus protocol, peripheral list khop raw text.

- `extraction_to_spec_consistent`
  - Spec khong doi AHB thanh APB ma khong co bridge/capability strategy.
  - Spec khong mat SPI.

- `spec_to_plan_consistent`
  - Markdown plan co primary protocol dung.
  - Diagram, tables, acceptance criteria cung noi mot kien truc.

- `negative_token_clean`
  - SPI-only khong co UART/I2C stale acceptance.
  - 64-bit khong co rv32 stale assumption.

- `downstream_capability_declared`
  - Unsupported/partial support phai xuat hien trong plan.

- `codex_expert_evidence_present`
  - Moi expert co model, latency, prompt hash, response hash, token usage neu endpoint tra ve.

Fail policy:
- Bat ky check critical fail thi Agent1 fail truoc Plan Review.
- Khong cho plan sai vao UI de user approve nham.

## Roadmap
### Phase 0 - Evidence Freeze
- Ghi lai bug evidence tu `cpu_soc`.
- Them failing tests cho AHB/SPI case truoc khi sua.
- Acceptance:
  - Test moi fail tren code hien tai vi APB-only/stale UART/I2C/rv32 drift.
  - `history.md` co evidence, khong ghi API key.

### Phase 1 - AI Requirement Analysis Contract
- Tao schema/dataclass/helper cho `agent1_ai_requirement_analysis/v1`.
- Mock Codex expert outputs trong tests.
- Principal Architect tong hop selected architecture.
- Acceptance:
  - Mocked AHB/SPI input tao extraction dung.
  - Missing expert output/citation fail.
  - Token/evidence fields present or `usage_status=not_reported_by_endpoint`.

### Phase 2 - Capability Registry
- Them local capability registry va assessment artifact.
- Support policy APB native, AHB bridge, pure AHB unsupported-HITL.
- Acceptance:
  - AHB requirement returns bridge-supported by default.
  - Pure AHB/no bridge returns unsupported HITL/capability gap.
  - Registry interface khong phu thuoc RAG implementation.

### Phase 3 - Spec Generator Refactor
- Generate spec from AI analysis, not hardcoded APB template.
- Them `bus_architecture`, `compatibility_strategy`, `capability_gaps`.
- SPI register map day du khi SPI duoc request.
- Acceptance:
  - 64-bit AHB SPI spec has CPU 64, AHB primary bus, SPI peripheral.
  - Bridge strategy keeps APB-side downstream compatibility without hiding AHB.
  - Existing APB UART/I2C tests van pass.

### Phase 4 - Plan Markdown Refactor
- Sinh plan tu selected architecture.
- Remove stale APB/UART/I2C hardcoded lines.
- Mermaid diagram the hien dung AHB/bridge/SPI.
- Acceptance:
  - `cpu_soc` plan khong con APB-only.
  - No UART/I2C in SPI-only acceptance criteria.
  - No rv32 assumption in 64-bit plan.

### Phase 5 - Quality Gate V2
- Nang `build_plan_quality_report` va `validate_plan_quality`.
- Them negative-token, bus drift, extraction/spec/plan consistency checks.
- Acceptance:
  - Bad plan with AHB raw + APB-only markdown fails.
  - Bad plan with SPI raw + UART/I2C stale text fails.
  - Good APB UART and AHB SPI bridge plans pass.

### Phase 6 - Swarm/App Integration
- Runner/UI show Agent1 expert council events.
- Plan Preview hien Downstream Capability Assessment.
- Agent1 pause/fail truoc Plan Review neu consistency gate fail.
- Acceptance:
  - Studio run `cpu_soc` shows expert actions and correct preview.
  - Agent2 receives compatible bridge/downstream contract.

### Phase 7 - Regression And UAT
- Chay unit/integration/docs tests.
- Chay mocked Codex UAT cho:
  - APB UART
  - AHB SPI
  - AXI GPIO unsupported/needs strategy
  - vague AI chip requiring clarification
  - extreme mixed requirement with multiple peripherals
- Acceptance:
  - No stale protocol/peripheral text.
  - No silent protocol rewrite.
  - Existing APB flow not broken.

## Test Plan
Unit tests:
- `test_agent1_ai_extracts_64bit_ahb_spi`
- `test_agent1_ahb_spi_plan_uses_ahb_not_apb_only`
- `test_agent1_spi_only_plan_rejects_uart_i2c_stale_text`
- `test_agent1_64bit_plan_rejects_rv32_stale_assumption`
- `test_agent1_capability_registry_selects_ahb_to_apb_bridge`
- `test_agent1_pure_ahb_no_bridge_routes_capability_gap`
- `test_agent1_quality_gate_rejects_raw_to_spec_bus_drift`
- `test_agent1_quality_gate_rejects_spec_to_plan_drift`
- `test_agent1_expert_evidence_redacts_api_key`

Regression commands:
```powershell
.venv_dv\Scripts\python.exe -m pytest -q tests\test_agent1.py
.venv_dv\Scripts\python.exe -m pytest -q tests\test_swarm_graph.py
.venv_dv\Scripts\python.exe -m pytest -q tests\test_agent_pipeline.py
.venv_dv\Scripts\python.exe -m pytest -q tests\test_docs_health.py tests\test_prompt_contracts.py
```

Manual Studio UAT:
- Requirement: `Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral`.
- Expected:
  - Plan says AHB primary bus.
  - SPI appears as requested peripheral.
  - Bridge/capability strategy explicit if APB-side downstream is used.
  - No unrelated UART/I2C/rv32 stale content.
  - Agent1 expert council events visible in log.

## Risks And Mitigations
- Risk: More Codex calls increase latency/cost.
  - Mitigation: expert prompts are compact; evidence stores hashes; UI Burn Rate already exists.

- Risk: AI outputs inconsistent expert opinions.
  - Mitigation: Principal Architect synthesis plus deterministic consistency gate.

- Risk: Downstream agents are APB-centric.
  - Mitigation: AHB bridge strategy for practical flow; pure AHB routes to HITL/capability gap until downstream upgrade.

- Risk: Future RAG changes break prompts.
  - Mitigation: Agent1 consumes context through capability/context provider interface, not direct hardwired RAG behavior.

## Assumptions
- Agent1 may call Codex multiple times per planning run.
- Deterministic tools remain final authority for numeric estimates.
- Current repo downstream support is APB-heavy; full AHB RTL/DV/Formal is not implemented yet.
- User intent has priority over existing APB template defaults.
- This plan only writes the upgrade plan. Implementation waits for approval.
