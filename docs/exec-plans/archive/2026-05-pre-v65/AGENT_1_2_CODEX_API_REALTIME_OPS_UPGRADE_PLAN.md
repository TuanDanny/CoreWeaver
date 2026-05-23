---
title: Agent 1/2 Codex API Realtime Ops Upgrade Plan
status: active
owner: agent-platform
type: exec-plan
last_reviewed: 2026-05-21
source_of_truth: true
---

# Agent 1/2 Codex API Realtime Ops Upgrade Plan

## Summary
Goal: make Agent 1 and Agent 2 API usage visible, enforce Agent 2 hybrid Codex participation, and stream real Agent 2 subagent activity into SWARM AI STUDIO without fake chat or log-regex control.

Current findings:
- Agent 1 already calls Codex API through OpenAI-compatible `/chat/completions`.
- Agent 1 evidence exists in `agent1_codex_evidence.json` with model, base URL, latency, prompt hash, and response hash.
- Agent 2 does **not** call Codex API today.
- Agent 2 uses deterministic orchestrator + 53 subagents + static validators.
- Agent 2 trace exists in `agent2_subgraph_trace.json`, but runner/UI currently show only coarse phase-level events.

Approved direction:
- Agent 2 uses **mandatory hybrid Codex**.
- Codex plans/reviews/suggests repairs; deterministic RTL generator, static validators, and tool gates remain final authority.
- UI realtime log streams **each Agent 2 subagent** as capped structured JSONL events, while Agent cards show stable stage-level rollups to avoid visual overload.

## Key Changes
- Add Agent 2 Codex API support:
  - Add Agent 2 config using shared OpenAI-compatible config.
  - Add fallback env `AGENT2_CODEX_API_KEY`.
  - Add Agent 2 client with prompt/response hashes, latency, retry count, model, base URL, and redacted auth evidence.
  - Agent 2 Codex unavailable blocks/pause-fails Agent 2; no silent deterministic pass in Studio flow.

- Add Agent 2 hybrid roles:
  - Pre-generation Codex RTL implementation plan.
  - Post-generation Codex RTL review summary.
  - Repair suggestion package when deterministic review fails.
  - Deterministic validators remain blocking gate.
  - Codex repair output must be patch-only; full RTL rewrites are forbidden.
  - Codex review output must cite concrete rules/patterns/contracts for every finding.
  - Codex repair prompts receive AST-aware context snippets, not full large RTL files.
  - Patch application gets one automatic self-healing retry before HITL.

- Add artifacts:
  - `agent2_codex_plan.md`
  - `agent2_codex_evidence.json`
  - `agent2_ai_review.json`
  - `agent2_ai_repair_suggestions.json`
  - `agent2_ai_contract.json`
  - Route these under `rtl/reports/`; never pollute `rtl/` root.

- Improve realtime UI observability:
  - Emit `agent_action` for Agent 1 Codex start/done/unavailable.
  - Emit `agent_action` for every Agent 2 subagent `A2.01` through `A2.56`.
  - Roll Agent 2 subagent events into six stable UI stages: Intake, Planning, IP Writers, Integration, Quality Gate, Repair.
  - Emit `agent_discussion` for short Codex review summaries.
  - Emit `agent_handoff` after Agent 2 contracts are ready.
  - Emit token/cost metrics for Agent 1 and Agent 2 Codex calls.
  - Keep event payloads capped; full artifacts travel by path only.

## Mandatory Safety Policies
### Surgical Patch-Only Repair
- `agent2_ai_repair_suggestions.json` must never contain full replacement RTL files.
- Allowed repair formats:
  - Unified diff with file path and minimal hunk.
  - JSON patch-style operation with file, line/range, action, old text hash, and new text.
- A deterministic Python patch applier validates every suggestion before applying:
  - target file exists and is under Agent 2 RTL output scope,
  - old text/hash matches current file,
  - affected line count is below the configured cap,
  - patch touches only allowlisted RTL files,
  - patch does not introduce forbidden RTL tokens,
  - patch is followed by deterministic validators.
- If patch validation fails, Agent 2 emits a blocking finding and requests HITL or deterministic repair; Codex must not rewrite the whole file.

### AST-Aware Context Snippets
- Codex repair calls must not receive full large RTL files by default.
- A deterministic context slicer builds minimal repair context from parsed RTL structure:
  - target file path,
  - module name,
  - affected line range,
  - nearest `always_ff`, `always_comb`, `assign`, instance, or register declaration block,
  - cited deterministic finding,
  - old text hash,
  - small surrounding window capped by line count.
- Default context caps:
  - target block max `80` lines,
  - surrounding context max `20` lines before/after,
  - total repair prompt RTL snippet max `140` lines.
