---
title: AGENT_2_Upgrade_V1 — Agent 2 RTL Designer Upgrade Plan
status: superseded
owner: semiconductor-swarm
type: exec-plan
last_reviewed: 2026-05-20
source_of_truth: false
superseded_by: docs/exec-plans/active/AGENT_2_V4_INDUSTRIAL_RTL_SIGNOFF_PLAN.md
related_tests:
  - tests/test_agent2.py
  - tests/test_swarm_graph.py
  - tests/test_prompt_contracts.py
---

# AGENT_2_Upgrade_V1 — Agent 2 RTL Designer Upgrade Plan

## 1. Mục tiêu

Nâng cấp Agent 2 từ bộ sinh RTL rule-based hiện tại thành RTL Designer có:

- Pattern Library dùng lại skeleton RTL chuẩn tổng hợp.
- Hook External IP cho GitHub/OpenCores/RAG sau này.
- RAG stub ổn định API để sau này gắn VectorDB mà không đổi logic Agent 2.
- Self-linting loop trong LangGraph ngay sau khi sinh RTL.
- UAT partial run chứng minh Agent 2 sinh SystemVerilog có dùng APB template và vượt lint.

Agent 1 giữ nguyên, đóng băng ở V4.1.

## 2. Phạm vi thay đổi

### 2.1 Files/thư mục sẽ tạo mới

- `patterns/`
- `patterns/pattern_manifest.yaml`
- `patterns/apb_slave_template.sv`
- `patterns/sync_fifo_template.sv`
- `semiconductor_swarm/tools/rag_retriever_stub.py`
- `semiconductor_swarm/tools/rtl_linter.py`
- Tests mới hoặc mở rộng trong `tests/test_agent2.py` và/hoặc `tests/test_swarm_graph.py`

### 2.2 Files sẽ sửa

- `semiconductor_swarm/agents/agent2_rtl/rtl_designer.py`
- `semiconductor_swarm/agents/agent2_rtl/agent2_prompt.py`
- `semiconductor_swarm/swarm_graph.py`
- `debug_runners/run_partial.py`
- Có thể cập nhật docs index nếu cần.

## 3. Pattern Library & External IP Hook

### 3.1 `patterns/pattern_manifest.yaml`

Manifest phải mô tả pattern bằng schema mở rộng được:

```yaml
schema_version: agent2_pattern_manifest_v1
patterns:
  - id: apb_slave_template
    description: Synthesizable APB slave skeleton with q/d register style and no non-synthesizable constructs.
    tags: [apb, slave, register, control, synthesizable]
    source_type: local
    external_uri: null
    local_path: apb_slave_template.sv
  - id: sync_fifo_template
    description: Synthesizable synchronous FIFO skeleton with pointer/count control and q/d style.
    tags: [fifo, synchronous, queue, buffer, synthesizable]
    source_type: local
    external_uri: null
    local_path: sync_fifo_template.sv
```

Trường bắt buộc theo yêu cầu:

- `id`
- `description`
- `tags`
- `source_type`: chỉ nhận `local | github | rag`
- `external_uri`: `null` cho local, chừa chỗ GitHub/OpenCores.

Trường bổ sung cần thiết:

- `local_path`: để RAG stub đọc file local tương ứng.

### 3.2 `patterns/apb_slave_template.sv`

Yêu cầu kỹ thuật:

- SystemVerilog tổng hợp được.
- Không có `#delay`.
- Không có `initial`.
- Không có `$display`.
- Dùng APB pin names chuẩn:
  - `clk_i`
  - `rst_ni`
  - `psel_i`
  - `penable_i`
  - `pwrite_i`
  - `paddr_i`
  - `pwdata_i`
  - `prdata_o`
  - `pready_o`
  - `pslverr_o`
- Dùng `logic`, `always_ff`, `always_comb`.
- Có marker rõ để UAT kiểm tra:
  - `AGENT2_PATTERN_ID: apb_slave_template`
