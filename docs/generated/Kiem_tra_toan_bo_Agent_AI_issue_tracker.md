---
title: Kiem tra toan bo Agent AI issue tracker
status: generated
owner: docs-governance
type: generated
last_reviewed: 2026-05-20
source_of_truth: false
---

# Kiem tra toan bo Agent AI - Issue Tracker

| ID | Severity | Area | File | Evidence | Impact | Fix proposal | Test needed | Status |
|---|---|---|---|---|---|---|---|---|
| BUG-P1-01 | high | agent2/packaging/imports | `semiconductor_swarm/agents/__init__.py` | import probe failed before remediation | package facade import broke expected module exports | lightweight facade exports nested modules/classes | import probe + agent tests | fixed |
| BUG-P1-02 | medium | docs/migration | `README.md`, `docs/legacy/index.md`, `scripts/reorg_project.py` | migration residue search found old root agent/generated paths | users may follow stale paths | update active docs; keep legacy references labeled | docs health + residue search | fixed for active docs |
| BUG-P1-03 | low | security/config | `codex_api.local.json`, `.gitignore` | secret-like `api_key`; ignored and untracked | accidental disclosure risk | keep ignored; guard in docs health | `git check-ignore`, docs health | guarded |
| PASS2-NONE | info | agent/tool/graph/tests | Agent1-Agent5, tools, tests | full suite `75 passed`; docs health ok; compileall ok; real tools found | no new verified issue | continue Pass 3 for generated/golden/negative paths | Pass 3 commands | closed |
| BUG-P3-01 | medium | cli/resume/error-path | `main.py`, `tests/test_swarm_graph.py` | missing/fresh checkpoint resume previously crashed with `KeyError: 'requirement'` | bad UX and opaque failure when resume checkpoint/state missing | `_ensure_resume_checkpoint()` validates paused checkpoint before graph resume; negative and positive preflight tests added | `python main.py --resume --thread-id missing-pass3 --checkpoint-db outputs\pass3_missing_resume.sqlite --output-dir outputs\pass3_missing_resume --output-policy overwrite` -> clear `Resume error`; `python -m pytest tests/test_swarm_graph.py -q` -> `8 passed`; `python -m pytest -q` -> `77 passed` | closed |
| BUG-P3-DOCS-01 | medium | docs/plans-routing | `PLANS.md`, `docs/knowledge-map.yaml`, `docs/exec-plans/active/`, `docs/exec-plans/completed/`, `docs/exec-plans/superseded/` | 2026-05-20 fix: active/completed/superseded routes separated; duplicate completed plan removed from active; Agent2 V1-V3 moved to superseded; `SWARM_WIDE...` added to active route maps; docs health now checks plan indexes | stale plan routing risk reduced and machine-guarded | keep plan indexes synchronized through docs health | `python scripts/check_docs_health.py` | closed |
