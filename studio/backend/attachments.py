"""Attachment staging and run-local input context helpers."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from studio.backend.config import ROOT

MAX_ATTACHMENTS = 10
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_EXTRACT_CHARS_PER_FILE = 20_000
MAX_TOTAL_CONTEXT_CHARS = 60_000
MAX_PDF_PAGES = 25
STAGED_ROOT = ROOT / ".swarm" / "staged_inputs"
ALLOWED_EXTENSIONS = {".md", ".markdown", ".pdf", ".png", ".jpg", ".jpeg", ".webp"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
TEXT_EXTENSIONS = {".md", ".markdown"}


@dataclass(frozen=True)
class AttachmentDraft:
    draft_id: str
    attachments: list[dict[str, Any]]


def _safe_id(value: str | None) -> str:
    raw = str(value or "").strip()
    if re.fullmatch(r"[a-fA-F0-9-]{8,64}", raw):
        return raw
    return uuid4().hex


def _safe_filename(name: str) -> str:
    base = Path(name or "attachment").name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return base[:120] or "attachment"


def _draft_dir(draft_id: str) -> Path:
    safe = _safe_id(draft_id)
    path = (STAGED_ROOT / safe).resolve(strict=False)
    root = STAGED_ROOT.resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="attachment draft outside sandbox") from exc
    return path


def _manifest_path(draft_id: str) -> Path:
    return _draft_dir(draft_id) / "manifest.json"


def _load_manifest(draft_id: str) -> dict[str, Any]:
    path = _manifest_path(draft_id)
    if not path.exists():
        return {"draftId": draft_id, "attachments": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="attachment manifest is corrupted") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="attachment manifest is invalid")
    attachments = data.get("attachments")
    if not isinstance(attachments, list):
        data["attachments"] = []
    return data


def _save_manifest(draft_id: str, manifest: dict[str, Any]) -> None:
    path = _manifest_path(draft_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def _kind_for_extension(extension: str) -> str:
    if extension in TEXT_EXTENSIONS:
        return "markdown"
    if extension == ".pdf":
        return "pdf"
    if extension in IMAGE_EXTENSIONS:
        return "image"
    raise HTTPException(status_code=415, detail=f"unsupported attachment type: {extension or 'unknown'}")


def _validate_magic(kind: str, extension: str, data: bytes) -> None:
    if kind == "pdf" and not data.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="PDF attachment has invalid header")
    if kind == "image":
        ok = (
            extension == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n")
            or extension in {".jpg", ".jpeg"} and data.startswith(b"\xff\xd8")
            or extension == ".webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
        )
        if not ok:
            raise HTTPException(status_code=415, detail="image attachment has invalid header")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _extract_markdown(data: bytes) -> tuple[str, str]:
    text = data.decode("utf-8", errors="replace")
    status = "ok" if len(text) <= MAX_EXTRACT_CHARS_PER_FILE else "truncated"
    return text[:MAX_EXTRACT_CHARS_PER_FILE], status


def _extract_pdf(data: bytes) -> tuple[str, str]:
    try:
        from pypdf import PdfReader
    except Exception:
        return "", "extract_unavailable"
    try:
        reader = PdfReader(BytesIO(data))
        chunks: list[str] = []
        for page in reader.pages[:MAX_PDF_PAGES]:
            chunks.append(page.extract_text() or "")
            if sum(len(item) for item in chunks) >= MAX_EXTRACT_CHARS_PER_FILE:
                break
        text = "\n".join(chunks).strip()
        status = "ok"
        if len(reader.pages) > MAX_PDF_PAGES or len(text) > MAX_EXTRACT_CHARS_PER_FILE:
            status = "truncated"
        return text[:MAX_EXTRACT_CHARS_PER_FILE], status
    except Exception as exc:
        return "", f"extract_failed:{type(exc).__name__}"


def _public_attachment(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record["id"],
        "name": record["name"],
        "kind": record["kind"],
        "mimeType": record.get("mimeType", ""),
        "bytes": record["bytes"],
        "sha256": record["sha256"],
        "extractStatus": record.get("extractStatus", ""),
        "extractedChars": record.get("extractedChars", 0),
        "preview": record.get("preview", ""),
    }


async def stage_attachments(files: list[UploadFile], draft_id: str | None = None) -> AttachmentDraft:
    clean_draft_id = _safe_id(draft_id)
    manifest = _load_manifest(clean_draft_id)
    existing = list(manifest.get("attachments", []))
    if len(existing) + len(files) > MAX_ATTACHMENTS:
        raise HTTPException(status_code=413, detail=f"maximum {MAX_ATTACHMENTS} attachments per draft")

    staged_dir = _draft_dir(clean_draft_id)
    staged_dir.mkdir(parents=True, exist_ok=True)
    for upload in files:
        original = _safe_filename(upload.filename or "attachment")
        extension = Path(original).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=415, detail=f"unsupported attachment type: {extension or 'unknown'}")
        data = await upload.read()
        if not data:
            raise HTTPException(status_code=400, detail=f"empty attachment: {original}")
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=413, detail=f"attachment exceeds 25MB: {original}")
        kind = _kind_for_extension(extension)
        _validate_magic(kind, extension, data)
        attachment_id = uuid4().hex
        stored_name = f"{attachment_id}_{original}"
        stored_path = staged_dir / stored_name
        stored_path.write_bytes(data)
        extracted_text = ""
        extract_status = "metadata_only"
        if kind == "markdown":
            extracted_text, extract_status = _extract_markdown(data)
        elif kind == "pdf":
            extracted_text, extract_status = _extract_pdf(data)
        text_path = ""
        if extracted_text:
            text_file = staged_dir / f"{attachment_id}.txt"
            text_file.write_text(extracted_text, encoding="utf-8")
            text_path = text_file.name
        existing.append(
            {
                "id": attachment_id,
                "name": original,
                "storedName": stored_name,
                "textName": text_path,
                "kind": kind,
                "mimeType": upload.content_type or "",
                "bytes": len(data),
                "sha256": _sha256_bytes(data),
                "extractStatus": extract_status,
                "extractedChars": len(extracted_text),
                "preview": extracted_text[:500],
            }
        )
    manifest = {"draftId": clean_draft_id, "attachments": existing}
    _save_manifest(clean_draft_id, manifest)
    return AttachmentDraft(clean_draft_id, [_public_attachment(item) for item in existing])


def get_staged_attachments(draft_id: str) -> AttachmentDraft:
    clean_draft_id = _safe_id(draft_id)
    manifest = _load_manifest(clean_draft_id)
    return AttachmentDraft(clean_draft_id, [_public_attachment(item) for item in manifest.get("attachments", [])])


def delete_staged_attachment(draft_id: str, attachment_id: str) -> AttachmentDraft:
    clean_draft_id = _safe_id(draft_id)
    manifest = _load_manifest(clean_draft_id)
    kept: list[dict[str, Any]] = []
    removed: dict[str, Any] | None = None
    for item in manifest.get("attachments", []):
        if str(item.get("id")) == attachment_id:
            removed = item
            continue
        kept.append(item)
    if removed is None:
        raise HTTPException(status_code=404, detail="attachment not found")
    staged_dir = _draft_dir(clean_draft_id)
    for key in ("storedName", "textName"):
        name = str(removed.get(key) or "")
        if name:
            path = (staged_dir / name).resolve(strict=False)
            try:
                path.relative_to(staged_dir.resolve(strict=False))
            except ValueError:
                continue
            if path.exists():
                path.unlink()
    manifest["attachments"] = kept
    _save_manifest(clean_draft_id, manifest)
    return AttachmentDraft(clean_draft_id, [_public_attachment(item) for item in kept])


def commit_staged_attachments(draft_id: str | None, attachment_ids: list[str] | None, output_dir: str | Path) -> dict[str, str]:
    if not draft_id:
        return {}
    clean_draft_id = _safe_id(draft_id)
    selected = set(attachment_ids or [])
    manifest = _load_manifest(clean_draft_id)
    records = [item for item in manifest.get("attachments", []) if not selected or str(item.get("id")) in selected]
    if not records:
        return {}
    staged_dir = _draft_dir(clean_draft_id)
    inputs_dir = Path(output_dir) / "inputs"
    attachments_dir = inputs_dir / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    committed: list[dict[str, Any]] = []
    context_parts = ["# Attached input digest", ""]
    remaining = MAX_TOTAL_CONTEXT_CHARS
    for item in records:
        stored_name = str(item.get("storedName") or "")
        source = staged_dir / stored_name
        if not source.exists():
            continue
        target = attachments_dir / stored_name
        shutil.copy2(source, target)
        text = ""
        if item.get("textName"):
            text_path = staged_dir / str(item["textName"])
            if text_path.exists():
                text = text_path.read_text(encoding="utf-8", errors="replace")
        if text and remaining > 0:
            excerpt = text[:remaining]
            remaining -= len(excerpt)
            context_parts.extend([f"## {item['name']}", f"- kind: {item['kind']}", f"- sha256: {item['sha256']}", "", excerpt, ""])
        else:
            context_parts.extend([f"## {item['name']}", f"- kind: {item['kind']}", f"- sha256: {item['sha256']}", f"- extractStatus: {item.get('extractStatus', '')}", ""])
        committed.append({key: value for key, value in item.items() if key not in {"storedName", "textName", "preview"}} | {"storedName": stored_name})
    run_manifest = {
        "schema_version": "studio.attachments_manifest.v1",
        "draftId": clean_draft_id,
        "attachment_count": len(committed),
        "attachments": committed,
    }
    manifest_path = inputs_dir / "attachments_manifest.json"
    context_path = inputs_dir / "attachment_context.md"
    manifest_path.write_text(json.dumps(run_manifest, indent=2, sort_keys=True), encoding="utf-8")
    context_path.write_text("\n".join(context_parts).strip() + "\n", encoding="utf-8")
    return {"attachment_manifest": str(manifest_path), "attachment_context": str(context_path)}
