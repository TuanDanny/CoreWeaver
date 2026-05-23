---
title: OpenAI Harness Engineering Full Compliance Matrix
status: active
owner: docs-governance
type: governance
last_reviewed: 2026-05-20
source_of_truth: true
related_plan:
  - docs/exec-plans/completed/openai-harness-full-compliance-plan.md
related_reference:
  - docs/references/openai-harness-engineering-full-notes.md
runtime_agent_changes: package-facade-only
---

# OpenAI Harness Engineering Full Compliance Matrix

## Scope
Audit Semiconductor Swarm against practical Harness Engineering principles from the official OpenAI article and the local reference notes.

This is a repo-harness compliance matrix, not a semiconductor signoff claim. Runtime chip-design quality is still governed by code, tests, product specs, and strict signoff gates.

## Verification Baseline
Minimum check:

```bash
python scripts/check_docs_health.py
```

Expected result:

```text
docs health ok
```

Prompt/runtime tests remain required for prompt or agent code changes. This pass changed only the package root facade so prompt/docs checks do not require optional LangGraph imports; swarm orchestration remains in `semiconductor_swarm/swarm_graph.py`.

## Principle Matrix

| ID | Principle | Status | Evidence | Guardrail |
|---|---|---|---|---|
| HE-001 | Repository knowledge is durable system of record | pass | `docs/design-docs/repo-knowledge-store.md`, `docs/governance/source-of-truth-policy.md`, `PLANS.md` | Code/tests still define executable behavior. |
| HE-002 | Agents get concise maps, not huge manuals | pass | `AGENTS.md`, `ARCHITECTURE.md`, `docs/knowledge-map.yaml` | `AGENTS.md` remains a map only. |
| HE-003 | Deep knowledge lives in structured docs | pass | `docs/design-docs/`, `docs/product-specs/`, `docs/governance/`, `docs/prompts/`, `docs/agent-task-cards/` | Frontmatter required by docs health. |
| HE-004 | Task routes are explicit | pass | `AGENTS.md`, `docs/knowledge-map.yaml`, `PLANS.md` | Health check validates active plan routing. |
| HE-005 | Plans are versioned and status is unambiguous | pass | `docs/exec-plans/active/`, `completed/`, `superseded/` | Health check compares folder contents to indexes. |
| HE-006 | Superseded knowledge is preserved but not active | pass | `docs/exec-plans/superseded/index.md` | Superseded plans have `source_of_truth: false`. |
| HE-007 | Generated/manual indexes do not drift silently | pass | `docs/generated/*`, `scripts/check_docs_health.py` | Health check validates selected backtick paths. |
| HE-008 | Docs are machine-checkable | pass | `scripts/check_docs_health.py`, `tests/test_docs_health.py` | Docs health checks required files, frontmatter, links, knowledge-map paths, plan indexes, generated paths. |
| HE-009 | Prompt/context sources are explicit | pass | `docs/prompts/index.md`, `docs/prompts/canonical-prompts.md`, `docs/prompt_compliance_matrix.yaml` | Prompt contract tests remain the runtime-prompt guard. |
| HE-010 | Source-of-truth hierarchy is clear | pass | `AGENTS.md`, `docs/governance/source-of-truth-policy.md` | Conflicts resolve to tests/code first. |
| HE-011 | Legacy knowledge is retained until migrated | pass | `docs/legacy/index.md`, `docs/exec-plans/superseded/index.md` | Historical docs are labelled non-primary. |
| HE-012 | Runtime quality is protected during harness work | pass | `semiconductor_swarm/__init__.py`, prompt/docs tests | Package root is lightweight; graph runtime stays in `semiconductor_swarm/swarm_graph.py`. |
| HE-013 | Compliance result is recorded | pass | `docs/governance/harness-engineering-compliance-audit.md`, this matrix | Re-run docs health after routing changes. |
| HE-014 | Recurring cleanup is cheap | pass | `scripts/check_docs_health.py`, `docs/exec-plans/tech-debt-tracker.md` | Checker can run locally/CI; automation may call same script. |

## Summary Counts

- pass: 14
- partial: 0
- gap: 0
- not-applicable: 0

Practical Harness Engineering compliance for repo knowledge/routing/checkability: 100%.

## Residual Non-Harness Risks

These do not reduce Harness Engineering compliance, but remain semiconductor workflow risks:

- Strict real signoff still depends on real formal, real DV, and real Quartus evidence.
- Agent2 V4 strict/nightly closure remains active work.
- Generated chip artifacts remain non-source-of-truth unless regenerated and verified.

## Maintenance Rule

Run this before claiming docs/harness health:

```bash
python scripts/check_docs_health.py
```

Run prompt tests too when prompts or runtime agent imports change:

```bash
python -m pytest -q tests/test_docs_health.py tests/test_prompt_contracts.py
```
