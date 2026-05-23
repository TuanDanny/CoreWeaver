---
title: SWARM AI STUDIO V6.3 Agent 1 Council Debugger Plan
status: active
owner: studio
type: exec-plan
created: 2026-05-22
source_of_truth: true
---

# SWARM AI STUDIO V6.3 Agent 1 Council Debugger Plan

## Summary
Muc tieu: nang Web Studio de debug Agent 1 Deep Planning ro rang hon. UI phai hien thi duoc toan bo qua trinh 24 leaf experts, 7 middle managers, Principal Architect, Guardrails, va cach tung middle node tong hop output tu node duoi.

Ket qua can dat:
- Nguoi dung thay ro Agent 1 dang hop vong nao.
- Thay tung middle manager nhan leaf nao.
- Thay decision nao duoc accept/reject.
- Thay conflict, feedback, handoff len Principal.
- Thay node nao cham, dot token cao, hoac gay conflict.
- Refresh web khong lam mat council state.
- Log phang van giu, nhung co them view debug chuyen dung.

## Key Changes
- Them structured events cho Agent 1:
  - `agent1_council_iteration`
  - `agent1_council_node`
  - `agent1_council_edge`
  - `agent1_council_artifact`
- Moi node event co schema co dinh:
  - `iteration`
  - `layer`: `leaf | middle | principal | guardrail`
  - `node_id`
  - `title`
  - `status`: `running | pass | fail | conflict`
  - `parent_id`
  - `child_ids`
  - `summary`
  - `accepted_decisions`
  - `rejected_decisions`
  - `conflicts`
  - `feedback_digest`
  - `handoff_digest`
  - `token_usage`
  - `duration_ms`
- Middle manager complete event phai ghi ro:
  - leaf inputs da doc
  - leaf nao pass/fail
  - accepted/rejected decisions
  - domain conflicts
  - feedback tra xuong leaf
  - handoff gui Principal
- Event ordering/dedup:
  - moi council event phai co `iteration`, `node_id`, `layer`, va `phase_seq`.
  - UI dedup bang `event_id` khi co, fallback bang `(iteration, layer, node_id, status, phase_seq)`.
  - reconnect/replay khong duoc tao card trung.

## Web UI Changes
- Sidebar phai thuc dung, khong de cho co:
  - `Project`: focus launch panel, project requirement, mode, output dir, Start/Stop state.
  - `Agents`: show agent timeline + Agent1 council rollup, jump toi Agent 1 Deep Council.
  - `Logs`: focus Real-time Operations Log, filter controls, clear/export visible logs.
  - `Plan Review`: focus Architecture Plan preview, Approve/Request Change, open plan artifact.
  - `Settings`: mo Settings modal, show credential health badge.
  - `Artifacts`: list output artifacts found for current run, open safe preview links.
  - `Debug Bundle`: open/export Agent1 debug bundle manifest.
  - `Future Wiki`: disabled/coming soon with ro ly do `Agent6 not implemented yet`, khong chi la nut chet.
- Sidebar moi item phai co:
  - active state.
  - status badge neu co state lien quan.
  - keyboard focus ro.
  - click behavior that changes visible panel, scroll target, or opens modal.
- Them panel/tab moi: `Agent 1 Deep Council`.
- Layout phai co:
  - Iteration selector: `Iteration 1 / 2 / 3...`
  - Swimlane: `Leaf Experts -> Middle Managers -> Principal -> Guardrails`
  - Middle manager cards noi toi leaf experts bang chips/edges.
  - Click middle card mo `Node Detail`.
- `Node Detail` hien thi:
  - Inputs From Leaf Experts
  - Accepted Decisions
  - Rejected Decisions
  - Conflicts
  - Feedback To Leaf
  - Handoff To Principal
  - Token / Duration
  - Open Trace Artifact
- `Node Detail` cua middle manager them input/output diff:
  - `Leaf Input Summary`
  - `Middle Accepted`
  - `Middle Rejected`
  - `Middle Modified/Merged`
  - `Unresolved Conflicts`
  - `Feedback To Leaf`
  - `Handoff To Principal`
- Them conflict-first navigation:
  - toggle `Show Conflicts Only`.
  - conflict list click vao dung node.
  - badge `critical/noncritical` tren node cards.
- Them heatmap:
  - token cao: amber border.
  - latency cao: violet/cyan pulse nhe.
  - fail/conflict: red border.
  - pass nhanh: green/cyan.
- Them `Export Agent1 Debug Bundle`:
  - gom plan, leaf trace, middle trace, principal trace, conflict matrix, guardrail report.
  - export bang link artifact/download API neu co, hoac tao manifest artifact de user mo trong output folder.
- Log panel them filter:
  - `All`
  - `Agent1`
  - `Leaf`
  - `Middle`
  - `Principal`
  - `Errors`
