---
title: Agent 1 V6.4 Real Codex Intake And Top-Down Bottom-Up Council Plan
status: active
owner: agent1
type: exec-plan
created: 2026-05-22
source_of_truth: true
---

# Agent 1 V6.4 Real Codex Intake And Top-Down Bottom-Up Council Plan

## Summary
Muc tieu: bien Agent 1 thanh AI architect thuc thu cho input bat ky cua nguoi dung. Moi node ra quyet dinh phai dung Codex LLM API that, khong dung AI gia/rule-based de chon kien truc. Deterministic code chi lam guardrail, audit, schema validation, concurrency control, va artifact hygiene.

Bug can sua:
- Input `Hi, ban la ai` bi nham chu `ai` thanh AI accelerator.
- Project name `cpu32bit_web` bi rui ro dung nhu bang chung ky thuat.
- START cung project co the reuse checkpoint/log cu, lam UI hien `SIGNOFF_READY`, `resume ok`, Agent2 events tu run truoc.
- Agent1 co the sinh CPU/APB baseline khi user chua dua Project Requirement chip that.

Ket qua can dat:
- Input nao cung duoc Codex boc tach truoc.
- Non-design input dung sau Intake Council, tra loi nguoi dung va xin requirement chip.
- Design-ready input moi di vao 24 leaf experts.
- Agent1 khong duoc invent CPU, APB, peripheral neu khong co citation tu user/intake.
- Studio khong tron log/checkpoint/output cu giua cac run.
- Output cuoi can co:
  - Non-design: `agent1_requirement_clarification.md`, `agent1_intake_router_report.json`, `agent1_policy_matrix.json`, khong co `architecture_plan.md`.
  - Clarification-needed: clarification artifact + missing field list, khong co Agent2 output.
  - Design-ready: architecture plan/spec + citation ledger + policy matrix + full Agent1 council traces.
  - Studio run: `studio_run_manifest.json`, `run_lineage.json`, logs chi thuoc run hien tai.

## Phase Roadmap
### Phase 0 - Baseline And Failure Reproduction
- Record current failing behavior for:
  - `Hi, ban la ai`
  - `hi`
  - `cpu32bit_web` project name with non-design input
  - stale replay/checkpoint logs on same project START
- Capture current artifacts in a debug fixture or test snapshot.
- Acceptance:
  - Baseline tests fail before fix or are marked expected-fail until implementation.
  - Evidence proves current bug: non-design input can produce `architecture_plan.md` and Agent2 can run.

### Phase 1 - Real Codex Intake Council
- Add 5 Intake experts with real Codex API calls.
- Add strict JSON schema, one repair retry, evidence digest/token/hash.
- Add Intake Adjudicator Codex call.
- Emit `agent1_intake_router_report.json`.
- Acceptance:
  - `Hi, ban la ai` calls 5 Intake experts + adjudicator and returns `NON_DESIGN_CONVERSATION`.
  - Invalid JSON triggers one repair.
  - Repair failure blocks architecture.
  - No deterministic architecture fallback exists in Intake path.

### Phase 2 - Canonical Intent, Consensus, And Guardrails
- Add canonical intent ontology.
- Add consensus score and calibrated confidence.
- Add contradiction detector.
- Add minimum viable requirement gate.
- Add project-name quarantine and prompt injection shield.
- Emit `agent1_requirement_citation_ledger.json` and `agent1_policy_matrix.json`.
- Acceptance:
  - `ban la ai` is not classified as AI accelerator.
  - `Tao chip AI camera APB 100MHz` is classified as design-ready.
  - `APB only but AXI bus` stops in clarification.
  - CPU/bus/peripheral without citation fails policy matrix.
  - Project name never appears as technical citation.

### Phase 3 - Top-Down / Bottom-Up Agent1 Council Integration
- Feed `normalized_requirement` and `canonical_intent` into Agent1 council.
- Add Principal Charter before middle/leaf execution.
- Keep bounded parallel leaf calls and deterministic trace ordering.
- Add expected call-count accounting.
- Acceptance:
  - Normal design-ready run produces 46 Codex calls.
  - Deep planning run produces at least 126 Codex calls.
  - Non-design and clarification-needed inputs do not call 24 leaf experts.
  - Final synthesis cannot release architecture with unresolved conflicts.

