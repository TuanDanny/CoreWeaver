from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for import_root in (SRC, ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from coreweaver.harness.knowledge import KnowledgeInventory
from coreweaver.harness.models import DebugIssue, IssueSeverity
from coreweaver.harness.rule_engine import HarnessContext, RuleEngine
from coreweaver.harness.rules import load_rules
from coreweaver.harness.secret_scan import scan_text_for_secrets


EXCLUDED_DIRS = {
    ".git",
    "_private",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "dist",
    "document",
    "template",
}

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".json",
    ".toml",
    ".txt",
    ".ts",
    ".tsx",
    ".css",
    ".js",
    ".mjs",
    ".yml",
    ".yaml",
    ".rule",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print JSON report")
    parser.add_argument("--inject-failing-context", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    knowledge_result = KnowledgeInventory(ROOT).check()
    private_ignored = _private_ignored()
    secret_scan = _secret_scan()
    checks = {
        "knowledge_inventory": _knowledge_inventory_report(knowledge_result),
        "private_ignored": private_ignored,
        "secret_scan": secret_scan["report"],
    }
    rules = _rules_check(
        knowledge_result,
        private_ignored,
        secret_scan["objects"],
        inject_failing_context=args.inject_failing_context,
    )
    passed = all(item["passed"] for item in checks.values()) and rules["passed"]
    report = {"passed": passed, "checks": checks, "rules": rules}

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for name, result in checks.items():
            status = "PASS" if result["passed"] else "FAIL"
            print(f"{status} {name}")
        print(("PASS" if rules["passed"] else "FAIL") + " rules")
    return 0 if passed else 1


def _knowledge_inventory_report(result) -> dict[str, object]:
    return {
        "passed": result.passed,
        "missing_paths": list(result.missing_paths),
        "stale_links": list(result.stale_links),
    }


def _private_ignored() -> dict[str, object]:
    target = "_private/plans/COREWEAVER_AGENT_V1_1_0_TRUE_SWARM_REBUILD_PLAN.md"
    completed = subprocess.run(
        ["git", "check-ignore", "-q", "--", target],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return {"passed": completed.returncode == 0, "target": target}


def _secret_scan() -> dict[str, object]:
    findings: list[dict[str, object]] = []
    finding_objects = []
    for path in _iter_text_files(ROOT):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for finding in scan_text_for_secrets(text):
            finding_objects.append(finding)
            findings.append(
                {
                    "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                    "code": finding.code,
                    "line": finding.line,
                    "column": finding.column,
                    "preview": finding.preview,
                }
            )
    return {"report": {"passed": not findings, "findings": findings}, "objects": tuple(finding_objects)}


def _rules_check(
    knowledge_result,
    private_ignored: dict[str, object],
    secret_findings,
    inject_failing_context: bool = False,
) -> dict[str, object]:
    target = str(private_ignored["target"])
    debug_issues = ()
    if inject_failing_context:
        debug_issues = (
            DebugIssue(
                severity=IssueSeverity.BLOCKER,
                source="harness_check",
                code="injected_failure",
                message="injected failing context",
                timestamp="2026-05-26T00:00:00Z",
            ),
        )
    context = HarnessContext(
        repo_root=str(ROOT),
        debug_issues=debug_issues,
        knowledge_inventory=knowledge_result,
        secret_findings=tuple(secret_findings),
        git_ignore_missing=() if private_ignored["passed"] else (target,),
    )
    try:
        rules = load_rules(ROOT / ".rules")
        results = RuleEngine(rules).run(context)
    except Exception as exc:
        return {"passed": False, "load_error": str(exc), "results": []}
    failed_results = [
        result
        for result in results
        if not result.passed and result.severity.value in {"error", "blocker"}
    ]
    return {
        "passed": not failed_results,
        "results": [result.to_dict() for result in results],
    }


def _iter_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = set(path.relative_to(root).parts)
        if parts & EXCLUDED_DIRS:
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            yield path


if __name__ == "__main__":
    raise SystemExit(main())
