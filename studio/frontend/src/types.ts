export type StageName = "planning" | "rtl" | "formal" | "hitl" | "dv" | "physical" | "signoff";
export type ConnectionState = "Connected" | "Reconnecting" | "Disconnected";
export type PlanningMode = "normal" | "deep_planning";
export type StartPolicy = "auto" | "fresh" | "continue";
export type JobStatus = "queued" | "running" | "paused" | "completed" | "failed" | "cancelled";
export type JobType = "agent1_plan_draft" | "agent2_rtl_draft" | "full_swarm_run" | "debug_bundle";
export type AttachmentKind = "markdown" | "pdf" | "image";

export type AttachmentRef = {
  id: string;
  name: string;
  kind: AttachmentKind;
  mimeType: string;
  bytes: number;
  sha256: string;
  extractStatus: string;
  extractedChars: number;
  preview: string;
};

export type AttachmentStagePayload = {
  draftId: string;
  attachments: AttachmentRef[];
};

export type StudioEvent = {
  type: string;
  event_id?: number | string;
  level?: string;
  message?: string;
  stage?: StageName;
  status?: string;
  agent?: string;
  action?: string;
  summary?: string;
  name?: string;
  value?: unknown;
  path?: string;
  plan_path?: string;
  pid?: number;
  returncode?: number;
  ts?: number;
  [key: string]: unknown;
};

export type RunState = {
  run_id: string;
  status: string;
  pid: number | null;
  project_name: string;
  requirement: string;
  output_dir: string;
  planning_mode: PlanningMode;
  apiKeyRef: string;
  attachment_manifest_path?: string;
  attachment_context_path?: string;
  job_id?: string;
  thread_id?: string;
  start_policy?: string;
  manifest_path?: string;
  stages: Record<StageName, string>;
  agents: Record<string, { status: string; action: string; evidence: number }>;
  metrics: Record<string, unknown>;
  pause: StudioEvent | null;
  current_plan_path: string | null;
  last_event_id: number;
  runtime?: RuntimeCompact | null;
};

export type RuntimeEvent = {
  type: "runtime_event";
  schema_version: "studio.runtime_event.v1";
  event_id: string;
  correlation_id: string;
  timestamp: string;
  run_id: string;
  job_id: string;
  project_name: string;
  agent: string;
  phase: string;
  node_id: string;
  event_type: string;
  status: string;
  message: string;
  duration_ms: number;
  artifact_refs: string[];
  metrics: Record<string, unknown>;
  error: Record<string, unknown> | null;
  source?: Record<string, unknown> | null;
};

export type RuntimeManifest = {
  schema_version: string;
  run_id: string;
  job_id: string;
  project_name: string;
  output_dir: string;
  planning_mode: string;
  credential_ref: string;
  status: string;
  active_agent: string;
  active_node_id: string;
  last_runtime_event_at: string;
  recoverable: boolean;
  recovery_status: string;
  agents: Record<string, unknown>;
  nodes: Record<string, unknown>;
  model_calls: Record<string, { agent?: string; node_id?: string; status?: string; duration_ms?: number; metrics?: Record<string, unknown>; message?: string; updated_at?: string }>;
  queue: Record<string, unknown>;
  metrics: Record<string, unknown>;
  artifact_refs: string[];
  agent1_cluster_council?: Record<string, unknown>;
  flow_coverage?: Record<string, unknown>;
};

export type RuntimeReport = Record<string, unknown> | null;

export type RuntimeBundle = {
  manifest: RuntimeManifest | null;
  recentEvents: RuntimeEvent[];
  debugIssues?: DebugIssue[];
  signoff?: SignoffBundle | null;
  recoveryReport: RuntimeReport;
  invariantReport: RuntimeReport;
  replayReport: RuntimeReport;
  flowCoverage: RuntimeReport;
  debugSummary: RuntimeReport;
  errors?: string[];
};