- If AST parsing cannot locate a block, fall back to line-window slicing around the deterministic finding; never send the entire file unless the file is below the configured cap.
- The slicer records `agent2_context_slices.json` with file, line range, hash, parser mode, and reason.

### Self-Healing Patch Retry
- Patch application is allowed one automatic retry before HITL.
- Retry flow:
  - apply patch in dry-run mode,
  - if line/hash/text mismatch occurs, build a compact failure report,
  - send Codex the original patch, expected old text/hash, actual old text/hash, and same context slice,
  - require a corrected patch-only response,
  - dry-run and apply corrected patch only if validation passes.
- Retry count is capped at `1` per patch suggestion.
- A second failure becomes a blocking finding and routes to deterministic repair or HITL.
- Retry artifacts:
  - `agent2_patch_apply_report.json`
  - `agent2_patch_retry_report.json`
  - retry records are linked to the original `suggested_patch_id`.

### Explainable AI Review Citations
- Every Codex review finding in `agent2_ai_review.json` must include:
  - `cited_rule`
  - `source`
  - `source_path`
  - `evidence_snippet`
  - `affected_file`
  - `severity`
  - `suggested_patch_id` when a repair is proposed.
- Valid citation sources:
  - Agent 2 prompt rule IDs,
  - golden pattern manifest entries,
  - APB/contract validator IDs,
  - deterministic lint/review finding IDs,
  - test names or schema IDs.
- Findings without citations are downgraded to non-blocking commentary unless a deterministic validator independently confirms them.

### Stage-Level UI Rollups
- Agent 2 card/timeline shows six rollup stages, not 56 flashing card updates:
  - Intake
  - Planning
  - IP Writers
  - Integration
  - Quality Gate
  - Repair
- The realtime log still shows each `A2.xx` subagent event under the `agent2` filter.
- Rollup state is derived from structured event fields, never raw log text.
- Header/card shows compact counters: passed, failed, warnings, current subagent, artifacts.

### Token And Cost Telemetry
- Agent 1 and Agent 2 Codex evidence must include token usage when returned by the API:
  - `prompt_tokens`
  - `completion_tokens`
  - `total_tokens`
  - optional `cached_tokens` if available.
- If the endpoint does not return usage, set usage fields to `null` and mark `usage_status="not_reported_by_endpoint"`.
- Add a local pricing config with default editable model rates; never hardcode billing truth as permanent facts.
- Emit metrics:
  - `codex_prompt_tokens`
  - `codex_completion_tokens`
  - `codex_total_tokens`
  - `codex_estimated_cost_usd`
  - `codex_burn_rate_tokens_per_min`
- UI shows a compact Burn Rate chip for the current project/run.
- Cost is explicitly labeled as estimate unless exact billing data is available.

## Implementation Roadmap
### Phase 0 - Evidence Freeze
- Document exact current behavior:
  - Agent 1 Codex works and has evidence.
  - Agent 2 has no API client/call path.
  - Agent 2 has 53 trace entries but UI only shows coarse events.
- Acceptance:
  - Add current-state notes to `history.md`.
  - Existing tests remain green.

### Phase 1 - Agent 2 Codex Client
- Add shared Agent 2 LLM config and OpenAI-compatible client.
- Mirror Agent 1 evidence style, but name schemas `agent2_codex_*`.
- Ensure no API key leaks in evidence, logs, UI, or artifacts.
- Capture token usage and estimated cost when API response includes usage.
- Acceptance:
  - Mocked success returns content + evidence.
  - Mocked failure raises `Agent2CodexUnavailable`.
  - Evidence includes base URL, model, hashes, timestamp, retry count, latency.
  - Evidence includes token usage fields or explicit `usage_status`.

### Phase 2 - Hybrid Agent 2 Orchestrator
- Call Codex before deterministic generation to create RTL implementation plan.
- Call Codex after deterministic generation to review generated RTL at summary level.
- Require Codex review findings to include citations; reject/cap uncited findings.
- Require Codex repair suggestions to be surgical patch-only.
- Use AST-aware context snippets for repair prompts.
- Allow exactly one self-healing patch retry on patch apply mismatch.
- Keep deterministic generation and validators as final gate.
- If Codex fails in Studio/default hybrid mode, pause/fail before claiming Agent 2 pass.
- Acceptance:
  - Agent 2 cannot silently skip Codex in hybrid mode.
  - Deterministic validators still catch bad RTL even if Codex says pass.
  - Full-file RTL rewrites from Codex are rejected.
  - Uncited Codex review findings cannot become blocking without deterministic confirmation.
  - Large RTL files are not sent wholesale to Codex repair calls.
  - Patch retry succeeds or produces a clear blocking report after one retry.
  - New artifacts route to `rtl/reports/`.

