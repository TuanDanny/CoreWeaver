---
title: Swarm-Wide Contract, Isolation, and Agent 6-Ready Plan
status: draft
owner: semiconductor-swarm
type: exec-plan
last_reviewed: 2026-05-18
source_of_truth: false
supersedes:
  - docs/exec-plans/active/AGENT1_TO_AGENT2_CONTRACT_AND_ISOLATION_PLAN.md
related_tests:
  - tests/test_agent_pipeline.py
  - tests/test_swarm_graph.py
  - tests/test_docs_health.py
---

# Swarm-Wide Contract, Isolation, and Agent 6-Ready Plan

Status: draft for review  
Owner: Semiconductor Swarm AI  
Scope: planning only; no production code change before approval  
Supersedes: `docs/exec-plans/active/AGENT1_TO_AGENT2_CONTRACT_AND_ISOLATION_PLAN.md`

## 1. Goal

Build a versioned, swarm-wide contract architecture for all current agents and future Agent 6 Wiki/Docs.

Current agents:

```text
Agent 1: System Architect
Agent 2: RTL Designer
Agent 3: DV Engineer
Agent 4: Physical Designer
Agent 5: Formal Verifier
```

Future agent:

```text
Agent 6: Wiki/Docs/Knowledge Publisher
```

Target outcomes:

- Every agent boundary uses explicit contract payloads.
- Every contract has stable `contract_version`.
- Every consumer fails fast on invalid input.
- Every agent can run in isolation with mock contract input.
- Whole swarm emits machine-readable artifact index.
- Agent 6 can consume one stable swarm index, not scrape random files.
- Future agents can attach without breaking existing agents.

## 2. Problem With Narrow Agent 1 → Agent 2 Plan

Old plan only covered:

```text
Agent 1 -> Agent 2
```

That is not enough because real flow is:

```text
Agent 1 -> Agent 2 -> Agent 3 -> DV reports
                  \-> Agent 4 -> Physical reports
                  \-> Agent 5 -> Formal reports
All agents -> Swarm artifact index -> Agent 6 Wiki/Docs
```

Risks if only Agent 1 → Agent 2 is fixed:

- Agent 3 still consumes RTL without strict manifest.
- Agent 4 still guesses top module, clocks, constraints.
- Agent 5 still infers formal targets from loose files.
- Reports stay inconsistent.
- Agent 6 must scrape docs/logs/output folders.
- Isolation tests cover only one edge, not full swarm.

## 3. Strategy

Use strategy: **contract bus first, graph rewrite later**.

Do not rewrite production graph immediately. Add contracts and manifests incrementally:

1. Create shared contract package.
2. Add schema + semantic validators.
3. Make agents emit contract JSON artifacts.
4. Make consumers validate contract if present.
5. Keep legacy fallback during transition.
6. Add isolated runners per agent.
7. Later, migrate graph state to contract envelopes.

This reduces breakage risk.

## 4. Design Principles

### 4.1 Contract is API

Agent output consumed by another agent must be stable API payload, not incidental Python dict.

### 4.2 Strict by version

Each contract version is immutable:

```text
agent1_to_agent2/v1
agent2_to_agent3/v1
agent2_to_agent4/v1
agent2_to_agent5/v1
agent3_result/v1
agent4_result/v1
agent5_result/v1
swarm_artifact_index/v1
swarm_to_docs_agent/v1
```

Future versions may extend/change behavior without mutating v1.

### 4.3 Two validation layers

Validation has two layers:

1. JSON Schema: required fields, types, enums, nested shape.
2. Python semantics: cross-field invariants and design rules.

### 4.4 Producer owns output, consumer validates input

- Producer validates before emitting.
- Consumer validates before executing.
- Invalid contract fails fast with exact path and reason.

### 4.5 Agent 6 consumes swarm index, not internals

Agent 6 must consume stable artifacts:

```text
swarm_artifact_index/v1
agent*_result/v1
agent*_handoff/v1
```

It must not depend on internal agent modules.

## 5. Planned Files

### 5.1 Contract package

```text
semiconductor_swarm/contracts/__init__.py
semiconductor_swarm/contracts/common.py
semiconductor_swarm/contracts/registry.py
semiconductor_swarm/contracts/envelope.py
semiconductor_swarm/contracts/artifacts.py
semiconductor_swarm/contracts/validators.py
```

### 5.2 Schemas

