import { useEffect, useSyncExternalStore } from "react";
import type { StudioEvent } from "./types";

export type LogEntry = {
  id: number;
  level: string;
  agent: string;
  text: string;
  ts: string;
};

const MAX_LOGS = 2000;
const FLUSH_MS = 150;

class LogStore {
  private logs: LogEntry[] = [];
  private pending: LogEntry[] = [];
  private listeners = new Set<() => void>();
  private timer: number | null = null;
  private seq = 1;
  private seenEventIds: string[] = [];
  private seenEventIdSet = new Set<string>();

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  snapshot = () => this.logs;

  appendEvent(event: StudioEvent) {
    if (event.type === "ping") return;
    const eventId = event.event_id ?? event.eventId;
    if (eventId !== undefined && eventId !== null) {
      const dedupeKey = `${String(event.run_id ?? "global")}:${String(eventId)}`;
      if (this.seenEventIdSet.has(dedupeKey)) return;
      this.seenEventIdSet.add(dedupeKey);
      this.seenEventIds.push(dedupeKey);
      if (this.seenEventIds.length > MAX_LOGS * 2) {
        const expired = this.seenEventIds.splice(0, this.seenEventIds.length - MAX_LOGS * 2);
        for (const key of expired) this.seenEventIdSet.delete(key);
      }
    }
    const level = String(event.level ?? event.status ?? event.type ?? "info").toLowerCase();
    const agent = String(event.agent ?? event.from_agent ?? event.speaker ?? "system");
    const message = event.type === "trace_event"
      ? `${String(event.node_id ?? "trace")} ${String(event.event_type ?? "event")} ${String(event.decision ?? event.summary ?? event.status ?? "")}`.trim()
      : String(event.message ?? event.summary ?? event.action ?? event.name ?? event.type);
    this.pending.push({ id: this.seq++, level, agent, text: message, ts: new Date().toLocaleTimeString() });
    if (this.timer === null) {
      this.timer = window.setTimeout(() => this.flush(), FLUSH_MS);
    }
  }

  clear() {
    this.logs = [];
    this.pending = [];
    this.seenEventIds = [];
    this.seenEventIdSet.clear();
    this.emit();
  }

  private flush() {
    this.timer = null;
    if (!this.pending.length) return;
    this.logs = [...this.logs, ...this.pending].slice(-MAX_LOGS);
    this.pending = [];
    this.emit();
  }

  private emit() {
    for (const listener of this.listeners) listener();
  }
}

export const logStore = new LogStore();

export function useLogs() {
  const logs = useSyncExternalStore(logStore.subscribe, logStore.snapshot, logStore.snapshot);
  useEffect(() => () => logStore.clear(), []);
  return logs;
}
