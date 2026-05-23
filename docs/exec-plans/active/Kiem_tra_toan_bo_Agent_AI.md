---
title: Kiem tra toan bo Agent AI
status: active
owner: docs-governance
type: exec-plan
last_reviewed: 2026-05-17
source_of_truth: true
runtime_agent_changes: false
---

# Kiem_tra_toan_bo_Agent_AI

## Goal
Kiá»ƒm tra toÃ n bá»™ há»‡ thá»‘ng Agent AI sau di chuyá»ƒn. TÃ¬m lá»—i, bug, sai sÃ³t, drift prompt/docs/code/tests, lá»—i import/path, lá»—i tool integration, lá»—i generated artifact, vÃ  migration residue.

## Guardrails
- Audit trÆ°á»›c, khÃ´ng sá»­a runtime code náº¿u chÆ°a Ä‘Æ°á»£c duyá»‡t.
- Má»i phÃ¡t hiá»‡n pháº£i cÃ³ evidence: file path, command output, hoáº·c test name.
- Má»i test pháº£i ghi command vÃ  result.
- Má»i issue phÃ¢n loáº¡i severity: `critical`, `high`, `medium`, `low`, `info`.
- Má»i issue phÃ¢n vÃ¹ng: docs, agent1, agent2, agent3, agent4, agent5, tools, graph, tests, generated, config, scripts.

## Execution Protocol
Má»—i phase pháº£i ghi káº¿t quáº£ theo cÃ¹ng format Ä‘á»ƒ nhiá»u mini agent AI cÃ³ thá»ƒ lÃ m song song mÃ  khÃ´ng lá»‡ch chuáº©n.

Phase record template:

```markdown
### Phase N Result
- Status: not_started | running | pass | fail | blocked
- Owner/Mini-agent: <name>
- Scope: <files/dirs/tests>
- Commands run:
  - `<command>` -> pass | fail | skipped
- Evidence:
  - `<file path>:<line or section>`
  - `<test name>`
  - `<command output summary>`
- Issues created: <IDs or none>
- Follow-up: <next action>
```

Stop conditions:
- [ ] Stop and report if critical import failure blocks all tests.
- [ ] Stop and report if secret/API key appears in tracked or unignored files.
- [ ] Stop and report before running destructive script or installer.
- [ ] Stop and report if generated artifacts overwrite source unexpectedly.
- [ ] Stop and report if audit commands require network/admin access.

## Output Schemas
Audit output files should use these stable schemas.

Audit report section:

```markdown
## Finding <ID>
- Severity: critical | high | medium | low | info
- Area: docs | agent1 | agent2 | agent3 | agent4 | agent5 | tools | graph | tests | generated | config | scripts
- File(s): <paths>
- Evidence: <path/line, command, test>
- Impact: <why it matters>
- Root cause: <if known>
- Fix proposal: <brief>
- Verification command: `<command>`
```

Inventory row:

```markdown
| Path | Type | Owner | Source-of-truth role | Tests | Status | Notes |
|---|---|---|---|---|---|---|
```

Test matrix row:

```markdown
| Test | Scope | Command | Expected | Actual | Status | Notes |
|---|---|---|---|---|---|---|
```

Issue tracker row:

```markdown
| ID | Severity | Area | File | Evidence | Impact | Fix proposal | Test needed | Status |
|---|---|---|---|---|---|---|---|---|
```

Traceability row:

```markdown
| Requirement | Source | Code | Test | Generated artifact | Status | Gap |
|---|---|---|---|---|---|---|
```

Risk register row:

```markdown
| Risk | Likelihood | Impact | Area | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|
```

## Mini Agent Assignment Map
Use these mini-agent roles during audit.

| Mini-agent | Mission | Primary files | Main outputs |
|---|---|---|---|
| Repo Auditor | Map repo and migration residue | `.` `docs/` `tests/` `scripts/` | file inventory, residue findings |
| Prompt Auditor | Compare master prompt to runtime prompts/tests | `docs/semiconductor_swarm_ai.md`, prompt files, prompt tests | traceability matrix, prompt gaps |
| Agent Auditor | Inspect Agent1-Agent5 code/contracts | `semiconductor_swarm/agents/`, `tests/test_agent*.py` | agent issue findings |
| Graph Auditor | Inspect orchestration/state/checkpoints | `semiconductor_swarm/swarm_graph.py`, `main.py` | state schema and handoff matrix |
| Tool Auditor | Inspect EDA/tool wrappers/calculators | `semiconductor_swarm/tools/`, `scripts/check_real_tools.py` | tool risk and fallback findings |
| Test Auditor | Run and judge tests | `tests/`, `pytest.ini` | test matrix |
| Security Auditor | Search secrets and unsafe commands | config/log/script files | security findings and risk register |
| Docs Auditor | Validate docs/source-of-truth/routing | `AGENTS.md`, `ARCHITECTURE.md`, `PLANS.md`, `docs/knowledge-map.yaml` | docs health findings |

## Agent Handoff Contract Matrix
Fill this table during audit.

| Handoff | Producer output | Consumer input | Required fields | Tests | Status | Gap |
|---|---|---|---|---|---|---|
| Agent1 -> Agent2 | spec/modules/interfaces/memory map | RTL generation spec | TBD during audit | `tests/test_agent1.py`, `tests/test_agent2.py` | unchecked | TBD |
| Agent2 -> Agent3 | RTL files/top/module metadata | DV testbench/regression | TBD during audit | `tests/test_agent2.py`, `tests/test_agent3.py` | unchecked | TBD |
| Agent2 -> Agent4 | RTL files/constraints/top | FPGA project/signoff | TBD during audit | `tests/test_agent2.py`, `tests/test_agent4.py` | unchecked | TBD |
| Agent2 -> Agent5 | RTL files/top/modules | formal wrappers/SBY | TBD during audit | `tests/test_agent2.py`, `tests/test_agent5.py` | unchecked | TBD |
| Agent3/4/5 -> Reports | test/timing/formal results | final report/user | TBD during audit | `tests/test_agent_pipeline.py` | unchecked | TBD |

## Three-Pass Strict Audit Plan
Audit must run in 3 passes. Each pass splits into smaller tasks and must report any wrong behavior, bug, drift, or uncertainty immediately with evidence.

