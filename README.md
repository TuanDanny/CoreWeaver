# Semiconductor Swarm AI

Semiconductor Swarm AI is a local semiconductor design swarm for turning chip/IP requirements into architecture JSON, APB SystemVerilog RTL, SymbiYosys/SVA formal collateral, Cocotb/Pytest DV collateral, and Quartus-oriented FPGA backend collateral.

The core flow is Python-first with explicit contracts, self-checks, and tests. The Studio web cockpit can connect to an OpenAI-compatible local endpoint through server-side credential references; raw API keys stay out of the browser and out of Git.

## Current Public Shape

- `semiconductor_swarm/` contains the core multi-agent engine.
- `studio/` contains the FastAPI + React local cockpit.
- `tests/` contains regression coverage for the core engine and Studio backend/frontend contracts.
- `outputs/`, `.swarm/`, local settings, SQLite checkpoints, frontend build output, and dependency folders are intentionally ignored.
- Copy `codex_api.example.json` to `codex_api.local.json` or use `python -m studio.backend.secret_admin set-owner-key` for local credentials.
- Use `docs/REPOSITORY_LAYOUT.md` and `docs/GITHUB_PUBLISHING.md` before splitting commits or pushing to GitHub.

## Repository Map

| Area | Main files | Purpose |
| --- | --- | --- |
| Agent 1 | `semiconductor_swarm/agents/agent1_planning/architect.py` | Generate and validate architecture JSON. |
| Agent 2 | `semiconductor_swarm/agents/agent2_rtl/rtl_designer.py` | Generate APB SystemVerilog RTL. |
| Agent 5 | `semiconductor_swarm/agents/agent5_formal/formal_verifier.py` | Generate SVA and `.sby` formal collateral. |
| Agent 3 | `semiconductor_swarm/agents/agent3_dv/dv_engineer.py` | Generate Cocotb/Pytest DV collateral. |
| Agent 4 | `semiconductor_swarm/agents/agent4_physical/physical_designer.py` | Generate Quartus FPGA backend collateral. |
| Orchestrator | `main.py`, `semiconductor_swarm/swarm_graph.py` | Run the five-agent LangGraph flow with HITL pause/resume. |
| Studio | `studio/backend/`, `studio/frontend/`, `run_studio.bat` | Local web mission-control UI with WebSocket logs and Agent 1 tracing. |
| Tools | `semiconductor_swarm/tools/*.py`, `scripts/*.py` | PPA, bandwidth, Quartus, SymbiYosys, and Windows OSS CAD Suite helpers. |
| Tests | `tests/` | Unit, pipeline, and LangGraph tests. |

## End-To-End Flow

```text
Natural-language requirement
  -> Agent 1 architecture spec
  -> Agent 2 APB RTL
  -> Agent 5 formal-first checks
  -> Human review checkpoint
  -> Agent 3 Cocotb/Pytest DV
  -> Agent 4 Quartus FPGA backend collateral
  -> SIGNOFF_READY outputs
```

Key gates:

- Agent 5 runs before Agent 3, so formal collateral gates simulation collateral.
- The LangGraph flow pauses for human-in-the-loop review after RTL and formal generation.
- Formal/backend failures can route back to Agent 2 auto-debug until the configured debug iteration limit is reached.

## Requirements

Required for normal repository tests and CLIs:

- Python 3.11+ recommended.
- `pytest`
- `langgraph`
- `langgraph-checkpoint-sqlite`

Optional for generated Cocotb tests:

- `cocotb`
- A Cocotb-supported simulator such as Icarus Verilog, Verilator, Questa, Xcelium, or VCS.

Optional for real formal proofs:

- OSS CAD Suite or equivalent tools on `PATH`: `sby`, `yosys`, and `z3`.

Optional for real FPGA backend compile:

- Intel Quartus command-line tools on `PATH`, especially `quartus_sh`.

## Setup

Run commands from the repository root.

### 1. Create A Virtual Environment

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Command Prompt:

```bat
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
```

Bash:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### 2. Install Python Dependencies

```bash
python -m pip install pytest langgraph langgraph-checkpoint-sqlite
```

Optional DV dependency:

```bash
python -m pip install cocotb
```

### 3. Verify Imports

Bash:

```bash
python - <<'PY'
import langgraph
import pytest
print('Python flow dependencies OK')
PY
```

PowerShell:

```powershell
@'
import langgraph
import pytest
print('Python flow dependencies OK')
'@ | python -
```

## Quick Start: Full LangGraph Flow

The full flow pauses for human review after Agent 5.

### 1. Start The Swarm

```bash
python main.py "IoT AI camera chip <1W 100MHz" --project-name iot_camera --thread-id demo --output-dir swarm_out --checkpoint-db swarm_checkpoints.sqlite
```

Expected first status:

```json
{
  "status": "PAUSED_FOR_HITL",
  "checkpoint_db": "swarm_checkpoints.sqlite",
  "thread_id": "demo"
}
```

At this point Agent 1, Agent 2, and Agent 5 have already run. The graph is waiting for a human review decision.

### 2. Resume With Approval

```bash
python main.py --resume --thread-id demo --output-dir swarm_out --checkpoint-db swarm_checkpoints.sqlite --reviewer your-name --notes "approved after RTL/formal review"
```

Reject instead:

```bash
python main.py --reject --thread-id demo --checkpoint-db swarm_checkpoints.sqlite --reviewer your-name --notes "needs RTL changes"
```

After approval, final output is written to:

```text
swarm_out/
  rtl/      SystemVerilog RTL and packages
  formal/   SVA and SymbiYosys collateral
  tb/       Cocotb/Pytest DV collateral
  fpga/     Quartus/backend collateral
```

## Run Agents Individually

Use this when you want explicit JSON handoff files or need to debug a single agent.

### Agent 1: Architecture

```bash
python -m semiconductor_swarm.agents.agent1_planning.architect "IoT AI camera chip <1W 100MHz" --project-name iot_camera > spec.json
```

Agent 1 output includes PPA, bandwidth, IP blocks, fixed APB interface, `formal_first`, and HITL constraints.

### Agent 2: RTL

```bash
python -m semiconductor_swarm.agents.agent2_rtl.rtl_designer spec.json --write-dir swarm_out/rtl --debug > rtl_files.json
```

Outputs include `swarm_out/rtl/*.sv`, `rtl_files.json`, and `swarm_out/rtl/agent2_self_check.json`.

### Agent 5: Formal

```bash
python -m semiconductor_swarm.agents.agent5_formal.formal_verifier spec.json rtl_files.json --write-dir swarm_out/formal --debug > formal_files.json
```

Outputs include `swarm_out/formal/fv_<block>.sv`, `swarm_out/formal/<block>.sby`, helper scripts, and `swarm_out/formal/agent5_self_check.json`.

### Agent 3: DV

```bash
python -m semiconductor_swarm.agents.agent3_dv.dv_engineer spec.json rtl_files.json --write-dir swarm_out/tb --debug > dv_files.json
```

Outputs include Cocotb APB tests, `test_plan.py`, a Makefile, runner helpers, and `swarm_out/tb/agent3_self_check.json`.

### Agent 4: Physical Design

```bash
python -m semiconductor_swarm.agents.agent4_physical.physical_designer spec.json rtl_files.json --write-dir swarm_out/fpga --debug > physical_files.json
```

Outputs include Quartus project/backend files and `swarm_out/fpga/agent4_self_check.json`.

## Real Formal Proofs With SymbiYosys/Z3

The Agent 5 CLI generates formal collateral. To run real proofs, install OSS CAD Suite and call the formal runner.

### Windows OSS CAD Suite Install

```powershell
python scripts/install_oss_cad_suite_windows.py --install-dir C:\oss-cad-suite --user-path
```

Open a new terminal and verify:

```powershell
sby --version
z3 --version
yosys -V
```

If `yosys` crashes or reports missing DLLs:

```powershell
python scripts/diagnose_yosys_deps.py --yosys C:\oss-cad-suite\bin\yosys.exe
```

### Formal Smoke Script

PowerShell:

```powershell
@'
from pathlib import Path
from semiconductor_swarm.agents.agent1_planning.architect import generate_architecture_spec
from semiconductor_swarm.agents.agent2_rtl.rtl_designer import generate_rtl_files
from semiconductor_swarm.agents.agent5_formal.formal_verifier import generate_formal_files, prove_formal_with_symbiyosys

spec = generate_architecture_spec('IoT AI camera chip <1W 100MHz', 'iot_camera')
rtl = [f for f in generate_rtl_files(spec) if f['language'] == 'systemverilog']
formal = generate_formal_files(spec, rtl)
report = prove_formal_with_symbiyosys(spec, rtl, formal, Path('runs') / 'smoke_formal')
print('PASS=', report['pass'])
for run in report['runs']:
    print(run['block'], run['returncode'], run['result']['status'])
'@ | python -
```

Expected passing shape:

```text
PASS= True
apb_interconnect 0 PASS
control_regs 0 PASS
timer 0 PASS
interrupt_ctrl 0 PASS
dma_engine 0 PASS
sram_controller 0 PASS
mac_array 0 PASS
```

## Run Tests

Full suite:

```bash
python -m pytest tests
```

Unittest discovery also works:

```bash
python -m unittest discover -s tests
```

Focused checks:

```bash
python -m pytest tests/test_agent1.py
python -m pytest tests/test_agent2.py
python -m pytest tests/test_agent3.py
python -m pytest tests/test_agent4.py
python -m pytest tests/test_agent5.py
python -m pytest tests/test_agent_pipeline.py tests/test_swarm_graph.py
```

