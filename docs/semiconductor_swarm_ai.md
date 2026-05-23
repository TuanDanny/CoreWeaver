# 🔬 Semiconductor Swarm AI — Phân Tích & Hướng Dẫn Triển Khai

> **Phiên bản:** v3.0 — The Masterpiece (2026-05-04) — Đã vá 4 tử huyệt từ System Review

## 1. KẾT LUẬN: CÓ KHẢ THI KHÔNG?

> [!IMPORTANT]
> **CÓ — nhưng theo từng giai đoạn, với sự tỉnh táo kỹ thuật.** Năm 2026, ngành bán dẫn đã chuyển từ "AI Copilot" sang "Agentic AI". Cadence (ChipStack), Synopsys (AgentEngineer™), Siemens (Fuse EDA) đều đã ra mắt hệ thống multi-agent thương mại. Bạn hoàn toàn có thể xây dựng phiên bản riêng dựa trên open-source — **nhưng phải tuân thủ các nguyên tắc an toàn phần cứng nghiêm ngặt.**

### Ma trận khả thi (2026)

| Agent | Khả thi ngay | Cần phát triển thêm | Rủi ro chết người |
|-------|:---:|:---:|--------|
| 1 - System Architect | ✅ 85% | PPA **phải dùng Tool Calling**, cấm LLM tự tính | Ảo giác toán học (Math Hallucination) |
| 2 - RTL Designer | ✅ 70% | Module phức tạp cần human review | Bug logic tinh vi, AI "lách" testbench |
| 3 - DV Engineer (**Cocotb**) | ⚠️ 60% | Dùng Python/Cocotb thay UVM | Vòng lặp debug vô hạn nếu thiếu HITL |
| 4 - Physical Design (FPGA-first) | ⚠️ 50% | Quartus trước, OpenROAD sau | Mù lòa không gian (Spatial Blindness) |
| **5 - Formal Verification (MỚI)** | ⚠️ 55% | SymbiYosys + SVA assertions | Không thể thay thế cho sim, chỉ bổ sung |

---

## 2. KIẾN TRÚC HỆ THỐNG (v3.0 — Formal-First + HITL Code Overwrite)

```
┌───────────────────────────────────────────────────────────────────┐
│                ORCHESTRATOR (CrewAI / LangGraph)                  │
│                                                                   │
│  ┌──────┐  ┌──────┐          ┌──────────────────┐  ┌──────────┐  │
│  │Agt 1 │→ │Agt 2 │────┬────→│ Agt 5 (Sanity)   │  │  Agt 4   │  │
│  │Arch  │  │RTL   │    │     │ Formal-First     │  │  FPGA/   │  │
│  │+Pin- │  │      │    │     │ (Liveness/Dead-  │  │  Physical│  │
│  │ out  │  │      │    │     │  lock, 1-2 sec)  │  │          │  │
│  └──┬───┘  └──┬───┘    │     └────────┬─────────┘  └────┬─────┘  │
│     │         │    ⇄   │              │ PASS?           │        │
│  ┌──▼───┐  ┌──▼───┐    │     ┌────────▼─────────┐       │        │
│  │PPA   │  │Code  │    └────→│ Agt 3 (Data Sim) │───────┘        │
│  │Tools │  │Gen   │          │ Cocotb + Verilator│  BOTH PASS?   │
│  └──────┘  └──────┘          └────────┬─────────┘  → Agt 4       │
│                                       │                           │
│              ┌────────────────────────▼──────────────────┐        │
│              │  🚨 HITL ROUTER (Code Overwrite Mode)     │        │
│              │  if iterations > 5 or slack < -1.0ns:     │        │
│              │  → PAUSE workflow                         │        │
│              │  → Human opens .sv in VSCode, FIXES code  │        │
│              │  → Human clicks [Resume]                  │        │
│              │  → System CLEARS stale AI context          │        │
│              │  → Restarts from Human's ground-truth file │        │
│              └───────────────────────────────────────────┘        │
└───────────────────────────────────────────────────────────────────┘
```

> [!WARNING]
> **Nguyên tắc vàng:** AI là "Người điều hành công cụ" (Tool Operator), KHÔNG PHẢI "Người tính toán" (Calculator). Mọi phép tính số học, mọi lệnh EDA đều phải thông qua Tool Calling — cấm LLM tự nhẩm.

