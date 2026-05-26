import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import * as Dialog from "@radix-ui/react-dialog";
import { Activity, AlertTriangle, CheckCircle2, Cpu, Info, Paperclip, Rocket, Settings, Square, Trash2, Upload, User, Wifi, WifiOff } from "lucide-react";
import "@fontsource/plus-jakarta-sans/400.css";
import "@fontsource/plus-jakarta-sans/500.css";
import "@fontsource/plus-jakarta-sans/600.css";
import "@fontsource/plus-jakarta-sans/700.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "./styles.css";
import { cancelAgentJob, createAgentJob, deleteStagedAttachment, getCurrentState, getHealth, getRuntime, getSettings, listJobs, liveInputRun, previewArtifact, resumeRun, saveSettings, stageAttachments, startRun, stopRun, testConnection, WS_BASE } from "./api";
import { councilStore, useCouncil } from "./councilStore";
import { logStore, useLogs } from "./logStore";
import { traceStore, useTrace } from "./traceStore";
import type { TraceEntry } from "./traceStore";
import type { AgentJob, AttachmentRef, ConnectionState, CouncilNode, DebugIssue, JobType, PlanningMode, RunState, SettingsPayload, StageName, StartPolicy, StudioEvent } from "./types";

const stages: StageName[] = ["planning", "rtl", "formal", "hitl", "dv", "physical", "signoff"];
const stageLabels: Record<StageName, string> = { planning: "Planning", rtl: "RTL", formal: "Formal", hitl: "HITL", dv: "DV", physical: "Physical", signoff: "Signoff" };
const agentLabels: Record<string, string> = { agent1: "Architect", agent2: "RTL", agent3: "DV", agent4: "Physical", agent5: "Formal", agent6: "Wiki" };
type SidebarView = "project" | "debug" | "setting" | "account" | "about";
type DebugTab = "log" | "signoff" | "issues" | "flow" | "trace" | "jobs" | "cluster" | "council" | "node" | "console" | "artifacts";
type LogFilter = "All" | "Agent1" | "Leaf" | "Middle" | "Principal" | "Errors";
type StartPayload = { requirement: string; project_name: string; output_dir: string; planning_mode: PlanningMode; checkpoint_db: string; apiKeyRef: string; startPolicy?: StartPolicy; attachmentDraftId?: string; attachmentIds?: string[] };
type HintAction = { kind: "appendRequirement"; value: string } | { kind: "setMode"; value: PlanningMode };
type LaunchHint = { label: string; detail: string; action: HintAction; accent: "cyan" | "green" | "amber" | "blue" };
type StageVisualState = "idle" | "running" | "pass" | "fail" | "paused" | "stopped";
type BlockedReason = { severity: string; source: string; code: string; message: string; artifact?: string };
type BackendHealthState = "checking" | "ok" | "error";
type HydrationState = "idle" | "hydrating" | "ready" | "error";
const traceArtifacts = ["agent1_leaf_expert_trace.jsonl", "agent1_middle_manager_trace.jsonl", "agent1_principal_trace.jsonl"];
const debugTraceArtifacts = [
  "studio_flow_trace.jsonl",
  "runner_process_trace.jsonl",
  "agent1_intake_trace.jsonl",
  "agent1_llm_trace.jsonl",
  "agent1_canonical_trace.jsonl",
  "agent1_defaults_trace.jsonl",
  "agent1_council_trace.jsonl",
  "agent1_guardrail_trace.jsonl",
  "agent1_final_decision_trace.jsonl",
  "agent1_state_snapshots.jsonl",
  "agent1_artifact_lineage.jsonl",
  "agent1_completion_trace.jsonl",
  "live_input_trace.jsonl",
];

function traceCorrelationId(entry: TraceEntry): string {
  return String(entry.payload.correlation_id ?? entry.payload.job_id ?? entry.id ?? "");
}

function findTraceEntryByCorrelation(entries: TraceEntry[], correlationId: string): TraceEntry | null {
  if (!correlationId) return null;
  return entries.find((entry) => entry.id === correlationId || traceCorrelationId(entry) === correlationId) ?? null;
}

function findRelatedTraceEntry(entries: TraceEntry[], selected: TraceEntry): TraceEntry | null {
  const correlationId = traceCorrelationId(selected);
  if (correlationId) {
    const paired = entries.find((entry) => entry.id !== selected.id && traceCorrelationId(entry) === correlationId);
    if (paired) return paired;
  }
  const sameNode = entries.find((entry) => entry.id !== selected.id && entry.node_id === selected.node_id && entry.trace_file === selected.trace_file);
  if (sameNode) return sameNode;
  return entries.find((entry) => entry.id !== selected.id && entry.agent === selected.agent && entry.phase === selected.phase) ?? null;
}

const emptyRun: RunState = {
  run_id: "",
  status: "idle",
  pid: null,
  project_name: "cpu32bit_web",
  requirement: "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
  output_dir: "D:/AI/AgentAI/outputs/studio_runs/cpu32bit_web",
  planning_mode: "normal",
  apiKeyRef: "owner",
  stages: { planning: "idle", rtl: "idle", formal: "idle", hitl: "idle", dv: "idle", physical: "idle", signoff: "idle" },
  agents: Object.fromEntries(Object.keys(agentLabels).map((key) => [key, { status: key === "agent6" ? "reserved" : "idle", action: "Waiting", evidence: 0 }])) as RunState["agents"],
  metrics: {},
  pause: null,
  current_plan_path: null,
  last_event_id: 0,
  runtime: null,
};

function debugIssueFlowDefaults(code: string): { flow_segment: string; source_layer: string } {
  if (code.startsWith("attachment_")) return { flow_segment: "attachment_staging", source_layer: "frontend" };
  if (code.startsWith("settings_")) return { flow_segment: "settings_preflight", source_layer: "frontend" };
  if (code.startsWith("websocket_") || code.includes("hydrate") || code === "current_state_load_failed") return { flow_segment: "websocket", source_layer: "frontend" };
  if (code.startsWith("job_")) return { flow_segment: "job_queue", source_layer: "frontend" };
  if (code.startsWith("start_")) return { flow_segment: "start_request", source_layer: "frontend" };
  if (code.startsWith("stop_")) return { flow_segment: "runner_process", source_layer: "frontend" };
  if (code.startsWith("approve_") || code.startsWith("plan_preview_")) return { flow_segment: "plan_review", source_layer: "frontend" };
  if (code.startsWith("console_") || code.startsWith("unknown_console_")) return { flow_segment: "live_input", source_layer: "frontend" };
  return { flow_segment: "", source_layer: "frontend" };
}

function eventBelongsToRun(event: StudioEvent, runId: string): boolean {
  const eventRunId = typeof event.run_id === "string" ? event.run_id : "";
  return !runId || !eventRunId || eventRunId === runId;
}

function issueBelongsToRun(issue: DebugIssue, runId: string): boolean {
  const issueRunId = String(issue.run_id ?? "");
  return !runId || !issueRunId || issueRunId === runId;
}

function issuesForRun(issues: DebugIssue[], runId: string): DebugIssue[] {
  return issues.filter((issue) => issueBelongsToRun(issue, runId));
}

function runClassifier(run: RunState): string {
  if (!run.run_id) return "NO_ACTIVE_RUN";
  if (run.status === "running" || run.status === "stopping") return "RUNNING";
  if (run.status === "paused") return "PAUSED_FOR_HITL";
  if (run.status === "failed") return run.runtime?.recoveryReport ? "FAILED_WITH_RECOVERY" : "FAILED";
  if (run.status === "stopped") return run.runtime?.signoff?.state === "PARTIAL" || run.runtime?.recoveryReport ? "STOPPED_WITH_PARTIAL" : "STOPPED_CLEANLY";
  if (run.status === "done") return "DONE";
  return String(run.status || "IDLE").toUpperCase();
}

function modelCallElapsedMs(call: Record<string, unknown>): number {
  const duration = Number(call.duration_ms ?? 0);
  if (duration > 0) return duration;
  const updatedAt = Date.parse(String(call.updated_at ?? ""));
  if (Number.isFinite(updatedAt) && updatedAt > 0) return Math.max(0, Date.now() - updatedAt);
  return 0;
}

function closeRunningStages(stages: RunState["stages"], status: "stopped" | "failed") {
  return Object.fromEntries(Object.entries(stages).map(([stage, value]) => [stage, ["running", "starting"].includes(String(value)) ? status : value])) as RunState["stages"];
}

function closeRunningAgents(agents: RunState["agents"], status: "stopped" | "failed") {
  return Object.fromEntries(Object.entries(agents).map(([agent, value]) => {
    const agentStatus = String(value?.status ?? "");
    return [agent, ["running", "starting"].includes(agentStatus) ? { ...value, status, action: status } : value];
  })) as RunState["agents"];
}

function isTerminalRuntimeFailure(event: StudioEvent): boolean {
  const eventType = String(event.event_type ?? "");
  return ["watchdog_timeout", "runtime_error", "run_failed", "runner_failed"].includes(eventType);
}

function reduceEvent(state: RunState, event: StudioEvent): RunState {
  if (event.type === "ping") return state;
  const eventRunId = typeof event.run_id === "string" ? event.run_id : "";
  if (eventRunId && state.run_id && eventRunId !== state.run_id) return state;
  const eventId = Number(event.event_id ?? 0);
  const seeded = eventRunId && !state.run_id ? { ...state, run_id: eventRunId } : state;
  if (eventId > 0 && seeded.last_event_id > 0 && eventId <= seeded.last_event_id) return seeded;
  const base = eventId > 0 ? { ...seeded, last_event_id: eventId } : seeded;
  if (event.type === "runtime_event") {
    if (isTerminalRuntimeFailure(event)) {
      if (["done", "stopped"].includes(base.status)) return base;
      return { ...base, status: "failed", pause: null, current_plan_path: null, stages: closeRunningStages(base.stages, "failed"), agents: closeRunningAgents(base.agents, "failed") };
    }
    if (event.event_type === "runtime_recovered") return { ...base, status: "recovered" };
    return base;
  }
  if (event.type === "stage" && event.stage) return { ...base, stages: { ...base.stages, [event.stage]: String(event.status ?? "idle") } };
  if (event.type === "agent_action" && event.agent) {
    return { ...base, agents: { ...base.agents, [event.agent]: { ...(base.agents[event.agent] ?? {}), status: String(event.status ?? "info"), action: String(event.action ?? "activity") } } };
  }
  if (event.type === "metric" && event.name) return { ...base, metrics: { ...base.metrics, [String(event.name)]: event.value } };
  if (event.type === "pause") {
    const action = String(event.action_required ?? "");
    return { ...base, status: "paused", pause: event, current_plan_path: action === "PLAN_REVIEW" ? String(event.plan_path ?? base.current_plan_path ?? "") : null };
  }
  if (event.type === "process_start") return { ...base, status: "running", pid: Number(event.pid) || base.pid };
  if (event.type === "process_exit") {
    if (base.status === "done") return { ...base, pid: null };
    if (base.status === "failed") return { ...base, pid: null };
    if (base.status === "stopping" || base.status === "stopped") return { ...base, status: "stopped", pid: null, pause: null, current_plan_path: null, stages: closeRunningStages(base.stages, "stopped"), agents: closeRunningAgents(base.agents, "stopped") };
    if (base.status === "paused" && Number(event.returncode ?? 0) === 0) return { ...base, pid: null };
    const terminal = Number(event.returncode ?? 0) === 0 ? "stopped" : "failed";
    return { ...base, status: terminal, pid: null, pause: null, current_plan_path: null, stages: closeRunningStages(base.stages, terminal), agents: closeRunningAgents(base.agents, terminal) };
  }
  if (event.type === "done") return { ...base, status: "done", pause: null, current_plan_path: null };
  if (event.type === "error") {
    if (base.status === "stopping" || base.status === "stopped") return { ...base, status: "stopped", pause: null, current_plan_path: null, stages: closeRunningStages(base.stages, "stopped"), agents: closeRunningAgents(base.agents, "stopped") };
    return { ...base, status: "failed", pause: null, current_plan_path: null, stages: closeRunningStages(base.stages, "failed"), agents: closeRunningAgents(base.agents, "failed") };
  }
  return base;
}