- Có q/d style:
  - `reg0_q`, `reg0_d`
  - `prdata_d`
  - `state_q`, `state_d`

### 3.3 `patterns/sync_fifo_template.sv`

Yêu cầu kỹ thuật:

- SystemVerilog tổng hợp được.
- Không có `#delay`, `initial`, `$display`.
- Dùng `logic`, `always_ff`, `always_comb`.
- Có marker:
  - `AGENT2_PATTERN_ID: sync_fifo_template`
- Có cấu trúc FIFO sync:
  - `wr_en_i`, `rd_en_i`
  - `full_o`, `empty_o`
  - `wr_ptr_q/d`, `rd_ptr_q/d`, `count_q/d`

## 4. RAG Stub

### 4.1 File

`semiconductor_swarm/tools/rag_retriever_stub.py`

### 4.2 API cố định

```python
def query_rtl_knowledge_base(query: str, tags: list[str]) -> str:
    ...
```

### 4.3 Behavior V1

- Đọc `patterns/pattern_manifest.yaml`.
- Match pattern bằng `tags` và text `query`.
- Nếu `source_type == local`, đọc `patterns/<local_path>` và trả content.
- Nếu `source_type == github` hoặc `rag`, trả lỗi rõ hoặc bỏ qua trong V1, không network fetch.
- Nếu không tìm thấy pattern, raise `ValueError` với message rõ.

### 4.4 Mục tiêu tương lai

Giữ API trên để sau này thay phần thân bằng:

- Chroma
- FAISS
- GitHub raw fetch
- OpenCores mirror
- internal IP catalog

Không đổi logic gọi hàm từ Agent 2.

## 5. Self-Linting Tool

### 5.1 File

`semiconductor_swarm/tools/rtl_linter.py`

### 5.2 API đề xuất

```python
def lint_rtl_files(files: list[dict[str, Any]], work_dir: str | Path | None = None) -> dict[str, Any]:
    ...
```

### 5.3 Behavior

1. Ghi các file SystemVerilog vào `work_dir` tạm.
2. Nếu có `verilator` trong PATH:
   - Chạy:
     ```bash
     verilator --lint-only -Wall <files>
     ```
   - Parse exit code/stdout/stderr.
3. Nếu không có `verilator`:
   - Dùng static fallback để CI không chết.
   - Kiểm tra:
     - cấm `initial`
     - cấm `$display`
     - cấm `#` trừ parameter syntax `#(` nếu cần
     - có `always_ff`
     - có `always_comb`
     - không dùng ` reg ` hoặc ` wire ` trong module generated
     - latch-risk basic: `always_comb` phải có default assignments phổ biến.

### 5.4 Report schema

```json
{
  "pass": true,
  "tool": "verilator" or "static_fallback",
  "command": "verilator --lint-only -Wall ...",
  "files_checked": ["..."],
  "failures": [],
  "stdout": "...",
  "stderr": "..."
}
```

## 6. Agent 2 Logic Update

### 6.1 Gọi RAG stub bắt buộc

Agent 2 phải gọi:

```python
query_rtl_knowledge_base(query="APB slave register skeleton", tags=["apb", "slave"])
```

khi spec có APB interface hoặc block liên quan register/control.

Agent 2 phải gọi FIFO pattern khi requirement/spec có FIFO/buffer/queue/CDC phức tạp.

### 6.2 Dùng skeleton trong generated RTL

Agent 2 không tự phát minh APB interface/register skeleton nữa. Generated APB module phải có dấu vết template:

- comment marker `AGENT2_PATTERN_ID: apb_slave_template`
- APB state/q-d structure tương thích template
- APB pin names không đổi

### 6.3 Giữ backward compatibility

Các rule hiện tại vẫn giữ:

- Một `.sv`, một `_pkg.sv`, một `_intf.sv` cho mỗi IP block.
- Top-level wrapper `<project>_top.sv`.
- APB pinout locked.
- Không `reg/wire` legacy.
- Không non-synth token.
- `agent2_debug_report.json` khi `debug=True`.

