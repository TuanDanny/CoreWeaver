import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import * as Dialog from "@radix-ui/react-dialog";
import { Activity, AlertTriangle, Bot, CheckCircle2, Cpu, FileText, Rocket, Settings, Square, Terminal, Wifi, WifiOff } from "lucide-react";
import "./styles.css";
import { getCurrentState, getSettings, previewArtifact, resumeRun, saveSettings, startRun, stopRun, testConnection, WS_BASE } from "./api";
import { councilStore, useCouncil } from "./councilStore";
import { logStore, useLogs } from "./logStore";
import { traceStore, useTrace } from "./traceStore";
import type { ConnectionState, CouncilNode, PlanningMode, RunState, SettingsPayload, StageName, StartPolicy, StudioEvent } from "./types";

const stages: StageName[] = ["planning", "rtl", "formal", "hitl", "dv", "physical", "signoff"];
const stageLabels: Record<StageName, string> = { planning: "Planning", rtl: "RTL", formal: "Formal", hitl: "HITL", dv: "DV", physical: "Physical", signoff: "Signoff" };
const agentLabels: Record<string, string> = { agent1: "Architect", agent2: "RTL", agent3: "DV", agent4: "Physical", agent5: "Formal", agent6: "Wiki" };
type SidebarView = "project" | "agents" | "logs" | "plan" | "settings" | "artifacts" | "debug" | "wiki";
type RightTab = "plan" | "council" | "trace" | "node" | "console";
type LogFilter = "All" | "Agent1" | "Leaf" | "Middle" | "Principal" | "Errors";
type StartPayload = { requirement: string; project_name: string; output_dir: string; planning_mode: PlanningMode; checkpoint_db: string; apiKeyRef: string; startPolicy?: StartPolicy };
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
];

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
};

function closeRunningStages(stages: RunState["stages"], status: "stopped" | "failed") {
  return Object.fromEntries(Object.entries(stages).map(([stage, value]) => [stage, ["running", "starting"].includes(String(value)) ? status : value])) as RunState["stages"];
}

function closeRunningAgents(agents: RunState["agents"], status: "stopped" | "failed") {
  return Object.fromEntries(Object.entries(agents).map(([agent, value]) => {
    const agentStatus = String(value?.status ?? "");
    return [agent, ["running", "starting"].includes(agentStatus) ? { ...value, status, action: status } : value];
  })) as RunState["agents"];
}

function reduceEvent(state: RunState, event: StudioEvent): RunState {
  if (event.type === "ping") return state;
  const eventRunId = typeof event.run_id === "string" ? event.run_id : "";
  if (eventRunId && state.run_id && eventRunId !== state.run_id) return state;
  const base = eventRunId && !state.run_id ? { ...state, run_id: eventRunId } : state;
  if (event.type === "stage" && event.stage) return { ...base, stages: { ...base.stages, [event.stage]: String(event.status ?? "idle") } };
  if (event.type === "agent_action" && event.agent) {
    return { ...base, agents: { ...base.agents, [event.agent]: { ...(base.agents[event.agent] ?? {}), status: String(event.status ?? "info"), action: String(event.action ?? "activity") } } };
  }
  if (event.type === "metric" && event.name) return { ...base, metrics: { ...base.metrics, [String(event.name)]: event.value } };
  if (event.type === "pause") return { ...base, status: "paused", pause: event, current_plan_path: String(event.plan_path ?? base.current_plan_path ?? "") };
  if (event.type === "process_start") return { ...base, status: "running", pid: Number(event.pid) || base.pid };
  if (event.type === "process_exit") {
    if (base.status === "done") return { ...base, pid: null };
    if (base.status === "failed") return { ...base, pid: null };
    if (base.status === "paused" && Number(event.returncode ?? 0) === 0) return { ...base, pid: null };
    const terminal = Number(event.returncode ?? 0) === 0 ? "stopped" : "failed";
    return { ...base, status: terminal, pid: null, stages: closeRunningStages(base.stages, terminal), agents: closeRunningAgents(base.agents, terminal) };
  }
  if (event.type === "done") return { ...base, status: "done", pause: null };
  if (event.type === "error") return { ...base, status: "failed", stages: closeRunningStages(base.stages, "failed"), agents: closeRunningAgents(base.agents, "failed") };
  return base;
}

