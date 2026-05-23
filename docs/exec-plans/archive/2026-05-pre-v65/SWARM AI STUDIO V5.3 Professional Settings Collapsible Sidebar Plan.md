---
title: SWARM AI STUDIO V5.3 Professional Settings Collapsible Sidebar Plan
status: active
owner: app-ux
type: exec-plan
last_reviewed: 2026-05-21
source_of_truth: true
---

# SWARM AI STUDIO V5.3 Professional Settings + Collapsible Sidebar Plan

## Summary
Muc tieu: sua app cho chuyen nghiep hon sau V5.2. Loi can sua ngay: `Test Connection` khong duoc bao OK khi chua co API key. UI can bot so sai, sidebar co the thu gon, Settings phai minh bach trang thai key, va visual can gan hon mau dark sidebar/topbar trong anh tham chieu.

Ket qua dau ra:
- App khong "bip" nguoi dung ve API connection.
- Sidebar co collapse/expand, bot ton dien tich man hinh.
- Settings ro rang hon: key saved/missing, show/hide, clear saved key.
- API key khong lo vao log, JSONL event, `history.md`, hay `app/settings.json`.
- Agent/backend behavior khong doi.

## Key Changes
### API Settings And Connection Truthfulness
- `Test Connection` phai fail som voi thong bao `Missing API key` neu:
  - API Key field trong dialog trong, va
  - `codex_api.local.json` khong co saved `api_key`.
- Neu API Key field la placeholder `********`, chi duoc dung saved key hien co.
- Neu endpoint tra HTTP OK nhung response khong co `choices[0].message.content`, hien thi `Connection reached endpoint but response was empty`, khong hien `Connection OK`.
- `Test Connection` khong duoc block UI:
  - chay trong background thread rieng, khong chay network call tren Tk main thread.
  - disable nut `Test Connection` trong luc dang test.
  - hien `Testing...` ngay lap tuc.
  - tra ket qua ve UI bang `after()` hoac queue-safe callback.
  - timeout mac dinh 10s.
  - neu user dong Settings dialog trong luc test dang chay, thread khong duoc update widget da bi destroy; chi log/status an toan.
- `Save` ghi endpoint/model/API key vao `codex_api.local.json`.
- `app/settings.json` chi giu UI/checkpoint settings, khong bao gio giu `api_key`.
- Khi field API key trong hoac placeholder, giu key cu; khi bam `Clear Saved Key`, xoa key khoi config.

### Professional Settings Dialog
- Them status row:
  - `Saved key: yes`
  - `Saved key: no`
- Them nut:
  - `Show/Hide`
  - `Clear Saved Key`
  - `Test Connection`
  - `Save`
- Khi `Test Connection` dang chay:
  - nut test hien `Testing...`
  - Save/Close van khong lam app freeze.
  - ket qua test chi cap nhat dialog neu dialog con ton tai.
- Dialog mau nen dark tech:
  - outer: `#211815`
  - input: `#1b2020`
  - primary: cyan
  - danger/clear: muted red
- Khong log API key. Log sau save chi duoc ghi endpoint/model/key state, vi du: `settings saved: endpoint=... model=... key=set`.

### Collapsible Sidebar UX
- Them nut collapse/expand o tren sidebar.
- Expanded:
  - width khoang `224px`
  - labels day du: `Project`, `Agents`, `Logs`, `Plan Review`, `Settings`, `Future Wiki`
- Collapsed:
  - width khoang `58px`
  - labels ngan: `P`, `A`, `L`, `R`, `S`, `W`
- Active state ro:
  - background `#37312f`
  - inactive transparent/dark
  - hover `#2b2928`
- Sidebar style gan anh tham chieu:
  - background `#211815`/`#1b1b1b`
  - muted text `#9d9690`
  - active text `#f0ece8`

### Agent 1 V5.1 Visibility
- Giu Agent 1 rollup da co, nhung hien ro hon:
  - `Leaf Experts`
  - `Middle Managers`
  - `Principal`
  - `Guardrails`
- Card Agent 1 chi hien summary/rollup, khong hien prompt/context dai.
- Log van chi tiet theo event stream hien co.

## Implementation Changes
- File chinh: `app/main_window.py`.
- Them helper:
  - `_resolve_api_key_for_test(api_key_value) -> tuple[str | None, str | None]`
  - `_clear_codex_api_key() -> None`
  - `_mask_key_state() -> str`
  - `_run_connection_test_async(endpoint, model, api_key_value, on_done) -> None`
  - `_toggle_sidebar() -> None`
  - `_render_sidebar_labels() -> None`
- Sua `_test_codex_connection()`:
  - goi `_resolve_api_key_for_test()`.
  - neu missing key thi return `(False, "Missing API key")` va khong goi `urllib.request.urlopen`.
  - timeout ngan 10s giu nguyen.
- Them async wrapper cho test connection:
  - dung `threading.Thread(..., daemon=True)`.
  - worker chi goi `_test_codex_connection()`.
  - UI update qua `self.after(0, ...)`.
  - khong truyen API key vao log/event.
- Sua `open_settings()`:
  - them key status, show/hide, clear key.
  - nut Test Connection goi async wrapper, khong block main loop.
  - update status label sau khi clear/save/test.
- Tests: `tests/test_app_codex_ui.py`.
  - mock `urllib.request.urlopen` de xac nhan missing key khong goi network.
  - placeholder dung saved key.
  - clear key xoa khoi `codex_api.local.json`.
  - Test Connection async khong block: ham click tra ve ngay trong thoi gian ngan, status thanh `Testing...`, result cap nhat sau.
  - closing/destroying dialog during async test does not raise.
  - sidebar collapse/expand doi width va label.
  - log khong chua secret.

## Test Plan
### Static
```powershell
.venv_dv\Scripts\python.exe -m py_compile app\main_window.py app\swarm_runner.py
```

### Targeted
```powershell
.venv_dv\Scripts\python.exe -m pytest -q tests\test_app_codex_ui.py
.venv_dv\Scripts\python.exe -m pytest -q tests\test_agent1_v51_deep_council.py
```

### Full Regression
```powershell
.venv_dv\Scripts\python.exe -m pytest -q
```

### Manual Smoke
- Mo app bang:
```powershell
.venv_dv\Scripts\python.exe app\main_window.py
```
- Settings voi API key trong va no saved key -> `Missing API key`.
- Nhap API key -> Test Connection goi endpoint va chi OK khi co content hop le.
- Bam `Test Connection` khi endpoint cham -> app van cuon/nhan click, dialog khong Not Responding.
- Clear Saved Key -> config khong con `api_key`.
- Collapse/expand sidebar hoat dong, layout khong vo.

## Acceptance Criteria
- `Test Connection` khong bao OK khi API key thieu.
- `Test Connection` khong lam freeze app; network call khong nam tren UI thread.
- Missing-key test chung minh khong co network call.
- API key khong xuat hien trong UI log, app settings, runtime events, hoac test output.
- Sidebar collapse/expand khong crash va co active state dung.
- Full regression xanh.

## Assumptions
- V5.3 bat buoc API key cho `Test Connection`, ke ca local endpoint co the chap nhan no-key, vi UX phai trung thuc voi nguoi dung.
- Khong doi backend Agent 1/2/3.
- Khong co Windows title-bar custom native; chi style command bar/sidebar ben trong app.
- `codex_api.local.json` tiep tuc la source of truth cho endpoint/model/key backend.
