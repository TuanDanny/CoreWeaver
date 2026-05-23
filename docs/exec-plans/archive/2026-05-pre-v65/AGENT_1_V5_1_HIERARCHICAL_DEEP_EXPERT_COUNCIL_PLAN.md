---
title: Agent 1 V5.1 Hierarchical Deep Expert Council Plan
status: active
owner: agent1-platform
type: exec-plan
last_reviewed: 2026-05-21
source_of_truth: true
---

# Agent 1 V5.1 Hierarchical Deep Expert Council Plan

## Summary
Muc tieu: nang Agent 1 tu V5 "AI-first 6 lead expert calls" len V5.1 "hierarchical deep expert council" dung nhu mot phong kien truc chip: 24 expert node day, 7 node trung gian gom cum chuyen mon, va 1 Principal Architect node cap cao. Agent 1 se co hai che do:

- `normal`: khong lap, dung 32 Codex calls cho mot lan planning.
- `deep_planning`: lap toi thieu 3 vong, it nhat 96 Codex calls, co the lap tiep neu conflict chua resolve.

Ket qua can dat:
- Agent 1 khong con dua vao template co dinh de quyet dinh architecture.
- Moi expert co nhiem vu rieng, goi Codex rieng, co evidence rieng.
- Node trung gian gom va phan bien expert output theo domain.
- Principal Architect goi Codex de tong hop, phan xu conflict, va gui feedback xuong vong lap tiep.
- Deterministic validators van la gate cuoi, khong de LLM consensus che loi.
- RAG duoc chua san qua context provider interface, chua can implement vector DB ngay.

## Operating Modes
### Normal Mode
- Dung cho workflow nhanh nhung van sau hon V5.
- Exactly 1 iteration.
- Exactly 32 Codex calls:
  - 24 leaf expert calls.
  - 7 middle manager calls.
  - 1 Principal Architect synthesis call.
- Neu deterministic gate fail, Agent 1 khong lap lai; route sang HITL/capability gap.
- Muc tieu latency: chap nhan cham hon V5, nhung predictable.

### Deep Planning Mode
- Dung cho planning nghiem tuc, yeu cau chat luong cao.
- Minimum 3 iterations.
- Minimum 96 Codex calls:
  - 24 leaf + 7 middle + 1 principal = 32 calls/iteration.
  - 32 * 3 = 96 calls minimum.
- Sau vong 3, tiep tuc lap neu con critical conflict.
- Default hard cap: 7 iterations.
- Neu den cap van con conflict critical, Agent 1 fail truoc Plan Review va emit HITL_REQUIRED.
- Token/cost khong phai blocker; van ghi telemetry de trace va debug.

## Hierarchy Design
### Leaf Expert Layer: 24 Expert Calls
Moi leaf expert nhan:
- raw requirement
- project name
- current iteration context
- feedback tu middle/principal vong truoc
- local deterministic extraction
- context provider payload, hien tai local docs/capability; sau nay RAG

24 leaf experts:
1. Requirement Intake Expert
2. Domain Classifier Expert
3. Architecture Option Expert
4. CPU ISA Expert
5. CPU Pipeline Expert
6. Reset Boot Trap Expert
7. Memory Map Expert
8. Memory Hierarchy Expert
9. Protocol AHB/APB/AXI Expert
10. Bridge Adapter Expert
11. Interconnect QoS Expert
12. Peripheral SPI Expert
13. Peripheral UART/I2C/GPIO Expert
14. Register/SystemRDL Expert
15. Firmware ABI Expert
16. DV Strategy Expert
17. Formal Property Expert
18. Physical Clock/Timing Expert
19. Power Intent Expert
20. DFT/Testability Expert
21. Safety/Security Expert
22. IP Reuse/Cost Expert
23. Downstream Agent Contract Expert
24. Plan Readability/Diagram Expert

Leaf output schema:
- `expert_id`
- `iteration`
- `domain`
- `summary`
- `decisions`
- `assumptions`
- `open_questions`
- `risks`
- `conflicts`
- `citations`
- `confidence`
- `needs_revision`
- `evidence`