function App() {
  const [run, setRun] = useState<RunState>(emptyRun);
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("Disconnected");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [requirement, setRequirement] = useState(emptyRun.requirement);
  const [projectName, setProjectName] = useState(emptyRun.project_name);
  const [outputDir, setOutputDir] = useState(emptyRun.output_dir);
  const [planningMode, setPlanningMode] = useState<PlanningMode>("normal");
  const [planText, setPlanText] = useState("Plan preview will appear here when Agent 1 pauses for review.");
  const [command, setCommand] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [newLogs, setNewLogs] = useState(0);
  const [activeView, setActiveView] = useState<SidebarView>("project");
  const [rightTab, setRightTab] = useState<RightTab>("plan");
  const [logFilter, setLogFilter] = useState<LogFilter>("All");
  const [outputConflict, setOutputConflict] = useState<{ message: string; payload: StartPayload } | null>(null);
  const [timelineWidth, setTimelineWidth] = useState(() => Number(localStorage.getItem("swarm.timelineWidth") ?? 290));
  const [rightWidth, setRightWidth] = useState(() => Number(localStorage.getItem("swarm.rightWidth") ?? 420));
  const logPanelRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);

  useEffect(() => {
    getSettings().then((value) => {
      setSettings(value);
      setOutputDir(`${value.output_root.replaceAll("\\", "/")}/${projectName}`);
    }).catch(() => setConnection("Disconnected"));
    getCurrentState().then((state) => {
      if (state.run_id) setRun(state);
    }).catch(() => null);
  }, []);

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
        logStore.appendEvent(event);
        councilStore.appendEvent(event);
        traceStore.appendEvent(event);
        setRun((previous) => reduceEvent(previous, event));
      };
      ws.onclose = () => {
        if (closed) return;
        setConnection("Reconnecting");
        window.setTimeout(connect, retry);
        retry = Math.min(retry * 1.5, 5000);
      };
      ws.onerror = () => setConnection("Disconnected");
    };
    connect();
    return () => {
      closed = true;
      ws?.close();
    };
  }, [run.run_id]);

  useEffect(() => {
    if (run.current_plan_path) {
      previewArtifact(run.current_plan_path).then((preview) => setPlanText(preview.text)).catch((error) => setPlanText(`Plan preview unavailable:\n${String(error)}`));
    }
  }, [run.current_plan_path]);

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

  const tokenTotal = Number(run.metrics.codex_total_tokens ?? 0);
  const cost = Number(run.metrics.codex_estimated_cost_usd ?? 0);
  const activeCredentialHealth = settings?.credentialHealth?.[settings.activeKeyRef] ?? "unchecked";
  const startBlockedReason = activeCredentialHealth === "missing"
    ? "Credential owner missing. Update server key before Start."
    : activeCredentialHealth === "invalid"
      ? "Credential owner invalid. Test Connection or update server key before Start."
      : "";

  const navigate = useCallback((view: SidebarView) => {
    setActiveView(view);
    if (view === "settings") {
      setSettingsOpen(true);
      return;
    }
    if (view === "logs") setLogFilter("All");
    if (view === "plan") setRightTab("plan");
    if (view === "agents") setRightTab("council");
    if (view === "debug") setRightTab("trace");
    if (view === "artifacts") setRightTab("council");
    if (view === "wiki") logStore.appendEvent({ type: "log", level: "info", agent: "agent6", message: "Future Wiki coming soon: Agent6 not implemented yet." });
  }, []);

  const startResize = useCallback((target: "timeline" | "right", startX: number) => {
    const startTimeline = timelineWidth;
    const startRight = rightWidth;
    let frame = 0;
    const onMove = (event: PointerEvent) => {
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const dx = event.clientX - startX;
        if (target === "timeline") {
          const next = Math.max(220, Math.min(520, startTimeline + dx));
          setTimelineWidth(next);
          localStorage.setItem("swarm.timelineWidth", String(next));
        } else {
          const next = Math.max(320, Math.min(760, startRight - dx));
          setRightWidth(next);
          localStorage.setItem("swarm.rightWidth", String(next));
        }
      });
    };
    const onUp = () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp, { once: true });
  }, [timelineWidth, rightWidth]);

  const doStart = useCallback(async (payload: StartPayload, clearStores = true) => {
    try {
      if (clearStores) {
        logStore.clear();
        councilStore.clear();
        traceStore.clear();
        setPlanText("Plan preview will appear here when Agent 1 pauses for review.");
      }
      const state = await startRun(payload);
      setRun(state);
      logStore.appendEvent({ type: "log", level: "info", message: `run started ${state.run_id}`, agent: "system" });
    } catch (error) {
      const message = String(error);
      if (message.includes("OUTPUT_EXISTS:")) {
        setOutputConflict({ message, payload });
        logStore.appendEvent({ type: "log", level: "warning", message: "Output directory already contains files. Choose run policy.", agent: "system" });
        return;
      }
      logStore.appendEvent({ type: "error", level: "error", message: `START failed: ${message}`, agent: "system" });
      setRun((previous) => ({ ...previous, status: "failed" }));
      getSettings().then(setSettings).catch(() => null);
    }
  }, []);

  const launch = useCallback(async () => {
    await doStart({ requirement, project_name: projectName, output_dir: outputDir, planning_mode: planningMode, checkpoint_db: settings?.checkpoint_db ?? "", apiKeyRef: settings?.activeKeyRef ?? "owner" });
  }, [requirement, projectName, outputDir, planningMode, settings, doStart]);

  const stop = useCallback(async () => {
    const targetRunId = run.run_id || "current";
    try {
      logStore.appendEvent({ type: "log", level: "warning", message: `STOP requested for ${targetRunId}`, agent: "system" });
      setRun((previous) => ({ ...previous, status: previous.status === "idle" ? "idle" : "stopping" }));
      setRun(await stopRun(targetRunId));
    } catch (error) {
      logStore.appendEvent({ type: "error", level: "error", message: `STOP failed: ${String(error)}`, agent: "system" });
    }
  }, [run.run_id]);

  const approve = useCallback(async () => {
    if (!run.run_id) return;
    if (run.pause?.action_required !== "PLAN_REVIEW") {
      logStore.appendEvent({ type: "log", level: "warning", message: "Approve is disabled until Agent 1 creates an architecture plan.", agent: "console" });
      return;
    }
    try {
      setRun(await resumeRun(run.run_id, { notes: "ok", resume_action: String(run.pause?.action_required ?? ""), planning_mode: planningMode, apiKeyRef: settings?.activeKeyRef ?? "owner" }));
    } catch (error) {
      logStore.appendEvent({ type: "error", level: "error", message: `Approve failed: ${String(error)}`, agent: "system" });
    }
  }, [run.run_id, run.pause, planningMode, settings]);

  const handleCommand = useCallback(async () => {
    const text = command.trim();
    setCommand("");
    if (!text) return;
    logStore.appendEvent({ type: "log", level: "console", message: `> ${text}`, agent: "console" });
    try {
      if (text === "ok") await approve();
      else if (text === "stop") await stop();
      else if (text === "clear") logStore.clear();
      else if (text.startsWith("change ") && run.run_id) setRun(await resumeRun(run.run_id, { notes: text.slice(7), change: text.slice(7), resume_action: String(run.pause?.action_required ?? ""), planning_mode: planningMode, apiKeyRef: settings?.activeKeyRef ?? "owner" }));
      else if (run.run_id && run.pause) setRun(await resumeRun(run.run_id, { notes: text, change: text, resume_action: String(run.pause?.action_required ?? ""), planning_mode: planningMode, apiKeyRef: settings?.activeKeyRef ?? "owner" }));
      else logStore.appendEvent({ type: "log", level: "warning", message: `unknown command: ${text}`, agent: "console" });
    } catch (error) {
      logStore.appendEvent({ type: "error", level: "error", message: `Console command failed: ${String(error)}`, agent: "console" });
    }
  }, [command, approve, stop, run.run_id, run.pause, planningMode, settings]);

  return (
    <div className="min-h-screen overflow-hidden bg-cosmic text-slate-100 font-ui">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_10%,rgba(53,214,255,.18),transparent_30%),radial-gradient(circle_at_80%_0%,rgba(47,128,255,.16),transparent_28%)]" />
      <div className="relative grid h-screen grid-rows-[42px_1fr_26px]">
        <TopBar onSettings={() => setSettingsOpen(true)} connection={connection} />
        <div className="grid min-h-0" style={{ gridTemplateColumns: sidebarOpen ? "230px 1fr" : "64px 1fr" }}>
          <Sidebar open={sidebarOpen} activeView={activeView} credentialHealth={activeCredentialHealth} onToggle={() => setSidebarOpen((value) => !value)} onNavigate={navigate} />
          <main className="grid min-h-0 grid-rows-[156px_52px_1fr] gap-3 p-3">
            <LaunchPanel requirement={requirement} setRequirement={setRequirement} projectName={projectName} setProjectName={setProjectName} outputDir={outputDir} setOutputDir={setOutputDir} planningMode={planningMode} setPlanningMode={setPlanningMode} onStart={launch} onStop={stop} running={run.status === "running"} startBlockedReason={startBlockedReason} />
            <Pipeline stages={run.stages} />
            <section className="grid min-h-0 gap-2" style={{ gridTemplateColumns: `${timelineWidth}px 6px minmax(280px,1fr) 6px minmax(320px,${rightWidth}px)` }}>
              <AgentTimeline agents={run.agents} />
              <div className="splitter" title="Resize Agent Timeline / Log" onPointerDown={(event) => startResize("timeline", event.clientX)} />
              <LogPanel panelRef={logPanelRef} atBottomRef={atBottomRef} newLogs={newLogs} setNewLogs={setNewLogs} filter={logFilter} setFilter={setLogFilter} />
              <div className="splitter" title="Resize Log / Debug Panel" onPointerDown={(event) => startResize("right", event.clientX)} />
              <RightPanel activeTab={rightTab} setActiveTab={setRightTab} planText={planText} command={command} setCommand={setCommand} onCommand={handleCommand} onApprove={approve} run={run} canApprove={run.pause?.action_required === "PLAN_REVIEW"} />
            </section>
          </main>
        </div>
        <StatusBar run={run} connection={connection} tokenTotal={tokenTotal} cost={cost} mode={planningMode} newLogs={newLogs} />
      </div>
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} settings={settings} setSettings={setSettings} />
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

