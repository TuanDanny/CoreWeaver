"""Agent 2 AI review and surgical patch guardrails."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

FORBIDDEN_PATCH_KEYS = {"full_file", "full_file_content", "replacement_file", "complete_file", "content"}
ALLOWED_PATCH_ACTIONS = {"replace", "insert_before", "insert_after", "delete"}


@dataclass(frozen=True)
class PatchApplyResult:
    pass_: bool
    content: str
    report: dict[str, Any]


def validate_ai_review(payload: dict[str, Any]) -> dict[str, Any]:
    findings = payload.get("findings", [])
    blocking = []
    for index, finding in enumerate(findings if isinstance(findings, list) else []):
        missing = [field for field in ("cited_rule", "source", "source_path", "evidence_snippet", "affected_file", "severity") if not finding.get(field)]
        if missing:
            blocking.append({"index": index, "rule": "missing_review_citation", "missing": missing})
    return {"schema_version": "agent2.ai_review_validation.v1", "pass": not blocking, "blocking_findings": blocking}


def validate_repair_suggestions(payload: dict[str, Any], *, max_patch_lines: int = 80) -> dict[str, Any]:
    suggestions = payload.get("patches", payload.get("suggestions", []))
    blocking = []
    for index, suggestion in enumerate(suggestions if isinstance(suggestions, list) else []):
        keys = set(suggestion)
        forbidden = sorted(keys & FORBIDDEN_PATCH_KEYS)
        action = suggestion.get("action")
        new_code = str(suggestion.get("new_code", ""))
        line_count = len(new_code.splitlines())
        if forbidden:
            blocking.append({"index": index, "rule": "full_file_rewrite_forbidden", "forbidden_keys": forbidden})
        if action not in ALLOWED_PATCH_ACTIONS and "unified_diff" not in suggestion:
            blocking.append({"index": index, "rule": "unsupported_patch_action", "action": action})
        if line_count > max_patch_lines:
            blocking.append({"index": index, "rule": "patch_too_large", "line_count": line_count, "max_patch_lines": max_patch_lines})
    return {"schema_version": "agent2.ai_repair_validation.v1", "pass": not blocking, "blocking_findings": blocking}


def build_context_slice(files: list[dict[str, Any]], finding: dict[str, Any], *, max_block_lines: int = 80, context_lines: int = 20, max_total_lines: int = 140) -> dict[str, Any]:
    filename = str(finding.get("file") or finding.get("affected_file") or "")
    target_line = int(finding.get("line", finding.get("line_start", 1)) or 1)
    file_entry = next((file for file in files if str(file.get("filename")) == filename), None)
    if not file_entry:
        return {"schema_version": "agent2.context_slice.v1", "pass": False, "reason": "file_not_found", "file": filename}
    content = str(file_entry.get("content", ""))
    lines = content.splitlines()
    if not lines:
        return {"schema_version": "agent2.context_slice.v1", "pass": False, "reason": "empty_file", "file": filename}

    block = _find_structural_block(lines, target_line)
    parser_mode = "ast_structural_block" if block else "line_window"
    if block:
        start, end = block
        if end - start + 1 > max_block_lines:
            center = min(max(target_line, start), end)
            start = max(start, center - max_block_lines // 2)
            end = min(end, start + max_block_lines - 1)
    else:
        start = max(1, target_line - context_lines)
        end = min(len(lines), target_line + context_lines)

    start = max(1, start - context_lines)
    end = min(len(lines), end + context_lines)
    if end - start + 1 > max_total_lines:
        center = min(max(target_line, start), end)
        start = max(1, center - max_total_lines // 2)
        end = min(len(lines), start + max_total_lines - 1)
    snippet = "\n".join(lines[start - 1 : end])
    return {
        "schema_version": "agent2.context_slice.v1",
        "pass": True,
        "file": filename,
        "line_start": start,
        "line_end": end,
        "target_line": target_line,
        "parser_mode": parser_mode,
        "sha256": hashlib.sha256(snippet.encode("utf-8")).hexdigest(),
        "line_count": len(snippet.splitlines()),
        "snippet": snippet,
        "finding": {key: finding.get(key) for key in ("rule", "message", "cited_rule", "severity") if key in finding},
    }


def _find_structural_block(lines: list[str], target_line: int) -> tuple[int, int] | None:
    start_patterns = (r"\balways_ff\b", r"\balways_comb\b", r"^\s*assign\s+", r"^\s*[A-Za-z_][A-Za-z0-9_]*\s+u_[A-Za-z0-9_]+")
    starts = [idx for idx, line in enumerate(lines, start=1) if any(re.search(pattern, line) for pattern in start_patterns)]
    starts = [idx for idx in starts if idx <= target_line]
    if not starts:
        return None
    start = starts[-1]
    if "assign" in lines[start - 1] and lines[start - 1].rstrip().endswith(";"):
        return start, start
    depth = 0
    seen_begin = False
    for idx in range(start, len(lines) + 1):
        text = lines[idx - 1]
        begins = len(re.findall(r"\bbegin\b", text))
        ends = len(re.findall(r"\bend\b", text))
        if begins:
            seen_begin = True
        depth += begins - ends
        if seen_begin and depth <= 0 and idx > start:
            return start, idx
        if not seen_begin and text.rstrip().endswith(";"):
            return start, idx
    return start, min(len(lines), start + 79)


def apply_json_patch(content: str, patch: dict[str, Any]) -> PatchApplyResult:
    lines = content.splitlines()
    line = int(patch.get("line", patch.get("line_start", 1)) or 1)
    old_text = str(patch.get("old_text", ""))
    old_hash = patch.get("old_sha256")
    new_code = str(patch.get("new_code", ""))
    action = str(patch.get("action", "replace"))
    if line < 1 or line > len(lines) + 1:
        return _patch_fail(content, "line_out_of_range", patch, actual_text="")
    actual_text = lines[line - 1] if line <= len(lines) else ""
    if old_hash and hashlib.sha256(actual_text.encode("utf-8")).hexdigest() != old_hash:
        return _patch_fail(content, "old_hash_mismatch", patch, actual_text=actual_text)
    if old_text and old_text != actual_text:
        return _patch_fail(content, "old_text_mismatch", patch, actual_text=actual_text)
    if action == "replace":
        lines[line - 1 : line] = new_code.splitlines()
    elif action == "insert_before":
        lines[line - 1 : line - 1] = new_code.splitlines()
    elif action == "insert_after":
        lines[line:line] = new_code.splitlines()
    elif action == "delete":
        del lines[line - 1 : line]
    else:
        return _patch_fail(content, "unsupported_action", patch, actual_text=actual_text)
    patched = "\n".join(lines) + ("\n" if content.endswith("\n") else "")
    return PatchApplyResult(True, patched, {"schema_version": "agent2.patch_apply_report.v1", "pass": True, "action": action, "file": patch.get("file"), "line": line})


def _patch_fail(content: str, reason: str, patch: dict[str, Any], *, actual_text: str) -> PatchApplyResult:
    return PatchApplyResult(
        False,
        content,
        {
            "schema_version": "agent2.patch_apply_report.v1",
            "pass": False,
            "reason": reason,
            "file": patch.get("file"),
            "line": patch.get("line", patch.get("line_start")),
            "expected_old_text": patch.get("old_text"),
            "actual_old_text": actual_text,
            "actual_old_sha256": hashlib.sha256(actual_text.encode("utf-8")).hexdigest(),
        },
    )
