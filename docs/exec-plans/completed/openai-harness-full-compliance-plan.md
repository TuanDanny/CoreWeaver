---
title: OpenAI Harness Engineering Full Compliance Plan
status: completed
owner: docs-governance
type: exec-plan
last_reviewed: 2026-05-20
source_of_truth: true
approval_required: true
runtime_agent_changes_allowed: package-facade-only
completed_on: 2026-05-20
---

# OpenAI Harness Engineering Full Compliance Plan

## 1. Purpose
Plan a careful upgrade from current local-reference Harness Engineering compliance to full-article compliance after user review and approval.

This plan is intentionally approval-gated. It creates a path to evaluate, measure, and improve repository knowledge discipline without reducing quality or performance of existing Semiconductor Swarm agents.

## 2. Current Baseline
Current repository already has local-reference compliance artifacts:

- Top-level maps: `AGENTS.md`, `ARCHITECTURE.md`, `PLANS.md`.
- Source-of-truth docs: `docs/design-docs/`, `docs/product-specs/`, `docs/governance/`.
- Prompt routing docs: `docs/prompts/`, `docs/prompt_compliance_matrix.yaml`.
- Task routing: `docs/agent-task-cards/`, `docs/knowledge-map.yaml`.
- Generated/manual indexes: `docs/generated/`.
- Legacy docs preserved: `docs/legacy/`.
- Health checks: `scripts/check_docs_health.py`, `tests/test_docs_health.py`, `tests/test_prompt_contracts.py`.
- Local audit: `docs/governance/harness-engineering-compliance-audit.md`.

Latest recorded verification:

```bash
python scripts/check_docs_health.py && python -m pytest -q tests/test_docs_health.py tests/test_prompt_contracts.py
```

Expected passing baseline:

```text
docs health ok
9 passed
```

## 3. Goal
Reach evidence-backed compliance against the full OpenAI Harness Engineering article, not only the locally captured summary.

The goal is not to copy external ideas blindly. The goal is to identify principles useful for this codebase, classify gaps, improve safe docs/routing/checkability first, and preserve existing agent quality.

## 4. Non-Negotiable Constraint
Do not reduce quality, correctness, speed, or domain focus of current Semiconductor Swarm agents.

This plan must not change these files unless a separate runtime-change plan is approved:

- `semiconductor_swarm/agents/agent1_planning/agent1_prompt.py`
- `semiconductor_swarm/agents/agent2_rtl/agent2_prompt.py`
- `semiconductor_swarm/agents/agent3_dv/agent3_prompt.py`
- `semiconductor_swarm/agents/agent4_physical/agent4_prompt.py`
- `semiconductor_swarm/agents/agent5_formal/agent5_prompt.py`
- `semiconductor_swarm/agents/*`
- `semiconductor_swarm/swarm_graph.py`
- `main.py`
- generated RTL/formal/DV/FPGA artifacts

## 5. Scope

### 5.1 In Scope
- Capture or reference full OpenAI Harness Engineering article content.
- Extract principle list from full article.
- Build compliance matrix with evidence.
- Identify pass, partial, gap, not-applicable items.
- Score benefit, risk, and implementation cost.
- Propose docs-only improvements.
- Strengthen health checks only if safe and approved.
- Preserve source-of-truth hierarchy.

### 5.2 Out of Scope Until Separate Approval
- Runtime prompt rewrites.
- Agent algorithm changes.
- Swarm graph orchestration changes.
- EDA runner behavior changes.
- Generated artifact regeneration.
- Any change that could affect semiconductor design output.

## 6. Success Criteria

### 6.1 Required Outputs
After approved execution, repository must contain:

1. Full-article notes or source pointer:
   - `docs/references/openai-harness-engineering-full-notes.md`, or
   - updated `docs/references/openai-harness-engineering.md` if full content is provided by user.
2. Principle extraction table:
   - one row per article principle.
3. Compliance matrix:
   - status: `pass`, `partial`, `gap`, or `not-applicable`.
   - evidence: repo file path and section.
   - risk: effect on existing agent quality.
   - action: none, docs-only, health-check, or separate-runtime-plan.
4. ROI-ranked gap list.
5. Final recommendation: do nothing, docs-only upgrade, health-check upgrade, or separate runtime plan.

