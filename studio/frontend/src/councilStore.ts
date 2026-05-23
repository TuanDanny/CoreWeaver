import { useSyncExternalStore } from "react";
import type { CouncilEdge, CouncilLayer, CouncilNode, CouncilSnapshot, StudioEvent } from "./types";

const FLUSH_MS = 150;
const MAX_COUNCIL_EVENTS = 3000;

function text(value: unknown, fallback = ""): string {
  return value === undefined || value === null ? fallback : String(value);
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value.slice(0, 20) : [];
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean).slice(0, 32) : [];
}

function layerOf(value: unknown): CouncilLayer {
  const layer = text(value, "leaf");
  if (["leaf", "middle", "principal", "guardrail", "iteration", "artifact", "edge"].includes(layer)) return layer as CouncilLayer;
  return "leaf";
}

function nodeKey(iteration: number, layer: CouncilLayer, nodeId: string): string {
  return `${iteration}:${layer}:${nodeId}`;
}

function eventDedupeKey(event: StudioEvent): string {
  if (event.event_id !== undefined) return `event:${event.event_id}`;
  return [
    text(event.type),
    text(event.iteration),
    text(event.layer),
    text(event.node_id),
    text(event.status),
    text(event.phase_seq),
  ].join(":");
}

function nodeFromEvent(event: StudioEvent): CouncilNode {
  const iteration = Number(event.iteration ?? 1);
  const layer = layerOf(event.layer);
  const nodeId = text(event.node_id, text(event.name, "node"));
  return {
    key: nodeKey(iteration, layer, nodeId),
    iteration,
    layer,
    node_id: nodeId,
    title: text(event.title, nodeId),
    status: text(event.status, "info"),
    parent_id: event.parent_id === undefined ? null : text(event.parent_id),
    child_ids: stringList(event.child_ids),
    summary: text(event.summary ?? event.message ?? event.action),
    accepted_decisions: list(event.accepted_decisions),
    rejected_decisions: list(event.rejected_decisions),
    conflicts: list(event.conflicts),
    feedback_digest: event.feedback_digest ?? {},
    handoff_digest: event.handoff_digest ?? {},
    token_usage: (event.token_usage && typeof event.token_usage === "object" ? event.token_usage : {}) as Record<string, unknown>,
    duration_ms: event.duration_ms === undefined ? null : Number(event.duration_ms),
    phase_seq: text(event.phase_seq),
  };
}

function nodeFromTrace(record: Record<string, unknown>): CouncilNode | null {
  const iteration = Number(record.iteration ?? 1);
  const output = (record.output && typeof record.output === "object" ? record.output : {}) as Record<string, unknown>;
  const recordType = text(record.record_type);
  const layer = recordType === "middle" ? "middle" : recordType === "principal" ? "principal" : "leaf";
  const nodeId = text(record.expert_id ?? record.manager_id ?? record.principal_id, "node");
  return {
    key: nodeKey(iteration, layer, nodeId),
    iteration,
    layer,
    node_id: nodeId,
    title: text(record.title, nodeId),
    status: list(record.conflicts).length ? "conflict" : "pass",
    parent_id: null,
    child_ids: stringList(record.covered_experts),
    summary: text(output.domain_summary ?? output.summary),
    accepted_decisions: list(output.accepted_decisions ?? output.decisions),
    rejected_decisions: list(output.rejected_decisions ?? output.rejected_alternatives),
    conflicts: list(record.conflicts).concat(list(output.domain_conflicts)),
    feedback_digest: output.feedback_to_leaf_experts ?? output.feedback_to_middle_managers ?? {},
    handoff_digest: output.handoff_to_principal ?? output.selected_architecture_candidate ?? {},
    token_usage: (record.token_usage && typeof record.token_usage === "object" ? record.token_usage : {}) as Record<string, unknown>,
    duration_ms: record.latency_s === undefined ? null : Math.round(Number(record.latency_s) * 1000),
    phase_seq: `${iteration}:${layer}:artifact:${nodeId}`,
  };
}

