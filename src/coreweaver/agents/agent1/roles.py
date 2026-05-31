from __future__ import annotations

from enum import Enum


class Agent1Role(str, Enum):
    PRINCIPAL = "principal"
    MIDDLE_MANAGER = "middle_manager"
    LEAF_EXPERT = "leaf_expert"
