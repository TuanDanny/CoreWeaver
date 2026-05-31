from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class KnowledgeInventoryResult:
    passed: bool
    missing_paths: tuple[str, ...]
    stale_links: tuple[str, ...]


class KnowledgeInventory:
    """Check repo-local knowledge map expected by harness engineering."""

    REQUIRED_PATHS = (
        "AGENTS.md",
        "ARCHITECTURE.md",
        "feature_list.json",
        "feature_list.schema.json",
        "progress.md",
        "session-handoff.md",
        "init.sh",
        "init.ps1",
        ".rules",
        "docs/HARNESS_ENGINEERING.md",
        "docs/adr/README.md",
        "docs/adr/0001-package-first-core.md",
        "docs/design-docs/index.md",
        "docs/design-docs/studio-agent1-core-contract.md",
        "docs/product-specs/index.md",
        "docs/generated/index.md",
        "docs/governance/harness-review-checklist.md",
        "docs/references/openai-harness-engineering.md",
        "benchmarks/README.md",
        "benchmarks/cases/.gitkeep",
        "benchmarks/schemas/benchmark_case.schema.json",
        "scripts/run_benchmarks.py",
        "scripts/dev_check.ps1",
        "src",
        "src/coreweaver/harness",
        "src/coreweaver/messages",
        "src/coreweaver/events",
        "src/coreweaver/runtime",
        "src/coreweaver/hooks",
        "src/coreweaver/models",
        "src/coreweaver/tools",
        "src/coreweaver/orchestration",
        "src/coreweaver/agents/agent1",
        "src/coreweaver/safety",
        "src/coreweaver/debug",
        "src/coreweaver/api.py",
        "src/coreweaver/contracts/studio_agent1.py",
        "src/coreweaver/run_profiles.py",
        "src/coreweaver/registry.py",
        ".rules/architecture.src_layout.rule",
        ".rules/packaging.package_boundary.rule",
        ".rules/docs.reference_doctrine_contract.rule",
        ".rules/core.framework_first.rule",
        "tests",
    )

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root)

    def check(self) -> KnowledgeInventoryResult:
        missing = tuple(
            path for path in self.REQUIRED_PATHS if not (self.repo_root / path).exists()
        )
        stale = self._check_agents_links()
        return KnowledgeInventoryResult(
            passed=not missing and not stale,
            missing_paths=missing,
            stale_links=stale,
        )

    def _check_agents_links(self) -> tuple[str, ...]:
        agents_path = self.repo_root / "AGENTS.md"
        if not agents_path.exists():
            return ()
        text = agents_path.read_text(encoding="utf-8")
        stale: list[str] = []
        for path in self.REQUIRED_PATHS:
            if path in text and not (self.repo_root / path).exists():
                stale.append(path)
        return tuple(stale)