### Middle Manager Layer: 7 Manager Calls
Moi middle manager chi nhan leaf outputs thuoc cum cua no, khong nhan toan bo trace neu khong can.

7 managers:
1. Requirement/Product Manager
   - Leaf: Requirement Intake, Domain Classifier, Architecture Option.
2. CPU/Memory Manager
   - Leaf: CPU ISA, CPU Pipeline, Reset Boot Trap, Memory Map, Memory Hierarchy.
3. Protocol/Interconnect Manager
   - Leaf: Protocol, Bridge Adapter, Interconnect QoS.
4. Peripheral/Register/Firmware Manager
   - Leaf: SPI, UART/I2C/GPIO, Register/SystemRDL, Firmware ABI.
5. Verification/Formal Manager
   - Leaf: DV Strategy, Formal Property.
6. Physical/Power/DFT Manager
   - Leaf: Physical Clock/Timing, Power Intent, DFT/Testability, Safety/Security.
7. Downstream Contract/Capability Manager
   - Leaf: IP Reuse/Cost, Downstream Agent Contract, Plan Readability/Diagram.

Middle output schema:
- `manager_id`
- `iteration`
- `covered_experts`
- `accepted_decisions`
- `rejected_decisions`
- `domain_summary`
- `domain_conflicts`
- `feedback_to_leaf_experts`
- `handoff_to_principal`
- `confidence`

### Principal Architect Layer: 1 Call
Principal Architect nhan:
- all 7 middle outputs
- previous principal decision
- conflict matrix
- deterministic gate report vong truoc
- raw requirement
- capability registry snapshot

Principal output schema:
- `iteration`
- `selected_architecture_candidate`
- `rejected_alternatives`
- `resolved_conflicts`
- `unresolved_conflicts`
- `feedback_to_middle_managers`
- `requirements_preserved`
- `capability_strategy`
- `plan_ready_candidate`
- `confidence`

## Iteration And Conflict Policy
### Iteration Flow
Moi iteration chay theo thu tu:
1. Build context package.
2. Run 24 leaf expert Codex calls.
3. Run 7 middle manager Codex calls.
4. Run 1 Principal Architect Codex call.
5. Build deterministic conflict matrix.
6. Generate provisional AI requirement analysis.
7. Run deterministic guardrails.
8. If mode is `normal`, stop sau vong 1.
9. If mode is `deep_planning`, lap toi thieu 3 vong.
10. Sau vong 3, stop chi khi critical conflicts = 0 va guardrails pass.

### Conflict Classes
Critical conflicts:
- raw requirement vs extracted intent
- selected architecture silently rewrites requested protocol
- selected architecture drops requested CPU width
- selected architecture drops requested peripheral
- middle managers disagree on primary bus/protocol
- capability gap exists but no bridge/HITL policy
- spec contradicts principal decision
- markdown plan contradicts spec
- stale unrequested protocol/peripheral appears in plan

Non-critical conflicts:
- naming style disagreement
- alternative architecture preference without requirement impact
- low-confidence optional feature suggestion
- open question about unspecified power/frequency/node

### Stop Conditions
`normal`:
- stop after exactly one 32-call iteration.
- if critical conflict exists, emit fail/HITL before Plan Review.

`deep_planning`:
- cannot stop before 3 iterations.
- after iteration 3, stop when:
  - critical conflicts = 0
  - deterministic gates pass
  - principal marks `plan_ready_candidate=true`
  - requirement/spec/plan consistency pass
- continue until default max 7 iterations if conflict remains.
- at max 7, emit HITL_REQUIRED with unresolved conflict matrix.

## Concurrency And Rate-Limit Policy
Agent 1 V5.1 must not execute expert calls sequentially. Leaf and middle calls are independent within their layer and must run with bounded parallelism.

### Execution Model
- Leaf layer:
  - Run 24 leaf expert Codex calls concurrently with a worker cap.
  - Default `max_concurrent_leaf_calls=8`.
  - Allowed range: 1 to 24.
  - Implementation can use `ThreadPoolExecutor` first because current Agent 1 Codex client is sync `urllib`.
  - Future async HTTP client may replace executor without changing orchestration contract.

