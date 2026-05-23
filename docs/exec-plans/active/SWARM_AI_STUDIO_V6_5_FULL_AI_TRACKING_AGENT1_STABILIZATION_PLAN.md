---
title: SWARM AI STUDIO V6.5 Full AI Tracking and Agent 1 Stabilization Plan
status: active
owner: studio-agent1
type: exec-plan
created: 2026-05-23
source_of_truth: true
---

# SWARM AI STUDIO V6.5 Full AI Tracking and Agent 1 Stabilization Plan

## Summary

Muc tieu cua V6.5 la bien Studio thanh he thong de debug AI flow nhu mot ky su phan mem that:

- Tracking day du tung flow tu UI -> Backend -> Runner -> Agent 1 -> sub-AI -> artifact.
- Ghi ro moi quyet dinh AI trong Agent 1: fast router, intake experts, adjudicator, canonical normalize, defaults applied, final routing, council layers.
- Sua loi Agent 1 lam roi evidence: LLM nhan ra `32-bit CPU`, `APB`, `UART` nhung canonical cuoi bi rong `cpu/peripheral/purpose`, dan den pause clarification sai.
- Tach UI debug thanh nhieu component thuc dung, de debug va bao tri de hon.
- Khong lo secret/API key trong log, JSONL, UI, artifact.

Quyet dinh san pham da chot:

- Pure chat/social input: fast-route, 0 LLM call.
- Minimum chip-design input: neu co chip intent toi thieu va khong co contradiction, Agent 1 duoc proceed voi default an toan.
- Deep Planning van chi chay sau khi intake da `DESIGN_READY`.
- Full trace luu vao artifact; UI chi hien bounded/live summary de khong lag.

## Current Findings From Investigation

Case trong anh:

```text
Input:
Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral

Observed:
classification=DESIGN_NEEDS_CLARIFICATION
Agent1 paused before architecture planning
```

Artifact `outputs/studio_runs/123/reports/agent1/agent1_intake_router_report.json` cho thay:

- `A1.00-REQ` thay ro:
  - `cpu.architecture_width_bits = 32`
  - `bus.type = APB`
  - `external_peripherals = UART`
- `A1.00-SOC` thay ro:
  - `cpu_width_bits = 32`
  - `bus = APB`
  - `external_peripheral = UART`
- `A1.00-ADJ` thay ro:
  - `artifact = CPU architecture`
  - `cpu_width_bits = 32`
  - `bus = APB`
  - `external_peripheral = UART`

Bug chinh:

- `_canonicalize_intent()` hien chi copy dung cac key co trong `ONTOLOGY_KEYS`.
- LLM output dung nhieu ten field hop ly nhung khac schema: `cpu_width_bits`, `external_peripheral`, `bus.type`, `artifact`.
- Evidence bi roi khi normalize, lam canonical cuoi thanh:
  - `cpu = null`
  - `peripheral = null`
  - `purpose = null`
- Policy `minimum_viable_requirement` va ready gate sau do ket luan can clarification.

## Target Behavior

### Pure Chat

Examples:

```text
Ban la ai
Ban may tuoi
hom nay troi dep qua
cam on
hello
```

Expected:

- `classification = NON_DESIGN_CONVERSATION`
- `codex_call_count = 0`
- no Agent 1 council
- UI shows fast-router reason
- trace artifact written

### Minimum Design

Examples:

```text
Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral
make a simple CPU
tao UART APB controller 50MHz
```

Expected:

- `classification = DESIGN_READY`
- canonical fields preserved
- missing optional fields converted to defaults/assumptions
- Agent 1 council starts
- UI shows:
  - raw expert evidence
  - canonical before/after
  - defaults applied
  - final route

### Contradictory Design

Examples:

```text
APB only but AXI bus 100MHz
32-bit CPU but RV64 only
no UART but include UART
```

Expected:

- `classification = DESIGN_NEEDS_CLARIFICATION`
- Agent 1 council does not start
- contradiction trace written
- UI shows blocking reason

## Trace Architecture

### Trace ID Model

Every tracked event must include:

```json
{
  "trace_id": "string",
  "run_id": "string",
  "thread_id": "string",
  "flow_id": "string",
  "phase": "string",
  "agent": "string",
  "node_id": "string",
  "parent_node_id": "string|null",
  "event_type": "string",
  "status": "running|pass|fail|paused|info",
  "started_at": "iso8601|null",
  "ended_at": "iso8601|null",
  "latency_ms": "number|null"
}
```

Rules:

- `trace_id` unique per trace event.
- `flow_id` groups one logical action, such as `start_run`, `agent1_intake`, `agent1_council_iteration_1`.
- `node_id` identifies exact sub-AI or deterministic node.
- `parent_node_id` links hierarchy: UI action -> backend route -> runner -> Agent 1 -> expert.
- All secret-like fields are redacted before write or emit.
- Trace hierarchy must be reconstructable from artifacts without reading UI logs.
- Every child span must know its parent span and final outcome.

### End-to-End Agent 1 Span Map

Every Agent 1 run must produce a single reconstructable span tree from user input to Agent 1 completion.