```text
semiconductor_swarm/contracts/schemas/agent1_to_agent2.schema.json
semiconductor_swarm/contracts/schemas/agent2_to_agent3.schema.json
semiconductor_swarm/contracts/schemas/agent2_to_agent4.schema.json
semiconductor_swarm/contracts/schemas/agent2_to_agent5.schema.json
semiconductor_swarm/contracts/schemas/agent3_result.schema.json
semiconductor_swarm/contracts/schemas/agent4_result.schema.json
semiconductor_swarm/contracts/schemas/agent5_result.schema.json
semiconductor_swarm/contracts/schemas/swarm_artifact_index.schema.json
semiconductor_swarm/contracts/schemas/swarm_to_docs_agent.schema.json
```

### 5.3 Debug runners

```text
debug_runners/test_agent1_isolated.py
debug_runners/test_agent2_isolated.py
debug_runners/test_agent3_isolated.py
debug_runners/test_agent4_isolated.py
debug_runners/test_agent5_isolated.py
debug_runners/test_agent6_wiki_isolated.py
```

### 5.4 Tests

```text
tests/test_swarm_contract_registry.py
tests/test_agent1_to_agent2_contract.py
tests/test_agent2_to_agent3_contract.py
tests/test_agent2_to_agent4_contract.py
tests/test_agent2_to_agent5_contract.py
tests/test_agent_result_contracts.py
tests/test_swarm_artifact_index_contract.py
tests/test_agent_isolation_runners.py
tests/test_agent6_ready_contract.py
```

### 5.5 Generated docs

```text
docs/generated/swarm-contract-index.md
docs/generated/swarm-artifact-index-example.json
docs/generated/agent6-docs-input-example.json
```

## 6. Contract Package API

Main imports:

```python
from semiconductor_swarm.contracts import (
    ContractEnvelope,
    validate_contract,
    validate_envelope,
    build_artifact_index,
)
```

Main API:

```python
validate_contract(contract_version: str, payload: dict) -> dict
validate_envelope(envelope: dict) -> dict
get_schema(contract_version: str) -> dict
list_contracts() -> list[str]
```

Canonical constants:

```python
AGENT1_TO_AGENT2_V1 = "agent1_to_agent2/v1"
AGENT2_TO_AGENT3_V1 = "agent2_to_agent3/v1"
AGENT2_TO_AGENT4_V1 = "agent2_to_agent4/v1"
AGENT2_TO_AGENT5_V1 = "agent2_to_agent5/v1"
AGENT3_RESULT_V1 = "agent3_result/v1"
AGENT4_RESULT_V1 = "agent4_result/v1"
AGENT5_RESULT_V1 = "agent5_result/v1"
SWARM_ARTIFACT_INDEX_V1 = "swarm_artifact_index/v1"
SWARM_TO_DOCS_AGENT_V1 = "swarm_to_docs_agent/v1"
```

## 7. Contract Envelope

Each handoff can be wrapped in a common envelope:

```json
{
  "envelope_version": "contract_envelope/v1",
  "contract_version": "agent2_to_agent3/v1",
  "producer": "agent2",
  "consumer": "agent3",
  "run_id": "...",
  "project_name": "...",
  "payload": {},
  "artifacts": [],
  "trace": {
    "created_at": "...",
    "agent_version": "...",
    "source_files": []
  }
}
```

Envelope rules:

- `contract_version` selects payload schema.
- `producer` and `consumer` must match expected edge.
- `artifacts[*].path` must be relative to run output root unless explicitly absolute.
- `payload` must pass versioned contract validation.

## 8. Contract Map

### 8.1 Agent 1 → Agent 2: Architecture Handoff

Contract:

```text
agent1_to_agent2/v1
```

Purpose: Agent 2 generates RTL from architecture spec.

Required payload fields:

- `contract_version`
- `project_name`
- `target_node`
- `isa`
- `core_config.frequency_mhz`
- `accelerator`
- `ppa_estimate`
- `bandwidth_estimate`
- `memory_map`
- `bus_topology`
- `ip_blocks`
- `clock_domains`
- `constraints`
- `interfaces.apb_slave`

Semantic rules:

- Project name safe for SystemVerilog prefix.
- IP block names unique.
- Memory map keys match IP block names.
- Memory ranges do not overlap.
- APB interface matches canonical contract.
- `constraints.agent2_port_renaming_allowed is False`.
- Clock/reset policy explicit.

Architecture constraints for this edge:

- Do not duplicate hardware math inside contract validators. Extract/reuse address parsing, 4KB alignment, and overlap checks from Agent 1 proof code into `semiconductor_swarm/utils/hardware_math.py`.
- Agent 1 proof/audit code and Agent 1 → Agent 2 contract validators must call the same shared hardware math functions.
- Agent 2 isolation must use production `build_swarm_graph()` with a controlled start/resume at `agent2_rtl`; do not create a fake mini `StateGraph` in `debug_runners/test_agent2_isolated.py`.
- Use dataclass-first contract validation with `Agent1ToAgent2ContractV1.__post_init__`; JSON Schema is optional interop/documentation and must not duplicate semantic math.
- Use `tests/fixtures/golden_spec_v1.json` as canonical mock input; tests and runners must not hardcode giant mock JSON payloads.

