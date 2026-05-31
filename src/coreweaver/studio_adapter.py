from __future__ import annotations

from .api import CoreRequest, CoreResponse, CoreWeaverRuntime


class CoreWeaverStudioAdapter:
    """Thin package boundary between Studio and CoreWeaver core."""

    def __init__(self, runtime: CoreWeaverRuntime | None = None) -> None:
        self.runtime = runtime or CoreWeaverRuntime()

    def capabilities(self) -> dict[str, object]:
        return self.runtime.capabilities()

    def start(self, payload: dict[str, object]) -> CoreResponse:
        request = CoreRequest(
            requirement=str(payload.get("requirement") or ""),
            project=str(payload.get("project_name") or "swarm_soc"),
            mode=str(payload.get("planning_mode") or "normal"),
        )
        return self.runtime.start(request)
