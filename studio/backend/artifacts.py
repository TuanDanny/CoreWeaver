"""Safe artifact preview helpers."""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from studio.backend.config import ROOT

TEXT_EXTENSIONS = {".md", ".txt", ".log", ".json", ".jsonl", ".rpt", ".sv", ".v", ".py", ".f", ".yaml", ".yml", ".toml", ".csv"}
MAX_PREVIEW_BYTES = 256 * 1024


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def preview_artifact(path_text: str, active_output_dir: str | None = None) -> dict[str, object]:
    if not path_text:
        raise HTTPException(status_code=400, detail="path is required")
    path = Path(path_text)
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=404, detail="artifact not found") from exc
    outputs_root = (ROOT / "outputs").resolve()
    allowed_roots = [outputs_root]
    if active_output_dir:
        try:
            allowed_roots.append(Path(active_output_dir).resolve(strict=False))
        except OSError:
            pass
    if not any(_is_relative_to(resolved, root) for root in allowed_roots):
        raise HTTPException(status_code=403, detail="artifact path outside output sandbox")
    if resolved.suffix.lower() not in TEXT_EXTENSIONS:
        raise HTTPException(status_code=415, detail="artifact type is not previewable")
    raw = resolved.read_bytes()
    truncated = len(raw) > MAX_PREVIEW_BYTES
    if truncated:
        raw = raw[:MAX_PREVIEW_BYTES]
    text = raw.decode("utf-8", errors="replace")
    if truncated:
        text += "\n...[preview truncated]"
    return {"path": str(resolved), "bytes": resolved.stat().st_size, "truncated": truncated, "text": text}