### 6.4 Verify report mở rộng

`verify_rtl_files()` thêm checks:

- `rag_stub_called`
- `apb_pattern_reused`
- `pattern_marker_present`
- `self_lint_ready`

Fail nếu APB design không có marker/template skeleton.

## 7. Prompt Update

File: `semiconductor_swarm/agents/agent2_rtl/agent2_prompt.py`

Thêm rule bắt buộc:

- Nếu thiết kế liên quan APB/FIFO/CDC/module phức tạp, Agent 2 phải gọi `query_rtl_knowledge_base()` trước khi viết RTL.
- Agent 2 phải dùng skeleton trả về làm khung phát triển logic.
- Agent 2 không tự phát minh cấu trúc thanh ghi/giao tiếp nếu pattern phù hợp tồn tại.
- Nếu skeleton thiếu capability, mở rộng cục bộ nhưng vẫn giữ APB pinout và q/d style.

## 8. LangGraph Self-Linting Loop

### 8.1 Node mới

Tên node:

```text
agent2_syntax_linter
```

Tên logic/report:

```text
Agent2_Syntax_Linter
```

### 8.2 Flow mới

Hiện tại:

```text
agent2_rtl -> agent5_formal
```

Sẽ đổi thành:

```text
agent2_rtl -> agent2_syntax_linter
agent2_syntax_linter -- PASS --> agent5_formal
agent2_syntax_linter -- REJECT --> auto_debug_agent2
auto_debug_agent2 -> agent2_rtl
```

Nếu `debug_iterations >= max_debug_iterations`, route tới `human_review` hoặc dừng theo policy hiện có.

### 8.3 Reject payload

Khi lint fail, set:

```json
{
  "agent2_fix_request": {
    "action": "REQUEST_AGENT2_FIX",
    "fix_type": "RTL_LINT_FIX",
    "severity": "critical",
    "failures": ["..."],
    "required_until": "Agent2_Syntax_Linter pass"
  },
  "status": "AGENT2_LINT_REJECT"
}
```

### 8.4 Report

Lưu vào:

```python
reports["agent2_lint"]
```

## 9. `debug_runners/run_partial.py` Update

Hiện `STOP_NODE["agent2"] = "agent2_rtl"`.

Sau khi thêm linter, đổi thành:

```python
STOP_NODE["agent2"] = "agent2_syntax_linter"
```

Mục tiêu: `--stop-after agent2` phải dừng sau khi Agent 2 sinh RTL và lint xong.

Summary mở rộng thêm checks:

- `agent2_lint_called`
- `agent2_lint_pass`
- `apb_pattern_marker_present`

## 10. Tests/UAT

### 10.1 Unit tests cần thêm

1. Manifest schema:
   - có `schema_version`
   - có `patterns`
   - mỗi pattern có `id`, `description`, `tags`, `source_type`, `external_uri`
   - `source_type` thuộc `local | github | rag`

2. Template safety:
   - `apb_slave_template.sv` không có `initial`, `$display`, `#delay`
   - `sync_fifo_template.sv` không có `initial`, `$display`, `#delay`

3. RAG stub:
   - query APB trả content có `AGENT2_PATTERN_ID: apb_slave_template`
   - query FIFO trả content có `AGENT2_PATTERN_ID: sync_fifo_template`

4. Agent2 generation:
   - generated APB RTL có marker `AGENT2_PATTERN_ID: apb_slave_template`
   - debug report pass
   - checks mới pass

5. RTL linter:
   - generated RTL pass `lint_rtl_files()`
   - file có `initial begin` fail fallback/static check

6. Graph:
   - `agent2_rtl` route qua `agent2_syntax_linter`
   - lint fail route về `auto_debug_agent2`

### 10.2 Full regression

Chạy:

```bash
python -X utf8 -m pytest -q
```

Kết quả cần đạt:

```text
all tests passed
```

