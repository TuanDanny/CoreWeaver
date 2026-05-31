from __future__ import annotations

from enum import Enum


class ErrorCategory(str, Enum):
    USER_INPUT = "USER_INPUT"
    CONFIG = "CONFIG"
    LLM_CALL = "LLM_CALL"
    CONTRACT = "CONTRACT"
    SIGNOFF = "SIGNOFF"
    RUNTIME = "RUNTIME"
    SECURITY = "SECURITY"