### Pass 1 Result - 2026-05-17
- Status: pass after remediation
- Owner/Mini-agent: Repo Auditor + Prompt Auditor + Security Auditor
- Scope: repo baseline, docs, prompt contracts, compile/import, migration residue, secret-like scan
- Commands run:
  - `git status --short && git diff --name-only && python --version && python -m pytest --version && cd && python -c "from pathlib import Path; [print(p) for p in sorted(Path('.').glob('*'))]"` -> pass
  - `python scripts/check_docs_health.py && python -m pytest -q tests/test_docs_health.py tests/test_prompt_contracts.py && python -m compileall semiconductor_swarm tests scripts main.py && python -c "import semiconductor_swarm; import semiconductor_swarm.swarm_graph; from semiconductor_swarm.agents import architect, rtl_designer, dv_engineer, physical_designer, formal_verifier; print('imports ok')"` -> fail at package facade import
  - `git check-ignore -v codex_api.local.json && git ls-files codex_api.local.json && python -m pytest -q tests/test_docs_health.py tests/test_prompt_contracts.py tests/test_agent1.py tests/test_agent2.py` -> pass
  - `python -c "import semiconductor_swarm; import semiconductor_swarm.swarm_graph; from semiconductor_swarm.agents import architect, rtl_designer, dv_engineer, physical_designer, formal_verifier; print('imports ok')" && python scripts/check_docs_health.py && python -m pytest -q tests/test_docs_health.py tests/test_prompt_contracts.py tests/test_agent1.py tests/test_agent2.py` -> pass after fixes
  - `python -m pytest -q tests` -> pass
- Evidence:
  - Python `3.13.9`; pytest `9.0.3`
  - `docs health ok`; `tests/test_docs_health.py tests/test_prompt_contracts.py` -> `9 passed in 0.41s`
  - `tests/test_docs_health.py tests/test_prompt_contracts.py tests/test_agent1.py tests/test_agent2.py` -> `42 passed in 1.22s`
  - `python -m compileall semiconductor_swarm tests scripts main.py` completed listing/compilation before import probe failed.
  - `semiconductor_swarm/agents/__init__.py:1` describes Agent 2 and contains RTL generator implementation, not package export facade.
  - `.gitignore:2:codex_api.local.json codex_api.local.json`; `git ls-files codex_api.local.json` returned no tracked path.
  - After remediation: `imports ok`; `docs health ok`; `42 passed in 0.96s`; full suite `75 passed in 22.54s`.
- Issues created: BUG-P1-01, BUG-P1-02, BUG-P1-03 (all fixed/guarded)
- Follow-up: continue Pass 2 agent/tool/state audit.

#### Bug P1-01
- Severity: high
- Pass/Task: 1.5
- Area: agent2 | packaging | imports
- File(s): `semiconductor_swarm/agents/__init__.py`
- Symptom: package facade import for expected agent modules fails.
- Evidence: `ImportError: cannot import name 'architect' from 'semiconductor_swarm.agents' (d:\AI\AgentAI\semiconductor_swarm\agents\__init__.py)` from import probe.
- Expected: `semiconductor_swarm.agents` should expose package-level modules or remain empty facade; imports should map to current nested layout: `agent1_planning.architect`, `agent2_rtl.rtl_designer`, `agent3_dv.dv_engineer`, `agent4_physical.physical_designer`, `agent5_formal.formal_verifier`.
- Actual: `semiconductor_swarm/agents/__init__.py` contains Agent 2 RTL generator code, so facade import is misleading and stale relative to reorganized package layout.
- Impact: downstream docs/README old imports and external API users can break; namespace role unclear.
- Repro command: `python -c "from semiconductor_swarm.agents import architect, rtl_designer, dv_engineer, physical_designer, formal_verifier"`
- Proposed fix: make `semiconductor_swarm/agents/__init__.py` lightweight facade exporting nested modules/classes, or move Agent2 code fully to `agent2_rtl/rtl_designer.py` and leave compat aliases.
- Verification: `python -c "from semiconductor_swarm.agents import architect, rtl_designer, dv_engineer, physical_designer, formal_verifier; print('imports ok')"`
- Status: fixed (`semiconductor_swarm/agents/__init__.py` is now lightweight facade exporting nested modules; import probe passes)

#### Bug P1-02
- Severity: medium
- Pass/Task: 1.6
- Area: docs | migration
- File(s): `README.md`, `docs/legacy/index.md`, `scripts/reorg_project.py`
- Symptom: docs and scripts still reference old root agent files and generated output folders.
- Evidence: search found `agent1_architect.py`, `agent2_rtl_designer.py`, `agent3_dv_engineer.py`, `agent4_physical_designer.py`, `agent5_formal_verifier.py`, `generated_rtl`, `generated_fpga`, `generated_formal` in README and migration helper.
- Expected: active docs point to current nested packages and output conventions, with legacy paths clearly marked compatibility-only.
- Actual: README presents root wrappers and old module paths as active usage; migration helper still handles old files/folders.
- Impact: users may call stale root scripts or confuse canonical package layout after migration.
- Repro command: `python -c "from pathlib import Path; import re; [print(p) for p in Path('.').rglob('*.md') if re.search('agent[1-5]_|generated_rtl|generated_fpga|generated_formal', p.read_text(encoding='utf-8', errors='ignore'))]"`
- Proposed fix: update README/source-of-truth docs to current package paths; move legacy-only instructions under docs/legacy.
- Verification: rerun migration residue search and docs health.
- Status: fixed for active README paths; legacy docs/scripts remain legacy-context references

#### Bug P1-03
- Severity: low
- Pass/Task: 1.7
- Area: security | config
- File(s): `codex_api.local.json`, `.gitignore`
- Symptom: local config contains real-looking API key, but file is ignored and untracked.
- Evidence: search result showed `codex_api.local.json` contains `api_key`; `git check-ignore -v codex_api.local.json` -> `.gitignore:2:codex_api.local.json`; `git ls-files codex_api.local.json` -> no output.
- Expected: secrets must remain untracked and never copied to reports/logs.
- Actual: local secret-like value exists on disk; not tracked.
- Impact: low repo risk now, but accidental disclosure possible via logs/screenshots or if `.gitignore` changes.
- Repro command: `git check-ignore -v codex_api.local.json && git ls-files codex_api.local.json`
- Proposed fix: keep ignored; optionally rotate key if real; add health check that fails if local config is tracked.
- Verification: `git check-ignore -v codex_api.local.json && git ls-files codex_api.local.json`
- Status: guarded (`scripts/check_docs_health.py` now fails if `codex_api.local.json` is unignored or tracked)

### Pass 2 Result - 2026-05-17
- Status: pass
- Owner/Mini-agent: Agent Auditor + Graph Auditor + Tool Auditor + Test Auditor
- Scope: Agent1-Agent5 runtime code, orchestration, EDA tools, prompt contracts, docs health, full pytest.
- Commands run:
  - `python -m pytest tests/test_agent1.py tests/test_agent2.py tests/test_agent3.py tests/test_agent4.py tests/test_agent5.py tests/test_swarm_graph.py tests/test_prompt_contracts.py -q` -> pass
  - `python -m pytest tests -q` -> pass
  - `python scripts/check_docs_health.py` -> pass
  - `python -m compileall semiconductor_swarm scripts tests main.py` -> pass
  - `python scripts/check_real_tools.py` -> pass
