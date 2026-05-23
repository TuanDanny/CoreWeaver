"""Deterministic RAG stub for Agent 2.

No network, no embeddings, no mutable external state.  This acts as local
retrieval scaffold so Agent 2 output records exact source rules used.
"""
from __future__ import annotations

from typing import Any

from semiconductor_swarm.agents.agent2_rtl.pattern_library import pattern_manifest, repo_patterns_dir, select_patterns_for_spec


def query_rtl_knowledge_base(query: str, tags: list[str] | None = None) -> list[dict[str, Any]]:
    """Return deterministic local pattern docs for Agent 2 RAG queries."""
    query_l = query.lower()
    tag_l = {tag.lower() for tag in (tags or [])}
    docs: list[dict[str, Any]] = []
    for path in sorted(repo_patterns_dir().glob("*.sv")):
        text = path.read_text(encoding="utf-8")
        key = path.stem.lower()
        if key.replace("_template", "") in query_l or key in tag_l or any(tag in key for tag in tag_l):
            docs.append({"doc_id": f"patterns/{path.name}", "path": str(path).replace("\\", "/"), "content": text, "tags": sorted(tag_l)})
    return docs


def retrieve_agent2_context(spec: dict[str, Any]) -> dict[str, Any]:
    patterns = select_patterns_for_spec(spec)
    blocks = [block.get("name", "unknown") for block in spec.get("ip_blocks", [])]
    local_docs = query_rtl_knowledge_base("APB FIFO CDC complex", ["apb", "fifo", "cdc", "complex"])
    return {
        "retriever": "deterministic_local_rag_stub",
        "query": {
            "project_name": spec.get("project_name"),
            "interfaces": sorted(spec.get("interfaces", {}).keys()),
            "ip_blocks": blocks,
        },
        "documents": [
            {
                "doc_id": f"golden-pattern::{pattern.name}",
                "title": pattern.description,
                "category": pattern.category,
                "required_tokens": list(pattern.required_tokens),
                "forbidden_tokens": list(pattern.forbidden_tokens),
            }
            for pattern in patterns
        ] + local_docs,
        "pattern_manifest": pattern_manifest(spec),
    }