export type DebugIssue = {
  type: "debug_issue";
  schema_version?: string;
  severity: string;
  source: string;
  code: string;
  message: string;
  details?: Record<string, unknown>;
  run_id?: string;
  revision_id?: string;
  artifact_ref?: string;
  node_id?: string;
  timestamp?: string;
  flow_segment?: string;
  source_layer?: string;
  span_id?: string;
  parent_span_id?: string;
  group_id?: string;
  model_call_id?: string;
  gate?: string;
  profile?: string;
  case_id?: string;
  expected_decision?: string;
  actual_decision?: string;
  false_pass?: boolean;
  must_not_pass_violation?: boolean;
};

export type RuntimeCompact = {
  manifest?: RuntimeManifest | null;
  recoveryReport?: RuntimeReport;
  debugSummary?: RuntimeReport;
  invariantReport?: RuntimeReport;
  replayReport?: RuntimeReport;
  flowCoverage?: RuntimeReport;
  debugIssues?: DebugIssue[];
  signoff?: SignoffBundle | null;
};

export type SignoffBundle = {
  schema_version?: string;
  state?: "NOT_REACHED" | "PARTIAL" | "BLOCKED" | "FAILED" | "PASSED" | string;
  stateReason?: string;
  certificate?: Record<string, unknown> | null;
  gateReport?: Record<string, unknown> | null;
  evidenceManifest?: Record<string, unknown> | null;
  runtimeManifest?: Record<string, unknown> | null;
  handoff?: Record<string, unknown> | null;
  benchmarkReport?: Record<string, unknown> | null;
  falsePassReport?: Record<string, unknown> | null;
  oracleDisagreements?: Record<string, unknown> | null;
  benchmarkManifestHash?: Record<string, unknown> | null;
  waivers?: Record<string, unknown> | null;
  artifactRefs?: Record<string, string>;
  artifactStatus?: Record<string, { path: string; exists: boolean }>;
  errors?: unknown[];
};

export type CredentialRef = {
  id: string;
  label: string;
  hasSecret: boolean;
  source: string;
};

export type CredentialHealth = "missing" | "unchecked" | "valid" | "invalid";

export type CouncilLayer = "leaf" | "middle" | "principal" | "guardrail" | "iteration" | "artifact" | "edge";

export type CouncilNode = {
  key: string;
  iteration: number;
  layer: CouncilLayer;
  node_id: string;
  title: string;
  status: string;
  parent_id?: string | null;
  child_ids: string[];
  summary: string;
  accepted_decisions: unknown[];
  rejected_decisions: unknown[];
  conflicts: unknown[];
  feedback_digest: unknown;
  handoff_digest: unknown;
  token_usage: Record<string, unknown>;
  duration_ms?: number | null;
  phase_seq?: string;
};

export type CouncilEdge = {
  key: string;
  iteration: number;
  from_node: string;
  to_node: string;
};

export type CouncilSnapshot = {
  iterations: number[];
  nodes: CouncilNode[];
  edges: CouncilEdge[];
  selectedKey: string | null;
  hydratedFromArtifacts: boolean;
};

export type SettingsPayload = {
  endpoint: string;
  model: string;
  checkpoint_db: string;
  output_root: string;
  activeKeyRef: string;
  credentialRefs: CredentialRef[];
  credentialHealth: Record<string, CredentialHealth>;
  modelProviders?: Array<{ id: string; label: string; enabled: boolean; kind: string }>;
};

export type AgentJob = {
  job_id: string;
  run_id: string;
  type: JobType;
  status: JobStatus;
  project_name: string;
  requirement: string;
  planning_mode: PlanningMode;
  output_dir: string;
  checkpoint_db: string;
  credential_ref: string;
  start_policy: StartPolicy;
  attachment_draft_id?: string;
  attachment_ids?: string[];
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  error: string | null;
  artifact_refs: string[];
};

export type JobListPayload = {
  jobs: AgentJob[];
  queueHealth: Record<string, unknown>;
};