function App() {
  const [run, setRun] = useState<RunState>(emptyRun);
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("Disconnected");
  const [backendHealth, setBackendHealth] = useState<BackendHealthState>("checking");
  const [hydrationState, setHydrationState] = useState<HydrationState>("idle");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [requirement, setRequirement] = useState(emptyRun.requirement);
  const [projectName, setProjectName] = useState(emptyRun.project_name);
  const [outputDir, setOutputDir] = useState(emptyRun.output_dir);
  const [planningMode, setPlanningMode] = useState<PlanningMode>("normal");
  const [attachmentDraftId, setAttachmentDraftId] = useState("");
  const [attachments, setAttachments] = useState<AttachmentRef[]>([]);
  const [attachmentBusy, setAttachmentBusy] = useState(false);
  const [planText, setPlanText] = useState("Plan preview will appear here when Agent 1 pauses for review.");
  const [command, setCommand] = useState("");
  const [newLogs, setNewLogs] = useState(0);
  const [activeView, setActiveView] = useState<SidebarView>("project");
  const [debugTab, setDebugTab] = useState<DebugTab>("log");
  const [logFilter, setLogFilter] = useState<LogFilter>("All");
  const [planFullscreenOpen, setPlanFullscreenOpen] = useState(false);
  const [outputConflict, setOutputConflict] = useState<{ message: string; payload: StartPayload } | null>(null);
  const [jobs, setJobs] = useState<AgentJob[]>([]);
  const [queueHealth, setQueueHealth] = useState<Record<string, unknown>>({});
  const [debugIssues, setDebugIssues] = useState<DebugIssue[]>([]);
  const [rightWidth, setRightWidth] = useState(() => Number(localStorage.getItem("swarm.rightWidth") ?? 420));
  const logPanelRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);
  const attachmentBusyRef = useRef(false);

  const appendDebugIssue = useCallback((issue: Partial<DebugIssue> & { code: string; message: string }) => {
    const flowDefaults = debugIssueFlowDefaults(issue.code);
    const full: DebugIssue = {
      type: "debug_issue",
      schema_version: "swarm.debug_issue.v1",
      severity: issue.severity ?? "warning",
      source: issue.source ?? "frontend",
      code: issue.code,
      message: issue.message,
      details: issue.details ?? {},
      run_id: issue.run_id ?? run.run_id,
      revision_id: issue.revision_id ?? "",
      artifact_ref: issue.artifact_ref ?? "",
      node_id: issue.node_id ?? "",
      timestamp: issue.timestamp ?? new Date().toISOString(),
      flow_segment: issue.flow_segment ?? flowDefaults.flow_segment,
      source_layer: issue.source_layer ?? flowDefaults.source_layer,
      span_id: issue.span_id ?? "",
      parent_span_id: issue.parent_span_id ?? "",
      group_id: issue.group_id ?? "",
      model_call_id: issue.model_call_id ?? "",
    };
    setDebugIssues((items) => [...items, full].slice(-2000));
    logStore.appendEvent(full);
  }, [run.run_id]);

  const clearWorkspaceRun = useCallback(() => {
    if (!["stopped", "failed", "done"].includes(run.status)) return;
    setRun(emptyRun);
    setDebugIssues([]);
    traceStore.clear();
    councilStore.clear();
    setHydrationState("idle");
    setPlanText("Plan preview will appear here when Agent 1 pauses for review.");
    logStore.appendEvent({ type: "log", level: "info", message: "Cleared terminal run from workspace view.", agent: "system" });
  }, [run.status]);

  useEffect(() => {
    let cancelled = false;
    const poll = () => {
      getHealth()
        .then((health) => {
          if (cancelled) return;
          setBackendHealth(String(health.status ?? "") === "ok" ? "ok" : "error");
        })
        .catch((error) => {
          if (cancelled) return;
          setBackendHealth("error");
          appendDebugIssue({ severity: "warning", source: "frontend", code: "backend_health_failed", message: `Backend health failed: ${String(error)}`, details: { error: String(error) } });
        });
    };
    poll();
    const id = window.setInterval(poll, 10000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [appendDebugIssue]);

  const refreshJobs = useCallback(async () => {
    try {
      const payload = await listJobs();
      setJobs(payload.jobs);
      setQueueHealth(payload.queueHealth);
    } catch (error) {
      logStore.appendEvent({ type: "error", level: "error", message: `Job list failed: ${String(error)}`, agent: "system" });
      appendDebugIssue({ severity: "error", source: "frontend", code: "job_list_failed", message: `Job list failed: ${String(error)}`, details: { error: String(error) } });
    }
  }, [appendDebugIssue]);

  useEffect(() => {
    getSettings().then((value) => {
      setSettings(value);
      setOutputDir(`${value.output_root.replaceAll("\\", "/")}/${projectName}`);
    }).catch((error) => {
      setConnection("Disconnected");
      appendDebugIssue({ severity: "warning", source: "frontend", code: "settings_load_failed", message: `Settings load failed: ${String(error)}`, details: { error: String(error) } });
    });
    getCurrentState().then((state) => {
      if (state.run_id) {
        setRun(state);
        if (state.runtime) traceStore.hydrateRuntimeBundle({ manifest: state.runtime.manifest ?? null, recentEvents: [], recoveryReport: state.runtime.recoveryReport ?? null, invariantReport: state.runtime.invariantReport ?? null, replayReport: state.runtime.replayReport ?? null, flowCoverage: state.runtime.flowCoverage ?? null, debugSummary: state.runtime.debugSummary ?? null, signoff: state.runtime.signoff ?? null });
        if (state.runtime?.debugIssues?.length) setDebugIssues(issuesForRun(state.runtime.debugIssues, state.run_id));
      }
    }).catch((error) => appendDebugIssue({ severity: "warning", source: "frontend", code: "current_state_load_failed", message: `Current state load failed: ${String(error)}`, details: { error: String(error) } }));
    refreshJobs();
  }, [appendDebugIssue, refreshJobs]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 500;
    const connect = () => {
      setConnection("Reconnecting");
      ws = new WebSocket(`${WS_BASE}/ws/runs/${run.run_id || "current"}`);
      ws.onopen = () => {
        retry = 500;
        setConnection("Connected");
      };
      ws.onmessage = (message) => {
        const event = JSON.parse(message.data) as StudioEvent;
        if (event.type === "ping") {
          setConnection("Connected");
          return;
        }
        if (!eventBelongsToRun(event, run.run_id)) return;
        logStore.appendEvent(event);
        if (event.type === "debug_issue") setDebugIssues((items) => [...items, event as DebugIssue].slice(-2000));
        councilStore.appendEvent(event);
        traceStore.appendEvent(event);
        if (String(event.type).startsWith("job_")) refreshJobs();
        setRun((previous) => reduceEvent(previous, event));
      };
      ws.onclose = () => {
        if (closed) return;
        setConnection("Reconnecting");
        appendDebugIssue({ severity: "warning", source: "frontend", code: "websocket_disconnected", message: "WebSocket disconnected; reconnecting", details: { run_id: run.run_id || "current" } });
        window.setTimeout(connect, retry);
        retry = Math.min(retry * 1.5, 5000);
      };
      ws.onerror = () => {
        setConnection("Disconnected");
        appendDebugIssue({ severity: "warning", source: "frontend", code: "websocket_error", message: "WebSocket error", details: { run_id: run.run_id || "current" } });
      };
    };
    connect();
    return () => {
      closed = true;
      ws?.close();
    };
  }, [appendDebugIssue, run.run_id, refreshJobs]);

  useEffect(() => {
    const actionRequired = String(run.pause?.action_required ?? "");
    const pausePayload = typeof run.pause?.payload === "object" && run.pause?.payload !== null ? run.pause.payload as Record<string, unknown> : {};
    const pausePreviewPath = actionRequired && actionRequired !== "PLAN_REVIEW"
      ? String(run.pause?.plan_path ?? run.pause?.artifact_path ?? pausePayload.artifact_path ?? pausePayload.plan_path ?? "")
      : "";
    const previewPath = run.current_plan_path || pausePreviewPath;
    if (!previewPath) {
      setPlanText(actionRequired && actionRequired !== "PLAN_REVIEW"
        ? `Plan preview unavailable.\nCurrent pause requires ${actionRequired}; submit a change/follow-up before approval.`
        : "Plan preview will appear here when Agent 1 pauses for review.");
      return;
    }
    previewArtifact(previewPath).then((preview) => setPlanText(preview.text)).catch((error) => {
      setPlanText(`Plan preview unavailable:\n${String(error)}`);
      appendDebugIssue({ severity: "error", source: "frontend", code: "plan_preview_failed", message: `Plan preview failed: ${String(error)}`, artifact_ref: previewPath, details: { error: String(error), path: previewPath } });
    });
  }, [appendDebugIssue, run.current_plan_path, run.pause]);

  useEffect(() => {
    if (!run.run_id) return;
    let cancelled = false;
    const runId = run.run_id;
    setHydrationState("hydrating");
    getRuntime(run.run_id)
      .then((bundle) => {
        if (cancelled) return;
        traceStore.hydrateRuntimeBundle(bundle);
        if (bundle.debugIssues?.length) setDebugIssues((items) => [...items, ...issuesForRun(bundle.debugIssues ?? [], runId)].slice(-2000));
        setHydrationState("ready");
      })
      .catch((error) => {
        if (cancelled) return;
        setHydrationState("error");
        traceStore.appendEvent({ type: "runtime_event", event_type: "runtime_error", status: "failed", node_id: "RUNTIME.API", phase: "studio", agent: "system", message: `Runtime hydrate failed: ${String(error)}`, run_id: run.run_id });
        appendDebugIssue({ severity: "error", source: "frontend", code: "runtime_hydrate_failed", message: `Runtime hydrate failed: ${String(error)}`, details: { error: String(error), run_id: run.run_id } });
      });
    return () => {
      cancelled = true;
    };
  }, [appendDebugIssue, run.run_id, run.status]);

  useEffect(() => {
    if (!run.output_dir) return;
    const base = `${run.output_dir.replaceAll("\\", "/")}/reports`;
    Promise.allSettled(traceArtifacts.map((name) => previewArtifact(`${base}/${name}`))).then((results) => {
      for (const result of results) {
        if (result.status === "fulfilled") councilStore.hydrateFromTraceText(result.value.text);
      }
    });
    const traceBase = `${base}/traces`;
    Promise.allSettled(debugTraceArtifacts.map((name) => previewArtifact(`${traceBase}/${name}`).then((preview) => ({ name, text: preview.text })))).then((results) => {
      for (const result of results) {
        if (result.status === "fulfilled") traceStore.hydrateJsonl(result.value.text, result.value.name);
      }
    });
  }, [run.output_dir, run.status]);

  const tokenTotal = run.metrics.codex_total_tokens === undefined ? null : Number(run.metrics.codex_total_tokens);
  const cost = run.metrics.codex_estimated_cost_usd === undefined ? null : Number(run.metrics.codex_estimated_cost_usd);
  const activeCredentialHealth = settings?.credentialHealth?.[settings.activeKeyRef] ?? "unchecked";
  const startBlockedReason = requirement.trim().length === 0
    ? "Requirement is required before Start."
    : requirement.length > 2000
      ? "Requirement exceeds 2000 characters."
      : activeCredentialHealth === "missing"
    ? "Credential owner missing. Update server key before Start."
    : activeCredentialHealth === "invalid"
      ? "Credential owner invalid. Test Connection or update server key before Start."
      : "";

  const navigate = useCallback((view: SidebarView) => {
    setActiveView(view);
    if (view === "debug") refreshJobs();
  }, [refreshJobs]);

  const startResize = useCallback((startX: number) => {
    const startRight = rightWidth;
    let frame = 0;
    const onMove = (event: PointerEvent) => {
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const dx = event.clientX - startX;
        const next = Math.max(320, Math.min(760, startRight - dx));
        setRightWidth(next);
        localStorage.setItem("swarm.rightWidth", String(next));
      });
    };
    const onUp = () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp, { once: true });
  }, [rightWidth]);

  const beginAttachmentRequest = useCallback(() => {
    if (attachmentBusyRef.current) return false;
    attachmentBusyRef.current = true;
    setAttachmentBusy(true);
    return true;
  }, []);

  const endAttachmentRequest = useCallback(() => {
    attachmentBusyRef.current = false;
    setAttachmentBusy(false);
  }, []);

  const uploadFiles = useCallback(async (files: File[]) => {
    if (!files.length || !beginAttachmentRequest()) return;
    try {
      const staged = await stageAttachments(files, attachmentDraftId);
      setAttachmentDraftId(staged.draftId);
      setAttachments(staged.attachments);
      logStore.appendEvent({ type: "attachment_staged", level: "info", agent: "system", message: `${files.length} file(s) staged for Agent1 input` });
    } catch (error) {
      logStore.appendEvent({ type: "attachment_rejected", level: "error", agent: "system", message: `Attachment upload failed: ${String(error)}` });
      appendDebugIssue({ severity: "error", source: "frontend", code: "attachment_upload_failed", message: `Attachment upload failed: ${String(error)}`, details: { error: String(error), file_count: files.length } });
    } finally {
      endAttachmentRequest();
    }
  }, [appendDebugIssue, attachmentDraftId, beginAttachmentRequest, endAttachmentRequest]);

  const removeAttachment = useCallback(async (attachmentId: string) => {
    if (!attachmentDraftId || !beginAttachmentRequest()) return;
    try {
      const staged = await deleteStagedAttachment(attachmentDraftId, attachmentId);
      setAttachments(staged.attachments);
      setAttachmentDraftId(staged.draftId);
    } catch (error) {
      logStore.appendEvent({ type: "attachment_rejected", level: "error", agent: "system", message: `Attachment remove failed: ${String(error)}` });
      appendDebugIssue({ severity: "error", source: "frontend", code: "attachment_delete_failed", message: `Attachment remove failed: ${String(error)}`, details: { error: String(error), attachmentId } });
    } finally {
      endAttachmentRequest();
    }
  }, [appendDebugIssue, attachmentDraftId, beginAttachmentRequest, endAttachmentRequest]);

  const doStart = useCallback(async (payload: StartPayload, clearStores = true) => {
    try {
      if (clearStores) {
        logStore.clear();
        councilStore.clear();
        traceStore.clear();
        setDebugIssues([]);
        setHydrationState("idle");
        setPlanText("Plan preview will appear here when Agent 1 pauses for review.");
      }
      const state = await startRun(payload);
      setRun(state);
      logStore.appendEvent({ type: "log", level: "info", message: `run started ${state.run_id}`, agent: "system" });
      refreshJobs();
    } catch (error) {
      const message = String(error);
      if (message.includes("OUTPUT_EXISTS:")) {
        setOutputConflict({ message, payload });
        logStore.appendEvent({ type: "log", level: "warning", message: "Output directory already contains files. Choose run policy.", agent: "system" });
        return;
      }
      logStore.appendEvent({ type: "error", level: "error", message: `START failed: ${message}`, agent: "system" });
      appendDebugIssue({ severity: "error", source: "frontend", code: "start_failed", message: `START failed: ${message}`, details: { error: message, payload } });
      setRun((previous) => ({ ...previous, status: "failed" }));
      getSettings().then(setSettings).catch((settingsError) => appendDebugIssue({ severity: "warning", source: "frontend", code: "settings_refresh_after_start_failed", message: `Settings refresh failed after START error: ${String(settingsError)}`, details: { error: String(settingsError) } }));
    }
  }, [appendDebugIssue, refreshJobs]);

  const launch = useCallback(async () => {
    await doStart({
      requirement,
      project_name: projectName,
      output_dir: outputDir,
      planning_mode: planningMode,
      checkpoint_db: settings?.checkpoint_db ?? "",
      apiKeyRef: settings?.activeKeyRef ?? "owner",
      attachmentDraftId,
      attachmentIds: attachments.map((item) => item.id),
    });
  }, [requirement, projectName, outputDir, planningMode, settings, doStart, attachmentDraftId, attachments]);

  const stop = useCallback(async () => {
    const targetRunId = run.run_id || "current";
    try {
      logStore.appendEvent({ type: "log", level: "warning", message: `STOP requested for ${targetRunId}`, agent: "system" });
      setRun((previous) => ({ ...previous, status: previous.status === "idle" ? "idle" : "stopping" }));
      setRun(await stopRun(targetRunId));
    } catch (error) {
      logStore.appendEvent({ type: "error", level: "error", message: `STOP failed: ${String(error)}`, agent: "system" });
      appendDebugIssue({ severity: "error", source: "frontend", code: "stop_failed", message: `STOP failed: ${String(error)}`, details: { error: String(error), run_id: targetRunId } });
    }
  }, [appendDebugIssue, run.run_id]);

  const submitJob = useCallback(async (type: JobType) => {
    try {
      const job = await createAgentJob({
        type,
        requirement,
        project_name: projectName,
        output_dir: outputDir,
        planning_mode: planningMode,
        checkpoint_db: settings?.checkpoint_db ?? "",
        apiKeyRef: settings?.activeKeyRef ?? "owner",
      });
      logStore.appendEvent({ type: "job_queued", level: "info", message: `Job queued ${job.type} ${job.job_id}`, agent: "system", job_id: job.job_id });
      setActiveView("debug");
      setDebugTab("jobs");
      await refreshJobs();
    } catch (error) {
      logStore.appendEvent({ type: "error", level: "error", message: `Job submit failed: ${String(error)}`, agent: "system" });
      appendDebugIssue({ severity: "error", source: "frontend", code: "job_submit_failed", message: `Job submit failed: ${String(error)}`, details: { error: String(error), type } });
    }
  }, [appendDebugIssue, requirement, projectName, outputDir, planningMode, settings, refreshJobs]);

  const cancelJob = useCallback(async (jobId: string) => {
    try {
      const job = await cancelAgentJob(jobId);
      logStore.appendEvent({ type: "job_cancelled", level: "warning", message: `Job cancelled ${job.job_id}`, agent: "system", job_id: job.job_id });
      await refreshJobs();
    } catch (error) {
      logStore.appendEvent({ type: "error", level: "error", message: `Job cancel failed: ${String(error)}`, agent: "system" });
      appendDebugIssue({ severity: "error", source: "frontend", code: "job_cancel_failed", message: `Job cancel failed: ${String(error)}`, details: { error: String(error), jobId } });
    }
  }, [appendDebugIssue, refreshJobs]);

  const approve = useCallback(async () => {
    if (!run.run_id) return;
    const action = String(run.pause?.action_required ?? "");
    if (!["PLAN_REVIEW", "HUMAN_REVIEW"].includes(action)) {
      logStore.appendEvent({ type: "log", level: "warning", message: "Approve is available only during plan review or human RTL/Formal review.", agent: "console" });
      appendDebugIssue({ severity: "warning", source: "frontend", code: "approve_blocked", message: "Approve blocked because current pause is not approveable.", details: { status: run.status, pause: run.pause } });
      return;
    }
    try {
      setRun(await resumeRun(run.run_id, { notes: action === "HUMAN_REVIEW" ? "approved after web review" : "ok", resume_action: action, planning_mode: planningMode, apiKeyRef: settings?.activeKeyRef ?? "owner" }));
    } catch (error) {
      logStore.appendEvent({ type: "error", level: "error", message: `Approve failed: ${String(error)}`, agent: "system" });
      appendDebugIssue({ severity: "error", source: "frontend", code: "approve_failed", message: `Approve failed: ${String(error)}`, details: { error: String(error), run_id: run.run_id } });
    }
  }, [appendDebugIssue, run.run_id, run.status, run.pause, planningMode, settings]);

  const handleCommand = useCallback(async () => {
    const text = command.trim();
    setCommand("");
    if (!text) return;
    logStore.appendEvent({ type: "log", level: "console", message: `> ${text}`, agent: "console" });
    try {
      if (text === "ok") await approve();
      else if (text === "stop") await stop();
      else if (text === "clear") logStore.clear();
      else if (run.run_id && run.status === "running") {
        const message = text.startsWith("change ") ? text.slice(7).trim() : text;
        const result = await liveInputRun(run.run_id, { message, clientMessageId: `${Date.now()}-${Math.random().toString(16).slice(2)}` });
        logStore.appendEvent({ type: "live_input_ack", level: "info", message: `queued to Agent1 checkpoint ${result.message_id}`, agent: "console", message_id: result.message_id });
      }
      else if (text.startsWith("change ") && run.run_id) setRun(await resumeRun(run.run_id, { notes: text.slice(7), change: text.slice(7), resume_action: String(run.pause?.action_required ?? ""), planning_mode: planningMode, apiKeyRef: settings?.activeKeyRef ?? "owner" }));
      else if (run.run_id && run.pause) setRun(await resumeRun(run.run_id, { notes: text, change: text, resume_action: String(run.pause?.action_required ?? ""), planning_mode: planningMode, apiKeyRef: settings?.activeKeyRef ?? "owner" }));
      else {
        logStore.appendEvent({ type: "log", level: "warning", message: `unknown command: ${text}`, agent: "console" });
        appendDebugIssue({ severity: "warning", source: "frontend", code: "unknown_console_command", message: `unknown command: ${text}`, details: { command: text } });
      }
    } catch (error) {
      logStore.appendEvent({ type: "error", level: "error", message: `Console command failed: ${String(error)}`, agent: "console" });
      appendDebugIssue({ severity: "error", source: "frontend", code: "console_command_failed", message: `Console command failed: ${String(error)}`, details: { error: String(error), command: text } });
    }
  }, [appendDebugIssue, command, approve, stop, run.run_id, run.status, run.pause, planningMode, settings]);

  const approveAction = String(run.pause?.action_required ?? "");
  const canApprovePlan = run.status === "paused" && (approveAction === "HUMAN_REVIEW" || (approveAction === "PLAN_REVIEW" && Boolean(run.current_plan_path)));
  const activeRunMode = (run.planning_mode || planningMode) as PlanningMode;

  return (
    <div className="min-h-screen overflow-hidden bg-cosmic text-slate-100 font-ui">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_10%,rgba(53,214,255,.18),transparent_30%),radial-gradient(circle_at_80%_0%,rgba(47,128,255,.16),transparent_28%)]" />
      <div className="relative grid h-screen grid-rows-[42px_1fr_26px]">
        <TopBar connection={connection} backendHealth={backendHealth} hydrationState={hydrationState} activeRun={Boolean(run.run_id)} />
        <div className="grid min-h-0" style={{ gridTemplateColumns: sidebarOpen ? "230px 1fr" : "64px 1fr" }}>
          <Sidebar open={sidebarOpen} activeView={activeView} credentialHealth={activeCredentialHealth} onToggle={() => setSidebarOpen((value) => !value)} onNavigate={navigate} />
          <main className="h-full min-h-0 p-3">
            {activeView === "project" && <ProjectWorkspace requirement={requirement} setRequirement={setRequirement} projectName={projectName} setProjectName={setProjectName} outputDir={outputDir} setOutputDir={setOutputDir} planningMode={planningMode} setPlanningMode={setPlanningMode} attachments={attachments} attachmentBusy={attachmentBusy} onFilesDropped={uploadFiles} onRemoveAttachment={removeAttachment} onStart={launch} onStop={stop} running={run.status === "running"} startBlockedReason={startBlockedReason} stages={run.stages} planText={planText} command={command} setCommand={setCommand} onCommand={handleCommand} onApprove={approve} canApprove={canApprovePlan} fullscreenOpen={planFullscreenOpen} setFullscreenOpen={setPlanFullscreenOpen} run={run} debugIssues={debugIssues} backendHealth={backendHealth} hydrationState={hydrationState} onClearRun={clearWorkspaceRun} onOpenDebugTab={(tab) => { setActiveView("debug"); setDebugTab(tab); }} />}
            {activeView === "debug" && <DebugWorkspace activeTab={debugTab} setActiveTab={setDebugTab} panelRef={logPanelRef} atBottomRef={atBottomRef} newLogs={newLogs} setNewLogs={setNewLogs} filter={logFilter} setFilter={setLogFilter} rightWidth={rightWidth} onResizeStart={startResize} command={command} setCommand={setCommand} onCommand={handleCommand} onApprove={approve} run={run} canApprove={canApprovePlan} jobs={jobs} queueHealth={queueHealth} debugIssues={debugIssues} onSubmitJob={submitJob} onCancelJob={cancelJob} />}
            {activeView === "setting" && <SettingWorkspace settings={settings} setSettings={setSettings} onDebugIssue={appendDebugIssue} />}
            {activeView === "account" && <AccountWorkspace settings={settings} activeHealth={activeCredentialHealth} connection={connection} />}
            {activeView === "about" && <AboutWorkspace />}
          </main>
        </div>
        <StatusBar run={run} connection={connection} tokenTotal={tokenTotal} cost={cost} mode={activeRunMode} newLogs={newLogs} />
      </div>
      <OutputConflictDialog
        conflict={outputConflict}
        onCancel={() => setOutputConflict(null)}
        onFresh={async () => {
          if (!outputConflict) return;
          const payload = { ...outputConflict.payload, startPolicy: "fresh" as const };
          setOutputConflict(null);
          await doStart(payload);
        }}
        onContinue={async () => {
          if (!outputConflict) return;
          const payload = { ...outputConflict.payload, startPolicy: "continue" as const };
          setOutputConflict(null);
          await doStart(payload, false);
        }}
        onRename={async () => {
          if (!outputConflict) return;
          const renamed = `${outputConflict.payload.output_dir}_${new Date().toISOString().replace(/[:.]/g, "-")}`;
          setOutputDir(renamed);
          const payload = { ...outputConflict.payload, output_dir: renamed, startPolicy: "auto" as const };
          setOutputConflict(null);
          await doStart(payload);
        }}
      />
    </div>
  );
}