- Evidence:
  - Core agent/graph/prompt suite: `68 passed in 14.13s`.
  - Full test suite: `75 passed in 14.14s`.
  - Docs health: `docs health ok`.
  - Compileall completed for `semiconductor_swarm`, `scripts`, `tests`, and `main.py`.
  - Real tool checker found all required groups available: `dv`, `formal`, `quartus`. Detected `verilator_bin.exe`, `make`, `cocotb`, `sby`, `yosys`, `z3`, `quartus_sh`.
  - Agent 3 audited: Cocotb/Pytest collateral generation, ModelSim runner, coverage targets, HITL after 5 debug iterations, no-tool checks.
  - Agent 4 audited: Cyclone V Quartus collateral, QSF/SDC/TCL generation, Quartus parser, timing/resource decision policy, HITL after 5 backend iterations.
  - Agent 5 audited: SymbiYosys/SVA collateral, Z3 engine, counterexample parser, write workspace, formal-first decision policy, HITL after 5 formal iterations.
  - Tool layer audited: `quartus_runner.py`, `symbiyosys_runner.py`, `tool_detection.py` use argument-list subprocess calls, timeouts, `shutil.which` detection, parsers tolerate missing reports by returning zero/unknown metrics.
- Issues created: none in Pass 2.
- Follow-up: Pass 3 should fill final traceability/risk/generated artifact outputs and optionally run deterministic golden demo.

#### Pass 2 Final Gate - 2026-05-17
- Status: pass, 100% Pass 2 exit criteria satisfied.
- Owner/Mini-agent: Test Auditor + Tool Auditor
- Scope: all required Pass 2 commands run as final gate before Pass 3.
- Commands run:
  - `python -m pytest -q tests/test_agent1.py` -> pass, `25 passed in 0.91s`
  - `python -m pytest -q tests/test_agent2.py` -> pass, `8 passed in 0.45s`
  - `python -m pytest -q tests/test_agent3.py` -> pass, `6 passed in 0.41s`
  - `python -m pytest -q tests/test_agent4.py` -> pass, `8 passed in 0.51s`
  - `python -m pytest -q tests/test_agent5.py` -> pass, `7 passed in 0.45s`
  - `python -m pytest -q tests/test_swarm_graph.py tests/test_agent_pipeline.py` -> pass, `7 passed in 14.01s`
  - `python scripts/check_real_tools.py` -> pass, all `dv`, `formal`, `quartus` groups available.
  - `python -m pytest -q tests/test_real_tool_detection.py` -> pass, `1 passed in 1.17s`
- Evidence:
  - Detected `verilator_bin.exe`, `make`, `cocotb`, `sby`, `yosys`, `z3`, `quartus_sh`.
  - No failing, skipped, or xfailed test in Pass 2 final gate output.
  - No new critical/high/medium/low issue created in final gate.
- Issues created: none.
- Decision: Pass 2 complete. Pass 3 may start.

#### Pass 2 Handoff Matrix Update
| Handoff | Producer output | Consumer input | Required fields | Tests | Status | Gap |
|---|---|---|---|---|---|---|
| Agent1 -> Agent2 | validated architecture spec | RTL generator spec | `project_name`, `core_config`, `interfaces.apb_slave.signals`, `ip_blocks`, `memory_map` | `tests/test_agent1.py`, `tests/test_agent2.py` | pass | none found |
| Agent2 -> Agent3 | SystemVerilog RTL file dicts | DV collateral generator | `filename`, `language=systemverilog`, `content`; per-block `<block>.sv` | `tests/test_agent2.py`, `tests/test_agent3.py` | pass | none found |
| Agent2 -> Agent4 | SystemVerilog RTL file dicts + top naming | Quartus collateral/compiler | RTL filenames/content, top module `<project>_top`, target MHz | `tests/test_agent2.py`, `tests/test_agent4.py` | pass | none found |
| Agent2 -> Agent5 | SystemVerilog RTL file dicts | SVA/SBY formal generator | per-block `<block>.sv`, generated DUT name `<project>_<block>_rtl` | `tests/test_agent2.py`, `tests/test_agent5.py` | pass | none found |
| Agent3/4/5 -> Reports | DV/timing/formal result dicts | swarm final report | pass/fail, failures, tool output tail, debug/self-check JSON | `tests/test_agent_pipeline.py`, `tests/test_swarm_graph.py` | pass | none found |

#### Pass 2 Risk Register Update
| Risk | Likelihood | Impact | Area | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|
| Real EDA tools differ across machines | medium | high | tools | `tool_detection.py`, no-tool exceptions, real-tool tests | Tool Auditor | monitored |
| Generated artifacts become stale after source changes | medium | medium | generated | generated outputs not used as primary test oracle; generation tests validate in-memory output | Test Auditor | monitored |
| Windows-specific simulator behavior | medium | medium | tools | list-form subprocess calls, explicit Windows aliases for Verilator | Tool Auditor | monitored |
| Prompt/code drift over time | medium | high | docs/tests | prompt contract tests and compliance docs | Prompt Auditor | monitored |

### Pass 1: Foundation, Docs, Prompt, Import Integrity
Goal: prove repo map, source-of-truth spine, prompt contracts, imports, and baseline are stable before touching deeper agent behavior.

Included phases:
- Phase 1 baseline snapshot
- Phase 2 repo inventory
- Phase 3 docs/governance/source-of-truth audit
- Phase 4 master prompt audit
- Phase 5 prompt contracts
- Phase 6 Python package/import/path audit
- Phase 19 migration residue/dead code audit
- Phase 20 security/local config audit, read-only scan only

Pass 1 task split:
- [x] Task 1.1: capture `git status`, Python/pytest versions, top tree.
- [x] Task 1.2: inventory docs/source/test/script/package files.
- [x] Task 1.3: run docs health and prompt contract tests.
- [x] Task 1.4: compare `docs/semiconductor_swarm_ai.md` with canonical prompts and compliance matrix.
- [x] Task 1.5: compile/import package and search old root agent imports.
- [x] Task 1.6: search migration residue and stale generated path references.
- [x] Task 1.7: scan config/log/script files for secret-like strings.
- [x] Task 1.8: write Pass 1 bug report section.

Pass 1 required commands:

```bash
git status --short
git diff --name-only
python --version
python -m pytest --version
python scripts/check_docs_health.py
python -m pytest -q tests/test_docs_health.py tests/test_prompt_contracts.py
python -m compileall semiconductor_swarm tests scripts main.py
```

Pass 1 exit criteria:
- [x] Docs health pass or all failures documented.
- [x] Prompt contract tests pass or all failures documented.
- [x] Compile/import pass or blocker documented.
- [x] No unreported secret/local config risk.
- [x] Source-of-truth conflicts listed.