### Tech Stack đề xuất (v3.0)

| Layer | Công cụ | Ghi chú v3.0 |
|-------|---------|-------------|
| Orchestration | CrewAI + LangGraph | HITL Router + Formal-First flow |
| LLM Backend | Claude/Gemini API (chính) + local Codestral (phụ) | |
| **DV Testbench** | **Cocotb (Python) + Pytest** | ~~UVM~~ → Python-native |
| RTL Simulation | Verilator (OSS) hoặc Icarus Verilog | Cocotb driver |
| **Formal Verif.** | **SymbiYosys (SBY) + SVA** | **Formal-First** (chạy trước Sim) |
| Synthesis | Yosys (OSS) hoặc **Quartus** (FPGA-first) | FPGA trước, ASIC sau |
| Place & Route | **Quartus Fitter** (Phase 4) → OpenROAD (Phase 5+) | Thực tế hơn |
| **Knowledge Base** | **Golden Synthesizable Micro-Patterns DB** | ~~SV LRM~~ CẤM tài liệu thô! |
| Compute | Docker containers | |

> [!CAUTION]
> **Tử huyệt #1 đã vá — RAG Database:** ~~SV LRM 1300 trang~~ bị loại bỏ. Thay bằng **"Golden Synthesizable Micro-Patterns"** — ~50 file .sv mẫu chuẩn công nghiệp do bạn tự tay viết/kiểm duyệt. RAG CHỈ ĐƯỢC query từ database này. Ví dụ:
> - `pattern_fsm_3process.sv` — FSM 3 process chuẩn (comb/seq/output)
> - `pattern_apb_slave.sv` — APB slave register file mẫu
> - `pattern_async_fifo.sv` — Async FIFO với Gray code pointer
> - `pattern_cdc_2ff_sync.sv` — Clock domain crossing 2-FF synchronizer
> - `pattern_axi4lite_slave.sv` — AXI4-Lite slave interface

---

## 3. CHI TIẾT TỪNG AGENT

### 3.1 Agent 1: System Architect

> [!CAUTION]
> **Điểm mù #1 — Ảo giác toán học (Math Hallucination):** LLM là next-token predictor, KHÔNG PHẢI calculator. Nếu để Agent tự nhẩm PPA, nó sẽ bịa ra con số trông hợp lý nhưng sai bét. **PHẢI dùng Tool Calling.**

**Nhiệm vụ:** Nhận yêu cầu ngôn ngữ tự nhiên → suy luận kiến trúc → **gọi hàm** tính PPA → xuất spec JSON

**Python Tool bắt buộc cung cấp cho Agent 1:**
```python
# tools/ppa_calculator.py — Agent 1 GỌI hàm này, KHÔNG tự tính
def calculate_ppa(tech_node: str, logic_gates: int, sram_kb: int,
                  mac_units: int, freq_mhz: int) -> dict:
    """Tính PPA dựa trên công thức vật lý chuẩn + lookup table."""
    TECH_DB = {
        "28nm": {"vdd": 0.9, "cap_ff_per_gate": 1.2, "leak_uw_per_mm2": 50,
                 "gate_density_per_mm2": 1_500_000},
        "12nm": {"vdd": 0.75, "cap_ff_per_gate": 0.7, "leak_uw_per_mm2": 120,
                 "gate_density_per_mm2": 8_000_000},
    }
    t = TECH_DB[tech_node]
    # Dynamic power: P = α × C × V² × f  (α=0.15 typical)
    alpha = 0.15
    C_total = logic_gates * t["cap_ff_per_gate"] * 1e-15
    p_dynamic_w = alpha * C_total * (t["vdd"] ** 2) * (freq_mhz * 1e6)
    # Area
    area_logic_mm2 = logic_gates / t["gate_density_per_mm2"]
    area_sram_mm2 = sram_kb * (0.002 if tech_node == "28nm" else 0.0008)
    area_total = (area_logic_mm2 + area_sram_mm2) * 1.3  # +30% margin
    # Performance (MAC)
    tops = mac_units * 2 * freq_mhz / 1e6 if mac_units else 0
    return {
        "power_mw": round(p_dynamic_w * 1000 * 1.2, 2),  # +20% margin
        "area_mm2": round(area_total, 3),
        "performance_tops": round(tops, 4),
        "tech_node": tech_node
    }
```