Recommended smoke after RTL/formal edits:

```bash
python -m pytest tests/test_agent2.py tests/test_agent5.py
```

## Programmatic API

Generate files directly from Python:

```python
from semiconductor_swarm.agents.agent1_planning.architect import generate_architecture_spec
from semiconductor_swarm.agents.agent2_rtl.rtl_designer import generate_rtl_files
from semiconductor_swarm.agents.agent5_formal.formal_verifier import generate_formal_files
from semiconductor_swarm.agents.agent3_dv.dv_engineer import generate_dv_files
from semiconductor_swarm.agents.agent4_physical.physical_designer import generate_physical_design_files

spec = generate_architecture_spec('IoT AI camera chip <1W 100MHz', 'iot_camera')
rtl_files = generate_rtl_files(spec, debug=True)
rtl_sv = [file for file in rtl_files if file['language'] == 'systemverilog']
formal_files = generate_formal_files(spec, rtl_sv, debug=True)
dv_files = generate_dv_files(spec, rtl_sv, debug=True)
physical_files = generate_physical_design_files(spec, rtl_sv, debug=True)
```

Run LangGraph in memory:

```python
from langgraph.types import Command
from semiconductor_swarm.swarm_graph import build_swarm_graph

app = build_swarm_graph()
config = {'configurable': {'thread_id': 'api-demo'}}
paused = app.invoke({'requirement': 'IoT AI camera chip <1W 100MHz', 'project_name': 'iot_camera', 'reports': {}}, config=config)
done = app.invoke(Command(resume={'approved': True, 'reviewer': 'api-user', 'notes': 'approved'}), config=config)
print(done['status'])
```

## Output Data Contract

Generated file entries are JSON-compatible dictionaries, typically shaped like:

```json
{
  "filename": "control_regs.sv",
  "language": "systemverilog",
  "content": "..."
}
```

Architecture specs and self-check reports are also JSON-compatible dictionaries.

## Guarantees And Design Rules

- PPA numbers come only from `calculate_ppa()`.
- Bandwidth numbers come only from `calculate_bandwidth()`.
- Output is strict JSON-compatible Python data.
- APB slave pinout is the single source of truth for RTL, formal, and DV.
- Agent 2 consumes Agent 1 JSON and emits SystemVerilog file JSON entries.
- Agent 2 refuses APB port renaming and uses `always_ff`/`always_comb` RTL style.
- Agent 5 is formal-first and gates Agent 3.
- The LangGraph flow carries HITL constraints and pauses for review before DV/backend generation.

## Troubleshooting

### `ModuleNotFoundError: langgraph`

```bash
python -m pip install langgraph langgraph-checkpoint-sqlite
```

### `ModuleNotFoundError: pytest`

```bash
python -m pip install pytest
```

### PowerShell Does Not Support Bash Here-Docs

Use PowerShell here-strings instead of `python - <<'PY'`:

```powershell
@'
print('hello from stdin')
'@ | python -
```

### `sby`, `yosys`, Or `z3` Not Found

Install OSS CAD Suite, open a new terminal, and verify `PATH`:

```powershell
python scripts/install_oss_cad_suite_windows.py --install-dir C:\oss-cad-suite --user-path
sby --version
z3 --version
yosys -V
```

### LangGraph Remains Paused

This is expected after Agent 5. Resume with the same checkpoint DB and thread ID:

```bash
python main.py --resume --thread-id demo --checkpoint-db swarm_checkpoints.sqlite --output-dir swarm_out
```

### Terminal JSON Output Is Too Large

Redirect JSON to files:

```bash
python -m semiconductor_swarm.agents.agent1_planning.architect "IoT AI camera chip <1W 100MHz" --project-name iot_camera > spec.json
python -m semiconductor_swarm.agents.agent2_rtl.rtl_designer spec.json --write-dir swarm_out/rtl > rtl_files.json
python -m semiconductor_swarm.agents.agent5_formal.formal_verifier spec.json rtl_files.json --write-dir swarm_out/formal > formal_files.json
```

## Recommended Development Loop

1. Edit agent logic in `semiconductor_swarm/agents/` or tool logic in `semiconductor_swarm/tools/`.
2. Run the focused test, for example `python -m pytest tests/test_agent5.py`.
3. Run `python -m pytest tests/test_agent_pipeline.py tests/test_swarm_graph.py`.
4. If formal collateral changed and OSS CAD Suite is installed, run the formal smoke script.
5. Run `python -m pytest tests` before sharing changes.

## Current Known Good Smoke Result

The current `IoT AI camera chip <1W 100MHz` / `iot_camera` smoke has been verified with:

```text
tests/test_agent2.py + tests/test_agent5.py: 15 passed
SymbiYosys/Z3 all-block smoke: PASS=True
```