### 8.2 Agent 2 → Agent 3: DV Handoff

Contract:

```text
agent2_to_agent3/v1
```

Purpose: Agent 3 generates testbench, tests, scoreboard, and coverage from RTL manifest.

Required payload fields:

- `project_name`
- `top_module`
- `rtl_files`
- `compile_order`
- `modules`
- `interfaces`
- `clock_domains`
- `resets`
- `memory_map`
- `behavioral_requirements`
- `lint_summary`
- `coverage_targets`

Semantic rules:

- `top_module` exists in `modules`.
- Every `rtl_files[*].path` exists at runtime when validation runs in strict artifact mode.
- Compile order includes packages before dependent modules.
- Reset polarity must match RTL manifest.
- Interface signal names must match Agent 1 contract unless deliberate versioned transform exists.
- Coverage targets must map to module/IP names.

### 8.3 Agent 2 → Agent 4: Physical Handoff

Contract:

```text
agent2_to_agent4/v1
```

Purpose: Agent 4 generates FPGA/backend files and physical signoff plan.

Required payload fields:

- `project_name`
- `top_module`
- `rtl_files`
- `compile_order`
- `target_backend`
- `target_device`
- `clock_constraints`
- `reset_constraints`
- `io_constraints`
- `timing_goals`
- `resource_estimate`

Semantic rules:

- `top_module` must be explicit; no filename guessing.
- Clock constraints cover all declared clock domains.
- Target backend enum allowed values: `quartus`, `openlane`, `mock`.
- FPGA device/family fields required for Quartus mode.
- Timing goal frequency must not contradict Agent 1 frequency.

### 8.4 Agent 2 → Agent 5: Formal Handoff

Contract:

```text
agent2_to_agent5/v1
```

Purpose: Agent 5 generates SVA/SBY and formal proof plans from RTL + properties.

Required payload fields:

- `project_name`
- `top_module`
- `rtl_files`
- `compile_order`
- `formal_targets`
- `clock_domains`
- `resets`
- `assumption_policy`
- `property_requirements`
- `bounded_depth_defaults`
- `blackbox_policy`
- `interface_invariants`

Semantic rules:

- Every formal target maps to existing module.
- Every property requirement maps to target module or interface.
- Assumptions must be labeled and justified.
- Bounded depth must be positive integer.
- Blackbox policy explicit for unsupported memories/vendor IP.

### 8.5 Agent 3 Result: DV Result Contract

Contract:

```text
agent3_result/v1
```

Purpose: machine-readable DV result for reports, dashboards, and Agent 6.

Required payload fields:

- `project_name`
- `tests_generated`
- `tests_run`
- `pass_fail_status`
- `coverage_summary`
- `failures`
- `tool_availability`
- `commands`
- `artifacts`

Semantic rules:

- `pass_fail_status` allowed values: `pass`, `fail`, `partial`, `not_run`.
- Failed tests must include file/line or log path.
- Coverage summary uses stable metric names.
- Artifacts paths point to produced TB/log/report files.

### 8.6 Agent 4 Result: Physical Result Contract

Contract:

```text
agent4_result/v1
```

Purpose: machine-readable backend result.

Required payload fields:

- `project_name`
- `backend_used`
- `pass_fail_status`
- `timing_summary`
- `resource_summary`
- `constraints_generated`
- `commands`
- `tool_availability`
- `artifacts`

Semantic rules:

- Backend result must specify real tool vs mock.
- Timing result status explicit: `met`, `violated`, `not_run`, `unknown`.
- Resource summary stable keys for FPGA/LUT/FF/BRAM/DSP when available.

### 8.7 Agent 5 Result: Formal Result Contract

Contract:

```text
agent5_result/v1
```

Purpose: machine-readable formal verification result.

Required payload fields:

- `project_name`
- `formal_targets`
- `properties_generated`
- `proof_results`
- `counterexamples`
- `engines`
- `bounded_depth`
- `commands`
- `tool_availability`
- `artifacts`

Semantic rules:

- Proof result allowed values: `pass`, `fail`, `unknown`, `not_run`.
- Counterexample entries include module/property/log path.
- Every generated SBY/SVA artifact listed.

### 8.8 Swarm Artifact Index

Contract:

```text
swarm_artifact_index/v1
```

Purpose: central run manifest for humans, automation, and Agent 6.

Required payload fields:

- `run_id`
- `project_name`
- `created_at`
- `status`
- `agents`
- `contracts`
- `artifacts`
- `dependency_graph`
- `summary`