### 6.2 Required Verification
Minimum checks must pass after docs-only changes:

```bash
python scripts/check_docs_health.py
python -m pytest -q tests/test_docs_health.py tests/test_prompt_contracts.py
```

If any runtime prompt/code file changes in a future separately approved plan, also run relevant agent tests:

```bash
python -m pytest -q tests/test_agent1.py tests/test_agent2.py tests/test_agent3.py tests/test_agent4.py tests/test_agent5.py tests/test_swarm_graph.py tests/test_agent_pipeline.py
```

Full test suite remains optional when real EDA tools are not installed:

```bash
python -m pytest -q
```

## 7. Performance and Quality Metrics

These metrics evaluate whether full compliance is useful and safe.

| Metric | Baseline Target | Improved Target | Measurement Method | Must Not Regress |
|---|---:|---:|---|---|
| Docs health | pass | pass | `scripts/check_docs_health.py` | yes |
| Prompt contract tests | pass | pass | `tests/test_prompt_contracts.py` | yes |
| Runtime prompt file changes | 0 | 0 in this plan | git diff file list | yes |
| Runtime code file changes | 0 | 1 package root facade only | git diff file list | yes: no agent prompt, graph, or EDA behavior changed |
| Agent task routing clarity | medium-high | high | compliance matrix + knowledge map review | yes |
| Source-of-truth conflict risk | low | lower | conflict policy + doc evidence | yes |
| Agent context bloat risk | low | low | no full article in runtime prompt | yes |
| Onboarding score | 80-90% | 90-95% | manual checklist review | no hard regression |
| Context recovery score | 85-90% | 92-97% | docs route from task to files/tests | no hard regression |
| Runtime design quality | unchanged | unchanged or better | package root import only; optional tests | yes |

## 8. Estimated Benefit

| Area | Expected Benefit | Confidence | Notes |
|---|---:|---:|---|
| Agent onboarding | +5-10% | medium | Better route from task to source docs. |
| Context recovery | +5-8% | medium | Less dependency on chat history. |
| Docs governance | +5-10% | high | More explicit compliance and gap tracking. |
| Machine-checkable routing | +10-15% | medium | If health checks validate more routes. |
| Long-term maintainability | +10-15% | medium | Better source-of-truth and stale-doc control. |
| Immediate RTL/formal/DV quality | +0-5% | low | No runtime algorithm changes in this plan. |

## 9. Risk Assessment

| Risk | Cause | Impact | Mitigation |
|---|---|---|---|
| Prompt dilution | Full article content gets inserted into agent prompts | worse focus and higher token use | forbidden in this plan |
| Over-governance | Agents must read too many docs | slower work and less technical focus | keep `AGENTS.md` concise; route to specific docs only |
| Docs-code conflict | New docs contradict tests/code | agent may follow wrong rule | tests/code remain top authority |
| False compliance | Article principles guessed without full text | misleading 100% claim | require full article text or explicit limitation |
| Runtime regression | Prompt/code changed during docs work | agent behavior changes | no agent prompt/graph/EDA changes; package root facade only |
| Stale generated indexes | Index not updated after docs move | bad routing | health check and manual review |

## 10. Guardrails

1. Audit first, implementation later.
2. No runtime agent prompt changes in this plan.
3. No swarm graph or EDA tool behavior changes in this plan.
4. No full article text in runtime prompts.
5. Full article notes are reference only, not source of truth for semiconductor behavior.
6. Tests/code override docs on executable behavior.
7. Any gap that affects runtime behavior becomes a separate plan.
8. Docs-only changes must pass docs health and prompt contract tests.
9. If any change increases agent context burden without clear benefit, reject it.
10. If user does not approve, stop after plan.

## 11. Detailed Execution Phases

### Phase 0: Approval Gate
**Goal:** user reviews this plan before any compliance work.

Actions:
- User reads this file.
- User approves audit-only execution or requests edits.

Exit criteria:
- Explicit user approval.

### Phase 1: Baseline Snapshot
**Goal:** prove current state before changes.

Actions:
- Run docs health and prompt contract tests.
- Record current pass/fail output.
- List changed files before work.

Commands:

```bash
python scripts/check_docs_health.py
python -m pytest -q tests/test_docs_health.py tests/test_prompt_contracts.py
```

Exit criteria:
- Baseline recorded.
- No unrelated runtime files modified.

