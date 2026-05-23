"""Studio run manifest and output-directory policy helpers."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_NAME = "studio_run_manifest.json"
LINEAGE_NAME = "run_lineage.json"


class OutputPolicyError(RuntimeError):
    """Raised when a start request needs user choice before touching output."""


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def is_nonempty_output_dir(output_dir: Path) -> bool:
    return output_dir.exists() and any(output_dir.iterdir())


def manifest_path(output_dir: Path) -> Path:
    return output_dir / MANIFEST_NAME


def lineage_path(output_dir: Path) -> Path:
    return output_dir / LINEAGE_NAME


def load_manifest(output_dir: Path) -> dict[str, Any]:
    path = manifest_path(output_dir)
    if not path.is_file():
        raise OutputPolicyError(f"Continue Existing requires valid {MANIFEST_NAME}.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OutputPolicyError(f"Continue Existing requires readable {MANIFEST_NAME}.") from exc
    required = {"schema_version", "run_id", "thread_id", "project_name", "output_dir"}
    missing = sorted(required - set(data))
    if data.get("schema_version") != "studio.run_manifest.v1" or missing:
        raise OutputPolicyError(f"Continue Existing requires valid {MANIFEST_NAME}; missing {missing}.")
    return data


def write_manifest(
    output_dir: Path,
    *,
    run_id: str,
    thread_id: str,
    project_name: str,
    planning_mode: str,
    start_policy: str,
    archived_from: str | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "studio.run_manifest.v1",
        "run_id": run_id,
        "thread_id": thread_id,
        "project_name": project_name,
        "output_dir": str(output_dir),
        "planning_mode": planning_mode,
        "start_policy": start_policy,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "archived_from": archived_from,
    }
    manifest_path(output_dir).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def append_lineage(output_dir: Path, entry: dict[str, Any]) -> dict[str, Any]:
    path = lineage_path(output_dir)
    if path.is_file():
        try:
            lineage = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            lineage = {}
    else:
        lineage = {}
    runs = lineage.get("runs")
    if not isinstance(runs, list):
        runs = []
    runs.append(entry)
    payload = {"schema_version": "studio.run_lineage.v1", "runs": runs}
    output_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def archive_output_dir(output_dir: Path) -> Path | None:
    if not is_nonempty_output_dir(output_dir):
        return None
    parent = output_dir.parent
    archive_root = parent / "_archives"
    archive_root.mkdir(parents=True, exist_ok=True)
    target = archive_root / f"{output_dir.name}_{utc_stamp()}"
    index = 1
    while target.exists():
        target = archive_root / f"{output_dir.name}_{utc_stamp()}_{index}"
        index += 1
    resolved_parent = parent.resolve()
    resolved_target_parent = target.parent.resolve()
    if resolved_parent not in resolved_target_parent.parents and resolved_target_parent != resolved_parent / "_archives":
        raise OutputPolicyError("Archive target escaped output parent.")
    shutil.move(str(output_dir), str(target))
    return target


def output_conflict_message(output_dir: Path) -> str | None:
    if not is_nonempty_output_dir(output_dir):
        return None
    has_manifest = manifest_path(output_dir).is_file()
    suffix = "valid manifest found" if has_manifest else f"missing {MANIFEST_NAME}"
    return f"OUTPUT_EXISTS: {output_dir} already contains files ({suffix}). Choose Archive + Fresh Run, Continue Existing, Rename Output, or Cancel."