### Phase 4 - Clarification Artifacts And UI Behavior
- Add `agent1_requirement_clarification.md`.
- Render `user_response`, `brief_form`, missing fields, examples, consensus/confidence, and policy matrix summary in Studio.
- Disable `Approve OK` unless pause action is `PLAN_REVIEW`.
- Acceptance:
  - Non-design input shows clarification form, not stale architecture diagram.
  - `Approve OK` disabled for `REQUIREMENT_CLARIFICATION`.
  - Request change/plain console text can restart planning with new requirement.

### Phase 5 - Studio Run Isolation And Replay Safety
- Add output-exists detection and modal policy.
- Implement Archive + Fresh Run, Continue Existing, Cancel/Rename.
- Add unique thread IDs per fresh run.
- Add WebSocket replay filtering by `run_id`.
- Add status tailer stale-log prevention.
- Emit `studio_run_manifest.json` and `run_lineage.json`.
- Acceptance:
  - START same project does not silently reuse old checkpoint.
  - Fresh run has clean logs, clean council state, unique thread id.
  - Continue Existing only works with valid manifest.
  - No old `SIGNOFF_READY`, `resume ok`, or Agent2 events appear in fresh run logs.

### Phase 6 - Runtime Budgets, Replay Mode, And Observability
- Add timeout/retry/cancel budget for Intake and council calls.
- Add cost/latency watchdog metrics.
- Add expert replay mode from artifacts for debug.
- Add CLI/test helper for replay.
- Acceptance:
  - STOP during Intake kills process tree and no late Agent2 events appear.
  - Metrics include call count, tokens, latency, estimated cost.
  - Replay mode reproduces hashes without Codex calls.
  - Replay cannot claim signoff if required hashes/versions are missing.

### Phase 7 - Full Regression And Manual UAT
- Run focused Agent1, Studio backend, frontend, and full repo tests.
- Manual UAT in Studio:
  - `Hi, ban la ai`
  - `hi`
  - `Tao chip AI camera APB 100MHz`
  - `ban la ai, tao UART APB controller 50MHz`
  - repeated START same project
- Acceptance:
  - Full pytest green.
  - Frontend smoke/build green.
  - Manual UAT screenshots/logs show correct stop/clarification/design-ready paths.
  - history.md records implementation and verification evidence.

## Key Architecture Changes
- Them `A1.00 Real Codex Intake Council` truoc Agent1 V5.1 council:
  - 5 Codex expert calls bat buoc.
  - Khong co deterministic fallback tao architecture.
  - Neu Codex unavailable/credential invalid thi fail som, khong chay Agent2.
- Intake experts:
  - `LanguageIntentExpert`: phan loai chat thuong, mixed, design request.
  - `RequirementExtractionExpert`: boc tach CPU, bus, protocol, IP/peripheral, frequency, power, node, unknowns.
  - `DomainSoCExpert`: nhan dien domain chip/SoC that, phan biet `AI chip` voi cau tieng Viet `ban la ai`.
  - `CompletenessRiskExpert`: danh gia du dieu kien de lap architecture hay can hoi lai.
  - `UserBriefExpert`: tao cau tra loi va brief form cho input chua thanh requirement.
- Intake output contract:
  - `agent1_intake_router_report.json`
  - `classification`: `DESIGN_READY | DESIGN_NEEDS_CLARIFICATION | NON_DESIGN_CONVERSATION | MIXED`
  - `normalized_requirement`
  - `canonical_intent`
  - `extracted_intent`
  - `missing_fields`
  - `user_response`
  - `brief_form`
  - `codex_evidence`
  - `citations`
  - `conflicts`
  - `contradictions`
  - `consensus_score`
  - `calibrated_confidence`
- Them `A1.00A Intake Adjudicator`:
  - 1 Codex call sau 5 Intake experts.
  - So sanh conflict giua 5 experts.
  - Chon `classification` cuoi cung, `normalized_requirement`, va `missing_fields`.
  - Bat buoc giai thich vi sao khong coi `ban la ai` la AI accelerator.
  - Neu adjudicator khong resolve duoc conflict thi return `DESIGN_NEEDS_CLARIFICATION`, khong chay council duoi.