- Real-time Operations Log phai resize duoc:
  - user keo splitter de tang/giam do rong log panel sang trai/phai.
  - khi log rong hon, Agent Timeline co the bi thu hep toi min width.
  - min width de khong vo layout: Agent Timeline 220px, Log 420px, Right Debug Panel 360px.
  - luu width vao localStorage de mo lai van giu layout.
  - resize khong duoc lam re-render toan bo log 2000 dong moi pixel; dung CSS grid column variable + pointer events co debounce/requestAnimationFrame.

## Implementation Changes
- Agent1:
  - sua `deep_expert_council.py` de emit council events song song voi `agent_action` hien tai.
  - khong emit raw prompt/response dai.
  - digest array toi da 20 item.
  - moi text field toi da 512 chars.
- Backend:
  - them council events vao critical event set de khong bi drop.
  - giu sanitizer 64KB/event.
  - current-state/hydration phai include council replay snapshot hoac endpoint rieng de UI khoi phuc sau refresh.
  - artifact preview/download phai tiep tuc bi sandbox trong `outputs/`.
- Frontend:
  - them council event types.
  - them `councilStore.ts` dung `useSyncExternalStore`.
  - batch flush 150ms.
  - max 3000 council events/run.
  - them `Agent1CouncilPanel`.
  - tich hop tab phai: `Plan Preview | Agent 1 Council | Node Detail | Console`.
  - refactor sidebar thanh navigation state thuc, khong phai static buttons.
  - moi sidebar item phai route toi view/panel/action ro rang.
  - item chua co backend phai disabled + `Coming soon` tooltip/status.
  - `councilStore` phai hydrate tu WebSocket replay va fallback artifacts.
  - neu WebSocket miss event hoac user refresh, UI doc artifacts trace de rebuild council graph.
  - card render phai virtual/batched, khong render lai toan bo UI moi event.
  - node detail khong hien raw prompt/response; chi hien digest va link artifact.
  - main work area dung resizable grid/splitter cho Agent Timeline, Log, va Right Debug Panel.
  - splitter chi cap nhat CSS variable/layout width; khong push log rows vao React state khi dang drag.
- History:
  - cap nhat `history.md` dau va cuoi luot implement.

## Test Plan
- Agent1 tests:
  - leaf emits start/complete node events.
  - middle emits start/complete node events.
  - middle event co `child_ids`, accepted/rejected/conflicts/feedback/handoff.
  - principal emits synthesis node events.
  - guardrail emits pass/fail node events.
  - event payload khong vuot 64KB.
- Frontend tests:
  - smoke co `Agent 1 Deep Council`.
  - smoke co `Node Detail`.
  - smoke co `Inputs From Leaf Experts`.
  - smoke co `Show Conflicts Only`.
  - smoke co `Export Agent1 Debug Bundle`.
  - smoke co sidebar items thuc dung: `Project`, `Agents`, `Logs`, `Plan Review`, `Settings`, `Artifacts`, `Debug Bundle`, `Future Wiki`.
  - smoke khong cho sidebar item rong: moi item phai co handler/action hoac disabled coming-soon reason.
  - smoke co `councilStore` va `useSyncExternalStore`.
  - khong hien thi raw prompt/response.
- Hydration/fallback tests:
  - reconnect/replay khong duplicate node cards.
  - refresh page rebuild duoc council view tu replay/current-state.
  - artifact fallback rebuild duoc middle-manager graph khi replay thieu event.
- UX/debug tests:
  - click middle node hien input/output diff dung leaf ids.
  - conflict-first navigation nhay dung node.
  - token/latency heatmap class dung voi metric cao.
  - debug bundle manifest chi tro toi artifact trong sandbox.
  - keo splitter thay doi do rong log panel va persist width qua reload.
  - resize khong duplicate log rows va khong reset scroll lock.
  - sidebar `Logs` focus log panel, `Plan Review` focus plan tab, `Settings` mo modal, `Future Wiki` disabled co reason.
- Integration:
  - deep planning mock co 3 iterations.
  - moi iteration co 24 leaf, 7 middle, 1 principal, 1 guardrail.
  - click middle node hien thi dung assigned leaf ids.
- Commands:
  - `.venv_dv\Scripts\python.exe -m pytest -q tests\test_agent1_v51_deep_council.py`
  - `.venv_dv\Scripts\python.exe -m pytest -q tests\test_studio_backend.py`
  - `npm run test --prefix studio\frontend`
  - `npm run build --prefix studio\frontend`
  - `.venv_dv\Scripts\python.exe -m pytest -q`

## Assumptions
- Full raw trace van nam trong artifacts:
  - `agent1_leaf_expert_trace.jsonl`
  - `agent1_middle_manager_trace.jsonl`
  - `agent1_principal_trace.jsonl`
- WebSocket chi stream debug digest, khong stream raw LLM prompt/response.
- Khong doi graph contract.
- Khong doi Agent2/3/4/5 UI ngoai phan log filter chung.
- V6.3 uu tien debug Agent1; export bundle co the la manifest/link artifacts, chua can zip file neu backend download API chua co.