- Middle layer:
  - Run 7 middle manager Codex calls concurrently after leaf layer completes.
  - Default `max_concurrent_middle_calls=4`.
  - Allowed range: 1 to 7.

- Principal layer:
  - Run Principal Architect call after all middle manager outputs complete.
  - Principal call remains sequential per iteration because it depends on all middle summaries and conflict matrix.

### Expected Runtime Shape
- One `normal` iteration should wait roughly for:
  - slowest bounded leaf batch group,
  - slowest bounded middle batch group,
  - one principal call,
  - deterministic validation.
- It must not wait for 24 leaf calls sequentially.
- `deep_planning` still requires at least 3 iterations and at least 96 calls, but each iteration must use bounded parallel batches.

### Endpoint Protection
- Do not fire all calls without control.
- Use bounded worker pool or semaphore.
- Default local endpoint protection:
  - `max_concurrent_leaf_calls=8`
  - `max_concurrent_middle_calls=4`
  - `expert_call_timeout_s` inherits Agent 1 LLM timeout unless mode config overrides.
  - retry policy inherits Agent 1 LLM `max_retries`.
- If local endpoint shows overload/rate-limit behavior, failed calls become structured expert failures and conflicts.

### Failure Handling
- Single non-critical leaf failure:
  - record failure in trace,
  - mark leaf output as `needs_revision=true`,
  - pass conflict to middle manager/principal.
- Critical leaf failure, such as Requirement Intake or Protocol Expert unavailable:
  - mark iteration critical conflict.
- Endpoint-wide failure threshold:
  - if more than 25% of leaf calls fail in one iteration, iteration fails as `endpoint_unstable`.
  - normal mode routes to HITL/fail before Plan Review.
  - deep mode may retry next iteration until cap.
- Middle manager failure:
  - if a manager fails, principal receives structured missing-manager conflict.
  - critical managers are Requirement/Product, Protocol/Interconnect, and Downstream Contract/Capability.
- Principal failure:
  - iteration cannot pass.
  - deep mode retries until cap.
  - normal mode fails/HITL.

### Determinism And Ordering
- Parallel execution must preserve deterministic output ordering in artifacts:
  - trace records sorted by iteration then expert/manager id before final JSON artifact emission.
  - call completion can be out of order, artifact order cannot.
- Prompt/response hashes are recorded per call.
- Runtime event stream may show completion order, but final reports must be stable.

## RAG-Ready Context Provider
Implement context access through provider interface, not direct RAG dependency.

Interface:
- `build_agent1_context_package(requirement, project_name, mode, iteration, expert_id) -> dict`
- `context_sources`: local docs, product specs, capability registry, prompt contracts, future RAG chunks.
- `source_hashes`: hash per context source.
- `rag_enabled`: false in V5.1 unless later configured.
- `rag_provider`: optional future provider name.

Policy:
- Leaf experts receive small, scoped context only.
- Middle managers receive leaf summaries and relevant capability context.
- Principal receives manager summaries, conflict matrix, capability report, and selected source hashes.
- No full large docs through prompt unless context provider marks source as compact.
- Future RAG can replace local context source without changing expert topology.

## Artifacts
New/updated artifacts:

- `agent1_deep_council_config.json`
  - mode, min iterations, max iterations, leaf expert list, cluster map, context provider config.

- `agent1_leaf_expert_trace.jsonl`
  - one record per leaf expert call.
  - includes iteration, expert_id, prompt hash, response hash, model, latency, token usage, parse status.

- `agent1_middle_manager_trace.jsonl`
  - one record per middle manager call.
  - includes covered experts and feedback to leaf layer.

- `agent1_principal_trace.jsonl`
  - one record per Principal Architect call.
  - includes selected candidate and feedback to managers.

- `agent1_conflict_matrix.json`
  - all critical/non-critical conflicts per iteration.

- `agent1_iteration_summary.json`
  - per-iteration pass/fail, resolved conflicts, new conflicts, remaining conflicts.

- `agent1_principal_decision.json`
  - final selected architecture, rejected alternatives, bridge/capability strategy, assumptions, confidence.

- `agent1_rag_context_manifest.json`
  - context provider sources and hashes; future RAG slot.

