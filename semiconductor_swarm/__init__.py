"""Semiconductor Swarm AI package.

Heavy runtime orchestration lives in :mod:`semiconductor_swarm.swarm_graph`.
The package root stays lightweight so docs, prompt, and contract checks can
import nested modules without requiring optional LangGraph dependencies.
"""

__all__ = ["agents", "contracts", "tools", "swarm_graph"]
