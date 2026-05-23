---
title: Tech Debt Tracker
status: active
owner: docs-governance
type: exec-plan
last_reviewed: 2026-05-20
source_of_truth: true
---

# Tech Debt Tracker

| Item | Area | Status | Notes |
|---|---|---|---|
| Docs health checks | knowledge-store | done | `scripts/check_docs_health.py` validates required files, frontmatter, links, knowledge-map paths, plan indexes, selected generated paths, and local-secret guards. |
| Machine-readable routing | knowledge-store | done | `docs/knowledge-map.yaml` is active and checked for path existence. |
| Legacy docs migration | knowledge-store | monitored | Legacy and superseded docs are preserved with explicit indexes; active/completed/superseded routes are separated. |
| Prompt contract tests in bundled runtime | environment | done | Package root facade no longer imports LangGraph; `tests/test_prompt_contracts.py` passes in bundled Python. |