function TopBar({ onSettings, connection }: { onSettings: () => void; connection: ConnectionState }) {
  return <header className="glass flex items-center justify-between border-b border-cyanGlow/20 px-4">
    <div className="flex items-center gap-3 text-sm"><Cpu className="h-5 w-5 text-cyanGlow" /><span className="font-bold tracking-wide">SWARM AI STUDIO V6.5</span><span className="text-slate-400">Web Mission Control</span></div>
    <div className="flex items-center gap-3"><span className="chip">{connection === "Connected" ? <Wifi className="h-4 w-4" /> : <WifiOff className="h-4 w-4" />} {connection}</span><button className="btn-secondary" onClick={onSettings}><Settings className="h-4 w-4" /> Settings</button></div>
  </header>;
}

function Sidebar({ open, activeView, credentialHealth, onToggle, onNavigate }: { open: boolean; activeView: SidebarView; credentialHealth: string; onToggle: () => void; onNavigate: (view: SidebarView) => void }) {
  const items: Array<[React.ElementType, string, SidebarView, string, boolean]> = [
    [Rocket, "Project", "project", "Run setup", false],
    [Bot, "Agents", "agents", "Council", false],
    [Terminal, "Logs", "logs", "Filters", false],
    [FileText, "Plan Review", "plan", "Review", false],
    [Settings, "Settings", "settings", credentialHealth, false],
    [Activity, "Artifacts", "artifacts", "Preview", false],
    [AlertTriangle, "Debug Bundle", "debug", "Export", false],
    [Cpu, "Future Wiki", "wiki", "Coming soon: Agent6 not implemented yet", true],
  ];
  return <aside className="glass min-h-0 border-r border-cyanGlow/20 p-3 transition-all">
    <button className="btn-secondary mb-4 w-full" onClick={onToggle}>{open ? "Collapse" : ">>"}</button>
    <div className="space-y-2">{items.map(([Icon, label, view, badge, disabled]) => <button className={`sidebar-item ${activeView === view ? "active" : ""}`} key={view} title={badge} disabled={disabled} onClick={() => onNavigate(view)}><Icon className="h-4 w-4" />{open && <><span className="flex-1">{label}</span><span className={disabled ? "text-[10px] text-slate-500" : "text-[10px] text-cyanGlow"}>{badge}</span></>}</button>)}</div>
  </aside>;
}

