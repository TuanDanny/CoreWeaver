<!--
Agent 1 V3.6 Upgrade Plan
Status: DRAFT FOR REVIEW
Scope: critical repair-loop and semantic-validation fixes only. RAG V4.0 deferred.
-->

# Agent 1 V3.6 Repair Loop Upgrade Plan

## 1. Goal

Fix critical Agent 1 V3 repair-loop bugs found in audit, without adding RAG and without changing Agent 2-5 behavior.

Agent 1 V3.6 must make validator feedback real:

- A repair node must persist repaired `spec_draft` into graph state.
- After repair, graph must route back to validator that raised REJECT.
- Router must evaluate latest validator decisions, not stale old rejects.
- Safety/security memory-map validation must catch semantic memory bugs.
- Expert/node naming must be consistent enough for trace/debug output.

## 2. Non-Goals

Deferred by Chief Architect request:

- No RAG V4.0 integration.
- No conversion of all 24 committee entries into separate LLM calls.
- No change to mandatory Codex policy.
- No large rewrite of Agent 1 architecture generator.

## 3. Maximum Target Outcomes For V3.6

V3.6 is not only a bug-fix release. It must raise Agent 1 from “artifact generator with validation labels” to “self-correcting architecture planner with auditable convergence”.

Maximum outcome expected after V3.6:

### 3.1 Real validator-repair convergence

Agent 1 must prove this loop works:

```text
Spec Draft -> Validator REJECT -> Target Expert Repair -> Same Validator Recheck -> ACCEPT -> Router
```

Target result:

- No cosmetic repair.
- No skipped validator.
- No stale reject poisoning final review.
- Revision history shows exact validator, target expert, finding, and post-repair state.

### 3.2 Architecture spec quality gate before Agent 2

Agent 1 output should be safe enough for Agent 2 RTL generation.

Minimum gates before handoff:

- APB interface locked and unchanged.
- Memory map has no overlap.
- Memory map bases are 4KB aligned.
- Register access policy is internally consistent.
- Safety/security constraints are reflected in memory map.
- Clock/power plan does not conflict with bus assumptions.
- QoS/memory hierarchy assumptions are not contradictory.

### 3.3 Deterministic, testable graph behavior

Agent 1 V3.6 graph must be deterministic under tests.

Target result:

- Same input state produces same route.
- Repair routing is observable by tests.
- Router decision can be unit-tested without running Codex.
- Semantic validators can be unit-tested with synthetic specs.

### 3.4 Deep semantic validation, not token validation only

V3.6 must move beyond “artifact exists” checks.

Target semantic checks:

- Memory overlap detection.
- 4KB alignment detection.
- Invalid/missing base or size detection.
- Stale reject cleanup through latest-decision router.

Future semantic checks can extend this pattern, but V3.6 must establish foundation.

### 3.5 Audit-grade evidence

Every repair must leave machine-readable evidence:

- `validator`
- `target_node`
- `decision`
- `findings`
- `revision_count`
- `before_summary`
- `after_summary`
- `route_back_to`

Target result:

- Human can inspect why Agent 1 changed spec.
- Tests can assert repair happened.
- Downstream agents can trust `spec` reached accepted state.

### 3.6 Backward-compatible pipeline stability

V3.6 must improve Agent 1 without breaking current project flow.

Target result:

- Existing `tests/test_agent1.py` still passes after updates.
- Full `python -m pytest -q` passes or unrelated failures are documented.
- Existing artifact filenames remain stable unless explicitly approved.
- Existing mandatory Codex contract remains intact.

### 3.7 Clear ceiling of success

Best possible V3.6 result:

```text
Agent 1 can generate a spec, detect semantic memory-map defects, repair them, re-run the rejecting validator, ignore resolved stale rejects, and emit an accepted architecture plan with full repair evidence and stable downstream handoff artifacts.
```

## 4. Current Bugs

### Bug A: Repair state mutation is lost

Current behavior:

```python
revision = _repair_spec_for_decision(state["spec_draft"], decision)
return {"spec_draft": state["spec_draft"], ...}
```

Repair result exists but state keeps old broken spec. Repair loop is cosmetic.

V3.6 fix:

```python
return {"spec_draft": revision, ...}
```

### Bug B: Repair routes to router too early

Current behavior:

```python
graph.add_edge(repair_node, "Super_Committee_Review_Router")
```

This skips revalidation by validator that rejected the spec.

V3.6 fix:

- `_repair_node` records source validator from latest decision.
- Repair node routes back to that source validator.
- If source validator missing/unknown, route to `hitl_plan_review` or safe router fallback.

### Bug C: Router treats stale REJECT as still active

Current behavior:

```python
rejects = [d for d in validation_decisions if d["decision"] == "REJECT"]
latest = rejects[-1]
```

If validator REJECTs once, then ACCEPTs after repair, old REJECT remains in history and can poison router.

V3.6 fix:

- Build latest decision per validator.
- Router only rejects validators whose latest decision is `REJECT` or `HITL_REQUIRED`.
- Old REJECT followed by ACCEPT is resolved.

### Bug D: Memory-map semantic validation too shallow

Current behavior:

- Checks mainly artifact presence and contract tokens.
- Does not catch address overlap.
- Does not catch base unaligned to 4KB.

V3.6 fix in `Safety_Security_vs_MemoryMap_Validator`:

- Parse each block range: `base`, `size`.
- Reject missing/invalid `base`/`size`.
- Reject `base % 0x1000 != 0`.
- Reject `size <= 0`.
- Sort address ranges and reject overlap when `current_start < previous_end`.

### Bug E: Naming inconsistency

Current issue:

- Committee list uses names with spaces, ampersands, and mixed naming.
- LangGraph repair nodes use underscore names.
- Conditional routing contains aliases that are not committee names.