### 10.3 UAT partial run

Chạy:

```bash
python -X utf8 debug_runners/run_partial.py "Mạch đếm Counter 16-bit giao tiếp APB" --stop-after agent2 --project-name counter16_apb --thread-id agent2_uat_v1 --output-dir outputs/agent2_uat_v1 --checkpoint-db outputs/agent2_uat_v1.sqlite --output-policy overwrite
```

Kết quả cần đạt:

- Exit code `0`.
- Summary JSON có:
  - `pass: true`
  - `status: AGENT2_LINT_PASS` hoặc status tương thích sau lint pass.
  - `rtl_sv_count > 0`
  - `agent2_lint_pass: true`
  - `apb_pattern_marker_present: true`
- RTL output trong `outputs/agent2_uat_v1/rtl/*.sv` có:
  - `AGENT2_PATTERN_ID: apb_slave_template`
  - APB pins chuẩn.
  - Không có `initial`, `$display`, `#delay`.

## 11. Definition of Done

Nâng cấp chỉ được coi xong khi đạt toàn bộ:

- [ ] `patterns/pattern_manifest.yaml` tồn tại và schema đúng.
- [ ] `patterns/apb_slave_template.sv` tồn tại, synthesizable, no non-synth constructs.
- [ ] `patterns/sync_fifo_template.sv` tồn tại, synthesizable, no non-synth constructs.
- [ ] `query_rtl_knowledge_base()` hoạt động với APB/FIFO local patterns.
- [ ] `rtl_linter.py` chạy được với Verilator nếu có, fallback an toàn nếu không có.
- [ ] Agent 2 gọi RAG stub khi gặp APB/FIFO/CDC/complex.
- [ ] Agent 2 generated RTL có marker skeleton APB.
- [ ] `verify_rtl_files()` bắt lỗi nếu APB pattern không được reuse.
- [ ] LangGraph có node `agent2_syntax_linter` và conditional edge PASS/REJECT.
- [ ] `debug_runners/run_partial.py --stop-after agent2` dừng sau lint.
- [ ] Full pytest pass.
- [ ] UAT partial run pass với project `counter16_apb`.
- [ ] Báo cáo cuối ghi rõ Verilator thật hay static fallback.

## 12. Rủi ro và kiểm soát

### Rủi ro 1: Verilator không có trên máy

Kiểm soát:

- `rtl_linter.py` detect tool bằng PATH.
- Nếu thiếu, dùng static fallback.
- Report ghi rõ `tool: static_fallback`.

### Rủi ro 2: Lint node làm vỡ partial runner

Kiểm soát:

- Cập nhật `STOP_NODE["agent2"]` sang `agent2_syntax_linter`.
- Update expected status và summary checks.

### Rủi ro 3: Refactor Agent2 phá contract cũ

Kiểm soát:

- Giữ schema output cũ.
- Giữ file naming cũ.
- Giữ APB pinout cũ.
- Chạy full pytest.

### Rủi ro 4: Template marker chỉ là comment, chưa chứng minh reuse sâu

Kiểm soát V1:

- Marker + structural tokens được check.
- V2 có thể thêm AST/template fingerprint.

## 13. Không làm trong V1

- Không fetch GitHub thật.
- Không tích hợp Chroma/FAISS thật.
- Không thay Agent 1 V4.1.
- Không thay Agent 3/4/5 ngoài compatibility nếu cần.
- Không yêu cầu Verilator bắt buộc cài sẵn.

## 14. Trình tự thực hiện sau khi được duyệt

1. Tạo pattern library.
2. Tạo RAG stub.
3. Tạo RTL linter.
4. Sửa Agent2 generator và verifier.
5. Sửa Agent2 prompt.
6. Sửa LangGraph lint node/edge.
7. Sửa partial runner.
8. Thêm/cập nhật tests.
9. Chạy pytest.
10. Chạy UAT partial run.
11. Báo cáo kết quả, test output, UAT artifacts.
