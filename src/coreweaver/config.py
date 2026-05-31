from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .harness.models import HarnessValidationError


@dataclass(frozen=True)
class CoreWeaverConfig:
    output_root: Path
    model_profile: str = "unset"
    provider_ref: str = "unset"

    def __post_init__(self) -> None:
        if not str(self.output_root):
            raise HarnessValidationError("output_root is required")
        if not self.model_profile:
            raise HarnessValidationError("model_profile is required")
        if not self.provider_ref:
            raise HarnessValidationError("provider_ref is required")


def default_config() -> CoreWeaverConfig:
    return CoreWeaverConfig(output_root=Path("runs"))