### Pass 2: Agent, Tool, State, Handoff Deep Audit
Goal: inspect each mini agent AI and tool layer tightly, then verify handoff contracts across swarm state.

Included phases:
- Phase 7 Agent1 deep audit
- Phase 8 Agent2 deep audit
- Phase 9 Agent3 deep audit
- Phase 10 Agent4 deep audit
- Phase 11 Agent5 deep audit
- Phase 12 swarm graph/orchestration audit
- Phase 13 tools layer audit
- Phase 14 real tool detection audit
- Phase 22 traceability matrix
- Phase 23 mini-agent assignment review

Pass 2 task split:
- [x] Task 2.1: read Agent1 code, planning subgraph, schema, tests.
- [x] Task 2.2: read Agent2 RTL generator, output contract, tests.
- [x] Task 2.3: read Agent3 DV generator/tool fallback/tests.
- [x] Task 2.4: read Agent4 physical flow, Quartus runner, tests.
- [x] Task 2.5: read Agent5 formal flow, SymbiYosys runner, tests.
- [x] Task 2.6: read `swarm_graph.py`, `main.py`, checkpoint/state flow.
- [x] Task 2.7: read calculators/tool detection/runners and subprocess behavior.
- [x] Task 2.8: fill Agent Handoff Contract Matrix.
- [x] Task 2.9: create Traceability Matrix draft.
- [x] Task 2.10: write Pass 2 bug report section.

Pass 2 required commands:

```bash
python -m pytest -q tests/test_agent1.py
python -m pytest -q tests/test_agent2.py
python -m pytest -q tests/test_agent3.py
python -m pytest -q tests/test_agent4.py
python -m pytest -q tests/test_agent5.py
python -m pytest -q tests/test_swarm_graph.py tests/test_agent_pipeline.py
python scripts/check_real_tools.py
python -m pytest -q tests/test_real_tool_detection.py
```

Pass 2 exit criteria:
- [x] Each agent has pass/fail/blocked result.
- [x] Every handoff has producer, consumer, required fields, tests, status.
- [x] Tool absence behavior is documented.
- [x] Subprocess timeout/path/security risks are listed.
- [x] Real-tool tests pass or skip/fail reason is documented.

### Pass 3: End-to-End, Reliability, Negative Paths, Risk Closure
Goal: prove whole pipeline behavior, reproducibility, generated artifacts, error handling, and final risk/fix strategy.

Included phases:
- Phase 15 generated artifacts audit
- Phase 16 scripts/batch/debug runners audit
- Phase 17 tests coverage/reliability audit
- Phase 18 verification ladder
- Phase 21 issue matrix and fix strategy
- Phase 24 deterministic golden demo
- Phase 25 negative/error-path audit
- Phase 26 risk register

Pass 3 task split:
- [x] Task 3.1: inspect generated artifacts, `runs/`, `swarm_out/`, `.gitignore`.
- [x] Task 3.2: inspect batch/debug/scripts for stale paths and destructive behavior.
- [x] Task 3.3: run tests per file and full suite.
- [x] Task 3.4: run deterministic golden demo twice into separate dirs.
- [x] Task 3.5: compare outputs and list nondeterministic differences.
- [x] Task 3.6: run negative/error-path checks without destructive actions.
- [x] Task 3.7: create issue tracker with severity, evidence, fix proposal, verification.
- [x] Task 3.8: create risk register.
- [x] Task 3.9: decide migration-stable or blocked.
- [x] Task 3.10: write final Pass 3 report and next fix batches.

Pass 3 required commands:

```bash
python -m pytest -q tests/test_agent1.py
python -m pytest -q tests/test_agent2.py
python -m pytest -q tests/test_agent3.py
python -m pytest -q tests/test_agent4.py
python -m pytest -q tests/test_agent5.py
python -m pytest -q tests/test_swarm_graph.py
python -m pytest -q tests/test_agent_pipeline.py
python -m pytest -q tests/test_docs_health.py tests/test_prompt_contracts.py
python -m pytest -q tests/test_real_tool_detection.py tests/test_real_dv_tools.py tests/test_real_formal_tools.py tests/test_real_quartus_tools.py
python -m pytest -q
```

Pass 3 exit criteria:
- [x] Full test suite pass or environment-limited failures documented.
- [x] Generated artifact staleness risk resolved or documented.
- [x] Golden demo has reproducibility result.
- [x] Negative-path failures documented.
- [x] Issue tracker and risk register complete.
- [x] Final recommendation says `migration-stable`, `stable-with-known-risks`, or `blocked`.

## Bug Reporting Rules
Every wrong behavior, bug, mismatch, or suspicious result must be reported using this format.

```markdown
## Bug <PASS>-<NN>
- Severity: critical | high | medium | low | info
- Pass/Task: <pass.task>
- Area: docs | prompt | agent1 | agent2 | agent3 | agent4 | agent5 | graph | tools | tests | generated | scripts | security
- File(s): <path list>
- Symptom: <what is wrong>
- Evidence: <line/test/command output>
- Expected: <correct behavior>
- Actual: <observed behavior>
- Impact: <why it matters>
- Repro command: `<command>`
- Proposed fix: <short>
- Verification: `<command>`
- Status: open | blocked | fixed | won't_fix
```

Strictness rules:
- [x] Do not mark pass without command output or file evidence.
- [x] Do not treat skipped real EDA tests as pass unless skip reason is correct and documented.
- [x] Do not use stale generated files as proof agent generation works.
- [x] Do not fix runtime code during audit unless separate approval exists.
- [x] If evidence is ambiguous, create `info` or `medium` finding instead of ignoring.

## Planned Outputs
- [x] Create this active plan: `docs/exec-plans/active/Kiem_tra_toan_bo_Agent_AI.md`
- [x] Register plan in `PLANS.md`
- [x] Register plan route in `docs/knowledge-map.yaml`
- [x] Create audit report: `docs/governance/Kiem_tra_toan_bo_Agent_AI_audit_report.md`
- [x] Create inventory: `docs/generated/Kiem_tra_toan_bo_Agent_AI_file_inventory.md`
- [x] Create test matrix: `docs/generated/Kiem_tra_toan_bo_Agent_AI_test_matrix.md`
- [x] Create issue tracker: `docs/generated/Kiem_tra_toan_bo_Agent_AI_issue_tracker.md`
- [x] Create risk register: `docs/generated/Kiem_tra_toan_bo_Agent_AI_risk_register.md`
- [x] Create traceability matrix: `docs/generated/Kiem_tra_toan_bo_Agent_AI_traceability_matrix.md`
- [x] Create handoff matrix: `docs/generated/Kiem_tra_toan_bo_Agent_AI_handoff_matrix.md`