function TopBar({ connection, backendHealth, hydrationState, activeRun }: { connection: ConnectionState; backendHealth: BackendHealthState; hydrationState: HydrationState; activeRun: boolean }) {
  return <header className="glass flex items-center justify-between border-b border-cyanGlow/20 px-4">
    <div className="flex items-center gap-3 text-sm"><Cpu className="h-5 w-5 text-cyanGlow" /><span className="font-bold tracking-wide">SWARM AI STUDIO V7.3</span><span className="text-slate-400">Workspace Mission Control</span></div>
    <div className="flex items-center gap-2">
      <span className={`chip ${backendHealth === "error" ? "danger" : ""}`}>Backend {backendHealth}</span>
      <span className="chip">{connection === "Connected" ? <Wifi className="h-4 w-4" /> : <WifiOff className="h-4 w-4" />} WS {connection}</span>
      <span className="chip">Hydrate {hydrationState}</span>
      <span className="chip">Run {activeRun ? "active" : "none"}</span>
    </div>
  </header>;
}

function Sidebar({ open, activeView, credentialHealth, onToggle, onNavigate }: { open: boolean; activeView: SidebarView; credentialHealth: string; onToggle: () => void; onNavigate: (view: SidebarView) => void }) {
  const items: Array<[React.ElementType, string, SidebarView, string]> = [
    [Rocket, "Project", "project", "Launch"],
    [Activity, "Debug", "debug", "Trace"],
    [Settings, "Setting", "setting", credentialHealth],
    [User, "Account", "account", "Local"],
    [Info, "About", "about", "V7.3"],
  ];
  return <aside className="glass sidebar-rail min-h-0 border-r border-cyanGlow/20 p-3 transition-all">
    <button className="btn-secondary mb-4 w-full" aria-label={open ? "Collapse" : "Expand"} title={open ? "Collapse" : "Expand sidebar"} onClick={onToggle}>{open ? "Collapse" : ">>"}</button>
    <div className="space-y-2">{items.map(([Icon, label, view, badge]) => <button className={`sidebar-item workspace-nav ${activeView === view ? "active" : ""}`} key={view} title={`${label}: ${badge}`} onClick={() => onNavigate(view)}><Icon className="h-4 w-4" />{open && <><span className="flex-1">{label}</span><span className="text-[10px] text-cyanGlow">{badge}</span></>}</button>)}</div>
  </aside>;
}

function ProjectWorkspace(props: { requirement: string; setRequirement: (v: string) => void; projectName: string; setProjectName: (v: string) => void; outputDir: string; setOutputDir: (v: string) => void; planningMode: PlanningMode; setPlanningMode: (v: PlanningMode) => void; attachments: AttachmentRef[]; attachmentBusy: boolean; onFilesDropped: (files: File[]) => void; onRemoveAttachment: (id: string) => void; onStart: () => void; onStop: () => void; running: boolean; startBlockedReason: string; stages: RunState["stages"]; planText: string; command: string; setCommand: (v: string) => void; onCommand: () => void; onApprove: () => void; canApprove: boolean; fullscreenOpen: boolean; setFullscreenOpen: (v: boolean) => void; run: RunState; debugIssues: DebugIssue[]; backendHealth: BackendHealthState; hydrationState: HydrationState; onClearRun: () => void; onOpenDebugTab: (tab: DebugTab) => void }) {
  return <div className="project-workspace grid h-full min-h-0 grid-rows-[auto_252px_76px_auto_1fr] gap-3">
    <RunContextBanner run={props.run} backendHealth={props.backendHealth} hydrationState={props.hydrationState} onOpenPlan={() => props.setFullscreenOpen(true)} onClearRun={props.onClearRun} onOpenDebugTab={props.onOpenDebugTab} />
    <LaunchPanel requirement={props.requirement} setRequirement={props.setRequirement} projectName={props.projectName} setProjectName={props.setProjectName} outputDir={props.outputDir} setOutputDir={props.setOutputDir} planningMode={props.planningMode} setPlanningMode={props.setPlanningMode} attachments={props.attachments} attachmentBusy={props.attachmentBusy} onFilesDropped={props.onFilesDropped} onRemoveAttachment={props.onRemoveAttachment} onStart={props.onStart} onStop={props.onStop} running={props.running} startBlockedReason={props.startBlockedReason} />
    <Pipeline stages={props.stages} />
    <LiveProgressPanel run={props.run} debugIssues={props.debugIssues} />
    <PlanReviewWorkspace planText={props.planText} command={props.command} setCommand={props.setCommand} onCommand={props.onCommand} onApprove={props.onApprove} canApprove={props.canApprove} fullscreenOpen={props.fullscreenOpen} setFullscreenOpen={props.setFullscreenOpen} run={props.run} debugIssues={props.debugIssues} onOpenDebugTab={props.onOpenDebugTab} />
  </div>;
}

function RunContextBanner({ run, backendHealth, hydrationState, onOpenPlan, onClearRun, onOpenDebugTab }: { run: RunState; backendHealth: BackendHealthState; hydrationState: HydrationState; onOpenPlan: () => void; onClearRun: () => void; onOpenDebugTab: (tab: DebugTab) => void }) {
  const planPath = run.current_plan_path || (typeof run.pause?.plan_path === "string" ? run.pause.plan_path : "");
  const partialPath = run.output_dir ? `${run.output_dir.replaceAll("\\", "/")}/reports/architecture_plan.partial.md` : "";
  const debugBundlePath = run.output_dir ? `${run.output_dir.replaceAll("\\", "/")}/reports/debug_bundle_manifest.json` : "";
  const copy = (label: string, value: string) => {
    if (!value) return;
    void navigator.clipboard?.writeText(value);
    logStore.appendEvent({ type: "log", level: "info", agent: "debug", message: `Copied ${label}: ${value}` });
  };
  const source = run.runtime?.manifest ? "runtime hydrate" : run.run_id ? "live backend" : "no active run";
  const classifier = runClassifier(run);
  const canClear = ["stopped", "failed", "done"].includes(run.status);
  return <section className="panel flex min-w-0 flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs">
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <span className={`mini-chip ${run.status === "failed" ? "danger" : ""}`}>{run.status || "idle"}</span>
      <span className="truncate font-mono text-slate-300">run {run.run_id || "-"}</span>
      <span className="truncate text-slate-400">project {run.project_name || "-"}</span>
      <span className="truncate text-slate-500">output {run.output_dir || "-"}</span>
      <span className="mini-chip">Active run: {run.planning_mode === "deep_planning" ? "Deep Planning" : run.planning_mode === "normal" ? "Normal" : "-"}</span>
      <span className="mini-chip">class {classifier}</span>
      <span className="mini-chip">Backend {backendHealth}</span>
      <span className="mini-chip">Hydrate {hydrationState}</span>
      <span className="truncate text-slate-500">{source}</span>
    </div>
    <div className="flex min-w-0 flex-wrap justify-end gap-2">
      <button className="chip" onClick={onOpenPlan} disabled={!planPath}>Open plan</button>
      <button className="chip" onClick={() => { copy("partial plan path", partialPath); onOpenDebugTab("artifacts"); }} disabled={!run.output_dir}>Open partial plan</button>
      <button className="chip" onClick={() => { copy("output dir", run.output_dir); onOpenDebugTab("artifacts"); }} disabled={!run.output_dir}>Open output folder</button>
      <button className="chip" onClick={() => { copy("debug bundle", debugBundlePath); onOpenDebugTab("artifacts"); }} disabled={!run.output_dir}>Open debug bundle</button>
      <button className="chip" onClick={() => copy("run id", run.run_id)} disabled={!run.run_id}>Copy run id</button>
      <button className="chip" onClick={() => copy("output dir", run.output_dir)} disabled={!run.output_dir}>Copy output folder</button>
      <button className="chip" onClick={() => copy("plan path", planPath)} disabled={!planPath}>Copy plan</button>
      <button className="chip" onClick={() => copy("partial plan path", partialPath)} disabled={!run.output_dir}>Copy partial plan</button>
      <button className="chip" onClick={onClearRun} disabled={!canClear}>Clear stopped run</button>
      <button className="chip" onClick={() => onOpenDebugTab("artifacts")}>Artifacts</button>
    </div>
  </section>;
}

function LiveProgressPanel({ run, debugIssues }: { run: RunState; debugIssues: DebugIssue[] }) {
  const trace = useTrace();
  const manifest = trace.runtime?.manifest ?? run.runtime?.manifest ?? null;
  const manifestRecord = asRecord(manifest);
  const modelCalls = asRecord(manifestRecord.model_calls);
  const activeModelId = String(manifestRecord.active_model_call_id ?? "");
  const activeModel = asRecord(activeModelId ? modelCalls[activeModelId] : Object.values(modelCalls).find((call) => asRecord(call).status === "running") ?? Object.values(modelCalls).slice(-1)[0]);
  const activeAgent = String(manifestRecord.active_agent ?? "idle");
  const activeNode = String(manifestRecord.active_node_id ?? run.agents.agent1?.action ?? "Waiting");
  const cluster = asRecord(manifestRecord.agent1_cluster_council);
  const groupSessions = asRecord(cluster.group_sessions);
  const runningGroup = Object.values(groupSessions).map(asRecord).find((session) => session.status === "running");
  const groupLabel = runningGroup ? `${String(runningGroup.group_id ?? "-")} / ${String(runningGroup.manager_id ?? "-")}` : "no active group";
  const retryCount = Object.values(groupSessions).reduce<number>((sum, raw) => sum + Number(asRecord(raw).retry_count ?? asRecord(raw).attempt ?? 0), 0)
    + asArray(cluster.retry_tree).length
    + issuesForRun(debugIssues, run.run_id).filter((issue) => /retry/i.test(`${issue.code} ${issue.message}`)).length;
  const elapsedMs = modelCallElapsedMs(activeModel);
  const timeoutMs = Number(activeModel.timeout_ms ?? asRecord(activeModel.metrics).timeout_ms ?? Number(activeModel.timeout_s ?? asRecord(activeModel.metrics).timeout_s ?? 0) * 1000);
  const remainingMs = timeoutMs > 0 ? Math.max(0, timeoutMs - elapsedMs) : 0;
  const artifactRefs = asArray(manifestRecord.artifact_refs).map(String);
  const partialEvidenceCount = artifactRefs.filter((item) => /partial|recovery/i.test(item)).length
    + issuesForRun(debugIssues, run.run_id).filter((issue) => /partial|recovery/i.test(`${issue.code} ${issue.message} ${issue.artifact_ref}`)).length;
  const slowReason = run.status === "running" && elapsedMs > 15000
    ? `Waiting on ${activeAgent || "agent"} ${activeNode || "node"}; model/API latency can be inspected in Debug -> Trace.`
    : run.status === "stopping"
      ? "Stop requested; waiting for runner/process confirmation."
      : run.status === "paused"
        ? String(run.pause?.message ?? "Paused for human review.")
        : run.status === "idle"
          ? "No active run."
          : "Runtime progress stable.";
  return <section className="panel grid gap-2 p-3 text-xs md:grid-cols-6">
    <TraceMini title="Current expert/group" value={`${activeAgent} | ${groupLabel}`} tone="info" />
    <TraceMini title="Current node" value={activeNode} tone="info" />
    <TraceMini title="Model call elapsed" value={activeModelId || activeModel.status ? `${activeModelId || "latest"} | ${elapsedMs}ms` : "no active model call"} tone={elapsedMs > 30000 ? "warning" : "info"} />
    <TraceMini title="Retry count" value={String(retryCount)} tone={retryCount > 0 ? "warning" : "info"} />
    <TraceMini title="Timeout budget left" value={timeoutMs > 0 ? `${remainingMs}ms / ${timeoutMs}ms` : "not reported"} tone={remainingMs === 0 && timeoutMs > 0 ? "warning" : "info"} />
    <TraceMini title="Partial evidence count" value={String(partialEvidenceCount)} tone={partialEvidenceCount > 0 ? "warning" : "info"} />
    <div className="md:col-span-6 rounded border border-cyanGlow/10 bg-black/20 px-3 py-2 text-slate-400">{slowReason}</div>
  </section>;
}

function PlanReviewWorkspace({ planText, command, setCommand, onCommand, onApprove, canApprove, fullscreenOpen, setFullscreenOpen, run, debugIssues, onOpenDebugTab }: { planText: string; command: string; setCommand: (v: string) => void; onCommand: () => void; onApprove: () => void; canApprove: boolean; fullscreenOpen: boolean; setFullscreenOpen: (v: boolean) => void; run: RunState; debugIssues: DebugIssue[]; onOpenDebugTab: (tab: DebugTab) => void }) {
  const blockedReasons = buildBlockedReasons(run, debugIssues);
  const body = <pre className="h-full min-h-0 overflow-auto whitespace-pre-wrap font-mono text-xs leading-relaxed text-slate-200">{planText}</pre>;
  return <section className="panel plan-review-workspace flex min-h-0 flex-col gap-3 p-3">
    <div className="flex min-w-0 items-center justify-between gap-3">
      <div><div className="field-kicker">Project workspace</div><h2 className="font-bold">Plan Review</h2></div>
      <button className="chip" onClick={() => setFullscreenOpen(true)}>Open full screen plan</button>
    </div>
    {blockedReasons.length > 0 && <WhyBlockedPanel reasons={blockedReasons} run={run} setCommand={setCommand} onOpenDebugTab={onOpenDebugTab} />}
    <div className="min-h-0 flex-1 overflow-hidden rounded border border-cyanGlow/15 bg-black/25 p-3">{body}</div>
    <div className="grid gap-2 md:grid-cols-[auto_1fr]">
      <div className="flex flex-wrap gap-2"><button className="btn-success" onClick={onApprove} disabled={!canApprove} title={canApprove ? "Approve current review gate" : "Available only during PLAN_REVIEW or HUMAN_REVIEW"}><CheckCircle2 className="h-4 w-4" /> Approve OK</button><button className="btn-warning" onClick={() => setCommand("change ")}><AlertTriangle className="h-4 w-4" /> Request Change</button></div>
      <div className="flex min-w-0 items-center gap-2 rounded border border-cyanGlow/30 bg-black/40 px-3 py-2 font-mono"><span className="shrink-0 text-cyanGlow">root@swarm:~$</span><input className="min-w-0 flex-1 bg-transparent text-success outline-none" maxLength={2000} value={command} onChange={(e) => setCommand(e.target.value.slice(0, 2000))} onKeyDown={(e) => { if (e.key === "Enter" && e.ctrlKey && canApprove) onApprove(); else if (e.key === "Enter") onCommand(); else if (e.key === "Escape") setCommand(""); }} placeholder="change request or follow-up" /></div>
    </div>
    <Dialog.Root open={fullscreenOpen} onOpenChange={setFullscreenOpen}><Dialog.Portal><Dialog.Overlay className="fixed inset-0 bg-black/70 backdrop-blur" /><Dialog.Content className="panel fixed inset-6 grid min-h-0 grid-rows-[auto_1fr_auto] gap-3 p-5"><Dialog.Title className="text-xl font-bold">Architecture Plan Review</Dialog.Title><div className="min-h-0 overflow-hidden rounded border border-cyanGlow/15 bg-black/30 p-3">{body}</div><div className="flex justify-end gap-2"><button className="btn-success" onClick={onApprove} disabled={!canApprove}>Approve OK</button><button className="btn-secondary" onClick={() => setFullscreenOpen(false)}>Close</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </section>;
}

