import type { AgentJob, AttachmentStagePayload, JobListPayload, JobType, PlanningMode, RunState, RuntimeBundle, SettingsPayload, StartPolicy } from "./types";

export const API_BASE = import.meta.env.VITE_STUDIO_API_BASE ?? "http://127.0.0.1:8000";
export const WS_BASE = API_BASE.replace(/^http/, "ws");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { ...(isFormData ? {} : { "Content-Type": "application/json" }), ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    let detail = text || response.statusText;
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      if (parsed.detail) detail = String(parsed.detail);
    } catch {
      // Keep raw response text when backend did not return JSON.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export function getCurrentState(): Promise<RunState> {
  return request<RunState>("/api/runs/current_state");
}

export function getRuntime(runId: string): Promise<RuntimeBundle> {
  return request<RuntimeBundle>(`/api/runs/${encodeURIComponent(runId)}/runtime`);
}

export function getSettings(): Promise<SettingsPayload> {
  return request<SettingsPayload>("/api/settings");
}

export function saveSettings(payload: SettingsPayload): Promise<SettingsPayload> {
  const serverPayload = {
    endpoint: payload.endpoint,
    model: payload.model,
    checkpoint_db: payload.checkpoint_db,
    output_root: payload.output_root,
    activeKeyRef: payload.activeKeyRef,
  };
  return request<SettingsPayload>("/api/settings", { method: "POST", body: JSON.stringify(serverPayload) });
}

export function testConnection(payload: { endpoint: string; model: string; apiKeyRef: string }): Promise<{ ok: boolean | string; message: string }> {
  return request("/api/settings/test-connection", { method: "POST", body: JSON.stringify(payload) });
}

export function startRun(payload: { requirement: string; project_name: string; output_dir: string; planning_mode: PlanningMode; checkpoint_db: string; apiKeyRef: string; startPolicy?: StartPolicy; attachmentDraftId?: string; attachmentIds?: string[] }): Promise<RunState> {
  return request<RunState>("/api/runs/start", { method: "POST", body: JSON.stringify(payload) });
}

export function resumeRun(runId: string, payload: { notes: string; change?: string; resume_action?: string; planning_mode: PlanningMode; apiKeyRef: string }): Promise<RunState> {
  return request<RunState>(`/api/runs/${runId}/resume`, { method: "POST", body: JSON.stringify(payload) });
}

export function stopRun(runId = "current"): Promise<RunState> {
  return request<RunState>(`/api/runs/${runId}/stop`, { method: "POST" });
}

export function stageAttachments(files: File[], draftId = ""): Promise<AttachmentStagePayload> {
  const form = new FormData();
  if (draftId) form.append("draft_id", draftId);
  for (const file of files) form.append("files", file);
  return request<AttachmentStagePayload>("/api/attachments/stage", { method: "POST", body: form });
}

export function deleteStagedAttachment(draftId: string, attachmentId: string): Promise<AttachmentStagePayload> {
  return request<AttachmentStagePayload>(`/api/attachments/stage/${encodeURIComponent(draftId)}/${encodeURIComponent(attachmentId)}`, { method: "DELETE" });
}

export function liveInputRun(runId: string, payload: { message: string; clientMessageId?: string }): Promise<{ ok: boolean; status: string; message_id: string; run_id: string }> {
  return request(`/api/runs/${runId}/live-input`, { method: "POST", body: JSON.stringify(payload) });
}

export function previewArtifact(path: string): Promise<{ path: string; text: string; truncated: boolean; bytes: number }> {
  return request(`/api/artifacts/preview?path=${encodeURIComponent(path)}`);
}

export function listJobs(): Promise<JobListPayload> {
  return request<JobListPayload>("/api/jobs");
}

export function createAgentJob(payload: { type: JobType; requirement: string; project_name: string; output_dir: string; planning_mode: PlanningMode; checkpoint_db: string; apiKeyRef: string; startPolicy?: StartPolicy }): Promise<AgentJob> {
  return request<AgentJob>("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
}

export function cancelAgentJob(jobId: string): Promise<AgentJob> {
  return request<AgentJob>(`/api/jobs/${jobId}/cancel`, { method: "POST" });
}
