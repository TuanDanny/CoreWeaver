from __future__ import annotations

import os
from dataclasses import dataclass

from .harness.models import HarnessValidationError

DEFAULT_RUN_PROFILE = "local_skeleton"

@dataclass(frozen=True)
class RunProfile:
    name: str
    runtime_kind: str
    requires_credential: bool
    description: str

    def to_capabilities(self) -> dict[str, object]:
        return {
            "profile": self.name,
            "runtimeKind": self.runtime_kind,
            "requiresCredential": self.requires_credential,
            "description": self.description,
        }

RUN_PROFILES: dict[str, RunProfile] = {
    "local_skeleton": RunProfile(
        name="local_skeleton",
        runtime_kind="skeleton",
        requires_credential=False,
        description="Local Studio shell with CoreWeaver skeleton adapter; no LLM call.",
    ),
    "local_llm": RunProfile(
        name="local_llm",
        runtime_kind="llm_core_socket",
        requires_credential=True,
        description="Local run profile for future LLM-backed Agent core.",
    ),
    "mock_swarm": RunProfile(
        name="mock_swarm",
        runtime_kind="mock_agent1_swarm",
        requires_credential=False,
        description="Full Agent1 swarm flow through model/tool adapters with deterministic mock model; no credential required.",
    ),
    "ci_no_llm": RunProfile(
        name="ci_no_llm",
        runtime_kind="skeleton",
        requires_credential=False,
        description="CI-safe profile for tests, harness checks, and frontend build without LLM.",
    ),
}

def current_run_profile_name() -> str:
    return os.environ.get("COREWEAVER_RUN_PROFILE", DEFAULT_RUN_PROFILE).strip() or DEFAULT_RUN_PROFILE

def load_run_profile(name: str | None = None) -> RunProfile:
    requested = (name or current_run_profile_name()).strip()
    try:
        return RUN_PROFILES[requested]
    except KeyError as exc:
        allowed = ", ".join(sorted(RUN_PROFILES))
        raise HarnessValidationError(f"unknown run profile '{requested}'. allowed: {allowed}") from exc