function WhyBlockedPanel({ reasons, run, setCommand, onOpenDebugTab }: { reasons: BlockedReason[]; run: RunState; setCommand: (v: string) => void; onOpenDebugTab: (tab: DebugTab) => void }) {
  const action = String(run.pause?.action_required ?? "");
  const title = action === "NON_DESIGN_CONVERSATION" ? "Non-design response ready" : action === "CONFLICT_REQUIRED" || action === "REQUIREMENT_CLARIFICATION" ? "Requirement clarification required" : action === "HUMAN_REVIEW" ? "Human review gate" : "Why Blocked";
  const needsDeepDiagnostics = ["CONFLICT_REQUIRED", "REQUIREMENT_CLARIFICATION", "HITL_REQUIRED"].includes(action) || run.status === "failed";
  const conflictArtifact = needsDeepDiagnostics ? reasons.find((reason) => reason.artifact && reason.code.includes("conflict"))?.artifact || (typeof run.pause?.artifact_path === "string" ? run.pause.artifact_path : "") : "";
  const contractLintReport = needsDeepDiagnostics && run.output_dir ? `${run.output_dir.replaceAll("\\", "/")}/reports/contract_lint_report.json` : "";
  return <div className="blocked-panel">
    <div className="flex min-w-0 items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="field-kicker">Flow guard</div>
        <h3 className="truncate font-bold">{title}</h3>
        <p className="mt-1 text-xs text-slate-400">{run.pause?.message ? String(run.pause.message) : "Current run needs review. Approve, send a change/follow-up, or inspect Debug."}</p>
      </div>
      <span className={`mini-chip ${run.status === "failed" ? "danger" : ""}`}>{run.status}{action ? ` | ${action}` : ""}</span>
    </div>
    <div className="blocked-reason-list">
      {reasons.slice(0, 6).map((reason, index) => <div key={`${reason.code}-${index}`} className="blocked-reason">
        <span className={`mini-chip ${reason.severity === "fatal" || reason.severity === "error" ? "danger" : ""}`}>{reason.severity}</span>
        <div className="min-w-0">
          <b className="block truncate">{reason.code}</b>
          <span className="block truncate text-slate-400">{reason.message}</span>
          {reason.artifact && <span className="block truncate font-mono text-[10px] text-cyanGlow">{reason.artifact}</span>}
        </div>
      </div>)}
    </div>
    <div className="mt-2 flex flex-wrap gap-2">
      <button className="btn-warning" onClick={() => setCommand("change ")}>Submit follow-up/change</button>
      <button className="btn-secondary" onClick={() => onOpenDebugTab("trace")}>Jump to Debug trace</button>
      <button className="btn-secondary" onClick={() => onOpenDebugTab("issues")}>Open Raw Issues</button>
      <button className="btn-secondary" onClick={() => onOpenDebugTab("artifacts")}>Open artifacts</button>
      {conflictArtifact && <button className="btn-secondary" onClick={() => { logStore.appendEvent({ type: "log", level: "info", agent: "debug", message: `Open conflict artifact: ${conflictArtifact}` }); onOpenDebugTab("artifacts"); }}>Open conflict artifact</button>}
      {contractLintReport && <button className="btn-secondary" onClick={() => { logStore.appendEvent({ type: "log", level: "info", agent: "debug", message: `Open contract lint report: ${contractLintReport}` }); onOpenDebugTab("artifacts"); }}>Open contract lint report</button>}
    </div>
  </div>;
}

function buildBlockedReasons(run: RunState, issues: DebugIssue[]): BlockedReason[] {
  const reasons: BlockedReason[] = [];
  const action = String(run.pause?.action_required ?? "");
  if (run.status === "done" && !action) return reasons;
  if (run.status === "failed") reasons.push({ severity: "error", source: "backend", code: "run_failed", message: "Run reached failed state; approval is blocked until a new change/start succeeds." });
  if (action === "CONFLICT_REQUIRED" || action === "REQUIREMENT_CLARIFICATION" || action === "NON_DESIGN_CONVERSATION") {
    reasons.push({ severity: "warning", source: "agent1", code: action.toLowerCase(), message: run.pause?.message ? String(run.pause.message) : "Agent 1 needs clarification before plan approval.", artifact: typeof run.pause?.artifact_path === "string" ? run.pause.artifact_path : "" });
  }
  if (action && !["PLAN_REVIEW", "HUMAN_REVIEW"].includes(action) && !run.current_plan_path) {
    reasons.push({ severity: "warning", source: "frontend", code: "plan_preview_not_approveable", message: "No current approveable architecture_plan.md is attached to this pause." });
  }
  const important = issuesForRun(issues, run.run_id).filter((issue) => {
    const severity = String(issue.severity || "").toLowerCase();
    const haystack = `${issue.code} ${issue.message}`.toLowerCase();
    const code = String(issue.code || "").toLowerCase();
    if (["PLAN_REVIEW", "HUMAN_REVIEW"].includes(action)) {
      if (code.includes("websocket")) return false;
      if (code === "flow_missing_required_span" && !["done", "failed"].includes(run.status)) return false;
      if (code.includes("signoff") && ["paused", "stopped"].includes(run.status)) return false;
    }
    return ["error", "fatal"].includes(severity) || /(stale|missing|artifact|contract|guardrail|conflict|threshold|irq|mermaid|credential|process_exit|lint|mismatch|partial|timeout)/.test(haystack);
  }).slice(-8);
  const seen = new Set(reasons.map((reason) => reason.code));
  for (const issue of important) {
    const code = String(issue.code || "debug_issue");
    if (seen.has(code)) continue;
    seen.add(code);
    const lowerCode = code.toLowerCase();
    let message = String(issue.message || code);
    let severity = String(issue.severity || "warning");
    if (lowerCode === "flow_missing_required_span" && !["done", "failed"].includes(run.status)) {
      message = "Flow segment not reached yet in this run; inspect only if release claims completion.";
      severity = "info";
    } else if (lowerCode.includes("websocket") && run.run_id) {
      message = "Live stream issue; backend state and trace replay may still be available.";
    } else if (lowerCode.includes("signoff") && ["paused", "stopped"].includes(run.status)) {
      message = "Signoff not reached yet because run stopped or paused before final handoff.";
      severity = "info";
    }
    reasons.push({ severity, source: String(issue.source || "debug"), code, message, artifact: String(issue.artifact_ref || "") });
  }
  return reasons;
}

function LaunchPanel(props: { requirement: string; setRequirement: (v: string) => void; projectName: string; setProjectName: (v: string) => void; outputDir: string; setOutputDir: (v: string) => void; planningMode: PlanningMode; setPlanningMode: (v: PlanningMode) => void; attachments: AttachmentRef[]; attachmentBusy: boolean; onFilesDropped: (files: File[]) => void; onRemoveAttachment: (id: string) => void; onStart: () => void; onStop: () => void; running: boolean; startBlockedReason: string }) {
  const hints = buildLaunchHints(props.requirement, props.planningMode);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const attachmentTotalBytes = props.attachments.reduce((sum, item) => sum + item.bytes, 0);
  const applyHint = (hint: LaunchHint) => {
    if (hint.action.kind === "setMode") {
      props.setPlanningMode(hint.action.value);
      return;
    }
    props.setRequirement(appendRequirementHint(props.requirement, hint.action.value));
  };
  const onDrop = (event: React.DragEvent<HTMLElement>) => {
    event.preventDefault();
    props.onFilesDropped(Array.from(event.dataTransfer.files));
  };
  const onPick = (event: React.ChangeEvent<HTMLInputElement>) => {
    props.onFilesDropped(Array.from(event.target.files ?? []));
    event.target.value = "";
  };
  return <section className="panel launch-panel launch-panel-grid p-3">
    <div className="command-deck" onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="field-kicker">Mission input</div>
          <div className="text-sm font-semibold text-slate-100">Requirement command deck</div>
        </div>
        <span className="ai-badge"><Activity className="h-3.5 w-3.5" /> local AI hints</span>
      </div>
      <textarea className="command-input font-mono" maxLength={2000} value={props.requirement} onChange={(e) => props.setRequirement(e.target.value.slice(0, 2000))} placeholder="Describe chip/IP target, bus, clock, peripherals, verification priority..." />
      <div className="input-utility-row">
        <button className="attach-button" onClick={() => fileInputRef.current?.click()} disabled={props.attachmentBusy} title="Attach markdown, PDF, or image files"><Upload className="h-3.5 w-3.5" /> {props.attachmentBusy ? "Uploading..." : "Attach files"}</button>
        <div className="flex min-w-0 items-center gap-3">
          {props.attachments.length > 0 && <span className="attachment-summary">{props.attachments.length} files | {formatBytes(attachmentTotalBytes)}</span>}
          <span className={`char-counter ${props.requirement.length > 1900 ? "warn" : ""}`}>{props.requirement.length} / 2000</span>
        </div>
        <input ref={fileInputRef} className="hidden" type="file" multiple accept=".md,.markdown,.pdf,.png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp,application/pdf,text/markdown,text/plain" onChange={onPick} />
      </div>
      <div className="attachment-strip">
        {props.attachments.map((item) => <div className={`attachment-chip ${item.kind}`} key={item.id} title={`${item.name} | ${item.extractStatus}`}>
          <Paperclip className="h-3.5 w-3.5" />
          <span className="truncate">{item.name}</span>
          <b>{item.kind}</b>
          <em>{formatBytes(item.bytes)}</em>
          <button disabled={props.attachmentBusy} onClick={() => props.onRemoveAttachment(item.id)} title="Remove attachment"><Trash2 className="h-3 w-3" /></button>
        </div>)}
        {!props.attachments.length && <div className="drop-hint">Drop `.md`, `.pdf`, `.png`, `.jpg`, `.webp` here. PDF/Markdown text becomes Agent1 context.</div>}
      </div>
      <div className="hint-row">
        {hints.map((hint) => <button key={`${hint.label}-${hint.detail}`} className={`hint-chip ${hint.accent}`} title={hint.detail} onClick={() => applyHint(hint)}>{hint.label}</button>)}
      </div>
    </div>
    <div className="setup-grid">
      <label className="setup-field">
        <span className="field-kicker">Project</span>
        <input className="tech-input" value={props.projectName} onChange={(e) => props.setProjectName(e.target.value)} placeholder="project_name" />
      </label>
      <div className="setup-field">
        <span className="field-kicker">Mode</span>
        <div className="mode-segment" role="group" aria-label="Planning mode">
          <button className={props.planningMode === "normal" ? "active" : ""} onClick={() => props.setPlanningMode("normal")}>Normal</button>
          <button className={props.planningMode === "deep_planning" ? "active" : ""} onClick={() => props.setPlanningMode("deep_planning")}>Deep Planning</button>
        </div>
      </div>
      <label className="setup-field output-field">
        <span className="field-kicker">Output Directory</span>
        <input className="tech-input font-mono" value={props.outputDir} onChange={(e) => props.setOutputDir(e.target.value)} placeholder="D:/AI/AgentAI/outputs/studio_runs/project" />
      </label>
      <div className="output-preview font-mono">target://{props.outputDir.replaceAll("\\", "/") || "not-set"}</div>
    </div>
    <div className="launch-actions">
      <button className="mission-button start" onClick={props.onStart} disabled={props.running || Boolean(props.startBlockedReason)}><Rocket className="h-5 w-5" /> START</button>
      <button className="mission-button stop" onClick={props.onStop}><Square className="h-5 w-5" /> STOP</button>
      {props.startBlockedReason ? <div className="launch-warning">{props.startBlockedReason}</div> : <div className="launch-note">Local browser cockpit. Core engine stays Python.</div>}
    </div>
  </section>;
}

function buildLaunchHints(requirement: string, planningMode: PlanningMode): LaunchHint[] {
  const lower = requirement.toLowerCase();
  const hints: LaunchHint[] = [];
  if (!lower.includes("apb")) hints.push({ label: "APB", detail: "Add APB bus intent", action: { kind: "appendRequirement", value: "Use APB bus with locked APB slave pinout." }, accent: "cyan" });
  if (!lower.includes("uart")) hints.push({ label: "UART", detail: "Add UART peripheral", action: { kind: "appendRequirement", value: "Include UART as external peripheral." }, accent: "blue" });
  if (!lower.includes("32-bit") && !lower.includes("32 bit")) hints.push({ label: "32-bit CPU", detail: "Add CPU width intent", action: { kind: "appendRequirement", value: "Target a 32-bit CPU architecture." }, accent: "green" });
  if (!lower.includes("formal")) hints.push({ label: "Formal-first", detail: "Prioritize formal collateral before simulation", action: { kind: "appendRequirement", value: "Use formal-first verification with SVA hooks." }, accent: "amber" });
  if (!lower.includes("cocotb")) hints.push({ label: "cocotb", detail: "Add cocotb DV intent", action: { kind: "appendRequirement", value: "Use cocotb plus SystemVerilog/SVA, no UVM." }, accent: "cyan" });
  if (!lower.includes("fpga")) hints.push({ label: "FPGA-safe", detail: "Bias toward FPGA-safe implementation collateral", action: { kind: "appendRequirement", value: "Keep implementation FPGA-safe and synthesis-friendly." }, accent: "blue" });
  if (planningMode !== "deep_planning") hints.push({ label: "Deep planning", detail: "Switch to deeper Agent 1 planning mode", action: { kind: "setMode", value: "deep_planning" }, accent: "green" });
  return hints.slice(0, 7);
}