Required span order:

```text
UI.START_CLICK
  -> UI.INPUT_CAPTURE
  -> UI.PAYLOAD_BUILD
  -> API.POST_RUNS_START
  -> API.CREDENTIAL_PREFLIGHT
  -> RUNNER.PROCESS_LAUNCH
  -> RUNNER.STDOUT_EVENT_STREAM
  -> APP.SWARM_RUNNER_START
  -> GRAPH.AGENT1_ENTER
  -> AGENT1.FAST_ROUTER
  -> AGENT1.INTAKE_COUNCIL
      -> A1.00-LANG
      -> A1.00-REQ
      -> A1.00-SOC
      -> A1.00-RISK
      -> A1.00-BRIEF
      -> A1.00-ADJ
  -> AGENT1.SCHEMA_VALIDATE
  -> AGENT1.SCHEMA_REPAIR_IF_NEEDED
  -> AGENT1.CANONICAL_NORMALIZE
  -> AGENT1.DEFAULTS_APPLY
  -> AGENT1.READY_GATE
  -> AGENT1.COUNCIL_ENTER
      -> AGENT1.LEAF_LAYER
      -> AGENT1.MIDDLE_LAYER
      -> AGENT1.PRINCIPAL_LAYER
      -> AGENT1.GUARDRAIL_LAYER
  -> AGENT1.SPEC_GENERATE
  -> AGENT1.DETERMINISTIC_TOOLS
  -> AGENT1.SCHEMA_VALIDATE_FINAL_SPEC
  -> AGENT1.ARTIFACT_WRITE
  -> AGENT1.HANDOFF_OR_PAUSE
  -> RUNNER.PROCESS_EXIT
  -> UI.STATE_REDUCE
```

If a branch is skipped, write a skip span with:

```json
{
  "event_type": "node_skipped",
  "node_id": "AGENT1.COUNCIL_ENTER",
  "skip_reason": "intake_not_ready"
}
```

### Span Payload Contract

Each span event must include these additional debug fields when available:

```json
{
  "input_hash": "sha256|null",
  "input_preview": "redacted short text|null",
  "output_hash": "sha256|null",
  "output_preview": "redacted short text|null",
  "state_before_hash": "sha256|null",
  "state_after_hash": "sha256|null",
  "decision": "string|null",
  "decision_reason": "string|null",
  "blocking_reasons": [],
  "non_blocking_warnings": [],
  "artifact_refs": [],
  "metrics": {},
  "redaction_applied": true
}
```

Rules:

- Preview fields capped for UI.
- Full raw values only in approved artifacts when safe.
- Prompt/response text stored as hashes plus redacted preview by default.
- For LLM output, store parsed JSON plus raw response hash.

### State Snapshots

Capture state snapshots at important boundaries:

```text
before_start_payload
after_backend_start
after_process_start
after_fast_router
after_intake_adjudicator
after_canonical_normalize
after_defaults_apply
after_ready_gate
after_each_council_iteration
after_final_spec_generation
after_artifact_write
after_pause_or_handoff
after_process_exit
```

Each snapshot includes:

- classification
- ready gate status
- current stage
- agent statuses
- canonical intent
- defaults applied
- unresolved conflicts
- planned next node
- artifact refs
- token/cost metrics

State snapshots must not include secrets.

### Standard Event Types

Use these event types across Studio and Agent 1:

```text
flow_start
flow_end
node_start
node_result
node_error
llm_call_start
llm_call_result
llm_call_fail
schema_validate_start
schema_validate_result
schema_repair_start
schema_repair_result
route_decision
canonical_before
canonical_after
defaults_applied
conflict_detected
validator_result
artifact_written
ui_action
api_request
api_response
process_start
process_stop_requested
process_stop_result
process_exit
state_snapshot
node_skipped
handoff_ready
pause_ready
spec_generated
tool_metric
```

### Trace Artifacts

Write these files per run:

```text
reports/traces/studio_flow_trace.jsonl
reports/traces/runner_process_trace.jsonl
reports/traces/agent1_intake_trace.jsonl
reports/traces/agent1_llm_trace.jsonl
reports/traces/agent1_canonical_trace.jsonl
reports/traces/agent1_defaults_trace.jsonl
reports/traces/agent1_council_trace.jsonl
reports/traces/agent1_guardrail_trace.jsonl
reports/traces/agent1_final_decision_trace.jsonl
reports/traces/agent1_state_snapshots.jsonl
reports/traces/agent1_artifact_lineage.jsonl
reports/traces/agent1_completion_trace.jsonl
reports/traces/trace_manifest.json
```

`trace_manifest.json` includes:

- run metadata
- artifact paths
- event counts by type
- event counts by agent/node
- error count
- warning count
- first/last timestamp
- redaction status
- completion status
- last successful span
- failed span if any
- artifact lineage root

### Artifact Lineage

Every Agent 1 artifact must declare:

- artifact name
- absolute path
- writer node id
- source span ids
- source input hashes
- schema version if structured
- content hash
- created timestamp

Required lineage targets:

```text
agent1_intake_router_report.json
agent1_requirement_citation_ledger.json
agent1_policy_matrix.json
agent1_prompt_pack_manifest.json
agent1_requirement_clarification.md
agent1_ai_requirement_analysis.json
agent1_expert_council_trace.jsonl
agent1_leaf_expert_trace.jsonl
agent1_middle_manager_trace.jsonl
agent1_principal_trace.jsonl
agent1_conflict_matrix.json
agent1_v51_guardrail_report.json
agent1_codex_evidence.json
agent1_contract_manifest.json
architecture_plan.md
```

### Completion Contract

Agent 1 is considered complete only when one of these terminal states is traced:

```text
AGENT1_COMPLETED_PLAN_REVIEW
AGENT1_COMPLETED_HANDOFF_TO_RTL
AGENT1_COMPLETED_REQUIREMENT_CLARIFICATION
AGENT1_COMPLETED_HITL_REQUIRED
AGENT1_COMPLETED_FAILED
AGENT1_STOPPED_BY_USER
```

Completion trace must include:

- terminal state
- final classification
- final canonical intent
- final artifact list
- handoff target if any
- pause action if any
- why Agent 2 can or cannot start
- total Agent 1 LLM calls
- total Agent 1 latency
- total tokens/cost
- unresolved conflicts count

### Trace Health Score

Every run gets a deterministic trace health score from 0 to 100.

Scoring:

```text
100 start
-20 missing required span
-15 missing terminal completion trace
-15 missing artifact lineage for emitted artifact
-10 parent/child span link broken
-10 state snapshot missing at required boundary
-10 secret redaction check failed
-10 unresolved duplicate critical event
-5 trace timestamp ordering violation
-5 missing token/latency on LLM node
```

Required output:

```text
reports/traces/trace_health_report.json
```

The report includes:

- score
- pass/fail
- failures
- warnings
- missing spans
- orphan spans
- duplicate critical events
- redaction audit result
- recommended fix hint

Acceptance:

- Healthy Agent 1 run must score at least 95.
- Any secret leak is automatic fail, regardless of score.

### Failure Taxonomy

All failures must use stable machine-readable codes.

Required taxonomy:

```text
UI_INPUT_INVALID
UI_STATE_RACE
API_REQUEST_FAILED
CREDENTIAL_MISSING
CREDENTIAL_INVALID
CREDENTIAL_TIMEOUT
RUNNER_LAUNCH_FAILED
RUNNER_PROCESS_EXIT_NONZERO
RUNNER_STOP_TIMEOUT
LLM_TIMEOUT
LLM_HTTP_401
LLM_HTTP_403
LLM_HTTP_429
LLM_INVALID_JSON
LLM_SCHEMA_REPAIR_FAILED
INTAKE_NO_DESIGN_INTENT
INTAKE_CONTRADICTION
CANONICAL_FIELD_DROPPED
CANONICAL_MINIMUM_INTENT_MISSING
DEFAULTS_NOT_APPLIED
READY_GATE_BLOCKED
COUNCIL_CONFLICT_UNRESOLVED
COUNCIL_ITERATION_LIMIT
SPEC_GENERATION_FAILED
SPEC_VALIDATION_FAILED
ARTIFACT_WRITE_FAILED
HANDOFF_BLOCKED
TRACE_INCOMPLETE
SECRET_REDACTION_FAILED
```

Each error trace must include:

- `error_code`
- user-facing message
- developer message
- retryable true/false
- recovery action

### Trace Invariants

Add deterministic invariant checks after each run:

```text
Every process_start has one process_exit.
Every run has exactly one terminal Agent1 completion state.
Every LLM call_start has call_result or call_fail.
Every artifact_written has artifact lineage.
Every child span parent exists.
Every ready gate has canonical_after.
Every defaults_applied has canonical_before and canonical_after.
Agent2 cannot start before Agent1 handoff_ready.
Deep Planning cannot complete before minimum iteration count.
No trace event contains api_key, authorization, Bearer token, or sk-*.
No event references project_name as technical citation.
```

Required output:

```text
reports/traces/trace_invariant_report.json
```

### Replay and Diff

Trace artifacts must support offline replay and run-to-run diff.

Replay command target:

```bash
.venv_dv\Scripts\python.exe -m studio.backend.trace_replay --run-dir outputs/studio_runs/<project>
```

Replay verifies:

- span tree integrity
- terminal state
- invariant report
- artifact hashes
- event ordering
- no secret leak

Diff command target:

```bash
.venv_dv\Scripts\python.exe -m studio.backend.trace_diff --left outputs/studio_runs/run_a --right outputs/studio_runs/run_b
```

Diff report includes:

- classification changes
- canonical changes
- defaults changes
- node latency/token changes
- prompt hash changes
- artifact hash changes
- terminal state changes

Required outputs:

```text
reports/traces/replay_report.json
reports/traces/diff_report.json
```

## Agent 1 Tracking Coverage

### Deterministic Fast Router

Track:

- raw input hash
- normalized input preview
- detected chat/social patterns
- detected design keywords
- decision:
  - `fast_non_design`
  - `requires_llm_intake`
