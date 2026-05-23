import { useSyncExternalStore } from "react";
import type { StudioEvent } from "./types";

export type TraceEntry = {
  id: string;
  trace_file: string;
  node_id: string;
  parent_node_id?: string | null;
  event_type: string;
  status: string;
  phase: string;
  agent: string;
  summary: string;
  latency_ms?: number | null;
  payload: Record<string, unknown>;
};

export type TraceSnapshot = {
  entries: TraceEntry[];
  selectedId: string | null;
  hydratedFromArtifacts: boolean;
  files: string[];
};

const MAX_TRACE = 5000;
const FLUSH_MS = 150;

function text(value: unknown, fallback = ""): string {
  return value === undefined || value === null ? fallback : String(value);
}

function toEntry(record: Record<string, unknown>, traceFile = "live"): TraceEntry {
  const id = text(record.trace_id, `${traceFile}:${record.node_id}:${record.event_type}:${record.ended_at}`);
  const payload = { ...record };
  delete payload.trace_id;
  return {
    id,
    trace_file: text(record.trace_file ?? record.source_trace_file, traceFile),
    node_id: text(record.node_id, "node"),
    parent_node_id: record.parent_node_id === undefined ? null : text(record.parent_node_id),
    event_type: text(record.event_type ?? record.type, "event"),
    status: text(record.status, "info"),
    phase: text(record.phase, ""),
    agent: text(record.agent, ""),
    summary: text(record.decision_reason ?? record.summary ?? record.decision ?? record.event_type ?? record.type),
    latency_ms: record.latency_ms === undefined || record.latency_ms === null ? null : Number(record.latency_ms),
    payload,
  };
}

class TraceStore {
  private entries = new Map<string, TraceEntry>();
  private files = new Set<string>();
  private snapshotValue: TraceSnapshot = { entries: [], selectedId: null, hydratedFromArtifacts: false, files: [] };
  private listeners = new Set<() => void>();
  private timer: number | null = null;

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  snapshot = () => this.snapshotValue;

  appendEvent(event: StudioEvent) {
    if (event.type !== "trace_event") return;
    const entry = toEntry(event as Record<string, unknown>, text(event.trace_file, "live"));
    this.entries.set(entry.id, entry);
    this.files.add(entry.trace_file);
    this.trim();
    this.schedule();
  }

  hydrateJsonl(traceText: string, traceFile: string) {
    for (const line of traceText.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const record = JSON.parse(trimmed) as Record<string, unknown>;
        const entry = toEntry(record, traceFile);
        this.entries.set(entry.id, entry);
        this.files.add(traceFile);
      } catch {
        // Ignore malformed debug lines. Backend artifacts remain source of truth.
      }
    }
    this.snapshotValue = { ...this.snapshotValue, hydratedFromArtifacts: true };
    this.trim();
    this.schedule();
  }

  select(id: string) {
    this.snapshotValue = { ...this.snapshotValue, selectedId: id };
    this.emit();
  }

  clear() {
    this.entries.clear();
    this.files.clear();
    this.snapshotValue = { entries: [], selectedId: null, hydratedFromArtifacts: false, files: [] };
    this.emit();
  }

  private trim() {
    if (this.entries.size <= MAX_TRACE) return;
    const keys = [...this.entries.keys()].slice(0, this.entries.size - MAX_TRACE);
    for (const key of keys) this.entries.delete(key);
  }

  private schedule() {
    if (this.timer !== null) return;
    this.timer = window.setTimeout(() => this.flush(), FLUSH_MS);
  }

  private flush() {
    this.timer = null;
    const entries = [...this.entries.values()].sort((a, b) => a.trace_file.localeCompare(b.trace_file) || a.node_id.localeCompare(b.node_id) || a.event_type.localeCompare(b.event_type));
    const selectedId = this.snapshotValue.selectedId && this.entries.has(this.snapshotValue.selectedId)
      ? this.snapshotValue.selectedId
      : entries.find((entry) => entry.node_id === "AGENT1.READY_GATE")?.id ?? entries[0]?.id ?? null;
    this.snapshotValue = {
      ...this.snapshotValue,
      entries,
      selectedId,
      files: [...this.files].sort(),
    };
    this.emit();
  }

  private emit() {
    for (const listener of this.listeners) listener();
  }
}

export const traceStore = new TraceStore();

export function useTrace() {
  return useSyncExternalStore(traceStore.subscribe, traceStore.snapshot, traceStore.snapshot);
}