function appendRequirementHint(requirement: string, hint: string) {
  const text = requirement.trim();
  if (text.toLowerCase().includes(hint.toLowerCase())) return requirement;
  return text ? `${text}\n${hint}` : hint;
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function Pipeline({ stages: values }: { stages: RunState["stages"] }) {
  return <section className="panel pipeline-shell" aria-label="Swarm stage progress">
    <div className="pipeline-track" />
    {stages.map((stage, index) => {
      const raw = String(values[stage] ?? "idle");
      const visual = stageVisualState(raw);
      return <div className={`stage-node ${visual}`} key={stage} data-stage={stage} data-status={raw}>
        <div className="stage-orbit"><span className="stage-index">{index + 1}</span><span className="stage-core" /></div>
        <div className="stage-copy"><span className="stage-label">{stageLabels[stage]}</span><span className="stage-state">{raw}</span></div>
      </div>;
    })}
  </section>;
}

function stageVisualState(value: string): StageVisualState {
  const normalized = value.toLowerCase();
  if (["running", "starting"].includes(normalized)) return "running";
  if (["pass", "passed", "done", "completed", "signoff_ready"].includes(normalized)) return "pass";
  if (["fail", "failed", "error"].includes(normalized)) return "fail";
  if (["pause", "paused"].includes(normalized)) return "paused";
  if (["stop", "stopped", "cancelled"].includes(normalized)) return "stopped";
  return "idle";
}

function LogPanel({ panelRef, atBottomRef, newLogs, setNewLogs, filter, setFilter }: { panelRef: React.RefObject<HTMLDivElement | null>; atBottomRef: React.MutableRefObject<boolean>; newLogs: number; setNewLogs: (v: number) => void; filter: LogFilter; setFilter: (v: LogFilter) => void }) {
  const logs = useLogs();
  useEffect(() => {
    if (atBottomRef.current) panelRef.current?.scrollTo({ top: panelRef.current.scrollHeight });
    else setNewLogs(newLogs + 1);
  }, [logs.length]);
  const visible = useMemo(() => logs.filter((log) => {
    if (filter === "All") return true;
    if (filter === "Errors") return ["error", "fail"].includes(log.level);
    if (filter === "Agent1") return log.agent === "agent1";
    if (filter === "Leaf") return log.text.includes("Leaf") || log.text.includes("leaf");
    if (filter === "Middle") return log.text.includes("Middle") || log.text.includes("middle");
    if (filter === "Principal") return log.text.includes("Principal") || log.text.includes("principal");
    return true;
  }).slice(-500), [logs, filter]);
  const filters: LogFilter[] = ["All", "Agent1", "Leaf", "Middle", "Principal", "Errors"];
  return <section className="panel grid min-h-0 grid-rows-[68px_1fr] p-3"><div className="space-y-2"><div className="flex items-center justify-between"><h2 className="font-bold">Real-time Operations Log</h2>{newLogs > 0 && <button className="chip" onClick={() => { atBottomRef.current = true; setNewLogs(0); panelRef.current?.scrollTo({ top: panelRef.current.scrollHeight }); }}>Jump to latest ({newLogs})</button>}</div><div className="flex flex-wrap gap-1">{filters.map((item) => <button key={item} className={`chip ${filter === item ? "active" : ""}`} onClick={() => setFilter(item)}>{item}</button>)}</div></div><div ref={panelRef} className="min-h-0 overflow-auto whitespace-pre font-mono text-xs" onScroll={(e) => { const el = e.currentTarget; atBottomRef.current = el.scrollTop + el.clientHeight >= el.scrollHeight - 20; }}>{visible.map((log) => <div key={log.id} className={`log ${log.level}`}>{log.ts} [{log.level.toUpperCase()}] [{log.agent}] {log.text}</div>)}</div></section>;
}

function DebugWorkspace(props: { activeTab: DebugTab; setActiveTab: (v: DebugTab) => void; panelRef: React.RefObject<HTMLDivElement | null>; atBottomRef: React.MutableRefObject<boolean>; newLogs: number; setNewLogs: (v: number) => void; filter: LogFilter; setFilter: (v: LogFilter) => void; rightWidth: number; onResizeStart: (startX: number) => void; command: string; setCommand: (v: string) => void; onCommand: () => void; onApprove: () => void; run: RunState; canApprove: boolean; jobs: AgentJob[]; queueHealth: Record<string, unknown>; debugIssues: DebugIssue[]; onSubmitJob: (type: JobType) => void; onCancelJob: (jobId: string) => void }) {
  const tabs: Array<[DebugTab, string]> = [["log", "Operations Log"], ["signoff", "Signoff"], ["issues", "Raw Issues"], ["flow", "Flow Coverage"], ["trace", "Trace Debug"], ["jobs", "Job Queue"], ["cluster", "Cluster Council"], ["council", "Agent 1 Council"], ["node", "Node Detail"], ["console", "Console"], ["artifacts", "Artifacts"]];
  const inspector = props.activeTab === "signoff"
    ? <SignoffDebugPanel issues={props.debugIssues} />
    : props.activeTab === "issues"
    ? <RawIssuesPanel issues={props.debugIssues} />
    : props.activeTab === "flow"
    ? <FlowCoveragePanel issues={props.debugIssues} />
    : props.activeTab === "trace"
    ? <TraceDebugPanel />
    : props.activeTab === "jobs"
      ? <JobQueuePanel jobs={props.jobs} queueHealth={props.queueHealth} onSubmitJob={props.onSubmitJob} onCancelJob={props.onCancelJob} />
      : props.activeTab === "cluster"
        ? <Agent1ClusterCouncilPanel />
      : props.activeTab === "council"
        ? <Agent1CouncilPanel />
        : props.activeTab === "node"
          ? <NodeDetailPanel run={props.run} />
          : props.activeTab === "console"
            ? <ConsolePanel command={props.command} setCommand={props.setCommand} onCommand={props.onCommand} onApprove={props.onApprove} canApprove={props.canApprove} />
            : props.activeTab === "artifacts"
              ? <ArtifactsDebugPanel run={props.run} onSubmitJob={props.onSubmitJob} />
              : <TraceDebugPanel />;
  return <section className="debug-workspace grid h-full min-h-0 grid-rows-[auto_auto_1fr] gap-3">
    <div className="panel flex min-w-0 items-center justify-between gap-3 p-3">
      <div><div className="field-kicker">Debug workspace</div><h2 className="font-bold">Operations, Trace, Jobs, Console</h2></div>
      <div className="tab-strip trace-scrollbar">{tabs.map(([tab, label]) => <button key={tab} className={`tech-tab ${props.activeTab === tab ? "active" : ""}`} onClick={() => props.setActiveTab(tab)}>{label}</button>)}</div>
    </div>
    <DebugNextStepsPanel issues={props.debugIssues} activeTab={props.activeTab} run={props.run} setActiveTab={props.setActiveTab} />
    {props.activeTab === "log"
      ? <LogPanel panelRef={props.panelRef} atBottomRef={props.atBottomRef} newLogs={props.newLogs} setNewLogs={props.setNewLogs} filter={props.filter} setFilter={props.setFilter} />
      : <section className="grid min-h-0 min-w-0 gap-2 overflow-hidden" style={{ gridTemplateColumns: `minmax(0,1fr) 6px minmax(280px,min(${props.rightWidth}px,42vw))` }}><LogPanel panelRef={props.panelRef} atBottomRef={props.atBottomRef} newLogs={props.newLogs} setNewLogs={props.setNewLogs} filter={props.filter} setFilter={props.setFilter} /><div className="splitter" title="Resize Log / Debug Panel" onPointerDown={(event) => props.onResizeStart(event.clientX)} /><section className="panel grid min-h-0 min-w-0 overflow-hidden p-3">{inspector}</section></section>}
  </section>;
}

function DebugNextStepsPanel({ issues, activeTab, run, setActiveTab }: { issues: DebugIssue[]; activeTab: DebugTab; run: RunState; setActiveTab: (v: DebugTab) => void }) {
  const latest = [...issuesForRun(issues, run.run_id)].reverse().find((issue) => ["fatal", "error", "warning"].includes(String(issue.severity))) ?? [...issues].reverse().find((issue) => ["fatal", "error", "warning"].includes(String(issue.severity)));
  const text = `${latest?.source ?? ""} ${latest?.code ?? ""} ${latest?.message ?? ""} ${latest?.gate ?? ""}`.toLowerCase();
  let target: DebugTab = "issues";
  let action = "Open Raw Issues, filter by severity/source/code, then copy JSON if deeper debug is needed.";
  if (/infra|model|codex|connection|endpoint|auth|provider/.test(text)) {
    target = "cluster";
    action = "Model/infra issue: check Setting > Test Connection, then inspect Raw Issues and Cluster Council group sessions.";
  } else if (/signoff|benchmark|handoff|g\d\d/.test(text)) {
    target = "signoff";
    action = "Signoff issue: open Signoff, read gate code, then open artifact_ref from Raw Issues.";
  } else if (/artifact|stale|missing/.test(text)) {
    target = "artifacts";
    action = "Artifact issue: open Artifacts, verify path/current revision, then inspect artifact_ref.";
  } else if (/websocket|hydrate|runtime/.test(text)) {
    target = "trace";
    action = "Runtime/UI issue: inspect Trace Debug, run_id/revision_id, then reload if websocket is stale.";
  } else if (/ambiguity|clarification|question/.test(text)) {
    target = "issues";
    action = "Agent1 ambiguity: read Project clarification questions, answer blocking fields, then resume/change request.";
  }
  return <div className="panel flex min-w-0 flex-wrap items-center gap-2 px-3 py-2 text-xs">
    <span className="field-kicker">What To Check Next</span>
    <span className="min-w-0 flex-1 truncate text-slate-300">{latest ? `${latest.severity} ${latest.source}/${latest.code}: ${action}` : "No issue yet. Start with Operations Log; when warning/error appears, this guide points to the next tab."}</span>
    <button className="chip" onClick={() => setActiveTab(target)} disabled={activeTab === target}>{target === "issues" ? "Open Raw Issues" : `Open ${target}`}</button>
  </div>;
}

function SignoffDebugPanel({ issues }: { issues: DebugIssue[] }) {
  const trace = useTrace();
  const signoff = trace.runtime?.signoff ?? null;
  const signoffState = String(signoff?.state ?? "NOT_REACHED");
  const signoffReason = String(signoff?.stateReason ?? (signoffState === "NOT_REACHED" ? "Signoff not reached yet." : ""));
  const certificate = asRecord(signoff?.certificate);
  const gateReport = asRecord(signoff?.gateReport);
  const handoff = asRecord(signoff?.handoff);
  const benchmark = asRecord(signoff?.benchmarkReport);
  const falsePass = asRecord(signoff?.falsePassReport);
  const disagreements = asRecord(signoff?.oracleDisagreements);
  const waivers = asRecord(signoff?.waivers);
  const artifactRefs = asRecord(signoff?.artifactRefs);
  const artifactStatus = asRecord(signoff?.artifactStatus);
  const gateResults = asRecord(gateReport.gate_results);
  const findings = asArray(gateReport.findings);
  const signoffIssues = issues.filter((issue) => /signoff|benchmark|handoff/i.test(`${issue.source} ${issue.code} ${issue.gate ?? ""}`));
  const blockerCodes = asArray(asRecord(certificate.finding_summary).blocking_codes).map(String);
  const falsePassItems = asArray(falsePass.items);
  const disagreementItems = asArray(disagreements.items);
  const copySignoffValue = (label: string, value: unknown) => {
    void navigator.clipboard?.writeText(typeof value === "string" ? value : JSON.stringify(value, null, 2));
    logStore.appendEvent({ type: "log", level: "info", agent: "debug", message: `Copied signoff ${label}` });
  };
  return <div className="grid h-full min-h-0 grid-rows-[auto_1fr] gap-3">
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div><div className="field-kicker">Industrial Signoff</div><h2 className="font-bold">Signoff Certificate / Gate Results / Benchmark</h2></div>
        <button className="chip" onClick={() => copySignoffValue("bundle JSON", signoff ?? {})}>Copy Signoff JSON</button>
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <TraceMini title="Signoff state" value={`${signoffState} | ${signoffReason}`} tone={["BLOCKED", "FAILED"].includes(signoffState) ? "warning" : "info"} />
        <TraceMini title="Signoff decision" value={certificate.decision ? `${String(certificate.decision)} | handoff ${String(certificate.handoff_allowed)}` : signoffState === "NOT_REACHED" ? "Signoff not reached" : "No certificate yet"} tone={certificate.handoff_allowed === false ? "warning" : "info"} />
        <TraceMini title="Score / profile" value={`${String(certificate.score ?? "-")} | ${String(certificate.profile ?? benchmark.profile ?? "-")}`} tone="info" />
        <TraceMini title="Gate blockers" value={`${String(asRecord(certificate.finding_summary).blocking_count ?? gateReport.blocking_count ?? 0)} blocking | ${String(asRecord(certificate.finding_summary).warning_count ?? gateReport.warning_count ?? 0)} warnings`} tone={Number(asRecord(certificate.finding_summary).blocking_count ?? gateReport.blocking_count ?? 0) > 0 ? "warning" : "info"} />
        <TraceMini title="Agent2 handoff" value={handoff.reason ? `${String(handoff.allowed)} | ${String(handoff.reason)}` : "No handoff report yet"} tone={handoff.allowed === false ? "warning" : "info"} />
        <TraceMini title="Benchmark safety" value={benchmark.case_count ? `${String(benchmark.case_count)} cases | false_pass ${String(benchmark.false_pass_count)} | must_not_pass ${String(benchmark.must_not_pass_violation_count)}` : "No benchmark report yet"} tone={Number(benchmark.false_pass_count ?? 0) || Number(benchmark.must_not_pass_violation_count ?? 0) ? "warning" : "info"} />
        <TraceMini title="Waivers" value={`${asArray(asRecord(certificate.waiver_summary).applied).length} applied | ${asArray(asRecord(certificate.waiver_summary).rejected).length} rejected | file ${waivers.schema_version ? "present" : "none"}`} tone={asArray(asRecord(certificate.waiver_summary).rejected).length ? "warning" : "info"} />
      </div>
      {signoffState === "NOT_REACHED" && <div className="rounded border border-cyanGlow/30 bg-cyanGlow/10 p-2 text-xs text-cyanGlow">Signoff not reached. This is normal before Agent1 approval/signoff.</div>}
      {asArray(signoff?.errors).length > 0 && signoffState !== "NOT_REACHED" && <div className="rounded border border-amber/40 bg-amber/10 p-2 text-xs text-amber">Signoff artifact read errors: {JSON.stringify(signoff?.errors)}</div>}
    </div>
    <div className="trace-scrollbar min-h-0 overflow-auto pr-1">
      <div className="mb-3 grid gap-2">
        <div className="agent-card">
          <div className="flex items-center justify-between gap-2"><b>Final Certificate</b><span className="mini-chip">{String(certificate.schema_version ?? "missing")}</span></div>
          <div className="mt-1 grid grid-cols-2 gap-1 font-mono text-[11px] text-slate-400">
            <span className="truncate">run {String(certificate.run_id ?? "-")}</span><span className="truncate">rev {String(certificate.revision_id ?? "-")}</span>
            <span className="truncate">project {String(certificate.project ?? "-")}</span><span className="truncate">created {String(certificate.created_at ?? "-")}</span>
            <span className="truncate">topology {String(certificate.topology_hash ?? "-")}</span><span className="truncate">config {String(certificate.config_hash ?? "-")}</span>
          </div>
          {blockerCodes.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{blockerCodes.map((code) => <span className="mini-chip danger" key={code}>{code}</span>)}</div>}
        </div>
        <div className="agent-card">
          <div className="flex items-center justify-between gap-2"><b>Gate Results</b><span className="mini-chip">{Object.keys(gateResults).length} gates</span></div>
          <div className="mt-2 grid gap-1">
            {Object.entries(gateResults).map(([gate, raw]) => {
              const result = asRecord(raw);
              const codes = asArray(result.finding_codes).map(String);
              const status = String(result.status || "UNKNOWN");
              return <div key={gate} className={`rounded border ${status === "FAIL" || status === "BLOCKED" ? "border-red-400/40" : status === "WARN" || status === "WAIVED" ? "border-amber/40" : "border-cyanGlow/10"} bg-black/20 p-2`}>
                <div className="flex items-center justify-between gap-2"><b className="font-mono text-xs">{gate}</b><span className="mini-chip">{status}</span></div>
                <div className="mt-1 flex flex-wrap gap-1">{codes.length ? codes.map((code) => <button className="mini-chip" key={code} onClick={() => copySignoffValue("finding code", code)}>{code}</button>) : <span className="text-xs text-slate-500">no findings</span>}</div>
              </div>;
            })}
          </div>
        </div>
        <div className="agent-card">
          <div className="flex items-center justify-between gap-2"><b>Benchmark Cases</b><span className="mini-chip">{String(benchmark.schema_version ?? "missing")}</span></div>
          <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
            <TraceMini title="false-pass report" value={`${falsePassItems.length} items`} tone={falsePassItems.length ? "warning" : "info"} />
            <TraceMini title="oracle disagreements" value={`${disagreementItems.length} items`} tone={disagreementItems.length ? "warning" : "info"} />
            <TraceMini title="waiver_accuracy" value={String(benchmark.waiver_accuracy ?? "-")} tone={Number(benchmark.waiver_accuracy ?? 1) < 1 ? "warning" : "info"} />
            <TraceMini title="handoff_gate_accuracy" value={String(benchmark.handoff_gate_accuracy ?? "-")} tone={Number(benchmark.handoff_gate_accuracy ?? 1) < 1 ? "warning" : "info"} />
          </div>
          <ClusterSection title="Gate Breakdown" rows={[asRecord(benchmark.gate_breakdown)]} empty="No benchmark gate breakdown." />
        </div>
        <div className="agent-card">
          <div className="flex items-center justify-between gap-2"><b>Waiver Results</b><span className="mini-chip">{String(asRecord(certificate.waiver_summary).schema_version ?? "no waiver summary")}</span></div>
          <ClusterSection title="Applied Waivers" rows={asArray(asRecord(certificate.waiver_summary).applied)} empty="No applied waiver." />
          <ClusterSection title="Rejected Waivers" rows={asArray(asRecord(certificate.waiver_summary).rejected)} empty="No rejected waiver." />
        </div>
        <div className="agent-card">
          <div className="flex items-center justify-between gap-2"><b>Findings</b><span className="mini-chip">{findings.length} gate findings | {signoffIssues.length} raw issues</span></div>
          {findings.slice(-80).map((finding, index) => {
            const item = asRecord(finding);
            return <div key={`${String(item.finding_id ?? index)}`} className="mt-2 rounded border border-cyanGlow/10 bg-black/20 p-2 font-mono text-[11px]">
              <div className="flex items-center justify-between gap-2"><b>{String(item.gate)} {String(item.code)}</b><span className="mini-chip">{String(item.severity)} {item.waiver_id ? `waived ${String(item.waiver_id)}` : ""}</span></div>
              <div className="mt-1 whitespace-pre-wrap break-words text-slate-300">{String(item.message ?? "")}</div>
              <div className="mt-1 truncate text-slate-500">artifact {String(item.artifact_ref ?? "-")}</div>
            </div>;
          })}
          {!findings.length && <p className="mt-2 text-sm text-slate-400">No signoff findings.</p>}
        </div>
        <div className="agent-card">
          <div className="flex items-center justify-between gap-2"><b>Artifact Refs</b><span className="mini-chip">{Object.keys(artifactRefs).length} refs</span></div>
          <div className="mt-2 grid gap-1 font-mono text-[11px]">
            {Object.entries(artifactRefs).map(([key, value]) => {
              const status = asRecord(artifactStatus[key]);
              return <button key={key} className="rounded border border-cyanGlow/10 bg-black/20 p-2 text-left text-cyanGlow" onClick={() => copySignoffValue(`${key} artifact path`, String(value))}>
                <span className="mr-2 text-slate-400">{key}</span>{String(value)} <span className={status.exists ? "text-success" : "text-amber"}>{status.exists ? "exists" : "missing"}</span>
              </button>;
            })}
            {!Object.keys(artifactRefs).length && <span className="text-slate-500">No signoff artifact refs hydrated yet.</span>}
          </div>
        </div>
      </div>
    </div>
  </div>;
}

function issueGroupId(issue: DebugIssue): string {
  const details = issue.details ?? {};
  const finding = typeof details.finding === "object" && details.finding ? details.finding as Record<string, unknown> : {};
  return String(details.group_id ?? details.target_group_id ?? details.owner_group_id ?? finding.group_id ?? finding.target_group_id ?? "");
}

function issueSpanId(issue: DebugIssue): string {
  const details = issue.details ?? {};
  const finding = typeof details.finding === "object" && details.finding ? details.finding as Record<string, unknown> : {};
  return String(issue.span_id ?? issue.parent_span_id ?? details.span_id ?? details.parent_span_id ?? finding.span_id ?? finding.parent_span_id ?? finding.correlation_id ?? "");
}

function issueFlowSegment(issue: DebugIssue): string {
  const details = issue.details ?? {};
  const finding = typeof details.finding === "object" && details.finding ? details.finding as Record<string, unknown> : {};
  return String(issue.flow_segment ?? details.flow_segment ?? finding.flow_segment ?? "");
}

function issueSourceLayer(issue: DebugIssue): string {
  const details = issue.details ?? {};
  const finding = typeof details.finding === "object" && details.finding ? details.finding as Record<string, unknown> : {};
  return String(issue.source_layer ?? details.source_layer ?? finding.source_layer ?? "");
}

type RawIssueGroup = { signature: string; count: number; firstTimestamp: string; lastTimestamp: string; issue: DebugIssue; samples: DebugIssue[] };

function issueSignature(issue: DebugIssue): string {
  return [
    issue.severity || "warning",
    issue.source || "unknown",
    issue.code || "debug_issue",
    issue.node_id || "",
    issueGroupId(issue),
    issueSpanId(issue),
    issueFlowSegment(issue),
    issueSourceLayer(issue),
    issue.artifact_ref || "",
  ].join("||");
}

function RawIssuesPanel({ issues }: { issues: DebugIssue[] }) {
  const [viewMode, setViewMode] = useState<"compact" | "raw">("compact");
  const [severity, setSeverity] = useState("all");
  const [source, setSource] = useState("all");
  const [code, setCode] = useState("all");
  const [group, setGroup] = useState("all");
  const [span, setSpan] = useState("all");
  const [flow, setFlow] = useState("all");
  const [layer, setLayer] = useState("all");
  const [runId, setRunId] = useState("all");
  const [revision, setRevision] = useState("all");
  const [artifact, setArtifact] = useState("all");
  const severities = useMemo(() => ["all", ...Array.from(new Set(issues.map((issue) => issue.severity || "warning")))], [issues]);
  const sources = useMemo(() => ["all", ...Array.from(new Set(issues.map((issue) => issue.source || "unknown")))], [issues]);
  const codes = useMemo(() => ["all", ...Array.from(new Set(issues.map((issue) => issue.code || "debug_issue")))], [issues]);
  const groups = useMemo(() => ["all", ...Array.from(new Set(issues.map((issue) => issueGroupId(issue)).filter(Boolean)))], [issues]);
  const spans = useMemo(() => ["all", ...Array.from(new Set(issues.map((issue) => issueSpanId(issue)).filter(Boolean)))], [issues]);
  const flows = useMemo(() => ["all", ...Array.from(new Set(issues.map((issue) => issueFlowSegment(issue)).filter(Boolean)))], [issues]);
  const layers = useMemo(() => ["all", ...Array.from(new Set(issues.map((issue) => issueSourceLayer(issue)).filter(Boolean)))], [issues]);
  const runIds = useMemo(() => ["all", ...Array.from(new Set(issues.map((issue) => issue.run_id || "").filter(Boolean)))], [issues]);
  const revisions = useMemo(() => ["all", ...Array.from(new Set(issues.map((issue) => issue.revision_id || "").filter(Boolean)))], [issues]);
  const artifacts = useMemo(() => ["all", ...Array.from(new Set(issues.map((issue) => issue.artifact_ref || "").filter(Boolean)))], [issues]);
  const visible = useMemo(() => issues.filter((issue) => (severity === "all" || issue.severity === severity) && (source === "all" || issue.source === source) && (code === "all" || issue.code === code) && (group === "all" || issueGroupId(issue) === group) && (span === "all" || issueSpanId(issue) === span) && (flow === "all" || issueFlowSegment(issue) === flow) && (layer === "all" || issueSourceLayer(issue) === layer) && (runId === "all" || issue.run_id === runId) && (revision === "all" || issue.revision_id === revision) && (artifact === "all" || issue.artifact_ref === artifact)).slice(-500), [issues, severity, source, code, group, span, flow, layer, runId, revision, artifact]);
  const groupedIssues = useMemo<RawIssueGroup[]>(() => {
    const groupsBySignature = new Map<string, RawIssueGroup>();
    for (const issue of visible) {
      const signature = issueSignature(issue);
      const timestamp = String(issue.timestamp || "");
      const current = groupsBySignature.get(signature);
      if (!current) {
        groupsBySignature.set(signature, { signature, count: 1, firstTimestamp: timestamp, lastTimestamp: timestamp, issue, samples: [issue] });
        continue;
      }
      current.count += 1;
      current.lastTimestamp = timestamp || current.lastTimestamp;
      current.issue = issue;
      current.samples = [...current.samples, issue].slice(-5);
    }
    return Array.from(groupsBySignature.values()).sort((a, b) => String(b.lastTimestamp).localeCompare(String(a.lastTimestamp)));
  }, [visible]);
  const copyIssue = (issue: DebugIssue) => {
    void navigator.clipboard?.writeText(JSON.stringify(issue, null, 2));
    logStore.appendEvent({ type: "log", level: "info", agent: "debug", message: `Copied debug issue ${issue.code}` });
  };
  const copyIssueGroup = (group: RawIssueGroup) => {
    void navigator.clipboard?.writeText(JSON.stringify({ signature: group.signature, count: group.count, firstTimestamp: group.firstTimestamp, lastTimestamp: group.lastTimestamp, latest: group.issue, samples: group.samples }, null, 2));
    logStore.appendEvent({ type: "log", level: "info", agent: "debug", message: `Copied debug issue group ${group.issue.code}` });
  };
  const jumpIssueNode = (issue: DebugIssue) => {
    const node = String(issue.node_id || "");
    if (node) traceStore.select(node);
    logStore.appendEvent({ type: "log", level: "info", agent: "debug", message: `Jump issue node: ${node || "unavailable"}` });
  };
  const openIssueArtifact = (issue: DebugIssue) => {
    logStore.appendEvent({ type: "log", level: "info", agent: "debug", message: `Open issue artifact: ${issue.artifact_ref || "unavailable"}` });
  };
  return <div className="grid h-full min-h-0 grid-rows-[auto_1fr] gap-3">
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2"><h2 className="font-bold">Raw Issues</h2><span className="chip">{viewMode === "compact" ? `${groupedIssues.length} groups / ${visible.length} raw / ${issues.length}` : `${visible.length} raw / ${issues.length}`}</span></div>
      <div className="flex flex-wrap gap-2">
        <button className={`chip ${viewMode === "compact" ? "active" : ""}`} onClick={() => setViewMode("compact")}>Compact Groups</button>
        <button className={`chip ${viewMode === "raw" ? "active" : ""}`} onClick={() => setViewMode("raw")}>Raw List</button>
        <span className="mini-chip">raw JSON preserved; compact only groups repeated UI rows</span>
      </div>
      <div className="rounded border border-cyanGlow/10 bg-black/20 p-2 text-xs text-slate-400">
        Raw Issues guide: <span className="text-cyanGlow">severity</span> says impact, <span className="text-cyanGlow">source</span> names subsystem, <span className="text-cyanGlow">code</span> is search key, <span className="text-cyanGlow">artifact_ref</span> is file to inspect, <span className="text-cyanGlow">run_id/revision_id</span> prevents stale-output confusion.
      </div>
      <div className="flex flex-wrap gap-2">
        <select className="field compact" value={severity} onChange={(event) => setSeverity(event.target.value)}>{severities.map((item) => <option key={item}>{item}</option>)}</select>
        <select className="field compact" value={source} onChange={(event) => setSource(event.target.value)}>{sources.map((item) => <option key={item}>{item}</option>)}</select>
        <select className="field compact" value={group} onChange={(event) => setGroup(event.target.value)}>{groups.map((item) => <option key={item}>{item}</option>)}</select>
        <select className="field compact" value={flow} onChange={(event) => setFlow(event.target.value)}>{flows.map((item) => <option key={item} value={item}>flow_segment {item}</option>)}</select>
        <select className="field compact" value={span} onChange={(event) => setSpan(event.target.value)}>{spans.map((item) => <option key={item} value={item}>span_id {item}</option>)}</select>
        <select className="field compact" value={layer} onChange={(event) => setLayer(event.target.value)}>{layers.map((item) => <option key={item} value={item}>source_layer {item}</option>)}</select>
        <select className="field compact" value={runId} onChange={(event) => setRunId(event.target.value)}>{runIds.map((item) => <option key={item} value={item}>run_id {item}</option>)}</select>
        <select className="field compact" value={revision} onChange={(event) => setRevision(event.target.value)}>{revisions.map((item) => <option key={item} value={item}>revision_id {item}</option>)}</select>
        <select className="field compact" value={artifact} onChange={(event) => setArtifact(event.target.value)}>{artifacts.map((item) => <option key={item} value={item}>artifact_ref {item}</option>)}</select>
        <select className="field compact min-w-0" value={code} onChange={(event) => setCode(event.target.value)}>{codes.map((item) => <option key={item}>{item}</option>)}</select>
      </div>
    </div>
    <div className="min-h-0 overflow-auto pr-1 font-mono text-[11px]">
      {viewMode === "compact" && groupedIssues.map((item) => <div key={item.signature} className={`agent-card mb-2 ${item.issue.severity === "fatal" || item.issue.severity === "error" ? "danger" : item.issue.severity === "warning" ? "paused" : ""}`}>
        <div className="flex items-center justify-between gap-2"><b className="truncate">{item.issue.code}</b><span className="mini-chip">{item.count}x | {item.issue.severity} | {item.issue.source}</span></div>
        <div className="mt-1 whitespace-pre-wrap break-words text-slate-200">{item.issue.message}</div>
        <div className="mt-1 grid grid-cols-2 gap-1 text-slate-500"><span className="truncate">node {item.issue.node_id || "-"}</span><span className="truncate">group {issueGroupId(item.issue) || "-"}</span><span className="truncate">span {issueSpanId(item.issue) || "-"}</span><span className="truncate">flow {issueFlowSegment(item.issue) || "-"}</span><span className="truncate">layer {issueSourceLayer(item.issue) || "-"}</span><span className="truncate">run {item.issue.run_id || "-"}</span><span className="truncate">first {item.firstTimestamp || "-"}</span><span className="truncate">last {item.lastTimestamp || "-"}</span></div>
        <div className="mt-2 flex flex-wrap gap-1"><button className="mini-chip" onClick={() => copyIssueGroup(item)}>Copy group JSON</button><button className="mini-chip" onClick={() => copyIssue(item.issue)}>Copy latest JSON</button>{item.issue.node_id && <button className="mini-chip" onClick={() => jumpIssueNode(item.issue)}>Jump Node</button>}{item.issue.artifact_ref && <button className="mini-chip" onClick={() => openIssueArtifact(item.issue)}>Open artifact</button>}</div>
      </div>)}
      {viewMode === "raw" && visible.map((issue, index) => <div key={`${issue.timestamp}-${issue.code}-${index}`} className={`agent-card mb-2 ${issue.severity === "fatal" || issue.severity === "error" ? "danger" : issue.severity === "warning" ? "paused" : ""}`}>
        <div className="flex items-center justify-between gap-2"><b className="truncate">{issue.code}</b><span className="mini-chip">{issue.severity} | {issue.source}</span></div>
        <div className="mt-1 whitespace-pre-wrap break-words text-slate-200">{issue.message}</div>
        <div className="mt-1 grid grid-cols-2 gap-1 text-slate-500"><span className="truncate">node {issue.node_id || "-"}</span><span className="truncate">group {issueGroupId(issue) || "-"}</span><span className="truncate">span {issueSpanId(issue) || "-"}</span><span className="truncate">flow {issueFlowSegment(issue) || "-"}</span><span className="truncate">layer {issueSourceLayer(issue) || "-"}</span><span className="truncate">run {issue.run_id || "-"}</span><span className="truncate">rev {issue.revision_id || "-"}</span><span className="truncate">artifact {issue.artifact_ref || "-"}</span><span className="truncate">{issue.timestamp || "-"}</span></div>
        <div className="mt-2 flex flex-wrap gap-1"><button className="mini-chip" onClick={() => copyIssue(issue)}>Copy JSON</button>{issue.node_id && <button className="mini-chip" onClick={() => jumpIssueNode(issue)}>Jump Node</button>}{issue.artifact_ref && <button className="mini-chip" onClick={() => openIssueArtifact(issue)}>Open artifact</button>}</div>
      </div>)}
      {!visible.length && <div className="rounded border border-cyanGlow/10 bg-black/20 p-3 text-sm text-slate-400">No debug issues captured.</div>}
    </div>
  </div>;
}

function FlowCoveragePanel({ issues }: { issues: DebugIssue[] }) {
  const trace = useTrace();
  const runtime = trace.runtime;
  const report = asRecord(runtime?.flowCoverage);
  const coverage = asRecord(report.coverage ?? runtime?.manifest?.flow_coverage);
  const segments = Object.entries(asRecord(report.segments ?? coverage.segments));
  const missingDetector = asRecord(report.missing_span_detector);
  const findings = asArray(missingDetector.findings);
  const flowIssues = issues.filter((issue) => issueFlowSegment(issue));
  const failed = segments.filter(([, raw]) => String(asRecord(raw).status || "") === "failed").length;
  const missing = segments.filter(([, raw]) => String(asRecord(raw).status || "") === "missing").length;
  const copyReport = () => {
    void navigator.clipboard?.writeText(JSON.stringify(report, null, 2));
    logStore.appendEvent({ type: "log", level: "info", agent: "debug", message: "Copied runtime_flow_coverage_report.json" });
  };
  const copySegment = (segmentId: string, value: Record<string, unknown>) => {
    void navigator.clipboard?.writeText(JSON.stringify({ segmentId, ...value }, null, 2));
    logStore.appendEvent({ type: "log", level: "info", agent: "debug", message: `Copied flow coverage segment ${segmentId}` });
  };
  return <div className="grid h-full min-h-0 grid-rows-[auto_1fr] gap-3">
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2"><h2 className="font-bold">Flow Coverage</h2><button className="chip" onClick={copyReport}>Copy report JSON</button></div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <TraceMini title="flow_coverage" value={coverage ? `${String(coverage.ok ?? "unknown")} | ${segments.length} segments` : "No runtime flow_coverage yet"} tone={coverage?.ok === false ? "warning" : "info"} />
        <TraceMini title="missing-span detector" value={`${String(missingDetector.finding_count ?? findings.length)} findings | ${String(missingDetector.missing_span_count ?? missing)} missing`} tone={findings.length || missing ? "warning" : "info"} />
        <TraceMini title="Segment health table" value={`${failed} failed | ${missing} missing | ${flowIssues.length} issue-linked`} tone={failed || missing ? "warning" : "info"} />
        <TraceMini title="open artifact/trace/issue actions" value="copy segment, jump node, open issue artifact" tone="info" />
      </div>
    </div>
    <div className="min-h-0 overflow-auto pr-1">
      <div className="mb-3 grid gap-2">
        {segments.map(([segmentId, raw]) => {
          const segment = asRecord(raw);
          const status = String(segment.status || "missing");
          const linkedIssues = flowIssues.filter((issue) => issueFlowSegment(issue) === segmentId);
          return <div key={segmentId} className={`agent-card ${status === "failed" ? "danger" : status === "started" ? "running" : status === "missing" ? "paused" : ""}`}>
            <div className="flex items-center justify-between gap-2"><b className="truncate">{String(segment.label || segmentId)}</b><span className="mini-chip">{status} | {String(segment.owner_layer || "-")}</span></div>
            <div className="mt-1 grid grid-cols-2 gap-1 font-mono text-[11px] text-slate-400"><span className="truncate">flow_segment {segmentId}</span><span className="truncate">last issue {String(segment.last_issue_code || "-")}</span><span className="truncate">first {String(segment.first_timestamp || "-")}</span><span className="truncate">last {String(segment.last_timestamp || "-")}</span><span className="truncate">spans {asArray(segment.span_ids).length}</span><span className="truncate">issues {linkedIssues.length}</span></div>
            <div className="mt-2 flex flex-wrap gap-1"><button className="mini-chip" onClick={() => copySegment(segmentId, segment)}>Copy segment</button>{linkedIssues[0]?.node_id && <button className="mini-chip" onClick={() => traceStore.select(String(linkedIssues[0].node_id))}>Jump issue node</button>}{linkedIssues[0]?.artifact_ref && <button className="mini-chip" onClick={() => logStore.appendEvent({ type: "log", level: "info", agent: "debug", message: `Open flow issue artifact: ${linkedIssues[0].artifact_ref}` })}>Open artifact</button>}</div>
          </div>;
        })}
        {!segments.length && <div className="rounded border border-cyanGlow/10 bg-black/20 p-3 text-sm text-slate-400">No Flow Coverage report captured yet. Runtime will emit runtime_flow_coverage_report.json after start.</div>}
      </div>
      <ClusterSection title="Missing Span Findings" rows={findings} empty="No missing-span detector finding." />
    </div>
  </div>;
}

function JobQueuePanel({ jobs, queueHealth, onSubmitJob, onCancelJob }: { jobs: AgentJob[]; queueHealth: Record<string, unknown>; onSubmitJob: (type: JobType) => void; onCancelJob: (jobId: string) => void }) {
  const visible = jobs.slice(0, 80);
  return <div className="grid h-full min-h-0 grid-rows-[auto_1fr] gap-3">
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2"><h2 className="font-bold">Agent Job Queue</h2><span className="chip">queued {String(queueHealth.queued ?? 0)} | jobs {String(queueHealth.jobs ?? jobs.length)}</span></div>
      <div className="grid grid-cols-2 gap-2">
        <button className="btn-primary" onClick={() => onSubmitJob("agent1_plan_draft")}>Create Agent 1 Plan Draft</button>
        <button className="btn-secondary" onClick={() => onSubmitJob("agent2_rtl_draft")}>Create Agent 2 RTL Draft</button>
        <button className="btn-secondary" onClick={() => onSubmitJob("debug_bundle")}>Export Debug Bundle</button>
        <button className="btn-secondary" onClick={() => onSubmitJob("full_swarm_run")}>Queue Full Swarm Run</button>
      </div>
    </div>
    <div className="min-h-0 overflow-auto pr-1">
      {visible.map((job) => <div key={job.job_id} className={`agent-card job-card ${job.status} mb-2`}>
        <div className="flex items-center justify-between gap-2"><b className="truncate">{job.type}</b><span className="mini-chip">{job.status}</span></div>
        <div className="mt-1 grid grid-cols-2 gap-1 font-mono text-[11px] text-slate-400"><span className="truncate">job {job.job_id}</span><span className="truncate">run {job.run_id || "-"}</span><span className="truncate">project {job.project_name}</span><span className="truncate">mode {job.planning_mode}</span></div>
        {job.error && <p className="mt-1 text-xs text-danger">{job.error}</p>}
        {job.artifact_refs.length > 0 && <p className="mt-1 truncate text-xs text-cyanGlow">{job.artifact_refs[0]}</p>}
        <div className="mt-2 flex gap-2"><button className="chip" onClick={() => traceStore.select(job.job_id)}>Trace by job_id</button>{["queued", "running", "paused"].includes(job.status) && <button className="chip danger" onClick={() => onCancelJob(job.job_id)}>Cancel</button>}</div>
      </div>)}
      {!visible.length && <div className="rounded border border-cyanGlow/10 bg-black/20 p-3 text-sm text-slate-400">No jobs yet. Draft and full-run jobs will appear here.</div>}
    </div>
  </div>;
}

function Agent1ClusterCouncilPanel() {
  const trace = useTrace();
  const cluster = (trace.runtime?.manifest?.agent1_cluster_council ?? {}) as Record<string, unknown>;
  const sessions = Object.entries(asRecord(cluster.group_sessions));
  const assignments = asArray(cluster.cluster_assignments);
  const retries = asArray(cluster.retry_tree);
  const challenges = asArray(cluster.challenges);
  const clarification = asRecord(cluster.clarification);
  const questions = asArray(clarification.questions);
  const answers = asArray(clarification.answers);
  const pending = asArray(clarification.pending_question_ids);
  return <div className="grid h-full min-h-0 grid-rows-[auto_1fr] gap-3">
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2"><h2 className="font-bold">Agent1 Cluster Council</h2><span className="chip">mode {String(cluster.mode ?? "legacy")}</span></div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <TraceMini title="Cluster Map" value={`assignments ${assignments.length} | topology ${String(cluster.topology_hash ?? "-")}`} tone="info" />
        <TraceMini title="Group Sessions" value={`${sessions.length} sessions | active ${sessions.filter(([, value]) => asRecord(value).status === "running").length}`} tone="info" />
        <TraceMini title="Retry Tree" value={`${retries.length} retries`} tone={retries.length ? "warning" : "info"} />
        <TraceMini title="Challenge Matrix" value={`${challenges.length} challenges`} tone={challenges.length ? "warning" : "info"} />
        <TraceMini title="Clarification Flow" value={`${questions.length} questions | ${answers.length} answers | ${pending.length} pending`} tone={pending.length ? "warning" : "info"} />
        <TraceMini title="per-group token/cost/latency" value={sessions.length ? "metrics captured per session" : "waiting for group-session events"} tone="info" />
      </div>
    </div>
    <div className="min-h-0 overflow-auto pr-1">
      <ClusterSection title="Cluster Map" rows={assignments} empty="No cluster assignment captured yet." />
      <div className="mb-3">
        <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">Group Sessions</div>
        <div className="grid gap-2">
          {sessions.map(([key, raw]) => {
            const session = asRecord(raw);
            const metrics = asRecord(session.metrics);
            return <div key={key} className={`agent-card ${session.status === "failed" ? "danger" : session.status === "running" ? "running" : ""}`}>
              <div className="flex items-center justify-between gap-2"><b>{String(session.group_id || key)}</b><span className="mini-chip">{String(session.status || "-")}</span></div>
              <div className="mt-1 flex flex-wrap gap-1"><span className="mini-chip">manager {String(session.manager_id || "-")}</span><span className="mini-chip">attempt {String(session.attempt || 1)}</span><span className="mini-chip">latency {String(metrics.latency_s ?? metrics.latency_ms ?? "-")}</span><span className="mini-chip">tokens {String(metrics.total_tokens ?? metrics.group_total_tokens ?? "-")}</span><span className="mini-chip">cost ${String(metrics.estimated_cost_usd ?? metrics.group_estimated_cost_usd ?? "-")}</span></div>
              <pre className="mt-2 max-h-36 overflow-auto rounded border border-cyanGlow/10 bg-black/30 p-2 text-[11px]">{JSON.stringify(session, null, 2)}</pre>
            </div>;
          })}
          {!sessions.length && <div className="rounded border border-cyanGlow/10 bg-black/20 p-3 text-sm text-slate-400">No group sessions captured yet.</div>}
        </div>
      </div>
      <ClusterSection title="Retry Tree" rows={retries} empty="No targeted group retry captured." />
      <ClusterSection title="Challenge Matrix" rows={challenges} empty="No cross-group challenge captured." />
      <ClusterSection title="Clarification Flow" rows={[...questions, ...answers]} empty="No structured clarification captured." />
    </div>
  </div>;
}

function ClusterSection({ title, rows, empty }: { title: string; rows: unknown[]; empty: string }) {
  return <div className="mb-3"><div className="mb-1 text-xs uppercase tracking-wide text-slate-400">{title}</div><div className="grid gap-2">{rows.map((row, index) => <pre key={`${title}-${index}`} className="max-h-40 overflow-auto rounded border border-cyanGlow/10 bg-black/30 p-2 font-mono text-[11px] text-slate-300">{JSON.stringify(row, null, 2)}</pre>)}{!rows.length && <div className="rounded border border-cyanGlow/10 bg-black/20 p-3 text-sm text-slate-400">{empty}</div>}</div></div>;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function Agent1CouncilPanel() {
  const council = useCouncil();
  const [selectedIteration, setSelectedIteration] = useState<number | "all">("all");
  const [conflictsOnly, setConflictsOnly] = useState(false);
  const iterations = council.iterations.length ? council.iterations : [1];
  const nodes = council.nodes.filter((node) => (selectedIteration === "all" || node.iteration === selectedIteration) && (!conflictsOnly || node.conflicts.length || ["fail", "conflict"].includes(node.status)));
  const layers: Array<[string, string]> = [["leaf", "Leaf Experts"], ["middle", "Middle Managers"], ["principal", "Principal"], ["guardrail", "Guardrails"]];
  return <div className="grid h-full min-h-0 grid-rows-[74px_1fr] gap-2"><div className="space-y-2"><div className="flex items-center justify-between"><h2 className="font-bold">Agent 1 Deep Council</h2><span className="chip">{council.hydratedFromArtifacts ? "artifact hydrated" : "live/replay"}</span></div><div className="flex flex-wrap gap-1"><button className={`chip ${selectedIteration === "all" ? "active" : ""}`} onClick={() => setSelectedIteration("all")}>All Iterations</button>{iterations.map((iteration) => <button key={iteration} className={`chip ${selectedIteration === iteration ? "active" : ""}`} onClick={() => setSelectedIteration(iteration)}>Iteration {iteration}</button>)}<button className={`chip ${conflictsOnly ? "active danger" : ""}`} onClick={() => setConflictsOnly((value) => !value)}>Show Conflicts Only</button></div></div><div className="min-h-0 overflow-auto pr-1">{layers.map(([layer, label]) => <div key={layer} className="mb-3"><div className="mb-1 text-xs uppercase tracking-wide text-slate-400">{label}</div><div className="grid gap-2">{nodes.filter((node) => node.layer === layer).map((node) => <CouncilNodeCard key={node.key} node={node} />)}</div></div>)}</div></div>;
}

function CouncilNodeCard({ node }: { node: CouncilNode }) {
  const totalTokens = Number(node.token_usage?.total_tokens ?? 0);
  const slow = Number(node.duration_ms ?? 0) > 20000;
  const expensive = totalTokens > 2000;
  const className = `council-card ${node.status} ${slow ? "slow" : ""} ${expensive ? "expensive" : ""}`;
  return <button className={className} onClick={() => councilStore.selectNode(node.key)}><div className="flex items-center justify-between gap-2"><b>{node.node_id}</b><span>{node.status}</span></div><div className="text-left text-xs text-slate-300">{node.title}</div><p>{node.summary}</p><div className="mt-1 flex flex-wrap gap-1">{node.child_ids.slice(0, 8).map((child) => <span className="mini-chip" key={child}>{child}</span>)}{node.conflicts.length > 0 && <span className="mini-chip danger">{node.conflicts.length} conflicts</span>}{node.duration_ms ? <span className="mini-chip">{node.duration_ms}ms</span> : null}{totalTokens ? <span className="mini-chip">{totalTokens} tok</span> : null}</div></button>;
}

function TraceDebugPanel() {
  const trace = useTrace();
  const [filter, setFilter] = useState("All");
  const filters = ["All", "Runtime", "Jobs", "Studio", "Intake", "LLM", "Canonical", "Defaults", "Council", "Completion", "Errors"];
  const visible = useMemo(() => trace.entries.filter((entry) => {
    if (filter === "All") return true;
    if (filter === "Errors") return ["fail", "failed", "error", "paused"].includes(entry.status.toLowerCase());
    if (filter === "Runtime") return entry.trace_file === "runtime_events";
    if (filter === "Jobs") return entry.trace_file === "live_job_events" || String(entry.payload?.job_id ?? "").length > 0;
    const textValue = `${entry.trace_file} ${entry.node_id} ${entry.event_type}`.toLowerCase();
    return textValue.includes(filter.toLowerCase());
  }).slice(-800), [trace.entries, filter]);
  const selected = trace.entries.find((entry) => entry.id === trace.selectedId) ?? visible[0] ?? null;
  const readyGate = [...trace.entries].reverse().find((entry) => entry.node_id === "AGENT1.READY_GATE");
  const completion = [...trace.entries].reverse().find((entry) => entry.node_id === "AGENT1.HANDOFF_OR_PAUSE");
  const slowest = [...trace.entries].filter((entry) => Number(entry.latency_ms ?? 0) > 0).sort((a, b) => Number(b.latency_ms ?? 0) - Number(a.latency_ms ?? 0))[0];
  const defaults = trace.entries.filter((entry) => entry.node_id === "AGENT1.DEFAULTS_APPLY").slice(-1)[0];
  const runtime = trace.runtime;
  const manifest = runtime?.manifest;
  const invariant = runtime?.invariantReport as Record<string, unknown> | null | undefined;
  const replay = runtime?.replayReport as Record<string, unknown> | null | undefined;
  const recovery = runtime?.recoveryReport as Record<string, unknown> | null | undefined;
  const modelCalls = Object.entries((manifest?.model_calls ?? {}) as Record<string, { agent?: string; status?: string; duration_ms?: number }>).slice(-8);
  const selectedArtifact = selected && Array.isArray(selected.payload.artifact_refs) ? String(selected.payload.artifact_refs[0] ?? "") : "";
  const selectedRelated = selected ? findRelatedTraceEntry(trace.entries, selected) : null;
  const copyTraceValue = (label: string, value: string) => {
    if (!value) return;
    navigator.clipboard?.writeText(value).catch(() => null);
    logStore.appendEvent({ type: "log", level: "info", agent: "system", message: `Copied ${label}: ${value}` });
  };
  const jumpToTraceEntry = (entry: TraceEntry | null, label = "related event") => {
    if (!entry) {
      logStore.appendEvent({ type: "log", level: "warning", agent: "system", message: `No ${label} found in current trace buffer` });
      return;
    }
    traceStore.select(entry.id);
    logStore.appendEvent({ type: "log", level: "info", agent: "system", message: `Jumped to ${label}: ${entry.node_id}` });
  };
  return <div className="trace-debug-shell grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-3 overflow-hidden">
    <div className="min-h-0 space-y-2">
      <div className="flex min-w-0 items-center justify-between gap-2"><h2 className="min-w-0 truncate font-bold">Trace Debug</h2><span className="chip shrink-0">{trace.hydratedFromArtifacts ? "artifact hydrated" : "live"}</span></div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <TraceMini title="Runtime" value={manifest ? `${manifest.status} | ${manifest.active_agent || "no active agent"} | ${manifest.active_node_id || "idle"}` : "No runtime manifest yet"} tone={manifest?.status === "failed" ? "warning" : "info"} />
        <TraceMini title="Invariants" value={invariant ? `${invariant.ok ? "PASS" : "FAIL"} | secret ${String(invariant.secret_scan ?? "unknown")} | ${String(invariant.event_count ?? 0)} events` : "No invariant report yet"} tone={invariant?.ok === false ? "warning" : "info"} />
        <TraceMini title="Why paused?" value={completion?.summary || readyGate?.summary || "No pause/completion trace yet"} tone={completion?.status === "paused" || readyGate?.status === "paused" ? "warning" : "info"} />
        <TraceMini title="Slowest node" value={slowest ? `${slowest.node_id} ${slowest.latency_ms}ms` : "No latency yet"} tone="info" />
        <TraceMini title="Defaults" value={defaults ? defaults.summary || "Defaults trace captured" : "No defaults trace yet"} tone="info" />
        <TraceMini title="Replay" value={replay ? `${String(replay.replay_status ?? "unknown")} | terminal ${String(replay.terminal_event_type ?? "-")}` : `${trace.files.length} trace files | ${trace.entries.length} events`} tone="info" />
      </div>
      <div className="runtime-metrics-grid">
        <div className="runtime-card">
          <div className="runtime-card-title">Queue / Recovery</div>
          <pre>{JSON.stringify({ queue: manifest?.queue ?? {}, recovery: recovery ?? null }, null, 2)}</pre>
        </div>
        <div className="runtime-card">
          <div className="runtime-card-title">Model Calls</div>
          <div className="runtime-model-table">
            {modelCalls.map(([id, call]) => <button key={id} className="runtime-model-row" onClick={() => jumpToTraceEntry(findTraceEntryByCorrelation(trace.entries, id), "model call event")} title={id}>
              <span>{String(call.agent ?? "-")}</span><span>{String(call.status ?? "-")}</span><span>{Number(call.duration_ms ?? 0)}ms</span>
            </button>)}
            {!modelCalls.length && <span className="text-slate-500">No model calls yet</span>}
          </div>
        </div>
      </div>
      <div className="trace-scrollbar flex gap-1 overflow-x-auto pb-1">{filters.map((item) => <button key={item} className={`chip shrink-0 ${filter === item ? "active" : ""}`} onClick={() => setFilter(item)}>{item}</button>)}</div>
    </div>
    <div className="trace-debug-body grid min-h-0 gap-2 overflow-hidden">
      <div className="trace-event-list trace-scrollbar min-h-0 overflow-y-auto overflow-x-hidden pr-1">
        {visible.map((entry) => <button key={entry.id} className={`agent-card trace-event-card mb-2 w-full text-left ${trace.selectedId === entry.id ? "ring-1 ring-cyanGlow" : ""}`} onClick={() => traceStore.select(entry.id)}>
          <div className="flex min-w-0 items-center justify-between gap-2"><b className="min-w-0 truncate text-xs">{entry.node_id}</b><span className="shrink-0 text-[10px]">{entry.status}</span></div>
          <p className="mt-1 truncate text-xs text-slate-300">{entry.event_type} | {entry.trace_file}</p>
          {entry.latency_ms ? <span className="mini-chip mt-2 inline-flex">{entry.latency_ms}ms</span> : null}
        </button>)}
        {!visible.length && <div className="rounded border border-cyanGlow/10 bg-black/20 p-3 text-sm text-slate-400">No trace events match this filter.</div>}
      </div>
      <div className="trace-detail trace-scrollbar min-h-0 overflow-auto rounded border border-cyanGlow/10 bg-black/20 p-3">
        {selected ? <><div className="mb-2 flex min-w-0 items-center justify-between gap-2"><b className="min-w-0 truncate">{selected.node_id}</b><span className="mini-chip shrink-0">{selected.status}</span></div><div className="mb-2 flex flex-wrap gap-1"><button className="mini-chip" onClick={() => copyTraceValue("correlation id", String(selected.payload.correlation_id ?? selected.id))}>Copy correlation id</button>{selectedArtifact && <button className="mini-chip" onClick={() => copyTraceValue("artifact path", selectedArtifact)}>Copy artifact path</button>}<button className="mini-chip" onClick={() => copyTraceValue("event JSON", JSON.stringify(selected.payload, null, 2))}>Copy event JSON</button><button className="mini-chip" onClick={() => jumpToTraceEntry(selectedRelated, "related event")}>Jump related event</button></div><pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-slate-300">{JSON.stringify(selected.payload, null, 2)}</pre></> : <p className="text-sm text-slate-400">No trace event yet.</p>}
      </div>
    </div>
  </div>;
}

function TraceMini({ title, value, tone }: { title: string; value: string; tone: "info" | "warning" }) {
  return <div className={`min-w-0 rounded border ${tone === "warning" ? "border-amber/40 text-amber" : "border-cyanGlow/20 text-slate-300"} bg-black/20 p-2`}><div className="truncate text-[10px] uppercase tracking-wide text-slate-500">{title}</div><div className="truncate">{value}</div></div>;
}

function NodeDetailPanel({ run }: { run: RunState }) {
  const council = useCouncil();
  const selected = council.nodes.find((node) => node.key === council.selectedKey) ?? council.nodes.find((node) => node.layer === "middle") ?? null;
  const bundle = [`${run.output_dir}/reports/architecture_plan.md`, ...traceArtifacts.map((name) => `${run.output_dir}/reports/${name}`), `${run.output_dir}/reports/agent1_conflict_matrix.json`, `${run.output_dir}/reports/agent1_v51_guardrail_report.json`];
  if (!selected) return <div className="h-full overflow-auto text-sm text-slate-300"><h2 className="mb-2 font-bold">Node Detail</h2><p>No Agent 1 council node selected yet.</p><p className="mt-3">Export Agent1 Debug Bundle will include plan, leaf trace, middle trace, principal trace, conflict matrix, and guardrail report when artifacts exist.</p></div>;
  return <div className="h-full overflow-auto pr-1 text-sm"><div className="mb-3 flex items-center justify-between"><h2 className="font-bold">Node Detail</h2><button className="chip" onClick={() => logStore.appendEvent({ type: "log", level: "info", agent: "agent1", message: `Export Agent1 Debug Bundle manifest: ${bundle.join(" | ")}` })}>Export Agent1 Debug Bundle</button></div><div className="agent-card mb-2"><div className="flex justify-between"><b>{selected.node_id} {selected.title}</b><span>{selected.status}</span></div><p>{selected.summary}</p></div><DetailSection title="Inputs From Leaf Experts" value={selected.child_ids} /><DetailSection title="Leaf Input Summary" value={selected.child_ids} /><DetailSection title="Middle Accepted" value={selected.accepted_decisions} /><DetailSection title="Middle Rejected" value={selected.rejected_decisions} /><DetailSection title="Middle Modified/Merged" value={selected.handoff_digest} /><DetailSection title="Unresolved Conflicts" value={selected.conflicts} /><DetailSection title="Feedback To Leaf" value={selected.feedback_digest} /><DetailSection title="Handoff To Principal" value={selected.handoff_digest} /><DetailSection title="Token / Duration" value={{ token_usage: selected.token_usage, duration_ms: selected.duration_ms }} /><DetailSection title="Open Trace Artifact" value={bundle} /></div>;
}

function ArtifactsDebugPanel({ run, onSubmitJob }: { run: RunState; onSubmitJob: (type: JobType) => void }) {
  const base = run.output_dir ? run.output_dir.replaceAll("\\", "/") : "";
  const artifacts = [
    `${base}/reports/architecture_plan.md`,
    `${base}/reports/traces/runtime_events.jsonl`,
    `${base}/reports/traces/runtime_session_manifest.json`,
    `${base}/reports/traces/runtime_invariant_report.json`,
    `${base}/reports/traces/runtime_recovery_report.json`,
    ...traceArtifacts.map((name) => `${base}/reports/${name}`),
    ...debugTraceArtifacts.map((name) => `${base}/reports/traces/${name}`),
  ].filter((item) => item && !item.startsWith("/reports"));
  return <div className="grid h-full min-h-0 grid-rows-[auto_1fr] gap-3">
    <div className="flex items-center justify-between gap-2"><div><h2 className="font-bold">Artifacts / Debug Bundle</h2><p className="text-xs text-slate-400">Debug artifact map for current run output.</p></div><button className="btn-secondary" onClick={() => onSubmitJob("debug_bundle")}>Export Debug Bundle</button></div>
    <div className="trace-scrollbar min-h-0 overflow-auto rounded border border-cyanGlow/10 bg-black/20 p-3">
      {artifacts.map((artifact) => <div key={artifact} className="mb-2 rounded border border-cyanGlow/10 bg-black/20 p-2 font-mono text-[11px] text-cyanGlow">{artifact}</div>)}
      {!artifacts.length && <p className="text-sm text-slate-400">No run output selected yet.</p>}
    </div>
  </div>;
}

function DetailSection({ title, value }: { title: string; value: unknown }) {
  return <div className="mb-2 rounded border border-cyanGlow/10 bg-black/20 p-2"><h3 className="mb-1 text-xs font-bold uppercase tracking-wide text-cyanGlow">{title}</h3><pre className="max-h-36 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-slate-300">{JSON.stringify(value, null, 2)}</pre></div>;
}

function ConsolePanel({ command, setCommand, onCommand, onApprove, canApprove }: { command: string; setCommand: (v: string) => void; onCommand: () => void; onApprove: () => void; canApprove: boolean }) {
  return <div className="grid h-full min-h-0 grid-rows-[auto_1fr] gap-3"><div className="flex gap-2"><button className="btn-success" onClick={onApprove} disabled={!canApprove} title={canApprove ? "Approve current review gate" : "Available only during PLAN_REVIEW or HUMAN_REVIEW"}><CheckCircle2 className="h-4 w-4" /> Approve OK</button><button className="btn-warning" onClick={() => setCommand("change ")}><AlertTriangle className="h-4 w-4" /> Request Change</button></div><div className="flex items-start gap-2 rounded border border-cyanGlow/30 bg-black/40 px-3 py-2 font-mono"><span className="text-cyanGlow">root@swarm:~$</span><input className="flex-1 bg-transparent text-success outline-none" maxLength={2000} value={command} onChange={(e) => setCommand(e.target.value.slice(0, 2000))} onKeyDown={(e) => { if (e.key === "Enter" && e.ctrlKey && canApprove) onApprove(); else if (e.key === "Enter") onCommand(); else if (e.key === "Escape") setCommand(""); }} /></div></div>;
}

function PlanConsole({ planText, command, setCommand, onCommand, onApprove }: { planText: string; command: string; setCommand: (v: string) => void; onCommand: () => void; onApprove: () => void }) {
  return <section className="panel grid min-h-0 grid-rows-[1fr_88px] gap-3 p-3"><pre className="overflow-auto whitespace-pre font-mono text-xs text-slate-200">{planText}</pre><div><div className="mb-2 flex gap-2"><button className="btn-success" onClick={onApprove}><CheckCircle2 className="h-4 w-4" /> Approve OK</button><button className="btn-warning" onClick={() => setCommand("change ")}><AlertTriangle className="h-4 w-4" /> Request Change</button></div><div className="flex items-center gap-2 rounded border border-cyanGlow/30 bg-black/40 px-3 py-2 font-mono"><span className="text-cyanGlow">root@swarm:~$</span><input className="flex-1 bg-transparent text-success outline-none" maxLength={2000} value={command} onChange={(e) => setCommand(e.target.value.slice(0, 2000))} onKeyDown={(e) => { if (e.key === "Enter" && e.ctrlKey) onApprove(); else if (e.key === "Enter") onCommand(); else if (e.key === "Escape") setCommand(""); }} /></div></div></section>;
}

function StatusBar({ run, connection, tokenTotal, cost, mode, newLogs }: { run: RunState; connection: ConnectionState; tokenTotal: number | null; cost: number | null; mode: PlanningMode; newLogs: number }) {
  const tokenText = tokenTotal === null || Number.isNaN(tokenTotal) ? "unknown" : String(tokenTotal);
  const costText = cost === null || Number.isNaN(cost) ? "unknown" : `$${cost.toFixed(4)}`;
  return <footer className="flex items-center gap-4 border-t border-cyanGlow/20 bg-[#06101e] px-3 font-mono text-[11px] text-slate-300"><span>{connection}</span><span>STATE {run.status}</span><span>PID {run.pid ?? "-"}</span><span>TOK {tokenText} | {costText}</span><span>MODE {mode}</span><span>{newLogs} new</span></footer>;
}

function SettingWorkspace({ settings, setSettings, onDebugIssue }: { settings: SettingsPayload | null; setSettings: (v: SettingsPayload) => void; onDebugIssue: (issue: Partial<DebugIssue> & { code: string; message: string }) => void }) {
  const [draft, setDraft] = useState<SettingsPayload | null>(settings);
  const [status, setStatus] = useState("");
  const [testing, setTesting] = useState(false);
  const [cooldown, setCooldown] = useState(false);
  useEffect(() => setDraft(settings), [settings]);
  if (!draft) return <section className="panel h-full p-5"><h2 className="text-xl font-bold">Studio Settings</h2><p className="mt-3 text-sm text-slate-400">Settings unavailable while backend is disconnected.</p></section>;
  const activeRef = draft.credentialRefs.find((ref) => ref.id === draft.activeKeyRef) ?? draft.credentialRefs[0];
  const activeHealth = draft.credentialHealth?.[draft.activeKeyRef] ?? "unchecked";
  const runConnectionTest = async () => {
    if (testing || cooldown) return;
    setTesting(true);
    setStatus("Testing auth via chat/completions...");
    try {
      const result = await testConnection({ endpoint: draft.endpoint, model: draft.model, apiKeyRef: draft.activeKeyRef });
      setStatus(`${result.ok ? "PASS" : "FAIL"}: ${result.message}`);
      const refreshed = await getSettings();
      setSettings(refreshed);
      setDraft(refreshed);
    } catch (error) {
      setStatus(`FAIL: ${String(error)}`);
      onDebugIssue({ severity: "error", source: "frontend", code: "settings_test_connection_failed", message: `Test Connection failed: ${String(error)}`, details: { error: String(error) } });
      getSettings().then((refreshed) => { setSettings(refreshed); setDraft(refreshed); }).catch((refreshError) => onDebugIssue({ severity: "warning", source: "frontend", code: "settings_refresh_after_test_failed", message: `Settings refresh failed after Test Connection: ${String(refreshError)}`, details: { error: String(refreshError) } }));
    } finally {
      setTesting(false);
      setCooldown(true);
      window.setTimeout(() => setCooldown(false), 3000);
    }
  };
  return <section className="setting-workspace panel grid h-full min-h-0 grid-rows-[auto_1fr_auto] gap-4 p-5">
    <div><div className="field-kicker">Workspace</div><h2 className="text-xl font-bold">Studio Settings</h2><p className="text-sm text-slate-400">Runtime endpoint, model, checkpoints, outputs, and credential reference.</p></div>
    <div className="grid min-h-0 gap-3 overflow-auto lg:grid-cols-2">
      <label className="setting-card"><span className="field-kicker">Endpoint</span><input className="input font-mono" value={draft.endpoint} onChange={(e) => setDraft({ ...draft, endpoint: e.target.value })} /></label>
      <label className="setting-card"><span className="field-kicker">Model</span><input className="input font-mono" value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })} /></label>
      <label className="setting-card"><span className="field-kicker">Credential Reference</span><select className="input" value={draft.activeKeyRef} onChange={(e) => setDraft({ ...draft, activeKeyRef: e.target.value })}>{draft.credentialRefs.map((ref) => <option key={ref.id} value={ref.id}>{ref.label}</option>)}</select></label>
      <div className="setting-card text-sm text-slate-300">Server-side secret: <span className={activeRef?.hasSecret ? "text-success" : "text-danger"}>{activeRef?.hasSecret ? "configured" : "missing"}</span>{activeRef && <span> ({activeRef.source})</span>}<br />Auth health: <span className={activeHealth === "valid" ? "text-success" : activeHealth === "invalid" || activeHealth === "missing" ? "text-danger" : "text-amber"}>{activeHealth}</span><br />Browser never sees raw secrets.</div>
      <label className="setting-card"><span className="field-kicker">Checkpoint DB</span><input className="input font-mono" value={draft.checkpoint_db} onChange={(e) => setDraft({ ...draft, checkpoint_db: e.target.value })} /></label>
      <label className="setting-card"><span className="field-kicker">Output Root</span><input className="input font-mono" value={draft.output_root} onChange={(e) => setDraft({ ...draft, output_root: e.target.value })} /></label>
      <div className="setting-card lg:col-span-2"><div className="field-kicker">Admin key rotation</div><div className="font-mono text-sm text-cyanGlow">python -m studio.backend.secret_admin set-owner-key</div><p className="mt-2 text-xs text-slate-400">Update owner key on server using local admin command. No raw API key field exists in web UI.</p></div>
    </div>
    <div className="flex items-center justify-end gap-2"><span className="mr-auto text-sm text-amber">{status}</span><button className="btn-secondary" disabled={testing || cooldown} onClick={runConnectionTest}>{testing ? "Testing..." : cooldown ? "Cooldown..." : "Test Connection"}</button><button className="btn-primary" onClick={async () => { try { const saved = await saveSettings(draft); setSettings(saved); setDraft(saved); setStatus("SAVE PASS"); } catch (error) { setStatus(`SAVE FAIL: ${String(error)}`); onDebugIssue({ severity: "error", source: "frontend", code: "settings_save_failed", message: `Settings save failed: ${String(error)}`, details: { error: String(error) } }); } }}>Save</button></div>
  </section>;
}