Example:

```json
{
  "contract_version": "swarm_artifact_index/v1",
  "run_id": "2026-05-18T21-20-00_agentai",
  "project_name": "iot_camera",
  "status": "partial",
  "agents": {
    "agent1": {"status": "pass", "outputs": []},
    "agent2": {"status": "pass", "outputs": []},
    "agent3": {"status": "not_run", "outputs": []},
    "agent4": {"status": "not_run", "outputs": []},
    "agent5": {"status": "not_run", "outputs": []}
  },
  "contracts": [],
  "artifacts": [],
  "dependency_graph": [],
  "summary": {}
}
```

Semantic rules:

- Every artifact has producer.
- Every consumer reference names existing agent.
- Every contract artifact points to valid `contract_version`.
- Overall status derives from agent statuses unless explicitly overridden with reason.

### 8.9 Swarm → Agent 6 Wiki/Docs

Contract:

```text
swarm_to_docs_agent/v1
```

Purpose: stable input for future Agent 6.

Required payload fields:

- `project_name`
- `run_id`
- `artifact_index_path`
- `architecture_handoff_path`
- `rtl_manifest_path`
- `dv_result_path`
- `physical_result_path`
- `formal_result_path`
- `traceability_matrix`
- `doc_targets`

Agent 6 generated docs:

- run summary
- architecture summary
- RTL module index
- DV report
- physical signoff report
- formal proof report
- traceability matrix
- known limitations

Semantic rules:

- Agent 6 consumes only contract files and declared artifacts.
- Missing optional result contracts become `not_available`, not crash.
- Generated docs include provenance back to artifact index.

## 9. Isolation Runners

Each agent gets a pull-plug runner. Each runner starts from valid mock contract input and does not run upstream agents.

### 9.1 Agent 1 isolated

File:

```text
debug_runners/test_agent1_isolated.py
```

Input: user requirement mock.

Output: `agent1_to_agent2/v1` contract.

Proof line:

```text
AGENT1_ISOLATED_PASS project=<project_name> contract=agent1_to_agent2/v1
```

### 9.2 Agent 2 isolated

File:

```text
debug_runners/test_agent2_isolated.py
```

Input: mock `agent1_to_agent2/v1`.

Output:

- RTL files
- `agent2_to_agent3/v1`
- `agent2_to_agent4/v1`
- `agent2_to_agent5/v1`

Proof line:

```text
AGENT2_ISOLATED_PASS project=<project_name> rtl_files=<count> contracts=3
```

### 9.3 Agent 3 isolated

File:

```text
debug_runners/test_agent3_isolated.py
```

Input: mock `agent2_to_agent3/v1`.

Output: TB/tests/coverage + `agent3_result/v1`.

Proof line:

```text
AGENT3_ISOLATED_PASS project=<project_name> tests=<count> result=agent3_result/v1
```

### 9.4 Agent 4 isolated

File:

```text
debug_runners/test_agent4_isolated.py
```

Input: mock `agent2_to_agent4/v1`.

Output: QSF/SDC/Tcl/backend reports + `agent4_result/v1`.

Proof line:

```text
AGENT4_ISOLATED_PASS project=<project_name> backend=<backend> result=agent4_result/v1
```

### 9.5 Agent 5 isolated

File:

```text
debug_runners/test_agent5_isolated.py
```

Input: mock `agent2_to_agent5/v1`.

Output: SVA/SBY/formal report + `agent5_result/v1`.

Proof line:

```text
AGENT5_ISOLATED_PASS project=<project_name> targets=<count> result=agent5_result/v1
```

### 9.6 Agent 6 Wiki isolated

File:

```text
debug_runners/test_agent6_wiki_isolated.py
```

Input: mock `swarm_to_docs_agent/v1` + mock `swarm_artifact_index/v1`.

Output: docs/wiki pages.

Proof line:

```text
AGENT6_WIKI_ISOLATED_PASS project=<project_name> docs=<count>
```

## 10. Output Layout

Recommended run folder:

```text
outputs/<run_id>/
  contracts/
    agent1_to_agent2.json
    agent2_to_agent3.json
    agent2_to_agent4.json
    agent2_to_agent5.json
    agent3_result.json
    agent4_result.json
    agent5_result.json
    swarm_artifact_index.json
    swarm_to_docs_agent.json
  rtl/
  tb/
  formal/
  fpga/
  reports/
  docs/
```

Legacy folders can remain during transition.

## 11. Dependency Policy

Preferred:

- Use `jsonschema` if already installed.

Fallback:

- Built-in lightweight structural validation plus semantic validation.

Do not add hard dependency until dependency management is explicit.

## 12. Production Integration Points

### Agent 1