- Update `agent1_ai_requirement_analysis.json`
  - add planning mode, iteration count, leaf expert count, middle manager count, principal call count, consensus status, unresolved conflicts.

- Update `agent1_requirement_consistency_report.json`
  - include consensus and conflict status.

## Implementation Roadmap
### Phase 0 - Plan And Baseline Lock
- Write this plan and wait for approval.
- Freeze current V5 behavior: 6 Codex calls, V5 artifacts, AHB/SPI no-drift tests pass.
- Acceptance:
  - docs health passes.
  - no Agent1 code changes before approval.

### Phase 1 - Topology And Config
- Add expert topology definitions for 24 leaf experts, 7 managers, 1 principal.
- Add mode config: `normal`, `deep_planning`.
- Add iteration config: `min_iterations`, `max_iterations`.
- Add concurrency config: `max_concurrent_leaf_calls`, `max_concurrent_middle_calls`, `expert_call_timeout_s`.
- Acceptance:
  - topology has exactly 24 leaf experts.
  - cluster map covers all leaf experts exactly once.
  - normal mode plans exactly 32 calls.
  - deep mode plans at least 96 calls.
  - default worker caps are leaf=8 and middle=4.

### Phase 2 - Context Provider
- Add local context provider interface.
- Include capability registry, product specs, prompt contracts, and optional future RAG metadata.
- Acceptance:
  - provider returns scoped context per expert.
  - provider emits source hashes.
  - `rag_enabled=false` path works without vector DB.
  - future RAG provider can be injected without changing expert loop.

### Phase 3 - Leaf Expert Execution
- Implement 24 leaf Codex calls per iteration.
- Run leaf calls with bounded parallelism, not sequential loop.
- Validate each leaf output schema.
- Store leaf trace JSONL.
- Acceptance:
  - normal mode emits 24 leaf records.
  - deep mode emits 24 leaf records per iteration.
  - missing/invalid leaf output becomes conflict, not silent pass.
  - no more than `max_concurrent_leaf_calls` are active at once.
  - wall-clock behavior proves leaf calls are batched, not sequential.

### Phase 4 - Middle Manager Execution
- Implement 7 middle manager Codex calls per iteration.
- Each manager receives only assigned leaf outputs and scoped context.
- Run manager calls with bounded parallelism, not sequential loop.
- Store middle trace JSONL.
- Acceptance:
  - every leaf output is consumed by exactly one middle manager.
  - managers emit accepted/rejected decisions and feedback.
  - manager conflicts are recorded.
  - no more than `max_concurrent_middle_calls` are active at once.
  - wall-clock behavior proves middle calls are batched, not sequential.

### Phase 5 - Principal Architect Execution
- Implement Principal Architect Codex synthesis per iteration.
- Principal receives all manager outputs and conflict matrix.
- Store principal trace JSONL and final principal decision.
- Acceptance:
  - normal mode emits one principal record.
  - deep mode emits one principal record per iteration.
  - principal feedback can route back to managers and leaf experts.

### Phase 6 - Iterative Consensus Loop
- Implement loop controller.
- Normal mode stops after one iteration.
- Deep planning runs minimum 3 iterations.
- Continue after iteration 3 if critical conflicts remain.
- Hard cap default 7 iterations.
- Each iteration uses parallel leaf and middle batches.
- Acceptance:
  - deep mode cannot stop before 3 iterations.
  - conflict remaining after 3 iterations triggers additional iteration.
  - unresolved conflict at cap produces HITL_REQUIRED before Plan Review.
  - deep mode minimum 96 calls are scheduled through bounded concurrent batches.

### Phase 7 - Deterministic Guardrail Integration
- Connect principal decision to existing spec generator.
- Run V5 quality gate and requirement consistency after each iteration candidate.
- Add conflict classes for spec/plan drift.
- Acceptance:
  - LLM consensus cannot override deterministic failure.
  - stale UART/I2C/rv32 plan text still fails.
  - AHB/SPI no-drift behavior remains green.

### Phase 8 - App/Runner Event Integration
- Emit structured events for:
  - leaf expert started/completed
  - middle manager started/completed
  - principal started/completed
  - iteration started/completed
  - conflict summary
