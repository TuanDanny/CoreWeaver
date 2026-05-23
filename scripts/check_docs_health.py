from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


REQUIRED_FILES = [
    "AGENTS.md",
    "ARCHITECTURE.md",
    "PLANS.md",
    "docs/knowledge-map.yaml",
    "docs/exec-plans/completed/harness-engineering-100-percent-plan.md",
    "docs/exec-plans/completed/openai-harness-full-compliance-plan.md",
    "docs/exec-plans/superseded/index.md",
    "docs/governance/docs-style-guide.md",
    "docs/governance/source-of-truth-policy.md",
    "docs/governance/docs-review-process.md",
    "docs/governance/stale-docs-policy.md",
    "docs/governance/openai-harness-full-compliance-matrix.md",
    "docs/references/openai-harness-engineering-full-notes.md",
]


FRONTMATTER_REQUIRED_DIRS = [
    ROOT / "docs" / "design-docs",
    ROOT / "docs" / "product-specs",
    ROOT / "docs" / "exec-plans",
    ROOT / "docs" / "prompts",
    ROOT / "docs" / "generated",
    ROOT / "docs" / "references",
    ROOT / "docs" / "governance",
    ROOT / "docs" / "agent-task-cards",
]


LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
BACKTICK_PATH_RE = re.compile(r"`([A-Za-z0-9_./-]+\.(?:md|py|yaml|yml|json))`")
STALE_IMPORT_RE = re.compile(
    r"semiconductor_swarm[./\\]agents[./\\]"
    r"(?:architect|rtl_designer|dv_engineer|physical_designer|formal_verifier|agent[1-5]_prompt)"
    r"(?:\.py)?"
)


def repo_path(path: str) -> Path:
    return ROOT / path


def has_frontmatter(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    return text.startswith("---\n") and "\n---\n" in text[4:]

def frontmatter_field(path: Path, field: str) -> str | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    for line in text[4:end].splitlines():
        if line.startswith(f"{field}:"):
            return line.split(":", 1)[1].strip()
    return None


def iter_docs_with_required_frontmatter():
    for base in FRONTMATTER_REQUIRED_DIRS:
        if not base.exists():
            continue
        yield from base.rglob("*.md")


def extract_yaml_paths(text: str):
    for match in re.finditer(r"(?:^|\s)([A-Za-z0-9_./-]+\.(?:md|py|yaml|yml))", text):
        value = match.group(1).strip()
        if value.startswith(("http://", "https://")):
            continue
        if value.startswith("../"):
            continue
        yield value


def check_required_files(errors: list[str]) -> None:
    for path in REQUIRED_FILES:
        if not repo_path(path).exists():
            errors.append(f"missing required file: {path}")


def check_frontmatter(errors: list[str]) -> None:
    for path in iter_docs_with_required_frontmatter():
        if not has_frontmatter(path):
            errors.append(f"missing frontmatter: {path.relative_to(ROOT).as_posix()}")


def check_markdown_links(errors: list[str]) -> None:
    for path in (ROOT / "docs").rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for target in LINK_RE.findall(text):
            if target.startswith(("http://", "https://", "#")):
                continue
            target = target.split("#", 1)[0]
            if not target:
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                errors.append(
                    f"broken markdown link: {path.relative_to(ROOT).as_posix()} -> {target}"
                )


def check_knowledge_map_paths(errors: list[str]) -> None:
    path = ROOT / "docs" / "knowledge-map.yaml"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    for candidate in extract_yaml_paths(text):
        if not repo_path(candidate).exists():
            errors.append(f"knowledge-map missing target: {candidate}")

def listed_markdown_files(index_path: Path) -> set[str]:
    text = index_path.read_text(encoding="utf-8")
    return {match.group(1) for match in re.finditer(r"- `([^`/\\]+\.md)`", text)}

def check_plan_indexes(errors: list[str]) -> None:
    groups = {
        "active": ROOT / "docs" / "exec-plans" / "active",
        "completed": ROOT / "docs" / "exec-plans" / "completed",
        "superseded": ROOT / "docs" / "exec-plans" / "superseded",
    }
    for name, folder in groups.items():
        index = folder / "index.md"
        if not index.exists():
            errors.append(f"missing {name} plans index: {index.relative_to(ROOT).as_posix()}")
            continue
        actual = {path.name for path in folder.glob("*.md") if path.name != "index.md"}
        listed = listed_markdown_files(index)
        missing = sorted(actual - listed)
        stale = sorted(listed - actual)
        if missing:
            errors.append(f"{name} plans index missing files: {missing}")
        if stale:
            errors.append(f"{name} plans index stale files: {stale}")

    active_dir = groups["active"]
    for path in active_dir.glob("*.md"):
        if path.name == "index.md":
            continue
        status = frontmatter_field(path, "status")
        if status in {"completed", "superseded"}:
            errors.append(f"non-active plan in active folder: {path.relative_to(ROOT).as_posix()} status={status}")

    plans_text = (ROOT / "PLANS.md").read_text(encoding="utf-8")
    for path in active_dir.glob("*.md"):
        if path.name == "index.md":
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel not in plans_text:
            errors.append(f"PLANS.md missing active plan: {rel}")

def check_generated_index_paths(errors: list[str]) -> None:
    for rel in [
        "docs/generated/agent-contract-index.md",
        "docs/generated/prompt-contract-index.md",
        "docs/generated/tool-index.md",
        "docs/generated/test-coverage-index.md",
    ]:
        path = repo_path(rel)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for candidate in BACKTICK_PATH_RE.findall(text):
            if candidate.startswith(("http://", "https://")):
                continue
            if not repo_path(candidate).exists():
                errors.append(f"generated index stale path: {rel} -> {candidate}")

def check_known_stale_paths(errors: list[str]) -> None:
    docs = [ROOT / "README.md", *list((ROOT / "docs").rglob("*.md"))]
    for path in docs:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in STALE_IMPORT_RE.finditer(text):
            errors.append(
                f"known stale agent path: {path.relative_to(ROOT).as_posix()} -> {match.group(0)}"
            )


def check_local_secret_files_not_tracked(errors: list[str]) -> None:
    """Fail docs health if known local-secret files become tracked by git."""
    local_secret_files = ["codex_api.local.json"]
    for relpath in local_secret_files:
        path = repo_path(relpath)
        if not path.exists():
            continue
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", relpath],
            cwd=ROOT,
            check=False,
        ).returncode == 0
        tracked = bool(
            subprocess.run(
                ["git", "ls-files", relpath],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        if not ignored:
            errors.append(f"local secret file is not ignored: {relpath}")
        if tracked:
            errors.append(f"local secret file is tracked: {relpath}")


def main() -> int:
    errors: list[str] = []
    check_required_files(errors)
    check_frontmatter(errors)
    check_markdown_links(errors)
    check_knowledge_map_paths(errors)
    check_plan_indexes(errors)
    check_generated_index_paths(errors)
    check_known_stale_paths(errors)
    check_local_secret_files_not_tracked(errors)
    if errors:
        print("docs health failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("docs health ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
