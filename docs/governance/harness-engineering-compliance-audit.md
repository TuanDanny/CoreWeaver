---
title: Harness Engineering Compliance Audit
status: active
owner: docs-governance
type: governance
last_reviewed: 2026-05-20
source_of_truth: true
related_reference:
  - docs/references/openai-harness-engineering.md
---

# Harness Engineering Compliance Audit

## Scope
Audit repository knowledge system against locally captured OpenAI Harness Engineering reference principles.

## Compliance Matrix
| Principle | Evidence | Status |
|---|---|---|
| Repository knowledge is system of record | `docs/design-docs/repo-knowledge-store.md`, `docs/governance/source-of-truth-policy.md`, local-only private plans | pass |
| Give agents a map, not a long manual | `AGENTS.md`, `ARCHITECTURE.md`, `docs/knowledge-map.yaml` | pass |
| Keep `AGENTS.md` concise | `AGENTS.md` is 43 lines and routes to deeper docs | pass |
| Put deeper knowledge in structured docs | `docs/design-docs/`, `docs/product-specs/`, `docs/governance/`, `docs/prompts/`, `docs/agent-task-cards/`, `docs/generated/`, `docs/legacy/` | pass |
| Make docs maintainable and checkable | `scripts/check_docs_health.py`, `tests/test_docs_health.py`, `tests/test_prompt_contracts.py` | pass |
| Keep canonical prompt paths explicit | `docs/prompts/index.md`, `docs/prompts/canonical-prompts.md`, `docs/knowledge-map.yaml` | pass |
| Preserve legacy knowledge until migration | `docs/legacy/index.md`, local-only private plan archive | pass |
| Define conflict/source-of-truth order | `AGENTS.md`, `docs/governance/source-of-truth-policy.md` | pass |
| Keep public/private boundary unambiguous | `.gitignore`, `docs/GITHUB_PUBLISHING.md`, `scripts/check_docs_health.py` | pass |
| Detect stale generated/manual index paths | `scripts/check_docs_health.py`, `docs/generated/agent-contract-index.md`, `docs/generated/prompt-contract-index.md` | pass |

## Verification Run
Latest verified commands:

```bash
python scripts/check_docs_health.py
python -m pytest -q tests/test_docs_health.py
python -m pytest -q tests/test_prompt_contracts.py
```

Latest result:

```text
docs health ok
1 passed
8 passed
```

## Limits
- This audit uses non-verbatim local notes from the official OpenAI Harness Engineering article.
- It does not mirror the external article text; external reference remains non-binding.
- Full `python -m pytest -q` may include real EDA/tooling tests and should be run only when environment/toolchain is ready.

## Verdict
Repository-level Harness Engineering system is practically compliant: maps are concise, deeper knowledge is routed, stale plan state is machine-checked, generated indexes are guarded, prompt contracts run without graph dependencies, and runtime agent behavior was not changed.
