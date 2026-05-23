---
title: Kiem tra toan bo Agent AI test matrix
status: generated
owner: docs-governance
type: generated
last_reviewed: 2026-05-17
source_of_truth: false
---

# Kiem tra toan bo Agent AI - Test Matrix

| Test | Scope | Command | Expected | Actual | Status | Notes |
|---|---|---|---|---|---|---|
| Docs health | docs/source-of-truth/local config guard | `python scripts/check_docs_health.py` | pass | `docs health ok` | pass | run after remediation |
| Prompt/docs contract | prompt compliance | `python -m pytest -q tests/test_docs_health.py tests/test_prompt_contracts.py` | pass | `9 passed in 0.41s` | pass | Pass 1 evidence |
| Agent1+Agent2 group | architect + RTL | `python -m pytest -q tests/test_docs_health.py tests/test_prompt_contracts.py tests/test_agent1.py tests/test_agent2.py` | pass | `42 passed in 0.96s` | pass | after remediation |
| Core agent/graph/prompt group | agents 1-5 + graph + prompt | `python -m pytest tests/test_agent1.py tests/test_agent2.py tests/test_agent3.py tests/test_agent4.py tests/test_agent5.py tests/test_swarm_graph.py tests/test_prompt_contracts.py -q` | pass | `68 passed in 14.13s` | pass | Pass 2 evidence |
| Full suite | all tests | `python -m pytest tests -q` | pass | `75 passed in 14.14s` | pass | Pass 2 evidence |
| Compileall | syntax/import compilation | `python -m compileall semiconductor_swarm scripts tests main.py` | pass | completed listings | pass | Pass 2 evidence |
| Real tool checker | EDA tool availability | `python scripts/check_real_tools.py` | pass or clear missing list | all groups available: `dv`, `formal`, `quartus` | pass | Windows tools detected |
| Pass 3 golden A | end-to-end stop-after agent4 | `python debug_runners\run_partial.py "IoT AI camera chip less than 1W 100MHz" --stop-after agent4 --project-name pass3golden --thread-id pass3golden_a --output-dir outputs\pass3_golden_a --checkpoint-db .swarm\pass3_golden_a.sqlite --output-policy overwrite` | `SIGNOFF_READY` | pass; 22 RTL `.sv`; plan exists; checkpoint exists | pass | generated artifact audit |
| Pass 3 golden B | deterministic repeat | `python debug_runners\run_partial.py "IoT AI camera chip less than 1W 100MHz" --stop-after agent4 --project-name pass3golden --thread-id pass3golden_b --output-dir outputs\pass3_golden_b --checkpoint-db .swarm\pass3_golden_b.sqlite --output-policy overwrite` | `SIGNOFF_READY` | pass; 22 RTL `.sv`; plan exists; checkpoint exists | pass | repeat run |
| Pass 3 golden compare | artifact determinism | `python -c "... compare outputs/pass3_golden_a outputs/pass3_golden_b ..."` | file lists equal; explain diffs | `FILE_LIST_EQUAL=True`; 109 files each; diffs only Agent1 trace/evidence files | pass-with-notes | runtime evidence differs by trace metadata |
| Resume negative | CLI error path | `python main.py --resume --thread-id missing-pass3 --checkpoint-db outputs\pass3_missing_resume.sqlite --output-dir outputs\pass3_missing_resume --output-policy overwrite` | clear nonzero error | exits `1` with `Resume error: no paused checkpoint found for thread_id='missing-pass3'...`; no `KeyError`; covered by `test_cli_resume_preflight_rejects_missing_checkpoint` and `test_cli_resume_preflight_accepts_paused_checkpoint` | pass | BUG-P3-01 fixed |
| Pass 3 post-fix full suite | regression | `python -m pytest -q` | all tests pass | `77 passed in 15.01s` | pass | after BUG-P3-01 fix |