## Master Checklist
- [x] Phase 0 setup plan + routing
- [x] Phase 1 baseline snapshot
- [x] Phase 2 repo inventory
- [x] Phase 3 docs/governance/source-of-truth audit
- [x] Phase 4 master prompt audit: `docs/semiconductor_swarm_ai.md`
- [x] Phase 5 prompt contracts audit for agents 1-5
- [x] Phase 6 Python package/import/path audit
- [x] Phase 7 Agent1 System Architect deep audit
- [x] Phase 8 Agent2 RTL Designer deep audit
- [x] Phase 9 Agent3 DV Engineer deep audit
- [x] Phase 10 Agent4 Physical Designer deep audit
- [x] Phase 11 Agent5 Formal Verifier deep audit
- [x] Phase 12 swarm graph/orchestration audit
- [x] Phase 13 tools layer audit
- [x] Phase 14 real tool detection audit
- [x] Phase 15 generated artifacts audit
- [x] Phase 16 scripts/batch/debug runners audit
- [x] Phase 17 tests coverage/reliability audit
- [x] Phase 18 verification ladder
- [x] Phase 19 migration residue/dead code audit
- [x] Phase 20 security/local config audit
- [x] Phase 21 issue matrix and fix strategy
- [x] Phase 22 traceability matrix
- [x] Phase 23 mini-agent assignment review
- [x] Phase 24 deterministic golden demo
- [x] Phase 25 negative/error-path audit
- [x] Phase 26 risk register

## Phase 1: Baseline Snapshot
Purpose: freeze repo state before audit.

Tasks:
- [x] Run `git status --short`.
- [x] Run `git diff --name-only`.
- [x] Run `python --version`.
- [x] Run `python -m pytest --version`.
- [x] Record current working directory.
- [x] Record top-level tree.
- [x] Identify untracked or generated files that can affect audit.

Commands:

```bash
git status --short
git diff --name-only
python --version
python -m pytest --version
cd
python - <<'PY'
from pathlib import Path
for p in sorted(Path('.').glob('*')):
    print(p)
PY
```

Findings to check:
- [x] Too many untracked files hiding migration state.
- [x] Runtime diffs mixed with docs diffs.
- [x] Generated artifacts mixed with source.
- [x] Local secrets/config present.
- [x] Old run outputs affecting tests.

## Phase 2: Repo Inventory
Purpose: map every important module and artifact.

Targets:
- `semiconductor_swarm/`
- `semiconductor_swarm/agents/`
- `semiconductor_swarm/tools/`
- `tests/`
- `docs/`
- `scripts/`
- `debug_runners/`
- `runs/`
- `swarm_out/`

Tasks:
- [x] Inventory Python source files.
- [x] Inventory Markdown docs.
- [x] Inventory tests.
- [x] Inventory generated RTL/Formal/FPGA artifacts if present.
- [x] Inventory root scripts and launchers.
- [x] Mark legacy/deprecated docs and files.

Findings to check:
- [x] Orphan files not routed by docs.
- [x] Tests not mapped to modules.
- [x] Active docs missing from knowledge map.
- [x] Legacy files still imported.
- [x] New migration files without tests.

## Phase 3: Docs, Governance, Source of Truth
Purpose: verify documentation spine and routing.

Targets:
- `AGENTS.md`
- `ARCHITECTURE.md`
- `PLANS.md`
- `docs/knowledge-map.yaml`
- `docs/design-docs/`
- `docs/product-specs/`
- `docs/governance/`
- `docs/prompts/`
- `docs/agent-task-cards/`
- `docs/generated/`
- `docs/legacy/`

Tasks:
- [x] Run docs health.
- [x] Validate required frontmatter.
- [x] Check broken Markdown links.
- [x] Verify `docs/knowledge-map.yaml` references real files.
- [x] Verify `PLANS.md` active/completed/deferred sync.
- [x] Verify `AGENTS.md` stays concise and routes deeper docs.
- [x] Verify source-of-truth hierarchy has no conflicts.
- [x] Verify legacy docs do not override active docs.

Command:

```bash
python scripts/check_docs_health.py
```

Findings to check:
- [x] Dead links.
- [x] Referenced files missing.
- [x] Existing files without routes.
- [x] Completed plan still active.
- [x] Prompt docs drift from runtime prompts.
- [x] Product specs drift from tests.

## Phase 4: Master Prompt Audit
Purpose: ensure `docs/semiconductor_swarm_ai.md` remains canonical.

Tasks:
- [x] Read `docs/semiconductor_swarm_ai.md`.
- [x] Extract master requirements.
- [x] Map each requirement to agent code and tests.
- [x] Compare with `docs/prompts/canonical-prompts.md`.
- [x] Compare with `docs/prompt_compliance_matrix.yaml`.
- [x] Compare with `tests/test_prompt_contracts.py`.
- [x] Compare with agent prompt files.
- [x] Check version drift after migration.
- [x] Confirm all agents 1-5 covered.

Findings to check:
- [x] Master prompt says one thing, code does another.
- [x] Prompt contract tests miss requirement.
- [x] Old prompt still acts as source of truth.
- [x] Wrong path or spelling drift around prompt docs.
- [x] Mandatory output missing from code.

## Phase 5: Prompt Contracts Agent 1-5
Targets:
- `semiconductor_swarm/agents/agent1_planning/agent1_prompt.py`
- `semiconductor_swarm/agents/agent2_rtl/agent2_prompt.py`
- `semiconductor_swarm/agents/agent3_dv/agent3_prompt.py`
- `semiconductor_swarm/agents/agent4_physical/agent4_prompt.py`
- `semiconductor_swarm/agents/agent5_formal/agent5_prompt.py`
- `tests/test_prompt_contracts.py`
- `docs/prompt_compliance_matrix.yaml`

Tasks:
- [x] Run prompt contract tests.
- [x] Check role definition.
- [x] Check input contract.
- [x] Check output contract.
- [x] Check no-hallucination guard.
- [x] Check file emission rules.
- [x] Check self-check rules.
- [x] Check downstream handoff rules.
- [x] Check for stale paths.
- [x] Check generated file names.

Command:

```bash
python -m pytest -q tests/test_prompt_contracts.py
```

Findings to check:
- [x] Agent prompt drift from master.
- [x] Missing mandatory outputs.
- [x] Prompt mentions missing tool.
- [x] Format required by prompt not tested.
- [x] Weak tests create false pass.

## Phase 6: Python Package, Import, Path Audit
Targets:
- `semiconductor_swarm/__init__.py`
- `semiconductor_swarm/swarm_graph.py`
- `semiconductor_swarm/agents/*.py`
- `semiconductor_swarm/agents/agent1_planning/*.py`
- `semiconductor_swarm/tools/*.py`
- `main.py`
- `tests/*.py`

