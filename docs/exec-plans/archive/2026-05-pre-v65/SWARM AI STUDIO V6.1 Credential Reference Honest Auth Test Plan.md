---
title: SWARM AI STUDIO V6.1 Credential Reference Honest Auth Test Plan
status: active
owner: studio
type: exec-plan
created: 2026-05-22
source_of_truth: true
---

# SWARM AI STUDIO V6.1 Credential Reference Honest Auth Test Plan

## Summary
V6.0 web Settings con loi bao `PASS: Connection OK` khi nhap API key sai. Nguyen nhan: backend dang test bang `GET /models`; local endpoint `http://localhost:20128/v1` chap nhan route nay du key sai, nen bang chung auth bi yeu.

V6.1 sua theo huong dung hon cho web nhieu nguoi dung:
- UI khong nhap, khong gui, khong hien raw API key.
- UI chi chon credential reference.
- Backend tu resolve secret server-side.
- Test Connection phai dung auth probe co that bang `POST /chat/completions` voi prompt nho.
- Key cua owner nam o local secret/env va khong bi nguoi khac ghi de tu browser.

## Key Changes

### Credential Reference Model
- Thay raw `apiKey` trong web Settings bang `apiKeyRef`.
- Ref mac dinh: `owner`.
- `owner` resolve key theo thu tu:
  - `SWARM_CODEX_API_KEY`
  - `AGENT1_CODEX_API_KEY`
  - `codex_api.local.json.api_key`
- `GET /api/settings` chi tra metadata an toan:
  - endpoint
  - model
  - checkpoint_db
  - output_root
  - activeKeyRef
  - credentialRefs: `{id, label, hasSecret, source}`
- Khong endpoint nao tra raw key ve frontend.

### Settings Save Policy
- `POST /api/settings` khong chap nhan raw `apiKey` tu web nua.
- Neu request co `apiKey` thi fail `400 Raw API key is not accepted by web settings`.
- Backend chi luu:
  - endpoint/model neu can dung chung voi owner local config.
  - checkpoint/output/activeKeyRef trong `studio/settings.json`.
- `codex_api.local.json` tiep tuc la secret local ignored file, khong nam trong web-editable settings.

### Honest Test Connection
- `POST /api/settings/test-connection` nhan:
  - endpoint
  - model
  - apiKeyRef
- Backend resolve secret theo ref.
- Neu ref khong co secret: fail `400 Missing API key for credential ref: owner`.
- Probe dung:
  - `POST <endpoint>/chat/completions`
  - headers co `Authorization: Bearer <resolved-key>`
  - body nho: model, message `Respond with OK only.`, `max_tokens: 1`, `temperature: 0`
- Probe bat buoc dung async HTTP:
  - `httpx.AsyncClient(timeout=5.0)` hoac async equivalent.
  - Cam dung `requests` trong FastAPI route.
  - Network call khong duoc block FastAPI event loop.
- Chi PASS khi:
  - HTTP 200
  - response JSON co `choices`
- Cac truong hop fail:
  - connection refused / DNS / network error: `Network error: cannot connect to endpoint. Check whether 9Router is running.`
  - timeout: `Network timeout: endpoint did not respond within 5s.`
  - `401/403`: `Access denied: API key is invalid, expired, or unauthorized.`
  - `429`: `Rate limited: wait before retrying.`
  - invalid URL: `Invalid endpoint URL`
  - malformed response: `Invalid chat/completions response`
- Tuyet doi khong dung `GET /models` lam auth evidence.
- Backend phai co cooldown/rate guard per credential ref:
  - Neu cung ref duoc test lien tuc trong vong 2 giay, return `429 Test connection cooldown active`.
  - Cooldown khong expose secret va khong goi provider.

### Runner Secret Isolation
- Start/resume payload nhan `apiKeyRef`, khong nhan raw key.
- `RunnerManager` resolve ref va inject key vao process env:
  - `SWARM_CODEX_API_KEY`
  - `AGENT1_CODEX_API_KEY`
  - `AGENT2_CODEX_API_KEY`
- Khong truyen key qua command line.
- Khong dua key vao JSONL, WebSocket event, logs, artifacts, state snapshot.
- Neu active ref thieu secret va mode can LLM, runner fail som voi event safe: `Missing credential ref secret`.

### Frontend UX
- Bo password API key input khoi web Settings.
- Them dropdown `Credential Reference`.
- Hien thi `Server-side secret: configured/missing`.
- Nút `Test Connection`:
  - disable khi dang test.
  - cooldown 3 giay sau moi lan bam.
  - hien `Testing auth via chat/completions...`.
  - tra `PASS` chi khi backend probe chat pass.
  - tra `FAIL` cho key sai.
- Them notice ngan: `Keys are managed on the server. Browser never sees raw secrets.`

## Roadmap

### Phase 0 - Baseline Repro
- Ghi lai loi hien tai:
  - `GET /models` voi key sai van accepted.
  - `POST /chat/completions` voi key sai bi `401 Unauthorized`.
