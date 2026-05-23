---
title: Kiem tra toan bo Agent AI audit report
status: active
owner: docs-governance
type: governance
last_reviewed: 2026-05-20
source_of_truth: false
---

# Kiem tra toan bo Agent AI - Audit Report

## Summary
- Audit source: `docs/exec-plans/active/Kiem_tra_toan_bo_Agent_AI.md`.
- Canonical prompt: `docs/semiconductor_swarm_ai.md`.
- Current result: Pass 1 fixed/guarded; Pass 2 100% final gate pass; Pass 3 generated/golden/negative audit complete and BUG-P3-01 fixed.
- Runtime code changes in this pass: `main.py` resume preflight; `tests/test_swarm_graph.py` regression tests.

## Verification Evidence
- `python -m pytest tests -q` -> `75 passed in 14.14s`.
- `python scripts/check_docs_health.py` -> `docs health ok`.
- `python -m compileall semiconductor_swarm scripts tests main.py` -> pass.
- `python scripts/check_real_tools.py` -> all `dv`, `formal`, `quartus` tool groups available.
- Pass 2 final gate:
  - `tests/test_agent1.py` -> `25 passed in 0.91s`.
  - `tests/test_agent2.py` -> `8 passed in 0.45s`.
  - `tests/test_agent3.py` -> `6 passed in 0.41s`.
  - `tests/test_agent4.py` -> `8 passed in 0.51s`.
  - `tests/test_agent5.py` -> `7 passed in 0.45s`.
  - `tests/test_swarm_graph.py tests/test_agent_pipeline.py` -> `7 passed in 14.01s`.
  - `tests/test_real_tool_detection.py` -> `1 passed in 1.17s`.

## Findings
- BUG-P1-01 fixed: package facade import mismatch.
- BUG-P1-02 fixed for active docs: migration residue in README/legacy context.
- BUG-P1-03 guarded: ignored local secret-like config remains untracked.
- Phase 3 docs health pass: `python scripts/check_docs_health.py` -> `docs health ok`.
- Phase 3 route checks: `docs/knowledge-map.yaml` references 58 paths, missing `[]`; rough local Markdown broken links `0`.
- BUG-P3-DOCS-01 closed on 2026-05-20: active/completed/superseded plan routes are separated; `PLANS.md`, `docs/knowledge-map.yaml`, and exec-plan indexes are sync-checked by docs health.
- Pass 2 created no new verified defects.
- Pass 2 final gate created no new defects.
- Pass 3 golden demo x2: `outputs/pass3_golden_a` and `outputs/pass3_golden_b` both `SIGNOFF_READY`, 109 files each, 22 RTL `.sv` files each.
- Pass 3 determinism: file lists match exactly; content diffs limited to Agent1 trace/evidence files (`agent1_codex_evidence.json`, `agent1_codex_response.md`, `agent1_v4_replay_bundle.json`, `agent1_v4_tool_ledger.jsonl`, `agent1_v4_trace.jsonl`).
- BUG-P3-01 fixed: `python main.py --resume --thread-id missing-pass3 --checkpoint-db outputs\pass3_missing_resume.sqlite --output-dir outputs\pass3_missing_resume --output-policy overwrite` now exits `1` with clear `Resume error: no paused checkpoint found...` instead of `KeyError: 'requirement'`.
- Post-fix tests: `python -m pytest tests/test_swarm_graph.py -q` -> `8 passed`; `python -m pytest -q` -> `77 passed`.

## Mini-Agent Notes
- Repo Auditor: repo/source/generated split mapped; generated artifact staleness tracked as risk.
- Prompt Auditor: prompt contract tests pass; canonical prompt routing intact.
- Agent Auditor: Agent1-Agent5 code/tests audited; handoffs pass.
- Graph Auditor: orchestration tests pass; state handoffs documented.
- Tool Auditor: detection/runners audited; real EDA tools detected.
- Test Auditor: full suite pass; compileall pass.
- Security Auditor: local config ignored/untracked guard present.
- Docs Auditor: docs health pass.

## Recommendation
Status: `Pass 3 100% pass`; BUG-P3-01 closed; full suite and resume negative test pass. System declared migration-stable for audited scope.
