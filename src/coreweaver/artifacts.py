from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunLayout:
    root: Path
    run_id: str

    @property
    def run_root(self) -> Path:
        return self.root / self.run_id

    def directories(self) -> tuple[Path, ...]:
        return (
            self.run_root / "input",
            self.run_root / "trace",
            self.run_root / "issues",
            self.run_root / "blackboard",
            self.run_root / "artifacts",
            self.run_root / "signoff",
            self.run_root / "replay",
        )

    def create(self) -> None:
        for directory in self.directories():
            directory.mkdir(parents=True, exist_ok=True)