function LaunchPanel(props: { requirement: string; setRequirement: (v: string) => void; projectName: string; setProjectName: (v: string) => void; outputDir: string; setOutputDir: (v: string) => void; planningMode: PlanningMode; setPlanningMode: (v: PlanningMode) => void; onStart: () => void; onStop: () => void; running: boolean; startBlockedReason: string }) {
  return <section className="panel grid grid-cols-[1.4fr_.55fr_.9fr_auto] gap-3 p-3">
    <textarea className="input font-mono" value={props.requirement} onChange={(e) => props.setRequirement(e.target.value)} />
    <div className="space-y-2"><label>Project</label><input className="input" value={props.projectName} onChange={(e) => props.setProjectName(e.target.value)} /><label>Mode</label><select className="input" value={props.planningMode} onChange={(e) => props.setPlanningMode(e.target.value as PlanningMode)}><option value="normal">Normal</option><option value="deep_planning">Deep Planning</option></select></div>
    <div className="space-y-2"><label>Output Directory</label><input className="input" value={props.outputDir} onChange={(e) => props.setOutputDir(e.target.value)} /><div className="text-xs text-slate-400">Local browser cockpit. Core engine stays Python.</div></div>
    <div className="flex flex-col justify-center gap-3"><button className="btn-primary" onClick={props.onStart} disabled={props.running || Boolean(props.startBlockedReason)}><Rocket className="h-5 w-5" /> START</button><button className="btn-danger" onClick={props.onStop}><Square className="h-5 w-5" /> STOP</button>{props.startBlockedReason && <div className="max-w-[170px] text-xs text-danger">{props.startBlockedReason}</div>}</div>
  </section>;
}

