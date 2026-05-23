---
title: Agent 3 DV Practical Upgrade Plan
status: active
owner: agent3-dv
type: exec-plan
last_reviewed: 2026-05-20
source_of_truth: true
---

# Agent 3 DV Practical Upgrade Plan

## Baseline
- `tests/test_agent3.py`: baseline green before upgrade.
- `tests/test_real_dv_tools.py`: expected to skip cleanly when local DV tools are absent.
- Known gaps fixed in current implementation pass: stale `../generated_rtl/*.sv` path, wildcard ModelSim runner, weak DV manifest, weak strict-mode gate, thin APB scoreboard collateral, text-only coverage intent.

## Implemented Slice
- Agent3 now emits `agent3_dv_manifest.json`, `agent3_tool_health.json`, `agent3_compile_order.f`, `agent3_sim_report.json`, `agent3_coverage_report.json`, `agent3_scoreboard_report.json`, `agent3_release_decision.json`, `agent3_result.json`, and `agent3_dv_dashboard.md`.
- Generated Makefile and ModelSim paths consume `agent3_compile_order.f` and point at `../rtl/`.
- `strict` and `nightly-real-tools` cannot produce `DV_STRICT_PASS` unless real simulation pass evidence exists.
- Cocotb collateral now uses reusable APB driver, monitor, and scoreboard helpers.
- Static validation catches missing RTL, wrong top module, APB port rename, and simple data width mismatch before simulator launch.
- Simulation log analysis classifies compile, port, reset, APB protocol, scoreboard, timeout, testbench, and tool-missing failures.
- Cocotb/Verilator is now the primary graph real-DV path; ModelSim/Questa remains secondary collateral.
- `run_cocotb_sim()` persists real sim, scoreboard, coverage, release, and result JSON reports back into `tb/`.
- Real-tool gated tests now cover a golden APB fixture and negative readback/reset/ready/error/width fixtures when `cocotb`, `make`, and Verilator are available.
- `requirements-dv.txt` and `scripts/bootstrap_dv_tools.py` define the pinned Python DV bootstrap path.

## Remaining Real-Tool Work
- Install `cocotb` in local/CI DV runtime and run the real-DV gated tests.
- Harden Verilator code coverage parsing against every output format seen in CI logs.
- Add CI profile that runs `nightly-real-tools` with required coverage evidence.
- Keep ModelSim/Questa secondary and optional.

## Green Gates
- `python -m pytest -q tests/test_agent3.py tests/test_agent3_manifest.py tests/test_agent3_scoreboard.py tests/test_agent3_failure_classification.py`
- `python -m pytest -q tests/test_real_dv_tools.py --basetemp D:\AI\AgentAI\.pytest_tmp_dv`
- `python scripts/check_docs_health.py`
- `python -m pytest -q tests/test_docs_health.py tests/test_prompt_contracts.py`