- reason list

Expected debug row:

```json
{
  "node_id": "A1.00-FAST",
  "event_type": "route_decision",
  "decision": "requires_llm_intake",
  "design_keyword_hits": ["cpu", "apb", "uart"],
  "chat_pattern_hits": [],
  "llm_calls": 0
}
```

### LLM Intake Experts

Track each expert:

```text
A1.00-LANG
A1.00-REQ
A1.00-SOC
A1.00-RISK
A1.00-BRIEF
A1.00-ADJ
```

For each:

- prompt hash
- response hash
- model
- endpoint public
- latency
- token usage
- parse status
- repair attempted/pass
- classification
- canonical raw output
- extracted intent
- missing fields
- citations
- confidence
- contradictions/conflicts

### Schema Validation and Repair

Track:

- required fields missing
- invalid classification
- non-object canonical
- list field type errors
- repair prompt hash
- repair result status

Expected:

- Invalid JSON causes exactly one repair retry.
- Both original and repair evidence are traceable.

### Canonical Normalizer

Add deterministic canonical normalization layer after adjudicator.

Raw variants to map:

```text
cpu_width -> cpu.width_bits
cpu_width_bits -> cpu.width_bits
cpu.architecture_width_bits -> cpu.width_bits
design_target -> purpose
target -> purpose
artifact -> purpose
requested_output -> purpose/details
bus -> bus.protocol
bus.type -> bus.protocol
interconnect -> bus.protocol
external_peripheral -> peripheral[]
external_peripherals -> peripheral[]
ip -> peripheral[] or custom_ip
peripheral -> peripheral[]
clock.frequency_mhz -> clock.frequency_mhz
frequency -> clock.frequency_mhz
```

Trace must include:

- `canonical_before`
- `mapping_actions`
- `canonical_after`
- `unmapped_fields`

Expected for project `123`:

```json
{
  "canonical_after": {
    "purpose": "32-bit CPU architecture with APB bus and UART external peripheral",
    "cpu": {"width_bits": 32, "isa": "rv32imc"},
    "bus": {"protocol": "APB"},
    "peripheral": ["uart"],
    "clock": {"frequency_mhz": 50, "source": "default"},
    "node": "28nm",
    "verification_scope": "formal-first"
  }
}
```

### Defaults Engine

Apply defaults only when:

- there is design intent
- no contradiction
- at least one of CPU/peripheral/accelerator/custom_ip is present or strongly inferable

Default table:

```text
cpu.width_bits missing but CPU requested -> 32
cpu.isa missing for 32-bit CPU -> rv32imc
bus.protocol missing but APB token hit -> APB
peripheral missing but UART token hit -> uart
clock.frequency_mhz missing -> 50
node missing -> 28nm
verification_scope missing -> formal-first
power missing -> leave null, add assumption
memory missing -> deterministic architecture generator default
reset missing -> active-low synchronous deassertion assumption
```

Trace:

- defaulted field
- default value
- reason
- source:
  - `raw_keyword`
  - `domain_default`
  - `flow_default`
  - `tool_default`

Missing fields after defaults become:

```text
open_questions
assumptions
defaulted_fields
```

They must not block ready route unless marked critical.

### Final Intake Decision

Decision rules:

- `NON_DESIGN_CONVERSATION`: pure chat/social, no design keyword.
- `DESIGN_READY`: minimum design intent + no contradiction + canonical has purpose and at least one of CPU/peripheral/accelerator/custom_ip.
- `DESIGN_NEEDS_CLARIFICATION`: contradiction, invalid schema unrepaired, or truly no actionable design intent.
- `MIXED`: chat plus design intent; proceed as design if canonical passes.

Trace:

- decision
- blocking reasons
- non-blocking assumptions
- council allowed true/false

## Agent 1 Council Tracking Coverage

### Normal Mode

Track:

- intake handoff to council
- leaf layer execution
- middle layer aggregation
- principal synthesis
- deterministic validators
- guardrail result
- final spec handoff

Expected minimum normal mode trace:

```text
agent1_intake_trace.jsonl
agent1_canonical_trace.jsonl
agent1_defaults_trace.jsonl
agent1_council_trace.jsonl
agent1_guardrail_trace.jsonl
agent1_final_decision_trace.jsonl
```

### Deep Planning Mode

Track every iteration:

- iteration index
- planned call count
- actual call count
- leaf nodes started/completed
- middle nodes started/completed
- principal started/completed
- conflicts detected
- feedback sent downward
- consensus score
- reason to continue
- reason to stop

Minimum:

- deep planning runs at least 3 iterations.
- if conflicts remain, continue until max iteration or HITL.
- trace says why loop stopped.

### Node Detail Requirements

For each council node:

- input summary
- child input summaries
- accepted decisions
- rejected decisions
- modified/merged decisions
- conflicts
- feedback to children
- handoff to parent
- token usage
- latency
- artifact refs

### Agent 1 Spec Generation Tracking

After intake and council pass, track deterministic spec generation separately from LLM reasoning.

Track:

- effective requirement used after intake/defaults
- selected architecture candidate from council
- deterministic parser output
- generated CPU subsystem
- generated bus/interconnect contract
- generated peripheral list
- generated memory map
- generated reset/clock assumptions
- generated verification strategy
- PPA tool inputs and outputs
- bandwidth tool inputs and outputs
- capability assessment
- schema validation results

Required trace nodes:

```text
AGENT1.SPEC_PARSE_REQUIREMENT
AGENT1.SPEC_GENERATE_ARCHITECTURE
AGENT1.SPEC_ATTACH_TOOL_PROVENANCE
AGENT1.SPEC_ATTACH_CONTRACT_MANIFEST
AGENT1.SPEC_VALIDATE_V37
AGENT1.SPEC_VALIDATE_V4
AGENT1.PLAN_MARKDOWN_GENERATE
AGENT1.PLAN_QUALITY_VALIDATE
AGENT1.REQUIREMENT_CONSISTENCY_VALIDATE
AGENT1.ARTIFACTS_PACKAGE
AGENT1.HANDOFF_DECIDE
```

Each node must write:

- input hash
- output hash
- critical fields changed
- validation pass/fail
- error traceback tail if fail

### Agent 1 Handoff Tracking

Track final Agent 1 output boundary:

```text
pause_for_requirement_clarification
pause_for_plan_review
handoff_to_agent2
hitl_required
failed
stopped
```

For every boundary:

- stage before/after
- agent statuses before/after
- handoff payload hash
- artifact list
- downstream readiness
- human action required if any
- exact UI message

Agent 2 must only start if trace contains:

```text
AGENT1.READY_GATE pass
AGENT1.COUNCIL final_status PASS
AGENT1.SPEC_VALIDATE_V4 pass
AGENT1.HANDOFF_DECIDE handoff_to_agent2
```

If any item is missing, trace must show why Agent 2 stayed idle.

### Agent 1 Failure Tracking

Every Agent 1 exception/failure must produce:

- failing node id
- exception type
- redacted message
- traceback tail
- last successful span
- last artifact written
- retry eligibility
- user-facing recovery hint

Failure examples:

```text
LLM timeout
401/403 auth failure
invalid JSON after repair
canonical normalization cannot preserve minimum intent
conflict unresolved after max deep iterations
validator rejects final spec
artifact write fails
user stop during Agent 1
```

## Studio Web Tracking Coverage

### UI Actions

Track these UI actions:

```text
START
STOP
Approve OK
Request Change
Console command
Test Connection
Save Settings
Open Artifact
Switch Mode
Switch Sidebar View
Resize Panels
Export Debug Bundle
Refresh/Hydrate
```

For each:

- UI state before
- payload redacted
- API endpoint called
- response status
- UI state after
- error if any

### Backend API Flow

Track:

```text
POST /api/runs/start
POST /api/runs/{run_id}/stop
POST /api/runs/current/stop
POST /api/runs/{run_id}/resume
GET /api/runs/current_state
GET /api/artifacts/preview
GET /api/settings
POST /api/settings
POST /api/settings/test-connection
WS /ws/runs/{run_id}
```

### Runner Process Tracking

Track:

- command redacted
- cwd
- run id
- thread id
- project
- output dir
- pid
- start time
- stop requested time
- kill method
- exit code
- duplicate exit guard
- stdout/stderr reader state

STOP acceptance:

- UI shows `STATE stopped`
- PID cleared
- only one `PROCESS_EXIT`
- no late Agent2 event after stop

### Input-to-Agent1 Tracking Matrix

The web debug panel must be able to show this matrix for every run:

| Step | Owner | Required trace |
|---|---|---|
| User types requirement | UI | input hash, preview, length, language hint |
| User selects mode | UI | old/new mode, normal/deep |
| User clicks START | UI | payload redacted, run config |
| API receives start | Backend | request id, route span, status |
| Credential preflight | Backend | ref id, status, endpoint public, no key |
| Runner launches process | Backend | command redacted, PID, cwd |
| Runner emits process_start | Runner | PID, run id |
| App runner starts graph | App | project, thread, output dir |
| Agent1 enters planning | Agent1 | requirement hash, mode |
| Fast router decides | Agent1 | chat hits, design hits, route |
| Intake experts run | Agent1 | each expert output summary |
| Adjudicator runs | Agent1 | raw final intake |
| Canonical normalizes | Agent1 | before/after diff |
| Defaults apply | Agent1 | defaults/assumptions |
| Ready gate decides | Agent1 | pass/fail reason |
| Council runs | Agent1 | leaf/middle/principal/guardrail |
| Spec generated | Agent1 | spec hash, major fields |
| Artifacts written | Agent1 | lineage and hashes |
| Pause/handoff/fail | Agent1 | terminal state |
| UI reduces state | UI | state before/after |

### Tracking Query Requirements

Debug UI must support these user questions without opening raw code:

```text
Why did Agent 1 call LLM?
Which sub-AI classified this as design?
Which sub-AI disagreed?
Where did CPU/APB/UART evidence come from?
Which field was dropped or remapped?
Which defaults were applied?
Why did Agent 1 pause?
Why did Agent 2 not start?
How many LLM calls did Agent 1 spend?
Which node was slow?
Which node produced invalid JSON?
Which artifact came from which node?
What happened after I clicked STOP?
```

