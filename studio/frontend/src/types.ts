export type StageName = "planning" | "rtl" | "formal" | "hitl" | "dv" | "physical" | "signoff";
export type ConnectionState = "Connected" | "Reconnecting" | "Disconnected";
export type PlanningMode = "normal" | "deep_planning";
export type StartPolicy = "auto" | "fresh" | "continue";

export type StudioEvent = {
  type: string;
  event_id?: number;
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
  thread_id?: string;
  start_policy?: string;
  manifest_path?: string;
  stages: Record<StageName, string>;
  agents: Record<string, { status: string; action: string; evidence: number }>;
  metrics: Record<string, unknown>;
  pause: StudioEvent | null;
  current_plan_path: string | null;
  last_event_id: number;
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
};