function Pipeline({ stages: values }: { stages: RunState["stages"] }) {
  return <section className="panel flex items-center gap-2 p-2">{stages.map((stage) => <div className={`stage ${values[stage]}`} key={stage}><span className="dot" />{stageLabels[stage]}<span>{values[stage]}</span></div>)}</section>;
}

function AgentTimeline({ agents }: { agents: RunState["agents"] }) {
  return <section className="panel min-h-0 overflow-auto p-3"><h2 className="mb-3 font-bold">Agent Timeline</h2><div className="space-y-2">{Object.entries(agentLabels).map(([key, label]) => <div className="agent-card" key={key}><div className="flex justify-between"><b>{key.toUpperCase()}</b><span>{agents[key]?.status ?? "idle"}</span></div><p>{label}: {agents[key]?.action ?? "Waiting"}</p></div>)}</div></section>;
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

function RightPanel(props: { activeTab: RightTab; setActiveTab: (v: RightTab) => void; planText: string; command: string; setCommand: (v: string) => void; onCommand: () => void; onApprove: () => void; run: RunState; canApprove: boolean }) {
  const tabs: Array<[RightTab, string]> = [["plan", "Plan Preview"], ["council", "Agent 1 Council"], ["trace", "Trace Debug"], ["node", "Node Detail"], ["console", "Console"]];
  return <section className="panel grid min-h-0 grid-rows-[auto_1fr] p-3"><div className="trace-scrollbar flex gap-1 overflow-x-auto pb-1">{tabs.map(([tab, label]) => <button key={tab} className={`chip shrink-0 ${props.activeTab === tab ? "active" : ""}`} onClick={() => props.setActiveTab(tab)}>{label}</button>)}</div><div className="min-h-0 overflow-hidden pt-1">{props.activeTab === "plan" && <pre className="h-full overflow-auto whitespace-pre font-mono text-xs text-slate-200">{props.planText}</pre>}{props.activeTab === "council" && <Agent1CouncilPanel />}{props.activeTab === "trace" && <TraceDebugPanel />}{props.activeTab === "node" && <NodeDetailPanel run={props.run} />}{props.activeTab === "console" && <ConsolePanel command={props.command} setCommand={props.setCommand} onCommand={props.onCommand} onApprove={props.onApprove} canApprove={props.canApprove} />}</div></section>;
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
  const filters = ["All", "Studio", "Intake", "LLM", "Canonical", "Defaults", "Council", "Completion", "Errors"];
  const visible = useMemo(() => trace.entries.filter((entry) => {
    if (filter === "All") return true;
    if (filter === "Errors") return ["fail", "failed", "error", "paused"].includes(entry.status.toLowerCase());
    const textValue = `${entry.trace_file} ${entry.node_id} ${entry.event_type}`.toLowerCase();
    return textValue.includes(filter.toLowerCase());
  }).slice(-800), [trace.entries, filter]);
  const selected = trace.entries.find((entry) => entry.id === trace.selectedId) ?? visible[0] ?? null;
  const readyGate = [...trace.entries].reverse().find((entry) => entry.node_id === "AGENT1.READY_GATE");
  const completion = [...trace.entries].reverse().find((entry) => entry.node_id === "AGENT1.HANDOFF_OR_PAUSE");
  const slowest = [...trace.entries].filter((entry) => Number(entry.latency_ms ?? 0) > 0).sort((a, b) => Number(b.latency_ms ?? 0) - Number(a.latency_ms ?? 0))[0];
  const defaults = trace.entries.filter((entry) => entry.node_id === "AGENT1.DEFAULTS_APPLY").slice(-1)[0];
  return <div className="trace-debug-shell grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-3 overflow-hidden">
    <div className="min-h-0 space-y-2">
      <div className="flex min-w-0 items-center justify-between gap-2"><h2 className="min-w-0 truncate font-bold">Trace Debug</h2><span className="chip shrink-0">{trace.hydratedFromArtifacts ? "artifact hydrated" : "live"}</span></div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <TraceMini title="Why paused?" value={completion?.summary || readyGate?.summary || "No pause/completion trace yet"} tone={completion?.status === "paused" || readyGate?.status === "paused" ? "warning" : "info"} />
        <TraceMini title="Slowest node" value={slowest ? `${slowest.node_id} ${slowest.latency_ms}ms` : "No latency yet"} tone="info" />
        <TraceMini title="Defaults" value={defaults ? defaults.summary || "Defaults trace captured" : "No defaults trace yet"} tone="info" />
        <TraceMini title="Files" value={`${trace.files.length} trace files | ${trace.entries.length} events`} tone="info" />
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
        {selected ? <><div className="mb-2 flex min-w-0 items-center justify-between gap-2"><b className="min-w-0 truncate">{selected.node_id}</b><span className="mini-chip shrink-0">{selected.status}</span></div><pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-slate-300">{JSON.stringify(selected.payload, null, 2)}</pre></> : <p className="text-sm text-slate-400">No trace event yet.</p>}
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

function DetailSection({ title, value }: { title: string; value: unknown }) {
  return <div className="mb-2 rounded border border-cyanGlow/10 bg-black/20 p-2"><h3 className="mb-1 text-xs font-bold uppercase tracking-wide text-cyanGlow">{title}</h3><pre className="max-h-36 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-slate-300">{JSON.stringify(value, null, 2)}</pre></div>;
}

function ConsolePanel({ command, setCommand, onCommand, onApprove, canApprove }: { command: string; setCommand: (v: string) => void; onCommand: () => void; onApprove: () => void; canApprove: boolean }) {
  return <div className="grid h-full min-h-0 grid-rows-[auto_1fr] gap-3"><div className="flex gap-2"><button className="btn-success" onClick={onApprove} disabled={!canApprove} title={canApprove ? "Approve architecture plan" : "Available only during PLAN_REVIEW"}><CheckCircle2 className="h-4 w-4" /> Approve OK</button><button className="btn-warning"><AlertTriangle className="h-4 w-4" /> Request Change</button></div><div className="flex items-start gap-2 rounded border border-cyanGlow/30 bg-black/40 px-3 py-2 font-mono"><span className="text-cyanGlow">root@swarm:~$</span><input className="flex-1 bg-transparent text-success outline-none" value={command} onChange={(e) => setCommand(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && e.ctrlKey && canApprove) onApprove(); else if (e.key === "Enter") onCommand(); else if (e.key === "Escape") setCommand(""); }} /></div></div>;
}

function PlanConsole({ planText, command, setCommand, onCommand, onApprove }: { planText: string; command: string; setCommand: (v: string) => void; onCommand: () => void; onApprove: () => void }) {
  return <section className="panel grid min-h-0 grid-rows-[1fr_88px] gap-3 p-3"><pre className="overflow-auto whitespace-pre font-mono text-xs text-slate-200">{planText}</pre><div><div className="mb-2 flex gap-2"><button className="btn-success" onClick={onApprove}><CheckCircle2 className="h-4 w-4" /> Approve OK</button><button className="btn-warning"><AlertTriangle className="h-4 w-4" /> Request Change</button></div><div className="flex items-center gap-2 rounded border border-cyanGlow/30 bg-black/40 px-3 py-2 font-mono"><span className="text-cyanGlow">root@swarm:~$</span><input className="flex-1 bg-transparent text-success outline-none" value={command} onChange={(e) => setCommand(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && e.ctrlKey) onApprove(); else if (e.key === "Enter") onCommand(); else if (e.key === "Escape") setCommand(""); }} /></div></div></section>;
}

function StatusBar({ run, connection, tokenTotal, cost, mode, newLogs }: { run: RunState; connection: ConnectionState; tokenTotal: number; cost: number; mode: PlanningMode; newLogs: number }) {
  return <footer className="flex items-center gap-4 border-t border-cyanGlow/20 bg-[#06101e] px-3 font-mono text-[11px] text-slate-300"><span>{connection}</span><span>STATE {run.status}</span><span>PID {run.pid ?? "-"}</span><span>TOK {tokenTotal} | ${cost.toFixed(4)}</span><span>MODE {mode}</span><span>{newLogs} new</span></footer>;
}

function SettingsDialog({ open, onOpenChange, settings, setSettings }: { open: boolean; onOpenChange: (v: boolean) => void; settings: SettingsPayload | null; setSettings: (v: SettingsPayload) => void }) {
  const [draft, setDraft] = useState<SettingsPayload | null>(settings);
  const [status, setStatus] = useState("");
  const [testing, setTesting] = useState(false);
  const [cooldown, setCooldown] = useState(false);
  useEffect(() => setDraft(settings), [settings]);
  if (!draft) return null;
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
      getSettings().then((refreshed) => { setSettings(refreshed); setDraft(refreshed); }).catch(() => null);
    } finally {
      setTesting(false);
      setCooldown(true);
      window.setTimeout(() => setCooldown(false), 3000);
    }
  };
  return <Dialog.Root open={open} onOpenChange={onOpenChange}><Dialog.Portal><Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur" /><Dialog.Content className="panel fixed left-1/2 top-1/2 w-[620px] -translate-x-1/2 -translate-y-1/2 p-5"><Dialog.Title className="mb-4 text-xl font-bold">Studio Settings</Dialog.Title><div className="space-y-3"><input className="input" value={draft.endpoint} onChange={(e) => setDraft({ ...draft, endpoint: e.target.value })} /><input className="input" value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })} /><label className="text-xs uppercase tracking-wide text-slate-400">Credential Reference</label><select className="input" value={draft.activeKeyRef} onChange={(e) => setDraft({ ...draft, activeKeyRef: e.target.value })}>{draft.credentialRefs.map((ref) => <option key={ref.id} value={ref.id}>{ref.label}</option>)}</select><div className="rounded border border-cyanGlow/20 bg-black/30 px-3 py-2 text-xs text-slate-300">Server-side secret: <span className={activeRef?.hasSecret ? "text-success" : "text-danger"}>{activeRef?.hasSecret ? "configured" : "missing"}</span>{activeRef && <span> ({activeRef.source})</span>}<br />Auth health: <span className={activeHealth === "valid" ? "text-success" : activeHealth === "invalid" || activeHealth === "missing" ? "text-danger" : "text-amber"}>{activeHealth}</span><br />Keys are managed on the server. Browser never sees raw secrets.<br />Update owner key on server using local admin command: <span className="font-mono text-cyanGlow">python -m studio.backend.secret_admin set-owner-key</span></div><input className="input" value={draft.checkpoint_db} onChange={(e) => setDraft({ ...draft, checkpoint_db: e.target.value })} /><input className="input" value={draft.output_root} onChange={(e) => setDraft({ ...draft, output_root: e.target.value })} /></div><div className="mt-4 flex justify-end gap-2"><button className="btn-secondary" disabled={testing || cooldown} onClick={runConnectionTest}>{testing ? "Testing..." : cooldown ? "Cooldown..." : "Test Connection"}</button><button className="btn-primary" onClick={async () => { try { const saved = await saveSettings(draft); setSettings(saved); onOpenChange(false); } catch (error) { setStatus(`SAVE FAIL: ${String(error)}`); } }}>Save</button></div><p className="mt-3 text-sm text-amber">{status}</p></Dialog.Content></Dialog.Portal></Dialog.Root>;
}