For each question, UI should point to one trace row and one artifact ref.

### Observability Dashboard Requirements

Add a compact "Trace Health" dashboard in Debug Bundle:

- current run trace health score
- terminal state
- missing spans count
- invariant failures count
- LLM call count
- total latency
- token total
- cost estimate
- slowest node
- most expensive node
- last error code
- artifact count
- redaction audit status

Add drill-down tabs:

```text
Timeline
Span Tree
Failures
Invariants
Artifacts
Diff
Replay
Cost/Latency
```

UI behavior:

- Red score if health < 80 or secret audit failed.
- Amber score if health < 95.
- Green score if health >= 95.
- Clicking any failed invariant jumps to trace row and artifact ref.

### Prompt and Response Provenance

For every LLM node, store:

- prompt template version
- prompt variable hash
- final prompt hash
- response hash
- parsed JSON hash
- schema version
- model
- endpoint public
- retry count
- repair count

Do not store raw prompt by default in UI.

Artifact storage:

```text
reports/traces/prompts/<node_id>_<span_id>.prompt.redacted.txt
reports/traces/responses/<node_id>_<span_id>.response.redacted.txt
```

These files are redacted and size-capped.

### Cost and Latency Budget Tracking

Track budget per Agent 1 run:

```text
max_llm_calls_planned
actual_llm_calls
max_wall_time_s_planned
actual_wall_time_s
max_tokens_planned
actual_tokens
estimated_cost_usd
```

Budget warnings:

- normal mode calls exceed expected
- deep planning calls below planned minimum
- one node latency > configured slow threshold
- total Agent 1 wall time > configured threshold
- token usage missing from provider

Required output:

```text
reports/traces/agent1_budget_report.json
```

### Trace Retention and Size Control

Rules:

- JSONL trace keeps full structured events.
- UI only loads bounded/summarized trace windows.
- Large fields are stored by hash + artifact ref.
- Trace files over size threshold get chunked:

```text
agent1_council_trace.part0001.jsonl
agent1_council_trace.part0002.jsonl
```

- Manifest lists chunks in order.
- Replay must support chunked traces.

## Web UI Refactor Plan

Current:

- `studio/frontend/src/main.tsx` has about 420 lines and owns too much UI/debug logic.

Refactor scope: debug-focused only.

Create components/modules:

```text
studio/frontend/src/components/TopBar.tsx
studio/frontend/src/components/Sidebar.tsx
studio/frontend/src/components/LaunchPanel.tsx
studio/frontend/src/components/StageRail.tsx
studio/frontend/src/components/AgentTimeline.tsx
studio/frontend/src/components/LogPanel.tsx
studio/frontend/src/components/RightDebugPanel.tsx
studio/frontend/src/components/ConsolePanel.tsx
studio/frontend/src/components/SettingsDialog.tsx
studio/frontend/src/components/OutputConflictDialog.tsx
studio/frontend/src/components/StatusBar.tsx
studio/frontend/src/components/Agent1IntakeTracePanel.tsx
studio/frontend/src/components/Agent1CouncilTracePanel.tsx
studio/frontend/src/components/NodeDetailPanel.tsx
studio/frontend/src/hooks/useRunSocket.ts
studio/frontend/src/hooks/useRunController.ts
studio/frontend/src/hooks/useResizablePanels.ts
studio/frontend/src/stores/traceStore.ts
```

Keep:

- existing styling theme
- existing behavior
- existing API surface

Change:

- debug panels read trace store/artifacts
- log panel can filter by trace event types
- node detail panel can show intake/canonical/default/council nodes

## Phase Roadmap

### Phase 0 - Baseline and Repro Harness

Tasks:

- Capture current failing cases into tests.
- Add fixture for project `123` style input.
- Add fixture for pure chat, mixed, complete design, contradiction.
- Add expected trace contracts before implementation.

Deliverables:

- Test file updates for Agent1 intake and Studio backend.
- No behavior change yet.

Result required:

- Failing tests prove current bug:
  - minimum CPU/APB/UART design pauses incorrectly.
  - canonical drops evidence.

### Phase 1 - Trace Data Model and Redaction

Tasks:

- Add trace event helper.
- Add span tree parent/child model.
- Add state snapshot serializer.
- Add artifact lineage serializer.
- Add completion contract constants.
- Add redaction for:
  - api key
  - authorization
  - bearer token
  - secret fields
- Add JSONL append writer.
- Add trace manifest generator.
- Add failure taxonomy constants.
- Add trace health score calculator.
- Add invariant checker framework.

Deliverables:

- Trace helper usable by backend, runner, Agent 1.
- `agent1_state_snapshots.jsonl`
- `agent1_artifact_lineage.jsonl`
- `agent1_completion_trace.jsonl`
- `trace_health_report.json`
- `trace_invariant_report.json`
- Unit tests for redaction and JSONL schema.

Result required:

- Trace events can be written without leaking secrets.
- One run can be reconstructed as a span tree from artifacts.
- Trace health can fail loudly when required spans are missing.

### Phase 2 - Studio Flow Tracking

Tasks:

- Track UI actions in frontend store.
- Track backend route entry/exit.
- Track runner process start/stop/exit.
- Track WebSocket replay/hydrate.
- Track UI state reducer before/after for critical events.
- Track input capture, mode selection, payload build, and API request/response.
- Keep bounded UI memory.

Deliverables:

- `studio_flow_trace.jsonl`
- `runner_process_trace.jsonl`
- visible UI debug filters.

Result required:

- Start/Stop/Test Connection flow can be debugged from one trace timeline.
- UI can answer what happened from click to backend response.

### Phase 3 - Agent1 Fast Router Tracking

Tasks:

- Add trace for pure chat detection.
- Add trace for design keyword hits.
- Add trace for mixed input routing.

Deliverables:

- `agent1_intake_trace.jsonl` includes `A1.00-FAST`.

Result required:

- Pure chat cases show 0 LLM calls and explicit reason.

### Phase 4 - LLM Intake Expert Tracking

Tasks:

- Track all 5 experts plus adjudicator.
- Track prompt/response hashes.
- Track schema validation and repair.
- Track token/latency.

Deliverables:

- `agent1_llm_trace.jsonl`
- UI list of expert outputs.

Result required:

- Each sub-AI output can be inspected independently.

### Phase 5 - Canonical Normalizer Fix

Tasks:

- Implement schema variant mapping.
- Preserve evidence from all expert/adjudicator outputs.
- Add deterministic keyword fallback from raw requirement.
- Emit before/after trace.

Deliverables:

- `agent1_canonical_trace.jsonl`
- tests for schema variants.

Result required:

- `32-bit CPU/APB/UART` maps to standard canonical schema.

### Phase 6 - Defaults Engine and Ready Gate

Tasks:

- Add default-fill layer.
- Split missing fields into:
  - blocking missing fields
  - non-blocking assumptions
  - defaulted fields
  - open questions
- Update ready gate.

Deliverables:

- `agent1_defaults_trace.jsonl`
- report includes defaults and assumptions.

Result required:

- Minimum design proceeds to council when no contradiction exists.

### Phase 7 - Council Tracking Expansion

Tasks:

- Track leaf/middle/principal/guardrail nodes.
- Track iteration feedback in Deep Planning.
- Track conflicts and consensus.
- Track reason to continue/stop.

Deliverables:

- richer `agent1_council_trace.jsonl`
- `agent1_guardrail_trace.jsonl`
- `agent1_final_decision_trace.jsonl`

Result required:

- Deep Planning debug shows every node and iteration reason.

### Phase 7B - Agent1 Spec, Artifact, and Handoff Tracking

Tasks:

- Track spec generation after council.
- Track deterministic tool inputs/outputs.
- Track schema validation for final spec.
- Track plan markdown generation and quality validation.
- Track every Agent 1 artifact write with lineage.
- Track terminal state:
  - plan review pause
  - requirement clarification pause
  - handoff to Agent2
  - HITL required
  - failed
  - stopped

Deliverables:

- `agent1_state_snapshots.jsonl`
- `agent1_artifact_lineage.jsonl`
- `agent1_completion_trace.jsonl`
- UI terminal-state explanation.

Result required:

- User can see exactly why Agent 1 completed, paused, failed, or handed off.
- Agent 2 never starts unless Agent 1 completion trace proves handoff readiness.

### Phase 7C - Replay, Diff, Health, and Budget Reports

Tasks:

- Implement trace replay verifier.
- Implement trace diff between two runs.
- Generate health score report.
- Generate invariant report.
- Generate Agent 1 budget report.
- Add prompt/response redacted provenance files.
- Add trace chunking support for large JSONL files.

Deliverables:

- `trace_health_report.json`
- `trace_invariant_report.json`
- `replay_report.json`
- `diff_report.json`
- `agent1_budget_report.json`
- `reports/traces/prompts/*.redacted.txt`
- `reports/traces/responses/*.redacted.txt`

Result required:

- One command can prove whether trace is complete and secret-safe.
- Two runs can be compared without manually reading logs.
- Debug UI can show health/cost/latency status.

### Phase 8 - Web Debug UI Split

Tasks:

- Extract debug-focused React components.
- Add trace panels:
  - Studio Flow
  - Agent1 Intake
  - LLM Calls
  - Canonical Normalize
  - Defaults
  - Council
  - Spec/Handoff
  - Artifact Lineage
  - Trace Health
  - Replay
  - Diff
  - Cost/Latency
  - Errors
- Add artifact hydration for trace JSONL.
- Add query-oriented debug cards:
  - Why paused?
  - Why Agent2 not started?
  - Which node was slow?
  - Which default was applied?
  - Which invariant failed?
  - What changed from previous run?

Deliverables:

- smaller `main.tsx`
- new components/hooks/stores.

Result required:

- UI can debug Agent1 AI path without reading raw files manually.
- UI can follow input-to-Agent1-completion path step by step.
- UI can show trace health, replay result, run diff, and budget warnings.

### Phase 9 - Tracking UAT Matrix

Tasks:

- Run matrix manually and automated where possible:
  - pure chat
  - minimum design
  - complete design
  - mixed
  - contradiction
  - bad endpoint
  - bad key
  - Stop during LLM call
  - browser refresh during run
- Save UAT report artifact.

Deliverables:

- `outputs/uat_evidence/studio_v65_tracking_<timestamp>/uat_report.json`
- screenshots if useful.

Result required:

- Every tested case has trace artifacts and UI result.

### Phase 10 - Regression and Documentation

Tasks:

- Run full tests.
- Update docs/plan status.
- Add short operator guide:
  - where trace files live
  - how to read debug bundle
  - what each classification means

Deliverables:

- test results
- trace guide doc

Result required:

- Full repo passes.
- User can reproduce debug flow.

## Test Plan

### Backend/Agent Tests

Commands:

```bash
.venv_dv\Scripts\python.exe -m pytest -q tests\test_agent1_v64_intake.py
.venv_dv\Scripts\python.exe -m pytest -q tests\test_agent1_v51_deep_council.py
.venv_dv\Scripts\python.exe -m pytest -q tests\test_studio_backend.py
.venv_dv\Scripts\python.exe -m pytest -q
```

Required cases:

- pure chat uses 0 calls
- weather/social input uses 0 calls
- minimum CPU/APB/UART design becomes ready
- mixed social/design becomes ready
- contradiction blocks
- invalid JSON repair tracked
- no secret in traces
- Stop emits one process exit
- refresh hydrate keeps state
- span tree is complete from UI input to Agent1 terminal state
- every Agent1 artifact has lineage
- terminal completion trace explains:
  - why paused
  - why failed
  - why handed off
  - why Agent2 did or did not start
- state snapshots exist at ready gate, council exit, spec generation, and terminal state
- trace health report scores healthy run >= 95
- invariant checker catches missing parent span
- invariant checker catches Agent2 starting before Agent1 handoff
- replay fails if artifact hash changed
- diff report shows canonical/default changes between two runs
- budget report warns when planned/actual call counts diverge

### Frontend Tests

Commands:

```bash
npm run test --prefix studio\frontend
npm run build --prefix studio\frontend
```

Required checks:

- trace filters exist
- no raw API key field
- bounded log store remains
- event dedupe remains
- debug panels hydrate artifacts
- component split compiles
- debug UI can filter:
  - Studio Flow
  - Agent1 Intake
  - LLM Calls
  - Canonical
  - Defaults
  - Council
  - Spec/Handoff
  - Artifact Lineage
  - Trace Health
  - Replay
  - Diff
  - Cost/Latency
- query cards render answers for:
  - Why paused?
  - Why Agent2 not started?
  - Which node was slow?
  - Which default was applied?
  - Which invariant failed?
  - What changed from previous run?

### Manual UAT

Inputs:

```text
Ban la ai
Ban may tuoi
hom nay troi dep qua
Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral
Generate a 32-bit CPU using APB with UART, 50MHz, 28nm
Ban la ai, tao UART APB controller 50MHz
APB only but AXI bus 100MHz
```

Expected:

- UI status matches route.
- log shows sub-flow.
- trace artifact exists.
- debug panel can explain decision.

## Acceptance Criteria

- Case in screenshot/project `123` no longer false-pauses.
- Agent 1 preserves evidence from experts into canonical schema.
- Agent 1 exposes every sub-AI decision through trace artifact.
- Deep Planning trace covers all iterations and node layers.
- Studio web can debug Start/Stop/Auth/Agent1 flow without guessing.
- Debug trace covers full path from UI input to Agent 1 terminal completion.
- Every Agent 1 sub-AI, deterministic gate, validator, tool, artifact write, and handoff decision has trace evidence.
- Debug UI can answer why Agent 1 paused, why it proceeded, why it failed, or why Agent 2 did not start.
- Trace health, invariant, replay, diff, and budget reports are generated per run.
- Any missing required span or secret leak is caught automatically.
- No secret appears in UI/log/artifact.
- Full tests pass:

```text
python pytest full suite pass
frontend smoke pass
frontend build pass
manual UAT pass
```

## Out of Scope

- Full Agent 2 AI tracking upgrade.
- Changing Agent 2 RTL generation behavior.
- New RAG implementation.
- New visual redesign beyond debug-focused component split.
- Exposing raw API key in browser.

## Risks and Mitigations

- Risk: trace noise too large.
  - Mitigation: full JSONL artifact, bounded UI summary.
- Risk: default-fill over-assumes.
  - Mitigation: defaults only when no contradiction and minimum design intent exists.
- Risk: schema variants keep expanding.
  - Mitigation: keep unmapped fields trace and add tests per new variant.
- Risk: UI refactor breaks behavior.
  - Mitigation: debug-focused split only, preserve API and visual behavior.

## Approval Gate

Do not implement until user approves this plan.

After approval, execute phase by phase and verify each phase before moving to the next.
