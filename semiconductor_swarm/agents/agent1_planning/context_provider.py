"""RAG-ready context provider for Agent 1 V5.1."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from semiconductor_swarm.agents.agent1_planning.capability_registry import assess_requirement_capability


LOCAL_CONTEXT_PATHS = (
    Path("docs/product-specs/agent1-system-architect.md"),
    Path("docs/product-specs/agent2-rtl-designer.md"),
    Path("docs/product-specs/agent3-dv-engineer.md"),
    Path("docs/prompts/index.md"),
)


class Agent1ContextProvider:
    """Small context interface that can later swap local docs for RAG chunks."""

    def __init__(self, *, rag_provider: Any | None = None) -> None:
        self.rag_provider = rag_provider

    def build_context_package(
        self,
        requirement: str,
        project_name: str,
        mode: str,
        iteration: int,
        expert_id: str,
        *,
        extracted_intents: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        local_sources = _local_sources()
        capability = assess_requirement_capability(
            {
                "raw_requirement": requirement,
                "extracted_intents": extracted_intents or {},
                "selected_architecture": {},
            }
        )
        package = {
            "schema_version": "agent1.context_package.v1",
            "project_name": project_name,
            "mode": mode,
            "iteration": iteration,
            "expert_id": expert_id,
            "rag_enabled": self.rag_provider is not None,
            "rag_provider": getattr(self.rag_provider, "name", None),
            "context_sources": local_sources,
            "source_hashes": {item["path"]: item["sha256"] for item in local_sources},
            "capability_assessment": capability,
        }
        if self.rag_provider is not None:
            package["rag_chunks"] = self.rag_provider.retrieve(requirement=requirement, expert_id=expert_id)
        else:
            package["rag_chunks"] = []
        return package


def build_agent1_context_package(
    requirement: str,
    project_name: str,
    mode: str,
    iteration: int,
    expert_id: str,
    *,
    extracted_intents: dict[str, Any] | None = None,
    provider: Agent1ContextProvider | None = None,
) -> dict[str, Any]:
    context_provider = provider or Agent1ContextProvider()
    return context_provider.build_context_package(
        requirement,
        project_name,
        mode,
        iteration,
        expert_id,
        extracted_intents=extracted_intents,
    )


def _local_sources() -> list[dict[str, str]]:
    sources = []
    for path in LOCAL_CONTEXT_PATHS:
        text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        compact = "\n".join(line.strip() for line in text.splitlines() if line.strip())[:1600]
        sources.append(
            {
                "type": "local_doc",
                "path": str(path).replace("\\", "/"),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "summary": compact,
            }
        )
    registry_text = json.dumps(assess_requirement_capability({}), sort_keys=True)
    sources.append(
        {
            "type": "local_capability_registry",
            "path": "semiconductor_swarm/agents/agent1_planning/capability_registry.py",
            "sha256": hashlib.sha256(registry_text.encode("utf-8")).hexdigest(),
            "summary": registry_text[:1600],
        }
    )
    return sources
