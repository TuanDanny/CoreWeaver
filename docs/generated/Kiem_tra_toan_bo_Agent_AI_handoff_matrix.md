---
title: Kiem tra toan bo Agent AI handoff matrix
status: generated
owner: docs-governance
type: generated
last_reviewed: 2026-05-17
source_of_truth: false
---

# Kiem tra toan bo Agent AI - Handoff Matrix

| Handoff | Producer output | Consumer input | Required fields | Tests | Status | Gap |
|---|---|---|---|---|---|---|
| Agent1 -> Agent2 | validated architecture spec | RTL generator spec | `project_name`, `core_config`, `interfaces.apb_slave.signals`, `ip_blocks`, `memory_map` | `tests/test_agent1.py`, `tests/test_agent2.py` | pass | none found |
| Agent2 -> Agent3 | SystemVerilog RTL file dicts | DV collateral generator | `filename`, `language=systemverilog`, `content`; per-block `<block>.sv` | `tests/test_agent2.py`, `tests/test_agent3.py` | pass | none found |
| Agent2 -> Agent4 | SystemVerilog RTL file dicts + top naming | Quartus collateral/compiler | RTL filenames/content, top module `<project>_top`, target MHz | `tests/test_agent2.py`, `tests/test_agent4.py` | pass | none found |
| Agent2 -> Agent5 | SystemVerilog RTL file dicts | SVA/SBY formal generator | per-block `<block>.sv`, generated DUT name `<project>_<block>_rtl` | `tests/test_agent2.py`, `tests/test_agent5.py` | pass | none found |
| Agent3/4/5 -> Reports | DV/timing/formal result dicts | swarm final report | pass/fail, failures, tool output tail, debug/self-check JSON | `tests/test_agent_pipeline.py`, `tests/test_swarm_graph.py` | pass | none found |