function AccountWorkspace({ settings, activeHealth, connection }: { settings: SettingsPayload | null; activeHealth: string; connection: ConnectionState }) {
  const activeRef = settings?.credentialRefs.find((ref) => ref.id === settings.activeKeyRef) ?? settings?.credentialRefs[0];
  const providers = settings?.modelProviders ?? [];
  return <section className="account-workspace panel grid h-full min-h-0 grid-rows-[auto_1fr] gap-4 p-5">
    <div><div className="field-kicker">Workspace</div><h2 className="text-xl font-bold">Account</h2><p className="text-sm text-slate-400">Local server identity and credential health. No cloud login is stored here.</p></div>
    <div className="grid min-h-0 gap-3 overflow-auto lg:grid-cols-2">
      <div className="setting-card"><div className="field-kicker">Connection</div><div className="mt-2 flex items-center gap-2 text-lg font-bold">{connection === "Connected" ? <Wifi className="h-5 w-5 text-success" /> : <WifiOff className="h-5 w-5 text-danger" />}{connection}</div></div>
      <div className="setting-card"><div className="field-kicker">Active credential ref</div><div className="mt-2 font-mono text-cyanGlow">{settings?.activeKeyRef ?? "owner"}</div><p className="mt-2 text-xs text-slate-400">{activeRef?.label ?? "Owner key"} | {activeRef?.source ?? "server"}</p></div>
      <div className="setting-card"><div className="field-kicker">Server-side secret</div><div className={activeRef?.hasSecret ? "text-success" : "text-danger"}>{activeRef?.hasSecret ? "configured" : "missing"}</div></div>
      <div className="setting-card"><div className="field-kicker">Auth health</div><div className={activeHealth === "valid" ? "text-success" : activeHealth === "invalid" || activeHealth === "missing" ? "text-danger" : "text-amber"}>{activeHealth}</div></div>
      <div className="setting-card lg:col-span-2"><div className="field-kicker">Model providers</div><div className="mt-2 grid gap-2 md:grid-cols-2">{providers.length ? providers.map((provider) => <div key={provider.id} className="rounded border border-cyanGlow/10 bg-black/20 p-2 text-sm"><b>{provider.label}</b><div className="text-xs text-slate-400">{provider.kind} | {provider.enabled ? "enabled" : "disabled"}</div></div>) : <p className="text-sm text-slate-400">Provider registry unavailable.</p>}</div></div>
      <div className="setting-card lg:col-span-2"><div className="field-kicker">Owner key update</div><div className="font-mono text-sm text-cyanGlow">python -m studio.backend.secret_admin set-owner-key</div></div>
    </div>
  </section>;
}