V3.6 fix:

- Introduce canonical underscore names for Agent 1 V3.6 graph/report paths.
- Keep compatibility aliases only where needed for existing prompt/tests.
- Prefer canonical names in `V3_SUPER_COMMITTEE_NODES`, validator decisions, graph edges, revision history.

## 5. Proposed Technical Design

### 4.1 State additions

Add optional state fields to `Agent1V3State`:

```python
last_repaired_validator: str | None
last_repaired_target: str | None
```

Purpose:

- preserve source validator after repair;
- route back deterministically;
- improve debug/revision history.

### 4.2 Decision shape

Keep existing decision keys:

```json
{
  "validator": "Safety_Security_vs_MemoryMap_Validator",
  "decision": "REJECT",
  "target_node": "Memory_Map_Interface_Expert",
  "findings": [...],
  "max_revisions": 3
}
```

Add optional keys if useful:

```json
{
  "source_validator": "Safety_Security_vs_MemoryMap_Validator",
  "repair_reason": "memory overlap"
}
```

Backwards-compatible: existing tests and artifacts still read `validator`, `decision`, `target_node`.

### 4.3 Repair node behavior

New behavior:

1. Read latest decision.
2. Increment revision count for target expert.
3. Compute repaired spec via `_repair_spec_for_decision`.
4. Append revision history with before/after summary and source validator.
5. Return:

```python
{
    "spec_draft": revision,
    "revision_counts": revision_counts,
    "artifacts": artifacts,
    "last_repaired_validator": decision.get("validator"),
    "last_repaired_target": target,
    "next_node": decision.get("validator"),
}
```

### 4.4 Repair routing behavior

Replace static repair-to-router edges with conditional routing:

```python
graph.add_conditional_edges(
    repair_node,
    route_after_repair,
    {
        "HWSW_vs_RegisterMap_Validator": "HWSW_vs_RegisterMap_Validator",
        "Safety_Security_vs_MemoryMap_Validator": "Safety_Security_vs_MemoryMap_Validator",
        ...,
        "hitl_plan_review": "hitl_plan_review",
    },
)
```

`route_after_repair(state)` returns `state["last_repaired_validator"]` if valid else `hitl_plan_review`.

### 4.5 Router behavior

New router algorithm:

```python
latest_by_validator = {}
for decision in validation_decisions:
    validator = decision.get("validator")
    if validator and validator in VALIDATOR_FUNCTIONS:
        latest_by_validator[validator] = decision

active_failures = [
    decision for decision in latest_by_validator.values()
    if decision.get("decision") in {"REJECT", "HITL_REQUIRED"}
]
```

If no active failures, router ACCEPTs.

### 4.6 Semantic memory validation

Add helper:

```python
def _validate_memory_ranges(memory_map: dict[str, Any]) -> list[str]:
    ...
```

Findings examples:

- `memory_map.block_a base 0x40000004 is not 4KB aligned`
- `memory_map.block_b range 0x40000800-0x40001800 overlaps block_a range 0x40000000-0x40001000`
- `memory_map.block_c has invalid size 0x0`

Integrate into `_validate_safety_security_memory_map(spec)`.

## 6. Tests To Add

### 5.1 State mutation test

Given broken spec and reject decision, call `_repair_node` or graph path and assert:

- returned `spec_draft` is not original object/content;
- fixed field exists in `spec_draft`;
- `last_repaired_validator` equals reject source validator.

### 5.2 Repair routes to source validator test

Build graph and inject reject decision with source validator.

Assert route after repair returns original validator, not router.

### 5.3 Router stale reject test

Given decisions:

1. `Safety_Security_vs_MemoryMap_Validator`: REJECT
2. same validator: ACCEPT

Assert router ACCEPTs or no active reject remains.

### 5.4 Memory overlap test

Spec memory map:

```json
{
  "a": {"base": "0x40000000", "size": "0x1000"},
  "b": {"base": "0x40000800", "size": "0x1000"}
}
```

Expected: `Safety_Security_vs_MemoryMap_Validator` returns REJECT with overlap finding.

### 5.5 Memory unaligned test

Spec memory map:

```json
{
  "a": {"base": "0x40000004", "size": "0x1000"}
}
```

Expected: REJECT with 4KB alignment finding.

### 5.6 Regression tests

Run:

```powershell
python -m pytest tests/test_agent1.py -q
python -m pytest -q
```

Then run partial runner if present:

```powershell
python debug_runners/run_partial.py
```

If `debug_runners/run_partial.py` does not exist, document that and run nearest available partial/debug runner.

## 7. Rollout Steps

1. Review and approve this plan.
2. Patch `semiconductor_swarm/agents/agent1_planning/agent1_subgraph.py`.
3. Patch tests in `tests/test_agent1.py`.
4. Run Agent 1 tests.
5. Run full pytest.
6. Run partial debug runner or document absence.
7. Report exact changed files and test output.

## 8. Acceptance Criteria

Agent 1 V3.6 accepted only if all conditions hold:

- `_repair_node` persists repaired `spec_draft`.
- Repair routing returns to source validator.
- Router ignores stale REJECT followed by ACCEPT.
- Memory overlap produces REJECT.
- Unaligned base address produces REJECT.
- `python -m pytest tests/test_agent1.py -q` passes.
- `python -m pytest -q` passes or any failures are unrelated and documented.
- Partial runner result is documented.
- Final report confirms V3.6 maximum target outcome reached or lists exact remaining gaps.

## 9. Risk Controls

- Keep changes scoped to Agent 1 and tests.
- Preserve artifact filenames where possible.
- Preserve existing mandatory Codex contract.
- Preserve existing APB and generated spec contracts.
- Use compatibility aliases if old expert names are externally referenced.