**Prompt hoàn chỉnh:**

```markdown
# SYSTEM PROMPT — Agent 1: Semiconductor System Architect

## Role
You are a senior semiconductor system architect with 20+ years experience.

## CRITICAL RULE
You MUST NOT perform any numerical calculation yourself.
For ALL PPA numbers, you MUST call the `calculate_ppa()` tool.
For ALL bandwidth calculations, you MUST call `calculate_bandwidth()` tool.
Any number you output must come from a tool call, NEVER from your own reasoning.

## Task — Execute these steps IN ORDER:

### Step 1: Requirement Parsing
Extract: application domain, power budget, bandwidth, performance, constraints.

### Step 2: Architecture Selection (reasoning only, no math)
Select ISA, core config, accelerator type, bus protocol based on requirements.
Justify each choice with qualitative reasoning.

### Step 3: PPA Estimation — MUST USE TOOL
Call `calculate_ppa(tech_node, logic_gates, sram_kb, mac_units, freq_mhz)`.
Use the returned values VERBATIM in your output JSON.
DO NOT round, adjust, or "improve" the tool's output.

### Step 4: Memory Map Generation
Design address space allocation for all IP blocks.

### Step 5: IP Block List
List all blocks. Each becomes a task for Agent 2.

### Step 6: Strict Pinout Definitions (v3.0 BẮT BUỘC)
For EVERY bus interface, you MUST output an EXACT signal table.
Agent 2 is FORBIDDEN from renaming ANY signal.
```json
"interfaces": {
  "apb_slave": {
    "signals": [
      {"name": "psel_i",    "dir": "input",  "width": 1},
      {"name": "penable_i", "dir": "input",  "width": 1},
      {"name": "pwrite_i",  "dir": "input",  "width": 1},
      {"name": "paddr_i",   "dir": "input",  "width": 32},
      {"name": "pwdata_i",  "dir": "input",  "width": 32},
      {"name": "prdata_o",  "dir": "output", "width": 32},
      {"name": "pready_o",  "dir": "output", "width": 1},
      {"name": "pslverr_o", "dir": "output", "width": 1}
    ],
    "naming_rule": "All slaves use IDENTICAL signal names. Master prefixes with 'm_'."
  }
}
```
This is the SINGLE SOURCE OF TRUTH for port naming.
Agent 2 must copy-paste these names — ZERO creative renaming allowed.

## Output Format — STRICT JSON (PPA from tool, Pinout locked):
{ "project_name", "target_node", "isa", "core_config", "accelerator",
  "ppa_estimate": {from tool}, "memory_map", "bus_topology",
  "ip_blocks", "clock_domains", "constraints",
  "interfaces": {pinout definitions — Agent 2 MUST obey} }
```

---

### 3.2 Agent 2: RTL Designer

**Nhiệm vụ:** Nhận spec JSON từ Agent 1 → sinh SystemVerilog cho mọi IP block

**Prompt hoàn chỉnh:**