- Intent canonicalizer:
  - Chuan hoa output ve ontology co dinh: `purpose`, `cpu`, `bus`, `peripheral`, `accelerator`, `clock`, `power`, `node`, `memory`, `interrupts`, `verification_scope`.
  - Downstream Agent1 council chi doc `canonical_intent` + raw citations, khong doc freestyle expert prose lam source of truth.
- Contradiction detector:
  - Bat mau thuan nhu `APB only` + `AXI`, `32-bit CPU` + `RV64`, `no UART` + `UART peripheral`.
  - Neu contradiction chua resolve thi classification thanh `DESIGN_NEEDS_CLARIFICATION`.
- Consensus score:
  - Tinh tu agreement giua 5 Intake experts, adjudicator decision, citation coverage, contradiction count, va missing field count.
  - Default threshold `consensus_score >= 0.75` moi duoc chay council duoi.
  - Duoi threshold thi pause clarification, khong sinh architecture.
- Confidence calibration:
  - `calibrated_confidence` khong chi lay tu Codex.
  - Tinh bang deterministic evidence: citation count, conflict count, missing fields, schema pass/fail, repair pass/fail.
- Evidence policy:
  - Luu digest, decisions, citations, conflicts, token usage, cost estimate, prompt hash, response hash.
  - Khong stream full prompt/response len UI.
  - Secret/API key khong bao gio vao artifact/log.
- Prompt pack versioning:
  - Moi expert evidence phai co `prompt_version`, `schema_version`, `policy_version`, `model`, `endpoint_public`.
  - Tao artifact `agent1_prompt_pack_manifest.json`.
- Strict Codex response policy:
  - Moi expert phai return strict JSON theo schema.
  - Neu JSON parse/validate fail, goi Codex repair 1 lan voi error/schema.
  - Neu repair fail, mark expert `fail` va intake/council khong duoc fallback tao architecture.
  - Luu `parse_status`, `schema_errors`, `repair_attempted`, `repair_pass`.

## Agent 1 Flow
- Non-design input:
  - Chay dung 5 Intake Codex calls.
  - Emit `REQUIREMENT_CLARIFICATION`.
  - Hien `user_response + brief_form`.
  - Khong goi 24 leaf, 7 middle, Principal final, Agent2/3/4/5.
  - Khong ghi `architecture_plan.md`; co the ghi `agent1_requirement_clarification.md`.
- Design-needs-clarification:
  - Chay dung 5 Intake Codex calls.
  - Dung o clarification voi missing fields cu the.
  - Khong sinh CPU/APB fallback.
- Minimum viable requirement gate:
  - `DESIGN_READY` toi thieu phai co `purpose` va it nhat mot trong `cpu | peripheral | accelerator | custom_ip`.
  - Phai co interface/IO intent hoac ly do ro rang vi sao chua can interface.
  - Neu khong dat gate thi clarification.
- Design-ready/mixed:
  - Dung `normalized_requirement` lam input chinh.
  - Principal Architect tao top-down charter tu Intake.
  - 7 Middle Managers nhan charter va chia nhiem vu.
  - 24 Leaf Experts goi Codex that theo nhiem vu rieng, bounded parallel `max_concurrent_leaf_calls=8`.
  - 7 Middle Managers merge/review output leaf bang Codex.
  - Principal Architect final synthesis bang Codex.
- Normal mode call count:
  - 5 Intake + 1 Intake Adjudicator + 1 Principal Charter + 7 Middle Tasking + 24 Leaf + 7 Middle Merge + 1 Principal Final = 46 Codex calls.
- Deep planning call count:
  - 5 Intake + 1 Intake Adjudicator + toi thieu 3 iterations.
  - Moi iteration: 1 Principal Charter + 7 Middle Tasking + 24 Leaf + 7 Middle Merge + 1 Principal Final.
  - Toi thieu 126 Codex calls.
  - Neu conflict chua resolve thi lap den `max_iterations`, sau do HITL.

