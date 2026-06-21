# Nâng Cấp Tư Duy Agent 1 (Agent 1 Reasoning Upgrade)

Kế hoạch này nhằm loại bỏ hoàn toàn các lớp "ảo giác" (hallucination) do việc sử dụng Regular Expression (Regex) hardcode trong phiên bản khung (Harness Skeleton) trước đó, đồng thời kích hoạt 100% khả năng tư duy (Reasoning) của các mô hình LLM thông qua Prompting nâng cao và Structured Outputs (Pydantic).

## Yêu cầu xem xét (User Review Required)

> [!WARNING]
> Kế hoạch này sẽ xóa bỏ toàn bộ các dòng code Regex hardcode liên quan đến NPU/AXI/AES trong `experts.py` và `reasoning.py`. Điều này có nghĩa là hệ thống sẽ phụ thuộc 100% vào năng lực của LLM (Gemini 3.5 Flash hoặc 3.1 Pro). Nếu LLM từ chối trả lời hoặc sinh kết quả sai, hệ thống sẽ báo lỗi thay vì sinh ra kết quả "giả" như trước.

## Thay đổi đề xuất (Proposed Changes)

---

### 1. Nâng cấp bộ tương thích Mô hình (Model Compatibility Layer)

Hiện tại, `openai_compatible.py` chỉ bật cờ `{"type": "json_object"}` nhưng **chưa cung cấp JSON Schema** cho LLM, khiến LLM không biết phải trả về cấu trúc Pydantic nào. 

#### [MODIFY] openai_compatible.py
- Nếu `response_format` (Pydantic Model) được cung cấp, tự động serialize `response_format.model_json_schema()` và tiêm (inject) thẳng vào System Prompt.
- Đảm bảo LLM hiểu rõ ràng các trường bắt buộc và định dạng của từng biến (List, Dict, String).

### 2. Nâng cấp Leaf Experts (Chuyên gia Phân tích Nhánh)

Hiện tại, `experts.py` đang phớt lờ đầu ra JSON của LLM và tự động append các phát hiện hardcode thông qua hàm `_domain_findings`.

#### [MODIFY] experts.py
- **Prompt:** Mở rộng Prompt từ 3 dòng lên thành một chỉ thị chi tiết, yêu cầu chuyên gia (ví dụ: Security Expert, Memory Expert) suy nghĩ sâu (Chain-of-Thought) trước khi chốt phát hiện.
- **Xóa Regex:** Xóa bỏ hoàn toàn hàm `_domain_findings` (nơi đang hardcode NPU AXI/AES).
- **Phân giải:** Sử dụng JSON Parser chuẩn xác, lấy trực tiếp kết quả từ LLM (Findings, Risks, Assumptions) để đưa vào Blackboard.

### 3. Nâng cấp Principal Agent (Kiến trúc sư Trưởng)

Hiện tại, nếu LLM trả về JSON bị lỗi, hệ thống sẽ câm lặng rơi vào `_synthesize_fallback` và tự động sinh ra một file Markdown giả dối chứa toàn thông tin của NPU.

#### [MODIFY] reasoning.py
- **Prompt:** Tiêm `ArchitecturePlan.model_json_schema()` vào prompt để bắt LLM phải format chuẩn.
- **Fallback an toàn:** Xóa nội dung Regex hardcode trong `_synthesize_fallback`. Thay vào đó, ném Exception để hệ thống tự động Retry (kích hoạt Self-Healing của Manager) hoặc trả về khung dữ liệu rỗng hợp lệ để báo lỗi rõ ràng.

### 4. Nâng cấp LLM-as-a-Judge (Cổng kiểm duyệt Signoff)

Cổng `signoff.py` hiện cũng đang dùng Regex `if "key" in plan` để bắt lỗi, cực kỳ cứng nhắc.

#### [MODIFY] signoff.py
- Mở rộng prompt để Giám khảo (Judge) tự động đánh giá linh hoạt dựa trên văn bản thực tế của `requirement_summary`.
- Loại bỏ các string match tĩnh trong `_evaluate_fallback`.

#### [MODIFY] verifier.py
- Xóa bỏ biến hardcode `expected_manager_count = 7`. Hệ thống sẽ tự động đếm số lượng Managers có mặt trong Topology thực tế.

---

## Kế hoạch Nghiệm thu (Verification Plan)

### Automated Tests
- Chạy `python -m pytest -q tests/` để đảm bảo không vỡ Unit Tests sau khi xóa các hàm fallback.
- Chạy `python scripts/harness_check.py --json` để đảm bảo hệ thống Framework vẫn xanh.

### Manual Verification
- Chạy E2E với Requirement thực tế (ví dụ: `SPI Master` hoặc `APB Timer`).
- Kiểm tra `architecture_plan.md` sinh ra: Đảm bảo thiết kế phản ánh ĐÚNG requirement, **không** dính ảo giác về NPU/AES, và **có** các thanh ghi đếm/trạng thái chuẩn mực của bài toán.
