from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch

from .models import ScopeContract


@dataclass(frozen=True)
class ScopeViolation:
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class ScopeCheckResult:
    in_scope: bool
    violations: tuple[ScopeViolation, ...] = field(default_factory=tuple)


class ScopeChecker:
    def __init__(self, contract: ScopeContract) -> None:
        self.contract = contract

    def check(self, touched_files: list[str], commands_run: list[str]) -> ScopeCheckResult:
        violations: list[ScopeViolation] = []
        for path in touched_files:
            normalized = path.replace("\\", "/")
            if self._matches(normalized, self.contract.forbidden_files):
                violations.append(
                    ScopeViolation("forbidden_file", "path matches forbidden_files", normalized)
                )
                continue
            if not self._matches(normalized, self.contract.allowed_files):
                violations.append(
                    ScopeViolation("off_scope_file", "path not covered by allowed_files", normalized)
                )

        missing_commands = [
            command
            for command in self.contract.acceptance_commands
            if command not in commands_run
        ]
        for command in missing_commands:
            violations.append(ScopeViolation("missing_acceptance_command", command))

        return ScopeCheckResult(in_scope=not violations, violations=tuple(violations))

    @staticmethod
    def _matches(path: str, patterns: tuple[str, ...]) -> bool:
        return any(fnmatch(path, pattern.replace("\\", "/")) for pattern in patterns)
