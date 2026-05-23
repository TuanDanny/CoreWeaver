"""Semiconductor Swarm agent package facade.

Canonical runtime modules live in versioned/namespaced subpackages:

- Agent 1: :mod:`semiconductor_swarm.agents.agent1_planning.architect`
- Agent 2: :mod:`semiconductor_swarm.agents.agent2_rtl.rtl_designer`
- Agent 3: :mod:`semiconductor_swarm.agents.agent3_dv.dv_engineer`
- Agent 4: :mod:`semiconductor_swarm.agents.agent4_physical.physical_designer`
- Agent 5: :mod:`semiconductor_swarm.agents.agent5_formal.formal_verifier`

This package facade preserves short compatibility imports such as
``from semiconductor_swarm.agents import rtl_designer`` without owning agent
implementation code.
"""
from __future__ import annotations

from semiconductor_swarm.agents.agent1_planning import architect as architect
from semiconductor_swarm.agents.agent2_rtl import rtl_designer as rtl_designer
from semiconductor_swarm.agents.agent3_dv import dv_engineer as dv_engineer
from semiconductor_swarm.agents.agent4_physical import physical_designer as physical_designer
from semiconductor_swarm.agents.agent5_formal import formal_verifier as formal_verifier
from semiconductor_swarm.agents.agent2_rtl.rtl_designer import *  # noqa: F401,F403

__all__ = [
    "architect",
    "rtl_designer",
    "dv_engineer",
    "physical_designer",
    "formal_verifier",
]

try:
    __all__ += list(rtl_designer.__all__)  # type: ignore[attr-defined]
except AttributeError:
    __all__ += [
        "RTLFile",
        "generate_rtl_files",
        "apply_agent2_fix_request",
        "verify_rtl_files",
        "write_rtl_files",
    ]