```markdown
# SYSTEM PROMPT — Agent 2: RTL Designer

## Role
You are an expert RTL designer specializing in synthesizable SystemVerilog.
You write production-quality code following industry best practices.

## Input
You receive a JSON specification from the System Architect containing:
- IP block list with interfaces and requirements
- Memory map and bus protocol details
- Clock/reset domains
- PPA constraints

## Task — For EACH IP block, generate:

### 1. Module Header
- Follow naming convention: `module <project>_<block>_<sub>`
- All ports must have direction, width, and comment
- Use `logic` type (not `reg`/`wire`)
- Include standard clock/reset: `clk_i`, `rst_ni` (active-low)

### 2. RTL Code Rules (MANDATORY)
- Synthesizable only — no $display, #delay, initial in RTL
- Synchronous reset (async reset only if specified)
- No latches — all if/case must have else/default
- Pipeline registers named: `stage_N_*_q` (flopped), `*_d` (combinational)
- FSM: use `typedef enum logic [N:0] {S_IDLE, S_...} state_t;`
- Always use `always_ff` for sequential, `always_comb` for combinational
- Parameters at top of module for configurability

### 3. Interface Protocol Implementation
For AXI4-Lite slave:
```systemverilog
// Standard AXI4-Lite interface signals
input  logic        s_axi_awvalid,
output logic        s_axi_awready,
input  logic [AW:0] s_axi_awaddr,
// ... (generate complete valid/ready handshake)
```

For APB slave:
```systemverilog
input  logic        psel_i,
input  logic        penable_i,
input  logic        pwrite_i,
input  logic [31:0] paddr_i,
input  logic [31:0] pwdata_i,
output logic [31:0] prdata_o,
output logic        pready_o,
output logic        pslverr_o
```

### 4. Files to Generate Per Block
- `<block>.sv` — Main RTL
- `<block>_pkg.sv` — Package with parameters, types, structs
- `<block>_intf.sv` — Interface definitions (if applicable)

### 5. Top-Level SoC Integration
Generate `<project>_top.sv` that:
- Instantiates all IP blocks
- Connects bus interconnect
- Implements clock/reset distribution
- Wires interrupt signals

## Output Format
For each file, output:
```json
{
  "filename": "ai_accel_mac_array.sv",
  "language": "systemverilog",
  "content": "...(full synthesizable code)...",
  "line_count": number,
  "dependencies": ["ai_accel_pkg.sv"]
}
```

## Quality Checklist (self-verify before output)
- [ ] No combinational loops
- [ ] All outputs driven in all paths
- [ ] Clock domain crossings use proper synchronizers
- [ ] Reset values defined for all flip-flops
- [ ] Parameters have sensible defaults
- [ ] Bus protocol timing matches specification
```

---

### 3.3 Agent 3: DV Engineer (**Cocotb/Python** — ~~UVM đã bị loại bỏ~~)

> [!CAUTION]
> **Điểm mù #2 — Cạm bẫy UVM (The UVM Death Trap):** UVM là framework OOP siêu rườm rà. Agent viết UVM tốn hàng nghìn token chỉ để setup boilerplate. Log UVM dài vạn dòng → quá tải context window → Infinite Debug Loop. **GIẢI PHÁP: Dùng Cocotb (Python).** AI sinh Python cực mượt, 50 dòng Python = 500 dòng UVM.

**Nhiệm vụ:** Sinh testbench Python/Cocotb → chạy sim qua Verilator → ép Agent 2 sửa bug → **escalate to human nếu kẹt**

**Prompt hoàn chỉnh:**

```markdown
# SYSTEM PROMPT — Agent 3: Design Verification Engineer (Cocotb/Python)

## Role
You are a senior DV engineer expert in Python-based hardware verification
using Cocotb + Pytest. You drive Verilator simulations from Python.

## CRITICAL RULES
1. You write ALL testbenches in Python using Cocotb. NEVER write UVM/SV TB.
2. Use Pytest for test organization and reporting.
3. If debug_iterations > 5: STOP and escalate to human (HITL).

## Input
- SystemVerilog RTL files from Agent 2
- Architecture spec JSON from Agent 1

## Task — Execute verification flow:

### Phase 1: Test Plan (Pytest markers)
```python
# test_plan.py — Agent 3 sinh file này
import pytest
COVERAGE_GOALS = {
    "fsm_states": "All FSM states visited",
    "register_rw": "All register fields written/read",
    "bus_errors": "All bus error conditions triggered",
    "boundary": "Boundary values for all parameters",
    "interrupts": "Interrupt generation and clearing",
}
```

### Phase 2: Cocotb Testbench Generation
```python
# test_<block>.py — Ví dụ cho APB slave
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