- UI can show rollup, not 96 blinking cards.
- UI receives batch-level progress:
  - leaf batch started/completed
  - middle batch started/completed
  - active/queued/completed call counts
  - endpoint overload warnings
- Acceptance:
  - Studio log shows deep planning activity.
  - Agent card remains readable.
  - no raw huge prompts/responses over JSONL.
  - UI does not flicker per 96 calls; detailed calls remain in log/filter.

### Phase 9 - Regression And UAT
- Test normal and deep modes with mocked Codex.
- Optional real local Codex smoke for normal mode.
- Deep real smoke only if user explicitly approves long run.
- Acceptance:
  - normal mode: exactly 32 calls.
  - deep mode: at least 96 calls.
  - deep mode final plan includes iteration summary and conflict resolution.

## Test Plan
Unit tests:
- `test_agent1_v51_topology_has_24_leaf_7_middle_1_principal`
- `test_agent1_v51_cluster_map_covers_all_leaf_experts_once`
- `test_agent1_v51_normal_mode_exactly_32_calls`
- `test_agent1_v51_deep_mode_minimum_96_calls`
- `test_agent1_v51_deep_mode_minimum_three_iterations`
- `test_agent1_v51_deep_mode_continues_when_critical_conflict_remains`
- `test_agent1_v51_deep_mode_hits_hitl_at_max_iterations`
- `test_agent1_v51_leaf_invalid_output_becomes_conflict`
- `test_agent1_v51_middle_feedback_routes_to_leaf`
- `test_agent1_v51_principal_feedback_routes_to_middle`
- `test_agent1_v51_context_provider_rag_disabled_local_sources`
- `test_agent1_v51_context_provider_future_rag_shape_stable`
- `test_agent1_v51_leaf_calls_are_bounded_parallel_not_sequential`
- `test_agent1_v51_middle_calls_are_bounded_parallel_not_sequential`
- `test_agent1_v51_leaf_concurrency_never_exceeds_configured_cap`
- `test_agent1_v51_middle_concurrency_never_exceeds_configured_cap`
- `test_agent1_v51_endpoint_overload_records_conflict`
- `test_agent1_v51_artifact_order_is_stable_despite_parallel_completion`

Scenario tests:
- APB UART simple.
- AHB SPI bridge.
- Pure AHB no APB bridge.
- AXI GPIO unsupported/capability gap.
- Mixed CPU + DMA + SPI + UART.
- Vague AI chip requiring clarification.
- Extreme noisy requirement with conflicting protocol hints.

Regression:
```powershell
.venv_dv\Scripts\python.exe -m pytest -q tests\test_agent1.py
.venv_dv\Scripts\python.exe -m pytest -q tests\test_swarm_graph.py
.venv_dv\Scripts\python.exe -m pytest -q tests\test_agent_pipeline.py
.venv_dv\Scripts\python.exe -m pytest -q tests\test_docs_health.py tests\test_prompt_contracts.py
```

## Required Final Results
Normal mode:
- Exactly 32 Codex calls.
- 24 leaf expert records.
- 7 middle manager records.
- 1 principal record.
- Leaf and middle calls use bounded parallelism.
- Default worker caps: leaf=8, middle=4.
- Plan generated only if deterministic gates pass.

Deep planning mode:
- At least 96 Codex calls.
- At least 3 iterations.
- Calls are scheduled in bounded concurrent batches, not sequential loops.
- Conflict matrix per iteration.
- Principal feedback loop active.
- Additional iterations when unresolved critical conflicts remain.
- HITL_REQUIRED if max iteration cap reached with unresolved critical conflicts.

Plan/output quality:
- No silent requirement rewrite.
- No stale unrelated protocol/peripheral text.
- Capability gap or bridge strategy explicit.
- RAG context manifest present and future-compatible.
- Existing V5 AHB/SPI correctness preserved.

## Assumptions
- Token/cost is acceptable and not a blocker.
- Latency is acceptable, especially in deep planning.
- Deterministic validators remain final authority.
- RAG is planned but not required for V5.1 implementation.
- Default max iterations is 7 unless user later asks to make it unbounded.
- Normal mode should be available for faster UI demos; deep planning is preferred for serious architecture signoff.
