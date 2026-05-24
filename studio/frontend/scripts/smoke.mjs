import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../src/main.tsx", import.meta.url), "utf8");
const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const logStore = readFileSync(new URL("../src/logStore.ts", import.meta.url), "utf8");
const councilStore = readFileSync(new URL("../src/councilStore.ts", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");

if (!html.includes("SWARM AI STUDIO V6.9")) {
  throw new Error("Browser title must match V6.9 shell");
}
for (const needle of ["getCurrentState", "new WebSocket", "Connected", "Reconnecting", "Disconnected", "root@swarm:~$", "Deep Planning"]) {
  if (!app.includes(needle)) throw new Error(`Missing UI contract: ${needle}`);
}
for (const needle of ["SWARM AI STUDIO V6.9", "Requirement command deck", "local AI hints", "mode-segment", "target://", "mission-button start", "mission-button stop"]) {
  if (!app.includes(needle)) throw new Error(`Missing V6.7 launch UI contract: ${needle}`);
}
for (const needle of ["maxLength={2000}", "stageAttachments", "deleteStagedAttachment", "liveInputRun", "attachmentDraftId", "AttachmentRef", "Drop `.md`, `.pdf`, `.png`, `.jpg`, `.webp` here", "queued to Agent1 checkpoint"]) {
  if (!app.includes(needle) && !api.includes(needle)) throw new Error(`Missing V6.7 input/live contract: ${needle}`);
}
for (const needle of ["@fontsource/plus-jakarta-sans", "@fontsource/inter", "attachment-summary"]) {
  if (!app.includes(needle) && !api.includes(needle)) throw new Error(`Missing V6.7.1 UI polish contract: ${needle}`);
}
for (const needle of ["/api/attachments/stage", "/live-input", "FormData"]) {
  if (!api.includes(needle)) throw new Error(`Missing V6.7 API contract: ${needle}`);
}
for (const needle of ["Pipeline", "pipeline-shell", "stage-node", "stageVisualState", "Planning", "RTL", "Formal", "HITL", "DV", "Physical", "Signoff"]) {
  if (!app.includes(needle)) throw new Error(`Missing V6.6 pipeline contract: ${needle}`);
}
for (const needle of ["LaunchHint", "HintAction", "buildLaunchHints", "appendRequirementHint", "APB", "UART", "32-bit CPU", "Formal-first", "cocotb", "FPGA-safe"]) {
  if (!app.includes(needle)) throw new Error(`Missing local smart hint contract: ${needle}`);
}
for (const needle of ["Testing auth via chat/completions...", "Cooldown...", "PASS", "FAIL", "Credential Reference", "Server-side secret", "Auth health", "python -m studio.backend.secret_admin set-owner-key", "Browser never sees raw secrets"]) {
  if (!app.includes(needle)) throw new Error(`Missing settings connection contract: ${needle}`);
}
if (app.includes("Connection test implementation is added in Phase 7")) {
  throw new Error("Settings connection test still contains Phase 7 placeholder");
}
if (app.includes('type="password"') || /\bapiKey\b/.test(app) || /\bapiKey\b/.test(api)) {
  throw new Error("Frontend must not expose raw API key input or payload contract");
}
if (!api.includes("apiKeyRef")) {
  throw new Error("Frontend must use credential references for connection tests and runs");
}
const saveSettingsBlock = api.slice(api.indexOf("export function saveSettings"), api.indexOf("export function testConnection"));
if (saveSettingsBlock.includes("JSON.stringify(payload)") || !saveSettingsBlock.includes("JSON.stringify(serverPayload)")) {
  throw new Error("saveSettings must strip UI-only credentialRefs and credentialHealth before POST");
}
if (app.includes('state.status === "done" ? "done" : "stopped"') || !app.includes('base.status === "failed"') || !app.includes("Number(event.returncode")) {
  throw new Error("process_exit reducer must preserve failed state and mark nonzero exits failed");
}
for (const needle of ["base.status === \"paused\"", "closeRunningStages", "closeRunningAgents"]) {
  if (!app.includes(needle)) throw new Error(`Missing terminal state cleanup contract: ${needle}`);
}
for (const needle of ['eventRunId && !state.run_id', 'run.run_id || "current"', 'STOP requested for']) {
  if (!app.includes(needle)) throw new Error(`Missing robust stop/run_id race handling: ${needle}`);
}
for (const needle of ["seeded.last_event_id", "eventId <= seeded.last_event_id", "last_event_id: eventId"]) {
  if (!app.includes(needle)) throw new Error(`Missing stale WebSocket replay guard: ${needle}`);
}
for (const needle of ['base.status === "stopping"', 'base.status === "stopped"', 'status: "stopped", pid: null']) {
  if (!app.includes(needle)) throw new Error(`Missing STOP-intent process_exit preservation: ${needle}`);
}
if (!api.includes('stopRun(runId = "current")')) {
  throw new Error("STOP must support current-run fallback when UI has not hydrated run_id yet");
}
for (const needle of ["START failed", "STOP failed", "Approve failed", "SAVE FAIL"]) {
  if (!app.includes(needle)) throw new Error(`Missing visible error handling: ${needle}`);
}
if (!app.includes("run.run_id && run.pause") || !app.includes("change: text")) {
  throw new Error("Console must treat plain text during pause as a change request");
}
for (const needle of ["canApprove", "Available only during PLAN_REVIEW", "Approve is disabled until Agent 1 creates an architecture plan."]) {
  if (!app.includes(needle)) throw new Error(`Missing clarification-safe approval UI: ${needle}`);
}
for (const needle of ["Agent 1 Deep Council", "Node Detail", "Inputs From Leaf Experts", "Show Conflicts Only", "Export Agent1 Debug Bundle", "Middle Modified/Merged"]) {
  if (!app.includes(needle)) throw new Error(`Missing Agent1 council debugger UI: ${needle}`);
}
for (const needle of ["trace-debug-shell", "trace-debug-body", "trace-event-card", "trace-scrollbar", "grid-rows-[auto_minmax(0,1fr)]"]) {
  if (!app.includes(needle) && !readFileSync(new URL("../src/styles.css", import.meta.url), "utf8").includes(needle)) throw new Error(`Missing Trace Debug layout fix: ${needle}`);
}
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
for (const needle of ["grid-template-columns: minmax(0, 1fr)", "inline-size: 100%", ".trace-debug-shell > *"]) {
  if (!styles.includes(needle)) throw new Error(`Missing Trace Debug overflow guard: ${needle}`);
}
for (const needle of ["@keyframes pipeline-scan", "@keyframes stage-pulse", "@keyframes button-sheen", "@keyframes field-focus-glow", ".pipeline-shell", ".stage-node.running", ".launch-panel-grid", ".command-deck", ".tech-tab"]) {
  if (!styles.includes(needle)) throw new Error(`Missing V6.6 UI style contract: ${needle}`);
}
if (app.includes("grid-rows-[112px_1fr]")) {
  throw new Error("Trace Debug must not use fixed 112px header that overlaps filters/body");
}
const sidebarBlock = app.slice(app.indexOf("function Sidebar"), app.indexOf("function ProjectWorkspace"));
for (const needle of ["Project", "Debug", "Setting", "Account", "About"]) {
  if (!sidebarBlock.includes(`"${needle}"`)) throw new Error(`Missing V6.9 sidebar workspace item: ${needle}`);
}
for (const forbidden of ["Job Queue", "Agents", "Logs", "Plan Review", "Artifacts", "Debug Bundle", "Future Wiki"]) {
  if (sidebarBlock.includes(`"${forbidden}"`)) throw new Error(`Old sidebar item still present: ${forbidden}`);
}
for (const needle of ["ProjectWorkspace", "PlanReviewWorkspace", "Open full screen plan", "SettingWorkspace", "AccountWorkspace", "AboutWorkspace"]) {
  if (!app.includes(needle)) throw new Error(`Missing V6.9 workspace contract: ${needle}`);
}
for (const needle of ["Operations Log", "Trace Debug", "Job Queue", "Agent 1 Council", "Node Detail", "Console", "Artifacts / Debug Bundle"]) {
  if (!app.includes(needle)) throw new Error(`Missing V6.9 debug workspace tab/content: ${needle}`);
}
for (const needle of ["Agent Job Queue", "Create Agent 1 Plan Draft", "Create Agent 2 RTL Draft", "Export Debug Bundle", "Queue Full Swarm Run", "cancelAgentJob", "listJobs", "createAgentJob"]) {
  if (!app.includes(needle) && !api.includes(needle)) throw new Error(`Missing job queue UI/API contract: ${needle}`);
}
for (const needle of ["live_job_events", "JOB.", "\"Jobs\""]) {
  if (!app.includes(needle) && !readFileSync(new URL("../src/traceStore.ts", import.meta.url), "utf8").includes(needle)) throw new Error(`Missing job trace debug contract: ${needle}`);
}
for (const needle of ["getRuntime", "runtime_events", "Runtime", "Invariants", "Model Calls", "Queue / Recovery", "runtime-metrics-grid", "Copy correlation id", "Copy artifact path", "Jump related event", "Copy event JSON", "findTraceEntryByCorrelation"]) {
  if (!app.includes(needle) && !api.includes(needle) && !readFileSync(new URL("../src/traceStore.ts", import.meta.url), "utf8").includes(needle) && !styles.includes(needle)) throw new Error(`Missing V6.8 runtime trace debug contract: ${needle}`);
}
for (const needle of ["Existing Output Detected", "Archive + Fresh Run", "Continue Existing", "Rename Output", "OUTPUT_EXISTS", "startPolicy"]) {
  if (!app.includes(needle) && !api.includes(needle)) throw new Error(`Missing output policy contract: ${needle}`);
}
for (const needle of ["swarm.rightWidth", "requestAnimationFrame", "splitter"]) {
  if (!app.includes(needle)) throw new Error(`Missing resizable log layout contract: ${needle}`);
}
if (app.includes("swarm.timelineWidth") || app.includes("<AgentTimeline") || app.includes("Resize Agent Timeline / Log")) {
  throw new Error("Agent Timeline must be removed from main screen");
}
if (!app.includes("minmax(0,1fr)") || !app.includes("minmax(280px,min(${props.rightWidth}px,42vw))")) {
  throw new Error("Resizable main grid must allow Log/Trace panels to shrink without horizontal overflow");
}
for (const needle of ["grid-template-columns: repeat(auto-fit, minmax(190px, 1fr))", "max-height: 54px", "overflow-y: auto", "Plus Jakarta Sans"]) {
  if (!styles.includes(needle)) throw new Error(`Missing V6.7.1 attachment/font style contract: ${needle}`);
}
for (const needle of ["FLUSH_MS = 150", "MAX_LOGS = 2000", "useSyncExternalStore", "seenEventIdSet"]) {
  if (!logStore.includes(needle)) throw new Error(`Missing log performance contract: ${needle}`);
}
for (const needle of ["FLUSH_MS = 150", "MAX_COUNCIL_EVENTS = 3000", "useSyncExternalStore", "hydrateFromTraceText", "eventDedupeKey"]) {
  if (!councilStore.includes(needle)) throw new Error(`Missing council store contract: ${needle}`);
}
console.log("frontend smoke contracts passed");