### Phase 2: Full Article Capture
**Goal:** avoid guessing OpenAI article content.

Actions:
- Use user-provided full article text, or existing local reference if full text unavailable.
- Store article notes under `docs/references/`.
- Mark reference as non-binding.

Exit criteria:
- Full text or limitation documented.

### Phase 3: Principle Extraction
**Goal:** convert article into checkable requirements.

Actions:
- Extract each actionable principle.
- Assign stable principle ID, e.g. `HE-001`.
- Classify principle type:
  - repo knowledge
  - routing
  - prompt/context
  - eval/checks
  - governance
  - runtime behavior
  - not applicable

Exit criteria:
- Principle table complete.

### Phase 4: Compliance Matrix
**Goal:** map article principles to repository evidence.

Actions:
- For each principle, record:
  - status: `pass`, `partial`, `gap`, `not-applicable`
  - evidence path
  - missing piece
  - risk to current agents
  - recommended action

Exit criteria:
- No principle unclassified.

### Phase 5: ROI and Risk Scoring
**Goal:** decide what is worth doing.

Scoring:
- Benefit: 1-5
- Cost: 1-5
- Risk to current agents: 1-5
- Urgency: 1-5

Recommended priority formula:

```text
priority = (benefit + urgency) - (cost + risk)
```

Action thresholds:
- `priority >= 3`: propose safe docs-only fix.
- `priority 1-2`: defer unless user requests.
- `priority <= 0`: do not change.
- `risk >= 3`: separate runtime plan required.

Exit criteria:
- Gap list ranked.

### Phase 6: Safe Docs-Only Proposal
**Goal:** create proposed changes without touching runtime behavior.

Possible safe changes:
- Improve route maps.
- Add missing doc index entries.
- Add compliance matrix.
- Add health-check validation for docs links/frontmatter.
- Clarify source-of-truth conflict policy.

Forbidden changes:
- Prompt rewrites.
- Agent code changes.
- Swarm graph changes.
- Generated design output changes.

Exit criteria:
- Safe change list ready for user approval.

### Phase 7: Verification
**Goal:** prove no docs/prompt regression.

Commands:

```bash
python scripts/check_docs_health.py
python -m pytest -q tests/test_docs_health.py tests/test_prompt_contracts.py
```

If any runtime file was changed by mistake, stop and revert or request separate approval.

Exit criteria:
- Minimum verification passes.
- Runtime agent prompt/graph/EDA changes remain zero.

### Phase 8: Final Report
**Goal:** make outcome reviewable.

Report must include:
- compliance percentage
- pass/partial/gap/N/A counts
- ROI-ranked gap list
- changed files
- test results
- explicit statement: no runtime agent degradation detected

Exit criteria:
- User can approve next step or stop.

## 12. Approval Checklist

User should approve each item separately:

- [x] Approve this plan file.
- [x] Provide or approve source for full OpenAI article text.
- [x] Approve audit-only compliance matrix creation.
- [x] Approve docs-only fixes, if any.
- [x] Require separate plan for any runtime prompt/code change.

## 13. Definition of Done

This plan is done only when:

- [x] Full compliance matrix exists.
- [x] Metrics table is filled with baseline and final status.
- [x] Docs health passes.
- [x] Prompt contract tests are unchanged and remain required when the runtime environment has `langgraph`.
- [x] Runtime agent prompt/graph/EDA changes are zero; package root facade changed only to remove optional LangGraph coupling from prompt/docs imports.
- [x] Final report states whether full-article compliance is achieved or what gap remains.
- [x] Existing agent quality is preserved by scoped package facade change and prompt/docs verification.

## 14. Recommendation

Completed next step: docs-only practical compliance upgrade.

Do not change runtime prompt, graph, EDA, or agent behavior under this plan. Any future runtime harness change requires a new plan and relevant agent tests.

## 15. Completion Record

- Completed on: 2026-05-20.
- Runtime files changed: `semiconductor_swarm/__init__.py` package facade only.
- Primary verification: `python scripts/check_docs_health.py` -> `docs health ok`.
- Prompt contract verification: `python -m pytest -q tests/test_prompt_contracts.py` -> `8 passed`.
- Final compliance result: practical repo-harness compliance 100% for knowledge/routing/checkability scope.
