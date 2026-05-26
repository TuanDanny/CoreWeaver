"""Deterministic Agent 2 RAG retriever stub.

This module is the stable public hook for local RTL pattern retrieval. It
intentionally performs no network fetches; local pattern retrieval remains
deterministic.
"""
from __future__ import annotations

from semiconductor_swarm.agents.agent2_rtl.rag_stub import query_rtl_knowledge_base as _query_local_docs


def query_rtl_knowledge_base(query: str, tags: list[str]) -> str:
    """Return matched local RTL pattern content as a single string."""
    docs = _query_local_docs(query, tags)
    if not docs:
        raise ValueError(f"No RTL knowledge-base pattern matched query={query!r}, tags={tags!r}")
    return "\n\n".join(str(doc.get("content", "")) for doc in docs)