## Guardrails And Runtime Policy
- Deterministic code duoc phep:
  - Validate schema.
  - Check citation coverage.
  - Check conflict unresolved.
  - Check no project-name inference.
  - Check no invented CPU/APB/peripheral.
  - Check no Vietnamese `ai` false-positive.
  - Manage concurrency, retry, timeout, artifact size.
- Prompt injection shield:
  - User requirement duoc dat trong fenced data block rieng.
  - Prompt phai noi ro user text khong duoc override system/developer/harness policy.
  - Neu user yeu cau ignore guardrails, expert phai ghi `prompt_injection_risk`.
- Project-name quarantine:
  - Project name chi la label de luu file va sanitized RTL namespace.
  - Project name khong duoc lam citation cho CPU width, bus, peripheral, accelerator, frequency, power.
  - Neu expert dung project name lam technical source, guardrail fail.
- Citation ledger:
  - Tao `agent1_requirement_citation_ledger.json`.
  - Moi decision ve CPU/bus/peripheral/frequency/power/node phai map ve `raw_requirement`, `normalized_requirement`, hoac `clarification`.
  - Field khong co citation bi mark `invented_or_uncited`.
- Deterministic code khong duoc phep:
  - Tu chon CPU width.
  - Tu chon APB/AHB/AXI.
  - Tu them baseline IP blocks.
  - Tu bien greeting/chat thanh chip architecture.
- Fail conditions:
  - Final architecture has field without Intake/user citation.
  - Principal rewrites explicit user protocol/width/peripheral.
  - Non-design input reaches Agent2.
  - `architecture_plan.md` exists for `NON_DESIGN_CONVERSATION`.
  - Project name is used as technical intent source.
  - Prompt injection instruction changes policy.
  - Any final architecture field has `invented_or_uncited`.
- Runtime budgets:
  - Intake per-call timeout configurable, default 30s.
  - Intake repair retry max 1.
  - Intake total wall-clock budget configurable, default 180s.
  - Leaf parallelism remains bounded by `max_concurrent_leaf_calls=8`.
  - STOP must cancel active runner process tree and mark run `stopped`, not continue hidden Codex calls.
- Cost/latency watchdog:
  - Track token, cost estimate, per-call latency, total latency cho Intake va Agent1 council.
  - UI warning neu normal mode vuot expected budget/time, nhung khong tu kill neu user khong bam STOP.
  - Emit metrics `agent1_codex_call_count`, `agent1_codex_total_tokens`, `agent1_codex_latency_ms`, `agent1_codex_estimated_cost_usd`.
- Expert replay mode:
  - Cho phep replay Agent1 tu artifacts cu ma khong goi Codex lai.
  - Replay chi dung cho debug/test, khong duoc signoff neu artifact thieu hash/version.
  - Tao CLI/test helper doc ro duong dan artifact replay.
- Policy matrix artifact:
  - Tao `agent1_policy_matrix.json`.
  - Moi guardrail co `policy_id`, `status`, `evidence`, `source_artifact`, `failure_reason`.
  - Dung cho UI/debug thay vi bat user doc log dai.

## Studio Run Safety
- START voi output/project da ton tai:
  - Backend tra `409 OUTPUT_EXISTS` voi output path, file count, last modified, manifest status.
  - UI hien modal:
    - `Continue Existing`
    - `Archive + Fresh Run`
    - `Cancel / Rename Project`
  - Default: `Archive + Fresh Run`.
- Fresh run:
  - Archive output cu vao `outputs/studio_runs/_archive/<project>_<timestamp>`.
  - Tao `thread_id = studio-web-<project>-<run_id>`.
  - Clear frontend `logStore` va `councilStore`.
  - WebSocket replay chi gui event co cung `run_id`.
  - Status tailer khong doc lai `status.log` cu.
  - Ghi `studio_run_manifest.json`.
  - Ghi `run_lineage.json` voi `run_id`, `thread_id`, `parent_run_id`, `start_policy`, `archived_output_path`, `created_at`.
- Continue existing:
  - Chi cho resume neu output co manifest hop le.
  - Dung dung `thread_id` trong manifest.
  - UI phai ghi ro dang tiep tuc run cu.
