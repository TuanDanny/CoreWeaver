---
title: Kiem tra toan bo Agent AI risk register
status: generated
owner: docs-governance
type: generated
last_reviewed: 2026-05-17
source_of_truth: false
---

# Kiem tra toan bo Agent AI - Risk Register

| Risk | Likelihood | Impact | Area | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|
| Real EDA tools differ across machines | medium | high | tools | `tool_detection.py`, no-tool exceptions, real-tool tests | Tool Auditor | monitored |
| Generated artifacts become stale after source changes | medium | medium | generated | generated outputs not used as primary test oracle; generation tests validate in-memory output | Test Auditor | monitored |
| Windows-specific simulator behavior | medium | medium | tools | list-form subprocess calls, explicit Windows aliases for Verilator | Tool Auditor | monitored |
| Prompt/code drift over time | medium | high | docs/tests | prompt contract tests and compliance docs | Prompt Auditor | monitored |
| Local ignored secret-like config disclosure | low | medium | security | `.gitignore` and docs health guard ensure `codex_api.local.json` remains untracked/ignored | Security Auditor | guarded |
| Resume checkpoint/state mismatch | low | medium | cli/orchestration | `_ensure_resume_checkpoint()` preflight plus negative/positive tests guard missing/fresh checkpoint state | Graph Auditor | guarded; BUG-P3-01 closed |