function AboutWorkspace() {
  const debugTabs = [
    ["Operations Log", "Live timeline. Start here. Red/error rows tell you which stage, agent, and message changed."],
    ["Signoff", "Agent1 release court. Check decision, failed gate, finding codes, benchmark result, and handoff_allowed."],
    ["Raw Issues", "Deepest issue list. Filter by severity/source/code, copy JSON, then match run_id, gate, artifact_ref, node_id."],
    ["Flow Coverage", "Shows which flow segment is waiting, failed, or passed. Use it when the run feels stuck."],
    ["Trace Debug", "Low-level event stream from browser, backend, runner, Agent1 intake, council, guardrail, and completion."],
    ["Cluster Council", "Agent1 group-session view. Use it for Principal/Middle/Leaf disagreements, retries, and HITL reasons."],
    ["Artifacts", "Generated files and debug bundle entry point. Use when you need the exact report path."],
  ];
  const issueFields = [
    ["severity", "fatal/error blocks flow; warning needs review; info/trace is context."],
    ["source", "Where it came from: frontend, backend, runtime, agent1, signoff, benchmark, handoff."],
    ["code", "Stable machine code. Best search key in repo and artifacts."],
    ["gate", "Industrial signoff gate G00-G12. Tells which release rule failed."],
    ["artifact_ref", "File or report to inspect next."],
    ["run_id / revision_id", "Confirms issue belongs to the current run, not stale output."],
  ];
  const debugFlow = [
    "Open Debug -> Operations Log and look for first red/error row.",
    "Open Raw Issues, filter severity=error/fatal, then copy the issue JSON.",
    "Read source + code + gate. These three usually identify the subsystem.",
    "If artifact_ref exists, open Debug -> Artifacts and inspect that file.",
    "For Agent1 release blocks, open Signoff and check failed gate plus handoff_allowed.",
    "For group debate/HITL, open Cluster Council or Trace Debug and follow span_id/parent_span_id.",
    "After fixing input or settings, return Project and send change/follow-up or press START again.",
  ];
  return <section className="about-workspace panel grid h-full min-h-0 grid-rows-[auto_1fr] gap-4 p-5">
    <div><div className="field-kicker">Workspace guide</div><h2 className="text-xl font-bold">About CoreWeaver Studio</h2><p className="text-sm text-slate-400">SWARM AI STUDIO V7.3 keeps Python core logic behind a React cockpit. Project runs work. Debug explains what happened.</p></div>
    <div className="grid min-h-0 gap-3 overflow-auto lg:grid-cols-2">
      <div className="setting-card"><div className="field-kicker">Architecture</div><p>Backend: Python + FastAPI + WebSocket runtime events.</p><p>Frontend: React + Tailwind workspace shell.</p></div>
      <div className="setting-card"><div className="field-kicker">Golden rules</div><p>Formal before simulation. No UVM. cocotb plus SystemVerilog/SVA. Agent2 must not rename locked ports.</p></div>
      <div className="setting-card"><div className="field-kicker">Docs</div><p className="font-mono text-cyanGlow">ARCHITECTURE.md</p><p className="font-mono text-cyanGlow">docs/design-docs/index.md</p><p className="font-mono text-cyanGlow">docs/GITHUB_PUBLISHING.md</p></div>
      <div className="setting-card"><div className="field-kicker">Safety</div><p>Secrets stay server-side. Debug artifacts are redacted and sandboxed under run output paths.</p></div>
      <div className="setting-card lg:col-span-2">
        <div className="field-kicker">Quick map</div>
        <div className="mt-3 grid gap-2 md:grid-cols-5">
          {[
            ["Project", "Write requirement, attach files, start/stop, approve plan."],
            ["Debug", "Read logs, raw issues, traces, signoff, artifacts."],
            ["Setting", "Endpoint, model, checkpoint DB, output root."],
            ["Account", "Credential ref and local server auth health."],
            ["About", "This guide and operating rules."],
          ].map(([title, body]) => <div key={title} className="rounded border border-cyanGlow/10 bg-black/20 p-3 text-sm"><b>{title}</b><p className="mt-1 text-xs text-slate-400">{body}</p></div>)}
        </div>
      </div>
      <div className="setting-card lg:col-span-2">
        <div className="field-kicker">How to read Debug</div>
        <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {debugTabs.map(([title, body]) => <div key={title} className="rounded border border-cyanGlow/10 bg-black/20 p-3 text-sm"><b className="text-cyanGlow">{title}</b><p className="mt-1 text-xs leading-5 text-slate-400">{body}</p></div>)}
        </div>
      </div>
      <div className="setting-card">
        <div className="field-kicker">Debug issue fields</div>
        <div className="mt-3 grid gap-2">
          {issueFields.map(([field, meaning]) => <div key={field} className="rounded border border-cyanGlow/10 bg-black/20 p-2 text-sm"><span className="font-mono text-cyanGlow">{field}</span><p className="mt-1 text-xs leading-5 text-slate-400">{meaning}</p></div>)}
        </div>
      </div>
      <div className="setting-card">
        <div className="field-kicker">When something fails</div>
        <ol className="mt-3 space-y-2 text-sm text-slate-300">
          {debugFlow.map((step) => <li key={step} className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" /><span>{step}</span></li>)}
        </ol>
      </div>
      <div className="setting-card lg:col-span-2">
        <div className="field-kicker">Signoff gates G00-G12</div>
        <p className="mt-2 text-sm text-slate-300">Agent1 must pass Industrial Signoff before Agent2 starts. G00 checks run/session integrity. G01 checks requirement coverage. G02 checks council convergence. G03 checks artifact currentness. G04 checks schema/contract stability. G05 checks memory/register/IRQ consistency. G06 checks formal-first readiness. G07 checks safety/security/power/clock/reset. G08 checks numeric evidence provenance. G09 checks independent critic. G10 checks waivers. G11 checks Agent2 handoff readiness. G12 checks benchmark proof.</p>
      </div>
    </div>
  </section>;
}

function OutputConflictDialog({ conflict, onFresh, onContinue, onRename, onCancel }: { conflict: { message: string; payload: StartPayload } | null; onFresh: () => void; onContinue: () => void; onRename: () => void; onCancel: () => void }) {
  return <Dialog.Root open={Boolean(conflict)} onOpenChange={(open) => { if (!open) onCancel(); }}><Dialog.Portal><Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur" /><Dialog.Content className="panel fixed left-1/2 top-1/2 w-[640px] -translate-x-1/2 -translate-y-1/2 p-5"><Dialog.Title className="mb-3 text-xl font-bold">Existing Output Detected</Dialog.Title><p className="mb-3 text-sm text-slate-300">This project output already has files. Pick one policy before START so old checkpoints and stale logs cannot leak into a fresh run.</p><pre className="mb-4 max-h-28 overflow-auto whitespace-pre-wrap rounded border border-cyanGlow/20 bg-black/30 p-3 font-mono text-xs text-amber">{conflict?.message}</pre><div className="grid grid-cols-2 gap-2"><button className="btn-primary" onClick={onFresh}>Archive + Fresh Run</button><button className="btn-secondary" onClick={onContinue}>Continue Existing</button><button className="btn-warning" onClick={onRename}>Rename Output</button><button className="btn-danger" onClick={onCancel}>Cancel</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>;
}

type StudioWindow = Window & { __swarmStudioRoot?: ReturnType<typeof createRoot> };
const studioWindow = window as StudioWindow;
let rootHost = document.getElementById("root")!;
const hasExistingReactRoot = Object.getOwnPropertyNames(rootHost).some((key) => key.startsWith("__reactContainer$") || key.startsWith("__reactFiber$"));
if (!studioWindow.__swarmStudioRoot && hasExistingReactRoot) {
  const replacement = rootHost.cloneNode(false) as HTMLElement;
  rootHost.replaceWith(replacement);
  rootHost = replacement;
}
const root = studioWindow.__swarmStudioRoot ?? createRoot(rootHost);
studioWindow.__swarmStudioRoot = root;
root.render(<App />);