- Plan Review UI:
  - `Approve OK` chi enabled khi pause action la `PLAN_REVIEW`.
  - Clarification state khong duoc approve nhu plan.
  - Plan Preview khong duoc hien stale `architecture_plan.md`.
  - Voi `NON_DESIGN_CONVERSATION`/clarification, preview `agent1_requirement_clarification.md` thay vi `architecture_plan.md`.
  - UI render clarification form gom: `Chip purpose`, `Bus/protocol`, `CPU/IP/peripheral`, `Clock`, `Power`, `Target flow`.
  - Clarification form hien vi du dien mau: `Generate a 32-bit CPU using APB with UART, 50MHz, 28nm`.
  - UI hien `consensus_score`, `calibrated_confidence`, va policy matrix summary cho Agent1 Intake.

## Test Plan
- Agent1 Intake unit tests:
  - `Hi, ban la ai` => `NON_DESIGN_CONVERSATION`, 5 Codex calls, no CPU/APB, no Agent2.
  - `hi` => clarification, no architecture plan.
  - `ban la ai` => non-design, Vietnamese `ai` not accelerator.
  - `Tao chip AI camera APB 100MHz` => AI technical recognized.
  - `Tao chip tri tue nhan tao APB 100MHz` => AI technical recognized without English `AI`.
  - `ban la ai, tao UART APB controller 50MHz` => `MIXED`, extracts UART APB controller only.
  - Project `cpu32bit_web` + requirement `Hi, ban la ai` => no CPU inference.
  - Prompt injection text does not override guardrails.
  - Intake invalid JSON triggers one repair retry.
  - Intake repair failure blocks architecture.
  - Consensus score duoi threshold blocks council.
  - Contradiction `APB only but AXI bus` blocks council.
  - Canonical intent contains stable ontology keys.
  - Minimum viable requirement gate rejects purpose-only text.
  - Prompt pack manifest records prompt/schema/policy versions.
- Agent1 council tests:
  - Normal design-ready runs expected 46-call topology.
  - Deep planning runs at least 126-call topology.
  - Leaf calls are bounded parallel and sorted deterministically before trace write.
  - Added CPU/APB without citation fails.
  - Unresolved conflict blocks final release.
  - `agent1_requirement_citation_ledger.json` marks every architecture decision cited.
  - Project-name citation causes guardrail failure.
  - `agent1_policy_matrix.json` records pass/fail evidence for guardrails.
  - Expert replay mode reproduces same intake/council hashes without Codex calls.
  - Cost/latency watchdog emits metrics without leaking secrets.
- Studio backend tests:
  - Existing output returns `409 OUTPUT_EXISTS`.
  - Archive + Fresh Run creates unique thread id and archives old output.
  - Continue Existing loads manifest thread id.
  - WebSocket replay filters by run id.
  - Status tailer does not replay stale status log.
  - `run_lineage.json` records archive/fresh/continue policy.
  - STOP during intake kills runner and does not emit late Agent2 events.
- Frontend tests:
  - Existing project modal shows 3 actions.
  - Fresh run clears logs and council store.
  - Approve disabled for clarification.
  - Clarification panel shows `user_response + brief_form`.
  - Plan Preview does not load stale plan.
  - Clarification form renders required fields and no stale architecture diagram.
- Regression commands:
  - `.venv_dv\Scripts\python.exe -m py_compile semiconductor_swarm\agents\agent1_planning\*.py studio\backend\*.py`
  - `.venv_dv\Scripts\python.exe -m pytest -q tests\test_agent1.py`
  - `.venv_dv\Scripts\python.exe -m pytest -q tests\test_agent1_v51_deep_council.py`
  - `.venv_dv\Scripts\python.exe -m pytest -q tests\test_swarm_graph.py tests\test_studio_backend.py`
  - `npm run test --prefix studio\frontend`
  - `npm run build --prefix studio\frontend`
  - `.venv_dv\Scripts\python.exe -m pytest -q`

## Assumptions
- Codex API is mandatory for Agent1 Intake and Agent1 council.
- Non-design input still uses Codex, but stops after Intake to avoid fake architecture.
- Agent2 real Codex expansion remains later; V6.4 focuses input + Agent1 only.
- Evidence default is digest/token/hash, not full prompt/response.
- Fresh run should archive old output instead of destructive delete.