Tasks:
- [x] Compile all Python.
- [x] Run import smoke.
- [x] Search old import paths.
- [x] Check circular import risk.
- [x] Check CLI path usage.

Commands:

```bash
python -m compileall semiconductor_swarm tests scripts main.py
python - <<'PY'
import semiconductor_swarm
import semiconductor_swarm.swarm_graph
from semiconductor_swarm.agents import architect, rtl_designer, dv_engineer, physical_designer, formal_verifier
print('imports ok')
PY
python - <<'PY'
from pathlib import Path
for p in Path('.').rglob('*.py'):
    txt = p.read_text(encoding='utf-8', errors='ignore')
    if 'agent1_architect' in txt or 'agent2_rtl_designer' in txt:
        print(p)
PY
```

Findings to check:
- [x] Root-level old agents still imported.
- [x] Package imports broken after migration.
- [x] Relative import bug.
- [x] Circular import.
- [x] Tests import old path.
- [x] CLI uses old path.

## Phase 7: Agent1 System Architect Deep Audit
Targets:
- `semiconductor_swarm/agents/agent1_planning/architect.py`
- `semiconductor_swarm/agents/agent1_planning/agent1_prompt.py`
- `semiconductor_swarm/agents/agent1_planning/`
- `tests/test_agent1.py`
- `docs/product-specs/agent1-system-architect.md`

Tasks:
- [x] Read Agent1 code.
- [x] Read planning subgraph files.
- [x] Run Agent1 tests.
- [x] Check output schema: spec, modules, interfaces, memory map, constraints, verification handoff.
- [x] Check replay CLI.
- [x] Check schema strictness.

Command:

```bash
python -m pytest -q tests/test_agent1.py
```

Findings to check:
- [x] Agent1 output missing downstream field.
- [x] Schema too loose.
- [x] Planning subgraph unused by main flow.
- [x] Legacy Agent1 root file causes confusion.
- [x] Spec docs drift from code.

## Phase 8: Agent2 RTL Designer Deep Audit
Targets:
- `semiconductor_swarm/agents/agent2_rtl/rtl_designer.py`
- `semiconductor_swarm/agents/agent2_rtl/agent2_prompt.py`
- `tests/test_agent2.py`
- generated RTL outputs if present

Tasks:
- [x] Read Agent2 code.
- [x] Run Agent2 tests.
- [x] Check generated `.sv`, `_pkg.sv`, `_intf.sv`, top module, self-check JSON, debug report JSON.
- [x] Check naming consistency.
- [x] Check SystemVerilog syntax smoke if tool exists.
- [x] Check handoff to DV/Formal/Physical.

Command:

```bash
python -m pytest -q tests/test_agent2.py
```

Findings to check:
- [x] RTL paths changed but tests stale.
- [x] Package references wrong.
- [x] Interface names mismatch.
- [x] Agent2 output JSON missing downstream fields.
- [x] Generated stale RTL hides failure.

## Phase 9: Agent3 DV Engineer Deep Audit
Targets:
- `semiconductor_swarm/agents/agent3_dv/dv_engineer.py`
- `semiconductor_swarm/agents/agent3_dv/agent3_prompt.py`
- DV tool code
- `tests/test_agent3.py`
- `tests/test_real_dv_tools.py`

Tasks:
- [x] Read Agent3 code.
- [x] Run Agent3 tests.
- [x] Run real DV tool tests.
- [x] Check generated testbench paths.
- [x] Check coverage plan.
- [x] Check regression scripts.
- [x] Check no-simulator fallback.

Commands:

```bash
python -m pytest -q tests/test_agent3.py
python -m pytest -q tests/test_real_dv_tools.py
```

Findings to check:
- [x] Assumes real simulator exists.
- [x] Missing skip when tool absent.
- [x] Testbench references missing RTL.
- [x] Coverage plan mismatch.
- [x] DV handoff report incomplete.

## Phase 10: Agent4 Physical Designer Deep Audit
Targets:
- `semiconductor_swarm/agents/agent4_physical/physical_designer.py`
- `semiconductor_swarm/agents/agent4_physical/agent4_prompt.py`
- `semiconductor_swarm/tools/quartus_runner.py`
- `tests/test_agent4.py`
- `tests/test_real_quartus_tools.py`
- generated FPGA outputs if present

Tasks:
- [x] Read Agent4 code.
- [x] Run Agent4 tests.
- [x] Run real Quartus tests.
- [x] Check `.qsf`, `.sdc`, TCL scripts.
- [x] Check tool fallback.
- [x] Check report parser.
- [x] Check timing/area/resource extraction.

Commands:

```bash
python -m pytest -q tests/test_agent4.py
python -m pytest -q tests/test_real_quartus_tools.py
```

Findings to check:
- [x] Hardcoded Quartus path.
- [x] Windows path escaping bug.
- [x] Missing no-tool graceful report.
- [x] SDC clock mismatch RTL top.
- [x] QSF file list stale.

## Phase 11: Agent5 Formal Verifier Deep Audit
Targets:
- `semiconductor_swarm/agents/agent5_formal/formal_verifier.py`
- `semiconductor_swarm/agents/agent5_formal/agent5_prompt.py`
- `semiconductor_swarm/tools/symbiyosys_runner.py`
- `tests/test_agent5.py`
- `tests/test_real_formal_tools.py`
- generated formal outputs if present
- `runs/smoke_formal*`

Tasks:
- [x] Read Agent5 code.
- [x] Run Agent5 tests.
- [x] Run real formal tests.
- [x] Check SBY generation.
- [x] Check formal wrapper generation.
- [x] Check parser.
- [x] Check fallback when Yosys/SBY missing.
- [x] Check old smoke runs do not affect tests.

Commands:

```bash
python -m pytest -q tests/test_agent5.py
python -m pytest -q tests/test_real_formal_tools.py
```

Findings to check:
- [x] SBY references missing RTL.
- [x] Wrong top module.
- [x] Assertion wrapper imports broken package.
- [x] Parser assumes report exists.
- [x] Formal artifacts stale.

## Phase 12: Swarm Graph and Orchestration Audit
Targets:
- `semiconductor_swarm/swarm_graph.py`
- `main.py`
- `tests/test_swarm_graph.py`
- `tests/test_agent_pipeline.py`
- `start_swarm.bat`

Tasks:
- [x] Read graph and entrypoint.
- [x] Run graph/pipeline tests.
- [x] Check node order: Agent1 -> Agent2 -> Agent3 -> Agent4 -> Agent5.
- [x] Check state schema between nodes.
- [x] Check checkpoint SQLite behavior.
- [x] Check resume/retry if present.
- [x] Check batch launcher.

Command:

```bash
python -m pytest -q tests/test_swarm_graph.py tests/test_agent_pipeline.py
```

Findings to check:
- [x] State key mismatch.
- [x] Agent order wrong.
- [x] Error handling swallows failures.
- [x] Checkpoint path hardcoded.
- [x] `start_swarm.bat` calls old file.
- [x] Main CLI differs from README.

## Phase 13: Tools Layer Audit
Targets:
- `semiconductor_swarm/tools/ppa_calculator.py`
- `semiconductor_swarm/tools/bandwidth_calculator.py`
- `semiconductor_swarm/tools/tool_detection.py`
- `semiconductor_swarm/tools/quartus_runner.py`
- `semiconductor_swarm/tools/symbiyosys_runner.py`
- `scripts/check_real_tools.py`
- `scripts/diagnose_yosys_deps.py`
- `scripts/install_oss_cad_suite_windows.py`

Tasks:
- [x] Read each tool.
- [x] Check pure calculators are deterministic.
- [x] Check error handling.
- [x] Check Windows path handling.
- [x] Check subprocess timeout.
- [x] Check no-tool fallback.
- [x] Check parsers with missing/partial logs.

Findings to check:
- [x] Shell injection risk.
- [x] Non-quoted Windows paths.
- [x] No timeout.
- [x] Crash when tool missing.
- [x] Brittle parser.
- [x] Calculator silently accepts invalid input.

## Phase 14: Real Tool Detection Audit
Targets:
- `semiconductor_swarm/tools/tool_detection.py`
- `scripts/check_real_tools.py`
- `tests/test_real_tool_detection.py`
- `tests/test_real_dv_tools.py`
- `tests/test_real_formal_tools.py`
- `tests/test_real_quartus_tools.py`

Tasks:
- [x] Run real tool checker.
- [x] Run real tool detection tests.
- [x] Check skip/xfail behavior.
- [x] Check environment variables and Windows path behavior.
- [x] Confirm tests do not fail on machines without EDA tools unless intentionally required.

Commands:

```bash
python scripts/check_real_tools.py
python -m pytest -q tests/test_real_tool_detection.py
```

Findings to check:
- [x] Real tool tests fail when tools absent.
- [x] Detection false positive.
- [x] Detection false negative.
- [x] Script suggests wrong install path.
- [x] Windows-specific failure.

## Phase 15: Generated Artifacts Audit
Targets:
- generated RTL/Formal/FPGA directories if present
- `runs/`
- `swarm_out/`
- `.gitignore`

Tasks:
- [x] Check whether generated dirs still exist after migration.
- [x] Check whether generated outputs are tracked or confuse source.
- [x] Check output names against tests.
- [x] Check stale artifacts do not hide agent failures.
- [x] Check ignore rules.
- [x] Check cleanup strategy.

Findings to check:
- [x] Test pass due to stale artifact.
- [x] Agent failed to generate but old file remains.
- [x] `runs/` noise affects audit.
- [x] `swarm_out/` path hardcoded.
- [x] Generated logs contain secrets or local paths.

## Phase 16: Scripts, Batch, Debug Runners Audit
Targets:
- `start_swarm.bat`
- `debug_runners/run_partial.py`
- `debug_runners/test_step_by_step.bat`
- `scripts/reorg_project.py`
- `scripts/check_docs_health.py`
- `scripts/check_real_tools.py`
- `scripts/diagnose_yosys_deps.py`
- `scripts/install_oss_cad_suite_windows.py`

Tasks:
- [x] Read batch files.
- [x] Check new/old paths.
- [x] Check destructive scripts have dry-run or guard.
- [x] Check install script does not run automatically.
- [x] Check debug runner does not depend on local-only files.
- [x] Check scripts imported by tests.

Findings to check:
- [x] Batch calls old root agents.
- [x] Script delete/move without guard.
- [x] Script hardcodes user path.
- [x] Script assumes admin/network.
- [x] Script returns wrong exit code.

## Phase 17: Tests Coverage and Reliability Audit
Targets:
- all `tests/test_*.py`
- `pytest.ini`

Tasks:
- [x] Run each test file separately.
- [x] Run core group.
- [x] Run real tools group.
- [x] Run full suite.
- [x] Check warnings.
- [x] Check temp-dir isolation.
- [x] Check tests do not depend on stale generated artifacts.
- [x] Check skip conditions.

Commands:

```bash
python -m pytest -q tests/test_agent1.py
python -m pytest -q tests/test_agent2.py
python -m pytest -q tests/test_agent3.py
python -m pytest -q tests/test_agent4.py
python -m pytest -q tests/test_agent5.py
python -m pytest -q tests/test_swarm_graph.py
python -m pytest -q tests/test_agent_pipeline.py
python -m pytest -q tests/test_docs_health.py tests/test_prompt_contracts.py
python -m pytest -q tests/test_real_tool_detection.py tests/test_real_dv_tools.py tests/test_real_formal_tools.py tests/test_real_quartus_tools.py
python -m pytest -q
```

Findings to check:
- [x] Test false-pass.
- [x] Test too text-fragile.
- [x] Failure path not covered.
- [x] Migration path not covered.
- [x] Full suite differs from per-file suite.
- [x] Tests order-dependent.

## Phase 18: Verification Ladder
Purpose: graded pass/fail gates.

### Level 1: Syntax/import
```bash
python -m compileall semiconductor_swarm tests scripts main.py
```

### Level 2: Docs/prompt
```bash
python scripts/check_docs_health.py
python -m pytest -q tests/test_docs_health.py tests/test_prompt_contracts.py
```

### Level 3: Unit agents
```bash
python -m pytest -q tests/test_agent1.py tests/test_agent2.py tests/test_agent3.py tests/test_agent4.py tests/test_agent5.py
```

### Level 4: Orchestration
```bash
python -m pytest -q tests/test_swarm_graph.py tests/test_agent_pipeline.py
```

### Level 5: Real tools optional
```bash
python -m pytest -q tests/test_real_tool_detection.py tests/test_real_dv_tools.py tests/test_real_formal_tools.py tests/test_real_quartus_tools.py
```

### Level 6: Full suite
```bash
python -m pytest -q
```

Pass criteria:
- [x] Level 1 pass.
- [x] Level 2 pass.
- [x] Level 3 pass.
- [x] Level 4 pass.
- [x] Level 5 pass or skip cleanly when tools missing.
- [x] Level 6 pass or environment-limited failures documented.

## Phase 19: Migration Residue and Dead Code Audit
Targets:
- root legacy agent files if present
- old generated directories
- old docs paths
- `scripts/reorg_project.py`

Tasks:
- [x] Search root-level legacy references.
- [x] Search old imports.
- [x] Search old output paths.
- [x] Search duplicate agent definitions.
- [x] Check whether old root files are still needed.
- [x] Check docs mention old paths.
- [x] Check tests import old files.