function OutputConflictDialog({ conflict, onFresh, onContinue, onRename, onCancel }: { conflict: { message: string; payload: StartPayload } | null; onFresh: () => void; onContinue: () => void; onRename: () => void; onCancel: () => void }) {
  return <Dialog.Root open={Boolean(conflict)} onOpenChange={(open) => { if (!open) onCancel(); }}><Dialog.Portal><Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur" /><Dialog.Content className="panel fixed left-1/2 top-1/2 w-[640px] -translate-x-1/2 -translate-y-1/2 p-5"><Dialog.Title className="mb-3 text-xl font-bold">Existing Output Detected</Dialog.Title><p className="mb-3 text-sm text-slate-300">This project output already has files. Pick one policy before START so old checkpoints and stale logs cannot leak into a fresh run.</p><pre className="mb-4 max-h-28 overflow-auto whitespace-pre-wrap rounded border border-cyanGlow/20 bg-black/30 p-3 font-mono text-xs text-amber">{conflict?.message}</pre><div className="grid grid-cols-2 gap-2"><button className="btn-primary" onClick={onFresh}>Archive + Fresh Run</button><button className="btn-secondary" onClick={onContinue}>Continue Existing</button><button className="btn-warning" onClick={onRename}>Rename Output</button><button className="btn-danger" onClick={onCancel}>Cancel</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>;
}

createRoot(document.getElementById("root")!).render(<App />);
