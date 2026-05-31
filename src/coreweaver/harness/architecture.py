from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Layer(str, Enum):
    TYPES = "types"
    CONFIG = "config"
    REPO = "repo"
    SERVICE = "service"
    RUNTIME = "runtime"
    UI = "ui"
    PROVIDERS = "providers"


_ORDER = {
    Layer.TYPES: 0,
    Layer.CONFIG: 1,
    Layer.REPO: 2,
    Layer.SERVICE: 3,
    Layer.RUNTIME: 4,
    Layer.UI: 5,
}


@dataclass(frozen=True)
class DependencyEdge:
    source_domain: str
    source_layer: Layer
    target_domain: str
    target_layer: Layer
    reason: str = ""


@dataclass(frozen=True)
class ArchitectureViolation:
    code: str
    message: str
    edge: DependencyEdge


class LayeredArchitectureRule:
    """Enforce predictable forward dependencies per domain."""

    def check_edges(self, edges: list[DependencyEdge]) -> tuple[ArchitectureViolation, ...]:
        violations: list[ArchitectureViolation] = []
        for edge in edges:
            if edge.source_layer == Layer.PROVIDERS or edge.target_layer == Layer.PROVIDERS:
                continue
            if edge.source_domain != edge.target_domain:
                violations.append(
                    ArchitectureViolation("cross_domain", "cross-domain edge needs provider", edge)
                )
                continue
            if _ORDER[edge.source_layer] > _ORDER[edge.target_layer]:
                violations.append(
                    ArchitectureViolation("backward_layer", "dependency points backward", edge)
                )
        return tuple(violations)