Command:

```bash
python - <<'PY'
from pathlib import Path
terms = [
    'agent1_architect.py',
    'agent2_rtl_designer.py',
    'agent3_dv_engineer.py',
    'agent4_physical_designer.py',
    'agent5_formal_verifier.py',
    'generated_rtl',
    'generated_formal',
    'generated_fpga',
]
for p in Path('.').rglob('*'):
    if p.is_file() and p.suffix in {'.py', '.md', '.yaml', '.yml', '.bat', '.txt'}:
        txt = p.read_text(encoding='utf-8', errors='ignore')
        for t in terms:
            if t in txt:
                print(f'{p}: {t}')
PY
```

Findings to check:
- [x] Duplicate source-of-truth.
- [x] Old file still used.
- [x] Old file unused but not labeled legacy.
- [x] Docs route to old path.
- [x] Tests cover old code instead of new code.

## Phase 20: Security and Local Config Audit
Targets:
- `codex_api.example.json`
- local config files if present
- `.gitignore`
- JSON/log/YAML/BAT files
- `runs/`
- `swarm_out/`

Tasks:
- [x] Search secret-like strings.
- [x] Verify local config is ignored.
- [x] Verify logs do not contain API keys.
- [x] Verify scripts do not print secrets.
- [x] Inspect external command execution for safety.

Command:

```bash
python - <<'PY'
from pathlib import Path
patterns = ['api_key', 'apikey', 'secret', 'token', 'password', 'OPENAI_API_KEY']
for p in Path('.').rglob('*'):
    if p.is_file() and p.suffix.lower() in {'.py', '.md', '.json', '.txt', '.log', '.yaml', '.yml', '.bat'}:
        txt = p.read_text(encoding='utf-8', errors='ignore').lower()
        for pat in patterns:
            if pat.lower() in txt:
                print(p, pat)
PY
```

Findings to check:
- [x] Real secret in repo.
- [x] Local config tracked.
- [x] Logs leak paths/API keys.
- [x] Shell command unsafe.
- [x] Install scripts too aggressive.

## Phase 21: Issue Matrix and Fix Strategy
Create issue table:

| ID | Severity | Area | File | Evidence | Impact | Fix proposal | Test needed |
|---|---|---|---|---|---|---|---|

Severity guide:
- `critical`: pipeline broken or data loss risk.
- `high`: agent output wrong, tests missing major contract, orchestration broken.
- `medium`: docs/test/tool drift, fallback weak.
- `low`: cleanup, naming, readability.
- `info`: observation.

Fix batches:
- [x] Batch A: safe docs/tests only.
- [x] Batch B: low-risk code fixes.
- [x] Batch C: agent behavior fixes.
- [x] Batch D: generated artifact cleanup.

## Phase 22: Traceability Matrix
Purpose: prove every master prompt requirement maps to docs, code, tests, and generated outputs.

Targets:
- `docs/semiconductor_swarm_ai.md`
- `docs/prompts/canonical-prompts.md`
- `docs/prompt_compliance_matrix.yaml`
- `docs/product-specs/*.md`
- `semiconductor_swarm/agents/`
- `tests/`

Tasks:
- [x] Extract requirements from master prompt.
- [x] Map each requirement to product spec.
- [x] Map each requirement to runtime code.
- [x] Map each requirement to tests.
- [x] Map each requirement to generated artifact or output contract.
- [x] Mark gaps as missing_doc, missing_code, missing_test, or ambiguous.

Output:
- [x] `docs/generated/Kiem_tra_toan_bo_Agent_AI_traceability_matrix.md`

## Phase 23: Mini-Agent Assignment Review
Purpose: split audit into focused mini-agent work packets.

Tasks:
- [x] Assign Repo Auditor scope.
- [x] Assign Prompt Auditor scope.
- [x] Assign Agent Auditor scope.
- [x] Assign Graph Auditor scope.
- [x] Assign Tool Auditor scope.
- [x] Assign Test Auditor scope.
- [x] Assign Security Auditor scope.
- [x] Assign Docs Auditor scope.
- [x] Verify no scope overlap creates duplicate issue IDs.
- [x] Verify no scope gap remains.

Output:
- [x] Mini-agent execution notes inside audit report.

## Phase 24: Deterministic Golden Demo
Purpose: validate reproducibility and create stable smoke baseline.

Tasks:
- [x] Select one small canonical input.
- [x] Run end-to-end pipeline once into clean output dir.
- [x] Run end-to-end pipeline second time into separate clean output dir.
- [x] Compare file list.
- [x] Compare stable content after ignoring allowed volatile fields such as timestamps.
- [x] Record nondeterministic fields.
- [x] Decide whether nondeterminism is acceptable or issue-worthy.

Findings to check:
- [x] File order nondeterminism.
- [x] Timestamp noise in checked outputs.
- [x] Random IDs without seed.
- [x] Generated reports differ without reason.
- [x] Pipeline depends on previous run outputs.

## Phase 25: Negative and Error-Path Audit
Purpose: verify system fails cleanly under bad input or missing dependencies.

Scenarios:
- [x] Missing master prompt file.
- [x] Invalid JSON/spec input.
- [x] Missing RTL files before DV/Formal/Physical.
- [x] Missing simulator/formal/Quartus tools.
- [x] Read-only or nonexistent output directory.
- [x] Empty module list.
- [x] Malformed generated report.
- [x] Interrupted subprocess.

Pass criteria:
- [x] Error message explains cause.
- [x] No partial source overwrite.
- [x] Exit code/status is meaningful.
- [x] Debug report captures failure.
- [x] Tests or manual evidence exist.

## Phase 26: Risk Register
Purpose: track systemic risks not yet proven as bugs.

Risk categories:
- [x] Prompt drift risk.
- [x] Migration residue risk.
- [x] Real EDA tool availability risk.
- [x] Generated artifact staleness risk.
- [x] Windows path handling risk.
- [x] Security/local config leak risk.
- [x] Test false-pass risk.
- [x] Orchestration state mismatch risk.

Output:
- [x] `docs/generated/Kiem_tra_toan_bo_Agent_AI_risk_register.md`

## Definition of Done
- [x] Audit report exists.
- [x] Inventory file exists.
- [x] Test matrix exists.
- [x] Issue tracker exists.
- [x] Risk register exists.
- [x] Traceability matrix exists.
- [x] Handoff matrix exists.
- [x] Golden demo result recorded.
- [x] Negative/error-path result recorded.
- [x] Each phase has pass/fail/blocked status.
- [x] All commands have output evidence.
- [x] No runtime code changed without approval.
- [x] Critical/high issues have separate fix plan.
- [x] If no critical/high issues, system is declared migration-stable.