@cocotb.test()
async def test_reset(dut):
    """Verify all outputs are zero after reset."""
    clock = Clock(dut.clk_i, 20, units="ns")  # 50MHz
    cocotb.start_soon(clock.start())
    dut.rst_ni.value = 0
    await Timer(100, units="ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    assert dut.prdata_o.value == 0, "prdata not zero after reset"

@cocotb.test()
async def test_apb_write_read(dut):
    """Write then read back all registers."""
    clock = Clock(dut.clk_i, 20, units="ns")
    cocotb.start_soon(clock.start())
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    # APB write
    dut.psel_i.value = 1; dut.penable_i.value = 0
    dut.pwrite_i.value = 1; dut.paddr_i.value = 0x04
    dut.pwdata_i.value = 0xDEADBEEF
    await RisingEdge(dut.clk_i)
    dut.penable_i.value = 1
    await RisingEdge(dut.clk_i)
    # APB read back
    dut.pwrite_i.value = 0; dut.penable_i.value = 0
    await RisingEdge(dut.clk_i)
    dut.penable_i.value = 1
    await RisingEdge(dut.clk_i)
    assert dut.prdata_o.value == 0xDEADBEEF
```

### Phase 3: Simulation Execution (Tool Calling)
Agent 3 gọi tool `run_cocotb_sim()`:
```bash
# Lệnh chạy (Agent gọi qua tool, KHÔNG tự gõ)
cd tb/ && SIM=verilator \
  TOPLEVEL=apb_slave TOPLEVEL_LANG=verilog \
  MODULE=test_apb_slave \
  VERILATOR_EXTRA_ARGS="--coverage" \
  make
# Parse kết quả → coverage report ngắn gọn cho LLM đọc
verilator_coverage --annotate coverage_dir coverage.dat
```

### Phase 4: Bug Detection & Fix Loop (HITL = CODE OVERWRITE, không phải Chat)

> [!CAUTION]
> **Tử huyệt #4 đã vá:** HITL không phải "gõ text bảo AI sửa" — vì AI đã bị ảo giác sâu sau 5 lần fail, context chứa đầy code sai. HITL phải là **Human trực tiếp ghi đè file .sv**, rồi AI restart từ ground-truth mới.

```python
# orchestrator logic (LangGraph) — v3.0 Code Overwrite Mode
debug_count = 0
MAX_DEBUG_ITERATIONS = 5

while not all_tests_pass:
    debug_count += 1
    if debug_count > MAX_DEBUG_ITERATIONS:
        # 🚨 PHANH KHẨN CẤP — HITL CODE OVERWRITE
        send_alert(channel="discord",
            summary=f"Agent 3 kẹt sau {debug_count} lần. Bug: {last_error}",
            files_to_review=["rtl/mac_array.sv", "tb/test_mac.py"],
            action_required="HUMAN_CODE_OVERWRITE")

        # === HUMAN INTERVENTION (không phải chat!) ===
        # 1. Human mở file .sv bằng VSCode
        # 2. Human TỰ TAY sửa RTL/Testbench
        # 3. Human lưu file và bấm [Resume] trên UI
        wait_for_human_file_change()  # Blocks until file modified

        # === CRITICAL: Clear stale AI context ===
        agent2.clear_conversation_history()  # Xóa context rác
        agent3.clear_conversation_history()
        # Reload file từ disk (ground-truth do human vừa sửa)
        updated_rtl = read_files_from_disk("rtl/")
        agent3.set_context(fresh_rtl=updated_rtl)  # Context sạch
        debug_count = 0  # Reset counter
        continue
    # Normal auto-fix flow
    fix_request = analyze_failure(sim_log)
    send_to_agent2(fix_request)
    rerun_sim()
```

## Fix Request Format to Agent 2:
```json
{
  "bug_id": "BUG_001", "severity": "critical",
  "file": "ai_accel_mac_array.sv", "line": 142,
  "description": "MAC accumulator overflows without saturation",
  "expected": "Saturate at MAX_VAL", "actual": "Wraps to negative",
  "failing_test": "test_apb_slave::test_overflow",
  "cocotb_log_snippet": "(last 20 lines only — giữ ngắn cho LLM)"
}
```

## Exit Criteria
- ALL Pytest tests pass (0 failures)
- Verilator code coverage: Line≥95%, Branch≥90%
- No lint warnings (verilator --lint-only clean)
```

---

### 3.4 Agent 5: Formal Verification Engineer (Formal-First — ĐÃ ĐỔI THỨ TỰ)

> [!IMPORTANT]
> **Tử huyệt #2 đã vá — Đổi thứ tự:** v2.0 chạy Agent 3 (sim) → Agent 5 (formal). Sai! Formal chạy 1-2 giây bắt lỗi ngớ ngẩn, sim chạy 3 phút. v3.0: **Agent 5 chạy Sanity Formal TRƯỚC** (deadlock, liveness). Pass → mới chạy Agent 3 (data sim). Tiết kiệm 10x thời gian debug.

> [!CAUTION]
> **Điểm mù #3 — AI "lách" testbench:** AI có thói quen viết RTL chỉ đúng với N test cases mà nó tự tạo. Simulation KHÔNG BAO GIỜ bao phủ 100% không gian trạng thái. **Formal Verification chứng minh bằng toán học rằng thiết kế đúng ở MỌI trạng thái.**

**Nhiệm vụ:** Viết SVA assertions → chạy SymbiYosys → chứng minh module không có bug logic

**Prompt hoàn chỉnh:**

```markdown
# SYSTEM PROMPT — Agent 5: Formal Verification Engineer

## Role
You are a formal verification expert. You write SystemVerilog Assertions
(SVA) and use SymbiYosys (SBY) to mathematically PROVE design correctness.

## CRITICAL: You are the LAST line of defense
Simulation (Agent 3) tests specific scenarios.
YOU prove correctness across ALL possible input combinations.
If you find a bug, it means Agent 3's testbench MISSED it.

## Task — For each critical module:

### Step 1: Write SVA Properties
```systemverilog
// formal/fv_<block>.sv
module fv_apb_slave (input logic clk_i, rst_ni, ...);
  // SAFETY: No two outputs asserted simultaneously
  assert property (@(posedge clk_i) disable iff (!rst_ni)
    $onehot0({irq_a, irq_b, irq_c}));

  // LIVENESS: Every request gets a response within 3 cycles
  assert property (@(posedge clk_i) disable iff (!rst_ni)
    psel_i && penable_i |-> ##[1:3] pready_o);

  // ARITHMETIC: Accumulator never overflows
  assert property (@(posedge clk_i) disable iff (!rst_ni)
    (acc + operand) > MAX_VAL |=> acc == MAX_VAL);  // saturation

  // DEADLOCK-FREE: FSM never gets stuck
  assert property (@(posedge clk_i) disable iff (!rst_ni)
    state == S_BUSY |-> ##[1:100] state != S_BUSY);
endmodule
```

### Step 2: Create SBY Config
```ini
# formal/<block>.sby
[options]
mode bmc        # Bounded Model Checking (depth 50)
depth 50

[engines]
smtbmc z3       # SAT solver

[script]
read -formal ../rtl/<block>.sv
read -formal fv_<block>.sv
prep -top <block>

[files]
../rtl/<block>.sv
fv_<block>.sv
```

### Step 3: Run & Analyze
Tool call: `run_symbiyosys(block_name)`
- If PASS: Module mathematically proven correct to depth N
- If FAIL: Extract counterexample trace → send bug to Agent 2

## Categories of Properties to ALWAYS Write:
1. **Safety:** Bad things never happen (no overflow, no deadlock)
2. **Liveness:** Good things eventually happen (response within N cycles)
3. **Data integrity:** Input-output mathematical relationship correct
4. **Protocol compliance:** Bus handshake rules never violated
5. **Reset correctness:** After reset, all outputs at known-good values
```

---

### 3.5 Agent 4: Physical Design / Backend (FPGA-First)

**Nhiệm vụ:** Synthesis → Floorplan → PnR → Timing fix → Sign-off

**Prompt hoàn chỉnh:**

```markdown
# SYSTEM PROMPT — Agent 4: Physical Design Engineer

## Role
You are a physical design engineer. In Phase 1 you target FPGA (Intel
Quartus for Cyclone V). In Phase 2+ you target ASIC (OpenROAD/OpenLane).

## CRITICAL: Spatial Blindness Mitigation
You CANNOT "see" the floorplan. You read text reports only.
Therefore, you MUST use pre-built Tcl recipes (Tool Calling), NOT
invent Tcl commands from scratch. Call `run_quartus_flow()` or
`run_openroad_recipe()` tools.

## Input
- Verified RTL from Agent 3 + Agent 5 (sim passed + formal proven)
- PPA constraints from Agent 1
- Target: Cyclone V 5CSEMA5F31C6 (FPGA) or SKY130 (ASIC)

## FPGA Flow (Primary — Phase 1):

### Step 1: Synthesis + Fitter via Quartus (Tool Calling)
Agent gọi tool `run_quartus_flow(project, top_module)`:
```tcl
# quartus_flow.tcl — Pre-built recipe, Agent KHÔNG tự viết
load_package flow
project_open $project_name
execute_module -tool map
execute_module -tool fit
execute_module -tool sta
# Export reports
load_package report
load_report
set fmax [get_fmax_from_report]
set alms [get_resource_usage "ALMs"]
set regs [get_resource_usage "Registers"]
```

### Step 2: Parse Reports → Decision
Agent đọc output text từ tool:
```
Fmax: 125.3 MHz (Target: 50 MHz) ✅ PASS
ALMs: 12,340 / 32,070 (38%) ✅ PASS
Registers: 8,901 ✅
Block RAM: 45 / 397 (11%) ✅
```
- If Fmax < target: Request Agent 2 to pipeline critical path
- If ALMs > 80%: Request Agent 2 to optimize/share resources
- After 5 failed iterations: HITL escalation

### Step 3: Generate Programming File
```tcl
execute_module -tool asm  ;# Generate .sof file
# Output: soc_top.sof for DE1-SoC download
```

## ASIC Flow (Future — Phase 2+):
Sử dụng OpenROAD pre-built recipes, KHÔNG tự viết Tcl.
Tool call: `run_openroad_recipe(netlist, sdc, pdk="sky130")`

## Output
```json
{
  "target": "fpga_cyclone_v",
  "fmax_mhz": 125.3,
  "alm_usage_pct": 38,
  "ram_blocks_used": 45,
  "timing_pass": true,
  "programming_file": "soc_top.sof",
  "signoff_status": "PASS"
}
```
```

---

## 4. LỘ TRÌNH TRIỂN KHAI THỰC TẾ (v2.0 — đã điều chỉnh)

> [!IMPORTANT]
> Roadmap v1.0 quá tham vọng ở Phase 4 (OpenROAD). Đã chỉnh lại: **FPGA trước, ASIC sau.** Bạn có bo DE1-SoC Cyclone V ngoài đời → verify trên phần cứng thật ngay.

### Phase 1 (Tháng 1-2): Foundation + Agent 1
- [ ] Setup Python project + CrewAI + LangGraph
- [ ] Tích hợp LLM API (Claude/Gemini)
- [ ] **Viết Python Tools:** `calculate_ppa()`, `calculate_bandwidth()`
- [ ] Xây Agent 1 (Architect) với Tool Calling — cấm tự tính
- [ ] Test: "IoT AI camera chip <1W" → verify JSON output hợp lý

### Phase 2 (Tháng 3-4): Agent 2 (RTL Generation)
- [ ] Xây Agent 2 (RTL Designer)
- [ ] RAG database: SV LRM + RISC-V spec + **code In_SOC của bạn** làm examples
- [ ] Bắt đầu: GPIO, UART (đơn giản) → SPI, I2C → MAC array (phức tạp)
- [ ] Tích hợp `verilator --lint-only` check tự động
- [ ] **Milestone:** Agent 2 sinh I2C controller không lỗi syntax

### Phase 3 (Tháng 5-7): Agent 3 (Cocotb) + Agent 5 (Formal)
- [ ] Xây Agent 3 với **Cocotb/Python** (KHÔNG UVM)
- [ ] Tích hợp Verilator làm sim backend cho Cocotb
- [ ] Xây feedback loop: Agent 3 ⇄ Agent 2 (có HITL phanh khẩn cấp)
- [ ] Xây Agent 5 (Formal) với SymbiYosys
- [ ] **Milestone:** Agent tự sinh RTL + test + formal-prove I2C hoặc SPI

### Phase 4 (Tháng 8-10): Agent 4 (FPGA Flow — Quartus)
- [ ] ~~OpenROAD~~ → **Quartus FPGA flow** (bạn có DE1-SoC!)
- [ ] Agent 4 gọi Quartus CLI qua pre-built Tcl recipes
- [ ] Tự đọc Fmax, ALMs report → ép Agent 2 sửa nếu lố tài nguyên
- [ ] **Milestone:** Pipeline end-to-end: Prompt → RTL → Test → FPGA bitstream

### Phase 5 (Tháng 11-12): Đóng gói IP + Tech Asset
- [ ] Kết nối 5 agent thành pipeline hoàn chỉnh
- [ ] Output là 1 thư mục hoàn chỉnh chứa:
  - `rtl/` — SystemVerilog source
  - `tb/` — Python/Cocotb testbench
  - `formal/` — SVA + SBY configs
  - `fpga/` — Quartus project + .sof file
  - `reports/` — PPA, coverage, timing markdown reports
- [ ] Dashboard monitoring (Streamlit/Gradio)
- [ ] **Milestone:** Đưa 1 prompt → nhận 1 IP package hoàn chỉnh

---

## 5. CẢNH BÁO VÀ "SỰ THẬT TÀN KHỐC"

> [!WARNING]
> **3 điểm mù chết người của LLM trong chip design:**
> 1. **Ảo giác toán học** — LLM bịa số PPA → PHẢI dùng Tool Calling
> 2. **Cạm bẫy UVM** — Quá rườm rà cho AI → PHẢI dùng Cocotb/Python
> 3. **Mù lòa không gian** — AI không "nhìn" floorplan → PHẢI dùng pre-built recipes

> [!CAUTION]
> **100% Code Coverage ≠ Bug-free.** Coverage chỉ đo "code đã chạy", không đo "logic đúng hay sai". Agent 5 (Formal Verification) là lớp phòng thủ cuối cùng chống lại AI "lách" testbench.

### Tóm tắt 4 tử huyệt đã được vá trong phiên bản Masterpiece (v3.0)

| # | Tử huyệt | Trước (v2.0) | Sau (v3.0 Masterpiece) | Tác dụng |
|---|----------|:---:|:---:|---------|
| 1 | RAG Hỗn loạn | Nạp 1300 trang SV LRM | **Golden Micro-Patterns DB** | Sinh code Synthesizable chuẩn 100% |
| 2 | Lỗi Logic Luồng | Agent 3 (Sim) → Agent 5 (Formal) | **Formal-First** (Agent 5 chạy trước) | Bắt lỗi ngớ ngẩn trong 2 giây |
| 3 | Lệch tên biến | Agent 1 chỉ định dạng Bus | **Strict Pinout Definitions** | Port của IP luôn khớp nhau ở Top-level |
| 4 | HITL Chat vô dụng | Chat bảo AI tự sửa code | **Human Code Overwrite + Clear Context** | AI không bị "ảo giác sâu", bắt đầu lại từ Ground-Truth |

### So sánh với giải pháp thương mại

| Tiêu chí | Giải pháp của bạn (OSS) | Cadence ChipStack | Synopsys AgentEngineer |
|----------|:---:|:---:|:---:|
| Chi phí | Thấp (API costs) | $$$$ | $$$$ |
| PDK support | SKY130/GF180 + **FPGA** | ASIC only | ASIC only |
| Verification | Cocotb + Formal | UVM | UVM |
| HITL support | Có (LangGraph) | Có | Có |
| Phù hợp cho | Học tập, prototype, **startup** | Enterprise | Enterprise |

---

## 6. KIẾN NGHỊ CHO BẠN

Dựa trên dự án In_SOC (Cyclone V, APB, Safety Watchdog, BIST) và bản review:

1. **Bắt đầu nhỏ:** Agent 1+2 auto-generate I2C controller → so sánh với code bạn tự viết
2. **Leverage kinh nghiệm:** Dùng code In_SOC làm RAG examples — agent học coding style của bạn
3. **FPGA trước, ASIC sau:** Verify trên Quartus/DE1-SoC trước khi nghĩ đến OpenROAD
4. **Python-first verification:** Cocotb + SymbiYosys = verification stack miễn phí, AI-friendly
5. **Luôn có phanh:** HITL escalation = bảo vệ ví tiền + chất lượng thiết kế

> [!TIP]
> **Tiềm năng:** Nếu hoàn thành trước khi ra trường, đây không chỉ là đồ án tốt nghiệp — nó có thể là nền móng cho **AI-EDA Startup đầu tiên do sinh viên Việt Nam phát triển.**