- Acceptance:
  - Test moi chung minh `/models` khong duoc xem la auth proof.

### Phase 1 - Backend Credential Registry
- Them helper credential registry trong backend config.
- Ho tro ref `owner`.
- Them public credential metadata.
- Acceptance:
  - Public settings khong co raw key.
  - Missing owner secret duoc report bang metadata `hasSecret=false`.

### Phase 2 - Settings Contract
- Doi Settings API sang `activeKeyRef`.
- Reject raw `apiKey` tu web.
- Giu backward compatibility toi thieu cho local secret file, nhung khong cho browser ghi de key.
- Acceptance:
  - POST settings voi `apiKey` fail.
  - endpoint/model/checkpoint/output van save dung.

### Phase 3 - Honest Auth Probe
- Doi test connection sang `chat/completions`.
- Dung `httpx.AsyncClient(timeout=5.0)`, khong dung `requests`.
- Kiem response shape.
- Phan loai loi proxy/network rieng voi loi provider/auth.
- Them backend cooldown per credential ref de chan spam.
- Redact all secret-like data.
- Acceptance:
  - Bogus key fail.
  - Saved owner key duoc dung server-side.
  - Endpoint `/models` accepted khong lam test pass.
  - 9Router off/connection refused bao loi network ro rang.
  - 401/403 bao loi API key sai/het han.
  - Spam Test Connection bi cooldown/429 va khong goi provider tiep.

### Phase 4 - Runner Ref Wiring
- Start/resume truyen `apiKeyRef`.
- Runner inject secret vao env, khong command line.
- Acceptance:
  - Process command khong chua key.
  - Env injection co key khi ref hop le.
  - State/event/log khong chua key.

### Phase 5 - Frontend Settings UX
- Bo raw key input.
- Them credential ref dropdown va configured/missing state.
- Test Connection non-blocking nhu V6.0.
- Test Connection co debounce/cooldown 3 giay tren UI.
- Acceptance:
  - UI khong co input password API key.
  - Network payload khong co `apiKey`.
  - Key sai trong local secret thi UI FAIL.
  - Bam lien tuc khong ban nhieu provider requests.

### Phase 6 - Regression And UAT
- Chay backend/frontend/full tests.
- Manual UAT voi key sai va key dung.
- Acceptance:
  - Key sai khong bao PASS.
  - Key dung bao PASS.
  - Full repo green.

## Test Plan

### Backend Tests
- `test_connection_rejects_bogus_key_even_if_models_endpoint_accepts`
- `test_connection_uses_chat_completions_not_models`
- `test_connection_uses_httpx_async_client_not_requests`
- `test_connection_refused_reports_network_error`
- `test_connection_unauthorized_reports_api_key_error`
- `test_connection_rate_limit_returns_429_without_provider_call`
- `test_settings_response_never_contains_api_key`
- `test_post_settings_rejects_raw_api_key_from_web`
- `test_owner_ref_resolves_saved_key_without_leaking`
- `test_missing_owner_ref_secret_fails_truthfully`
- `test_runner_injects_key_ref_secret_only_via_env`
- `test_runner_command_line_never_contains_secret`

### Frontend Tests
- Settings UI khong co raw API key field.
- Credential ref dropdown render `owner`.
- Test Connection payload co `apiKeyRef`, khong co `apiKey`.
- Test Connection button disables while running and remains cooled down for 3s.
- Smoke fail neu source con chuoi `GET /models` auth proof hoac placeholder Phase 7.
- UI hien configured/missing state.

### Commands
```powershell
.venv_dv\Scripts\python.exe -m py_compile studio\backend\server.py studio\backend\config.py studio\backend\runner.py tests\test_studio_backend.py
.venv_dv\Scripts\python.exe -m pytest -q tests\test_studio_backend.py
npm run test --prefix studio\frontend
npm run build --prefix studio\frontend
.venv_dv\Scripts\python.exe -m pytest -q tests\test_app_codex_ui.py tests\test_agent1_v51_deep_council.py
.venv_dv\Scripts\python.exe -m pytest -q
```

### Manual UAT
- Dat key sai trong `codex_api.local.json`.
- Mo web Settings.
- Chon `owner`.
- Bam `Test Connection`.
- Ket qua bat buoc: `FAIL: Authentication failed`.
- Dat key dung.
- Bam lai `Test Connection`.
- Ket qua mong doi: `PASS`.

## Assumptions
- Web Studio co the duoc nhieu nguoi dung chung, nen browser khong duoc giu raw API key cua owner.
- `owner` la server-managed credential ref dau tien; multi-user login va per-user encrypted vault se la phase sau.
- Existing Python Tk app giu legacy, khong la muc tieu chinh cua V6.1.
- `codex_api.local.json` van ignored va khong tracked.
- Endpoint chuan OpenAI-compatible ho tro `POST /chat/completions`.