class CouncilStore {
  private snapshotValue: CouncilSnapshot = { iterations: [], nodes: [], edges: [], selectedKey: null, hydratedFromArtifacts: false };
  private nodes = new Map<string, CouncilNode>();
  private edges = new Map<string, CouncilEdge>();
  private iterations = new Set<number>();
  private seen = new Set<string>();
  private listeners = new Set<() => void>();
  private timer: number | null = null;

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  snapshot = () => this.snapshotValue;

  appendEvent(event: StudioEvent) {
    if (!String(event.type ?? "").startsWith("agent1_council_")) return;
    const dedupe = eventDedupeKey(event);
    if (this.seen.has(dedupe)) return;
    this.seen.add(dedupe);
    if (this.seen.size > MAX_COUNCIL_EVENTS) this.seen.delete(this.seen.values().next().value as string);

    const iteration = Number(event.iteration ?? 1);
    this.iterations.add(iteration);
    if (event.type === "agent1_council_edge") {
      const from = text(event.from_node);
      const to = text(event.to_node);
      const key = `${iteration}:${from}->${to}`;
      this.edges.set(key, { key, iteration, from_node: from, to_node: to });
    } else if (event.type === "agent1_council_node" || event.type === "agent1_council_iteration" || event.type === "agent1_council_artifact") {
      const node = nodeFromEvent(event);
      this.nodes.set(node.key, { ...(this.nodes.get(node.key) ?? node), ...node });
      if (!this.snapshotValue.selectedKey && node.layer === "middle") this.snapshotValue = { ...this.snapshotValue, selectedKey: node.key };
    }
    this.schedule();
  }

  hydrateFromTraceText(traceText: string) {
    for (const line of traceText.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const record = JSON.parse(trimmed) as Record<string, unknown>;
        const node = nodeFromTrace(record);
        if (node) {
          this.nodes.set(node.key, { ...(this.nodes.get(node.key) ?? node), ...node });
          this.iterations.add(node.iteration);
          for (const childId of node.child_ids) {
            const key = `${node.iteration}:${childId}->${node.node_id}`;
            this.edges.set(key, { key, iteration: node.iteration, from_node: childId, to_node: node.node_id });
          }
        }
      } catch {
        // Ignore malformed trace lines; backend artifacts remain source of truth.
      }
    }
    this.snapshotValue = { ...this.snapshotValue, hydratedFromArtifacts: true };
    this.schedule();
  }

  selectNode(key: string) {
    this.snapshotValue = { ...this.snapshotValue, selectedKey: key };
    this.emit();
  }

  clear() {
    this.nodes.clear();
    this.edges.clear();
    this.iterations.clear();
    this.seen.clear();
    this.snapshotValue = { iterations: [], nodes: [], edges: [], selectedKey: null, hydratedFromArtifacts: false };
    this.emit();
  }

  private schedule() {
    if (this.timer !== null) return;
    this.timer = window.setTimeout(() => this.flush(), FLUSH_MS);
  }

  private flush() {
    this.timer = null;
    const selectedKey = this.snapshotValue.selectedKey && this.nodes.has(this.snapshotValue.selectedKey)
      ? this.snapshotValue.selectedKey
      : [...this.nodes.values()].find((node) => node.layer === "middle")?.key ?? null;
    this.snapshotValue = {
      ...this.snapshotValue,
      iterations: [...this.iterations].sort((a, b) => a - b),
      nodes: [...this.nodes.values()].sort((a, b) => a.iteration - b.iteration || a.layer.localeCompare(b.layer) || a.node_id.localeCompare(b.node_id)),
      edges: [...this.edges.values()],
      selectedKey,
    };
    this.emit();
  }

  private emit() {
    for (const listener of this.listeners) listener();
  }
}

export const councilStore = new CouncilStore();

export function useCouncil() {
  return useSyncExternalStore(councilStore.subscribe, councilStore.snapshot, councilStore.snapshot);
}