### Phase 3 - Realtime Agent 2 Subagent Events
- Add event/status sink to Agent 2 orchestrator.
- Emit one capped event per subagent result:
  - `agent=agent2`
  - `subagent_id`
  - `name`
  - `status`
  - `summary`
  - `finding_count`
  - `artifact_count`
- Add `rollup_stage` to each Agent 2 event using the six-stage mapping.
- Runner maps sink records into JSONL `agent_action`.
- Acceptance:
  - UI Agent2 filter shows subagent-by-subagent progress.
  - Agent 2 timeline/card updates by rollup stage, not by flashing every subagent as a top-level card state.
  - No event exceeds JSONL cap.
  - No raw RTL/report body is streamed.

### Phase 4 - Agent 1 API Visibility
- Emit Agent 1 Codex lifecycle events:
  - request started
  - response received
  - evidence artifact ready
  - unavailable/fail
- UI shows model, latency, and evidence path in logs.
- Acceptance:
  - Agent 1 API call is visible before Plan Review.
  - API key remains redacted.

### Phase 5 - UI Evidence Surfacing
- Keep Agent Cards compact.
- Agent 2 card shows rollup stage, latest subagent, pass/fail/warning count, and artifact count.
- Realtime log `agent2` filter shows all subagent events.
- Collaboration log shows Codex review summaries and Agent2 handoffs.
- Header shows current run token/cost Burn Rate chip.
- Acceptance:
  - User can see Agent 2 “working” during RTL stage.
  - UI does not flicker through 56 card states; rollup stages remain readable.
  - Burn Rate chip updates from structured token/cost metrics.
  - Log volume remains bounded by V5.1 ring buffer and render cap.

### Phase 6 - Regression And UAT
- Run mocked API tests, graph tests, docs health, and app smoke.
- Run a Studio flow with mock/real Codex endpoint and inspect UI.
- Acceptance:
  - Agent 1 evidence visible.
  - Agent 2 Codex evidence visible.
  - Agent 1/2 token telemetry visible when endpoint reports usage.
  - Agent 2 subagent stream visible.
  - Existing V5.1 hard-kill, smart-scroll, and JSONL caps still pass.

## Test Plan
- Unit:
  - `test_agent2_codex_client_success`
  - `test_agent2_codex_client_failure_blocks_hybrid`
  - `test_agent2_codex_evidence_redacts_api_key`
  - `test_agent2_hybrid_keeps_deterministic_gate_authoritative`
  - `test_agent2_codex_artifacts_route_to_rtl_reports`
  - `test_agent2_ai_review_requires_cited_rule`
  - `test_agent2_ai_repair_rejects_full_file_rewrite`
  - `test_agent2_ai_repair_applies_minimal_patch_only_when_old_hash_matches`
  - `test_agent2_context_slicer_extracts_always_block_not_full_file`
  - `test_agent2_patch_retry_corrects_hash_mismatch_once`
  - `test_agent2_patch_retry_second_failure_routes_hitl`
  - `test_agent2_codex_usage_telemetry_present_or_not_reported`
  - `test_agent2_rollup_stage_mapping_covers_all_subagents`

- Runner/UI:
  - Mock Agent 2 sink records and assert JSONL `agent_action` events for `A2.xx`.
  - Assert UI Agent2 filter renders subagent events.
  - Assert Agent 2 card/timeline renders rollup stages instead of flashing all 56 subagents.
  - Assert large Codex review text is truncated and full content is artifact-by-path.
  - Assert Burn Rate chip updates from `metric` events and labels cost as estimate.

- Integration:
  - `python -m py_compile app/main_window.py app/swarm_runner.py`
  - `python -m pytest -q tests/test_agent1.py tests/test_agent2.py tests/test_swarm_graph.py`
  - `python -m pytest -q tests/test_docs_health.py tests/test_prompt_contracts.py`

## Assumptions
- Studio/default flow should require Agent 2 hybrid Codex evidence.
- Codex is advisory for RTL generation; deterministic validators remain final authority.
- Codex repair suggestions are patch-only; full RTL regeneration is forbidden for repair.
- Codex repair prompts use AST-aware snippets where possible; full-file context is an explicit small-file fallback only.
- Patch auto-retry is capped at one retry.
- Codex review findings require citations before they can affect signoff decisions.
- Token/cost telemetry is best-effort because local OpenAI-compatible endpoints may omit usage fields.
- No raw full RTL, full report, prompt body, response body, or API key over JSONL stdout.
- Agent 2 subagent stream uses structured events, not regex text parsing.
- No implementation starts until this plan is approved.
