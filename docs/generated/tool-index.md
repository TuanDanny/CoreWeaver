---
title: Tool Index
status: active
owner: docs-governance
type: generated
last_reviewed: 2026-05-20
source_of_truth: false
---

# Tool Index

| Tool Area | Files | Tests |
|---|---|---|
| PPA calculator | `semiconductor_swarm/tools/ppa_calculator.py` | Agent tests and pipeline tests. |
| Bandwidth calculator | `semiconductor_swarm/tools/bandwidth_calculator.py` | Agent tests and pipeline tests. |
| Tool detection | `semiconductor_swarm/tools/tool_detection.py` | `tests/test_real_tool_detection.py` |
| SymbiYosys runner | `semiconductor_swarm/tools/symbiyosys_runner.py` | `tests/test_real_formal_tools.py` |
| Quartus runner | `semiconductor_swarm/tools/quartus_runner.py` | `tests/test_real_quartus_tools.py` |
| Agent2 Verilator adapter | `semiconductor_swarm/agents/agent2_rtl/tools/verilator_adapter.py` | `tests/test_agent2_v4_strict_eda.py` |
| Agent2 Yosys adapter | `semiconductor_swarm/agents/agent2_rtl/tools/yosys_adapter.py` | `tests/test_agent2_v4_quality_score.py` |
| Agent2 tool health matrix | `semiconductor_swarm/agents/agent2_rtl/tools/tool_health_matrix.py` | `tests/test_agent2_v4_toolchain_reproducibility.py` |
| Real tool check script | `scripts/check_real_tools.py` | Manual/CI diagnostic. |
| Yosys deps diagnostic | `scripts/diagnose_yosys_deps.py` | Manual diagnostic. |
| OSS CAD Suite installer | `scripts/install_oss_cad_suite_windows.py` | Manual setup. |
