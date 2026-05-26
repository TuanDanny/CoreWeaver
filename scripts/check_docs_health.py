from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


REQUIRED_FILES = [
    "AGENTS.md",
    "ARCHITECTURE.md",
    "docs/knowledge-map.yaml",
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

def check_private_plan_files_not_public(errors: list[str]) -> None:
    """Internal planning material must stay outside the publishable tree."""
    forbidden_paths = [
        ROOT / "PLANS.md",
        ROOT / "docs" / "exec-plans",
        ROOT / "docs" / "design-docs" / "agent1-v72-industrial-signoff-contract.md",
    ]
    for path in forbidden_paths:
        if path.exists():
            errors.append(f"private planning path must stay local-only: {path.relative_to(ROOT).as_posix()}")

    for pattern in (
        "*PLAN*.md",
        "*Plan*.md",
        "*plan*.md",
        "*UPGRADE*.md",
        "*Upgrade*.md",
        "*upgrade*.md",
        "*TASKS*.md",
        "*Tasks*.md",
        "*tasks*.md",
    ):
        for path in (ROOT / "docs").glob(pattern):
            errors.append(f"private planning doc in public docs root: {path.relative_to(ROOT).as_posix()}")

    for path in (ROOT / "docs" / "prompts").glob("*upgrade*.md"):
        errors.append(f"private upgrade prompt in public prompt docs: {path.relative_to(ROOT).as_posix()}")
    for path in (ROOT / "docs" / "prompts").glob("*Upgrade*.md"):
        errors.append(f"private upgrade prompt in public prompt docs: {path.relative_to(ROOT).as_posix()}")
    for base in (ROOT / "docs" / "generated", ROOT / "docs" / "governance"):
        for path in base.glob("Kiem_tra_toan_bo_Agent_AI_*.md"):
            errors.append(f"private audit artifact in public docs: {path.relative_to(ROOT).as_posix()}")

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
    check_private_plan_files_not_public(errors)
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