- Emit `agent1_to_agent2/v1`.
- Validate before return.
- Write contract JSON to output folder.

### Agent 2

- Validate `agent1_to_agent2/v1` on entry.
- Emit RTL manifest-like payloads:
  - `agent2_to_agent3/v1`
  - `agent2_to_agent4/v1`
  - `agent2_to_agent5/v1`
- Stop importing Agent 1 internals.

### Agent 3

- Prefer `agent2_to_agent3/v1` input.
- Emit `agent3_result/v1`.

### Agent 4

- Prefer `agent2_to_agent4/v1` input.
- Emit `agent4_result/v1`.

### Agent 5

- Prefer `agent2_to_agent5/v1` input.
- Emit `agent5_result/v1`.

### Swarm graph

- Add artifact index builder.
- Record contract artifacts after each node.
- Keep legacy `SwarmState` until contract bus migration.

### Agent 6 future

- Start as docs/wiki generator consuming `swarm_to_docs_agent/v1`.
- No dependency on agent internals.

## 13. Testing Plan

### 13.1 Registry tests

- Lists all contract versions.
- Loads every schema.
- Rejects unknown contract version.
- Validates envelope producer/consumer.

### 13.2 Contract tests

For every contract:

- valid payload passes
- missing required field fails
- wrong `contract_version` fails
- invalid enum fails
- semantic invariant failure raises precise `ValueError`

### 13.3 Isolation tests

- Each isolated runner executes without upstream agent calls.
- Each runner writes expected outputs.
- Each runner prints proof line.

### 13.4 Integration tests

- Full graph emits `swarm_artifact_index/v1`.
- Artifact index references all produced files.
- Agent 6 mock can consume index.

## 14. Verification Commands

Phase-specific:

```powershell
python -m pytest tests/test_swarm_contract_registry.py -q
python -m pytest tests/test_agent1_to_agent2_contract.py tests/test_agent2_to_agent3_contract.py tests/test_agent2_to_agent4_contract.py tests/test_agent2_to_agent5_contract.py -q
python -m pytest tests/test_agent_result_contracts.py tests/test_swarm_artifact_index_contract.py -q
```

Isolation:

```powershell
python debug_runners/test_agent1_isolated.py
python debug_runners/test_agent2_isolated.py
python debug_runners/test_agent3_isolated.py
python debug_runners/test_agent4_isolated.py
python debug_runners/test_agent5_isolated.py
python debug_runners/test_agent6_wiki_isolated.py
```

Full suite:

```powershell
python -m pytest -q
```

## 15. Phased Implementation Order

### Phase 1: Foundation

1. Add `semiconductor_swarm/contracts/` package.
2. Add contract constants.
3. Add schema loader and registry.
4. Add `validate_contract()`.
5. Add common envelope model.
6. Add artifact index schema.
7. Add registry tests.

### Phase 2: Agent 1 → Agent 2 hardening

1. Move APB constants to contract package.
2. Add `agent1_to_agent2/v1` schema.
3. Add semantic validator.
4. Add Agent 1 output `contract_version`.
5. Add Agent 2 input validation.
6. Add Agent 2 isolated runner.
7. Add tests.

### Phase 3: Agent 2 fan-out contracts

1. Add `agent2_to_agent3/v1`.
2. Add `agent2_to_agent4/v1`.
3. Add `agent2_to_agent5/v1`.
4. Make Agent 2 emit all three contracts.
5. Add isolated runners for Agents 3/4/5.
6. Add contract tests.

### Phase 4: Result contracts

1. Add `agent3_result/v1`.
2. Add `agent4_result/v1`.
3. Add `agent5_result/v1`.
4. Make Agents 3/4/5 emit result JSON.
5. Add result contract tests.

### Phase 5: Swarm artifact index

1. Add artifact index builder.
2. Update graph/run output to write `swarm_artifact_index.json`.
3. Add traceability metadata.
4. Add integration tests.

### Phase 6: Agent 6-ready interface — 100% PASS 2026-05-19

1. Add `swarm_to_docs_agent/v1`.
2. Generate docs input from artifact index.
3. Add Agent 6 isolated mock runner.
4. Add minimal docs/wiki generator stub later if approved.

Verification:

```text
AGENT6_WIKI_ISOLATED_PASS project=agent6_demo docs=8
AGENT6_WIKI_ISOLATED_PASS project=agent6_demo docs=8
AGENT6_WIKI_ISOLATED_PASS project=agent6_demo docs=8
AGENT6_WIKI_ISOLATED_PASS project=agent6_demo docs=8
2 passed in 0.42s
35 passed in 18.14s
1 passed in 0.10s
36 passed in 17.80s
36 passed in 18.63s
137 passed in 29.43s
```

Repeated verification commands:

```powershell
python debug_runners/test_agent6_wiki_isolated.py
python debug_runners/test_agent6_wiki_isolated.py
python debug_runners/test_agent6_wiki_isolated.py
python -m pytest tests/test_agent6_ready_contract.py -q
python -m pytest tests/test_agent6_ready_contract.py tests/test_swarm_contract_registry.py tests/test_swarm_graph.py -q
python -m pytest tests/test_docs_health.py -q
python -m pytest tests/test_agent6_ready_contract.py tests/test_swarm_contract_registry.py tests/test_swarm_graph.py tests/test_docs_health.py -q
python -m pytest tests/test_agent6_ready_contract.py tests/test_swarm_contract_registry.py tests/test_swarm_graph.py tests/test_docs_health.py -q
python -m pytest -q
```

Implemented files:

- `debug_runners/test_agent6_wiki_isolated.py`
- `tests/test_agent6_ready_contract.py`

### Phase 7: Contract bus migration

1. Introduce `ContractEnvelope` in graph state.
2. Migrate one edge at a time.
3. Remove legacy fallback when tests prove stable.

## 16. Rollback Plan

If implementation breaks existing flow:

1. Keep contract package and schemas.
2. Disable strict consumer validation behind feature flag.
3. Keep producer-side contract emission.
4. Keep isolated runners for debugging.
5. Re-enable strict validation edge by edge.

## 17. Definition of Done

- Contract package exists.
- Registry lists all planned v1 contracts.
- Each current agent boundary has versioned contract.
- Agents 1-5 can run isolated from valid mock inputs.
- Agent 2 emits fan-out contracts for Agents 3/4/5.
- Agents 3/4/5 emit result contracts.
- Swarm run emits `swarm_artifact_index/v1`.
- Agent 6 docs input contract exists.
- Contract tests pass.
- Isolation tests pass.
- Existing tests pass or failures documented with exact reason.

## 18. Approval Gate

No production implementation should begin until review confirms:

1. Contract list is complete enough for v1.
2. Agent 6 should consume swarm-level input, not per-agent hard-coded inputs.
3. Legacy fallback is allowed during transition.
4. `jsonschema` remains optional dependency.
5. Output layout under `outputs/<run_id>/contracts/` is acceptable.

## 19. Missing Contract Hardening Additions

### 19.1 `contract_version` required everywhere

Every payload, not only envelope, must include `contract_version`.

Add `contract_version` to required fields for:

- `agent2_to_agent3/v1`
- `agent2_to_agent4/v1`
- `agent2_to_agent5/v1`
- `agent3_result/v1`
- `agent4_result/v1`
- `agent5_result/v1`
- `swarm_artifact_index/v1`
- `swarm_to_docs_agent/v1`

Rule:

```text
payload.contract_version == envelope.contract_version
```

If no envelope is used, payload `contract_version` remains mandatory.

### 19.2 Compatibility matrix

Maintain compatibility table in contract docs and tests:

```text
producer -> consumer -> contract_version -> mode -> legacy fallback -> removal phase
```

Initial matrix:

| Producer | Consumer | Contract | Initial mode | Legacy fallback | Removal phase |
|---|---|---|---|---|---|
| Agent 1 | Agent 2 | `agent1_to_agent2/v1` | warn/validate | yes | Phase 7 |
| Agent 2 | Agent 3 | `agent2_to_agent3/v1` | emit/optional consume | yes | Phase 7 |
| Agent 2 | Agent 4 | `agent2_to_agent4/v1` | emit/optional consume | yes | Phase 7 |
| Agent 2 | Agent 5 | `agent2_to_agent5/v1` | emit/optional consume | yes | Phase 7 |
| Agent 3 | Swarm index | `agent3_result/v1` | emit | n/a | n/a |
| Agent 4 | Swarm index | `agent4_result/v1` | emit | n/a | n/a |
| Agent 5 | Swarm index | `agent5_result/v1` | emit | n/a | n/a |
| Swarm graph | Agent 6 | `swarm_to_docs_agent/v1` | mock only | n/a | n/a |

### 19.3 Error taxonomy

Contract package should expose stable exception classes:

```python
class ContractError(ValueError): ...
class ContractVersionError(ContractError): ...
class ContractSchemaError(ContractError): ...
class ContractSemanticError(ContractError): ...
class ContractArtifactMissingError(ContractError): ...
class ContractProducerConsumerError(ContractError): ...
```

Error message format:

```text
<ContractErrorType>: contract=<contract_version> path=<json_path> reason=<reason>
```

Examples:

```text
ContractVersionError: contract=agent2_to_agent3/v1 path=$.contract_version reason=expected agent2_to_agent3/v1
ContractSemanticError: contract=agent1_to_agent2/v1 path=$.memory_map reason=overlapping address ranges
ContractArtifactMissingError: contract=agent2_to_agent5/v1 path=$.rtl_files[2].path reason=file does not exist in strict artifact mode
```

### 19.4 Partial run status semantics

Use shared status enum:

```text
pass
fail
partial
skipped
not_run
blocked
unknown
```

Dependency rule:

- If Agent 1 fails, Agents 2/3/4/5 become `blocked`.
- If Agent 2 fails, Agents 3/4/5 become `blocked`.
- If Agent 3 fails, Agent 4/5 may still run unless graph policy says otherwise.
- If physical/formal tools are missing, corresponding result may be `partial` or `not_run`, not hidden.
- Overall swarm status derives from worst agent status and must include reason.

### 19.5 Schema evolution policy

Rules:

- v1 schemas are immutable after approval.
- Additive compatible fields require optional fields and tests.
- Breaking changes require `/v2` contract.
- Consumers may accept multiple versions only through explicit adapter functions.
- Golden v1 fixtures must remain in tests forever unless contract is formally retired.

Adapter naming:

```python
adapt_agent1_to_agent2_v1_to_v2(payload: dict) -> dict
```

No silent coercion across versions.

### 19.6 Golden fixtures

Add stable fixtures:

```text
tests/fixtures/golden_spec_v1.json
tests/fixtures/contracts/v1/agent1_to_agent2.valid.json
tests/fixtures/contracts/v1/agent2_to_agent3.valid.json
tests/fixtures/contracts/v1/agent2_to_agent4.valid.json
tests/fixtures/contracts/v1/agent2_to_agent5.valid.json
tests/fixtures/contracts/v1/agent3_result.valid.json
tests/fixtures/contracts/v1/agent4_result.valid.json
tests/fixtures/contracts/v1/agent5_result.valid.json
tests/fixtures/contracts/v1/swarm_artifact_index.valid.json
tests/fixtures/contracts/v1/swarm_to_docs_agent.valid.json
```

Test rule:

- Every schema must validate its golden fixture.
- Every golden fixture must include at least one realistic artifact entry.
- Contract fixtures must use POSIX-style relative paths.

## 20. Feature Flags and Rollout Controls

Add runtime flags for safe rollout:

```text
SWARM_CONTRACTS_ENABLED=1
SWARM_CONTRACTS_STRICT=0
SWARM_WRITE_ARTIFACT_INDEX=1
SWARM_LEGACY_FALLBACK=1
SWARM_CONTRACT_ARTIFACT_STRICT=0
```

Flag behavior:

| Flag | Default during rollout | Meaning |
|---|---:|---|
| `SWARM_CONTRACTS_ENABLED` | `1` | emit contracts and run non-destructive validation |
| `SWARM_CONTRACTS_STRICT` | `0` | fail consumer on invalid contract when `1` |
| `SWARM_WRITE_ARTIFACT_INDEX` | `1` | write `swarm_artifact_index.json` |
| `SWARM_LEGACY_FALLBACK` | `1` | allow old dict/file inference path |
| `SWARM_CONTRACT_ARTIFACT_STRICT` | `0` | require referenced artifact files to exist during validation |

Phase policy:

- Phase 1-3: emit + validate, legacy fallback allowed.
- Phase 4-5: strict validation enabled in tests.
- Phase 6: Agent 6 mock consumes only contracts.
- Phase 7: production strict mode enabled edge by edge.

Rollback command shape:

```powershell
$env:SWARM_CONTRACTS_STRICT="0"
$env:SWARM_LEGACY_FALLBACK="1"
python -m pytest -q
```

## 21. Artifact Provenance, Hashing, and Path Policy

### 21.1 Artifact record shape

Every artifact in any result or swarm index should use this shape:

```json
{
  "id": "artifact.agent2.rtl.iot_camera_top",
  "kind": "rtl",
  "path": "rtl/iot_camera_top.sv",
  "sha256": "...",
  "producer": "agent2",
  "consumer": ["agent3", "agent4", "agent5"],
  "contract_version": "agent2_to_agent3/v1",
  "external": false,
  "description": "Top-level SystemVerilog RTL"
}
```

Allowed `kind` values:

```text
contract
rtl
tb
formal
fpga
constraint
report
log
doc
config
checkpoint
unknown
```

### 21.2 Hashing

Hash policy:

- `sha256` required for files that exist at index-build time.
- Missing file in non-strict mode uses `sha256: null` and `status: missing`.
- Hash uses file bytes exactly as stored.
- Generated docs must cite hash when referencing source artifacts.

### 21.3 Windows-safe path policy

Repo runs on Windows, but JSON contracts should be platform-neutral.

Rules:

- Store paths as POSIX-style relative paths in JSON: `rtl/top.sv`.
- Do not store machine-specific absolute paths unless `external: true`.
- Normalize `\` to `/` before writing contract JSON.
- Reject `..` path traversal in strict mode.
- Redact user home paths from docs.

## 22. Existing Agent 2 Contract Migration Policy

Repo already has Agent 2 local contract/schema code under:

```text
semiconductor_swarm/agents/agent2_rtl/contracts.py
semiconductor_swarm/agents/agent2_rtl/schemas/rtl_manifest.schema.json
semiconductor_swarm/agents/agent2_rtl/schemas/agent2_subgraph_trace.schema.json
semiconductor_swarm/agents/agent2_rtl/schemas/semantic_review_report.schema.json
```

Policy:

- Do not create duplicate incompatible Agent 2 contracts.
- First wrap existing Agent 2 manifest into shared `agent2_to_agent3/v1`, `agent2_to_agent4/v1`, and `agent2_to_agent5/v1` payloads.
- Keep Agent 2 internal schemas for subgraph internals.
- Shared `semiconductor_swarm/contracts/` owns cross-agent boundary contracts.
- Add adapter functions when internal shape differs from cross-agent shape.

Adapter examples:

```python
build_agent2_to_agent3_from_rtl_manifest(manifest: dict) -> dict
build_agent2_to_agent4_from_rtl_manifest(manifest: dict) -> dict
build_agent2_to_agent5_from_rtl_manifest(manifest: dict) -> dict
```

No consumer outside Agent 2 should import Agent 2 internal schema modules after shared contracts exist.

## 23. Prompt and Docs Governance Updates

### 23.1 Prompt compliance with `semiconductor_swarm_ai.md`

Agent prompts must explicitly state:

- accepted input contract version(s)
- emitted output contract version(s)
- fail-fast behavior on invalid contract
- artifact writing responsibility
- no silent port/interface renaming
- provenance requirements for reports

Files to update later:

```text
docs/prompt_compliance_matrix.yaml
docs/prompts/canonical-prompts.md
docs/generated/prompt-contract-index.md
semiconductor_swarm/agents/*prompt*.py
semiconductor_swarm/agents/agent2_rtl/agent2_prompt.py
```

### 23.2 Docs index updates

When implementation starts, update:

```text
docs/exec-plans/active/index.md
PLANS.md
docs/generated/agent-contract-index.md
docs/generated/test-coverage-index.md
docs/generated/tool-index.md
```

Docs health rule:

- New active plan must be discoverable from active exec-plan index.
- Superseded plan must point to replacement.
- Generated contract index must list all v1 contracts and schema files.

### 23.3 Governance approval checklist

Before production changes:

- Owner named.
- Reviewer named.
- Contract version list approved.
- Feature flags approved.
- Rollback path approved.
- Target test list approved.
- Golden fixtures approved.
- Agent 6 security/redaction rule approved.

Approval evidence should be appended to this plan or linked from active plan index.

## 24. Security and Agent 6 Redaction Rules

Agent 6 will read many artifacts and produce docs. It must not leak secrets or local machine details.

Redaction rules:

- Do not render environment variables.
- Do not render API keys, tokens, credentials, cookies, private keys, or local secrets.
- Do not render absolute user paths unless explicitly marked safe.
- Do not render contents from files outside declared artifact index.
- Redact values matching common secret patterns.
- Include redaction summary in generated docs.

Suggested redaction record:

```json
{
  "redactions": [
    {
      "artifact": "reports/run.log",
      "pattern": "possible_api_key",
      "count": 1
    }
  ]
}
```

Agent 6 provenance rule:

- Every generated page must cite source artifact IDs.
- Every generated page must cite `swarm_artifact_index/v1` run ID.
- Generated docs must not infer from undeclared files.

## 25. Canonical Traceability Matrix Shape

Traceability must be machine-readable, not only Markdown.

Recommended record:

```json
{
  "requirement_id": "REQ-001",
  "requirement_text": "APB timer exposes control/status registers",
  "architecture_element": "timer",
  "rtl_modules": ["timer"],
  "interfaces": ["apb_slave"],
  "dv_tests": ["test_timer_apb_read_write"],
  "formal_properties": ["timer_apb_stable_ready"],
  "physical_constraints": ["clk_main_100mhz"],
  "artifacts": [
    "artifact.agent2.rtl.timer",
    "artifact.agent3.tb.timer",
    "artifact.agent5.formal.timer"
  ],
  "status": "partial"
}
```

Traceability status enum:

```text
covered
partial
missing_dv
missing_formal
missing_physical
not_applicable
unknown
```

Agent 6 should use this matrix for wiki pages and audit docs.