"""Local settings and secret-safe config helpers for Studio V6."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CODEX_CONFIG_PATH = ROOT / "codex_api.local.json"
STUDIO_SETTINGS_PATH = ROOT / "studio" / "settings.json"
DEFAULT_CHECKPOINT_DB = ROOT / ".swarm" / "studio_web_checkpoints.sqlite"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "studio_runs"
API_KEY_PLACEHOLDER = "********"
DEFAULT_CREDENTIAL_REF = "owner"
OWNER_KEY_ENV_VARS = ("SWARM_CODEX_API_KEY", "AGENT1_CODEX_API_KEY", "GEMINI_API_KEY")


@dataclass(frozen=True)
class StudioSettings:
    endpoint: str
    model: str
    checkpoint_db: str
    output_root: str
    active_key_ref: str


@dataclass(frozen=True)
class CredentialRef:
    id: str
    label: str
    has_secret: bool
    source: str
    secret: str | None = None


class CredentialError(ValueError):
    """Raised when a credential ref cannot be resolved safely."""


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def load_settings() -> StudioSettings:
    codex = _read_json(CODEX_CONFIG_PATH)
    ui = _read_json(STUDIO_SETTINGS_PATH)
    return StudioSettings(
        endpoint=str(codex.get("base_url") or ui.get("endpoint") or "http://localhost:20128/v1"),
        model=str(codex.get("model") or ui.get("model") or "cx/gpt-5.5"),
        checkpoint_db=str(ui.get("checkpoint_db") or DEFAULT_CHECKPOINT_DB),
        output_root=str(ui.get("output_root") or DEFAULT_OUTPUT_ROOT),
        active_key_ref=str(ui.get("active_key_ref") or DEFAULT_CREDENTIAL_REF),
    )


def has_api_key() -> bool:
    return credential_refs()[0].has_secret


def credential_refs() -> list[CredentialRef]:
    key = None
    source = "missing"
    for env_name in OWNER_KEY_ENV_VARS:
        value = os.environ.get(env_name)
        if value:
            key = value
            source = f"env:{env_name}"
            break
    if key is None:
        local_key = _read_json(CODEX_CONFIG_PATH).get("api_key")
        if local_key:
            key = str(local_key)
            source = "codex_api.local.json"
    return [
        CredentialRef(
            id=DEFAULT_CREDENTIAL_REF,
            label="Owner Local Key",
            has_secret=bool(key),
            source=source,
            secret=key,
        )
    ]


def public_credential_refs() -> list[dict[str, Any]]:
    return [
        {"id": ref.id, "label": ref.label, "hasSecret": ref.has_secret, "source": ref.source}
        for ref in credential_refs()
    ]


def resolve_credential_ref(ref_id: str | None) -> tuple[str | None, dict[str, Any] | None, str | None]:
    requested = (ref_id or DEFAULT_CREDENTIAL_REF).strip() or DEFAULT_CREDENTIAL_REF
    for ref in credential_refs():
        if ref.id == requested:
            public_ref = {"id": ref.id, "label": ref.label, "hasSecret": ref.has_secret, "source": ref.source}
            if ref.secret:
                return ref.secret, public_ref, None
            return None, public_ref, f"Missing API key for credential ref: {ref.id}"
    return None, None, f"Unknown credential ref: {requested}"


def save_settings(endpoint: str, model: str, checkpoint_db: str, output_root: str, active_key_ref: str | None = None) -> StudioSettings:
    current = _read_json(CODEX_CONFIG_PATH)
    next_codex = {
        "base_url": endpoint.strip() or current.get("base_url") or "http://localhost:20128/v1",
        "model": model.strip() or current.get("model") or "cx/gpt-5.5",
    }
    if current.get("api_key"):
        next_codex["api_key"] = current["api_key"]
    _write_json(CODEX_CONFIG_PATH, next_codex)

    ref = (active_key_ref or DEFAULT_CREDENTIAL_REF).strip() or DEFAULT_CREDENTIAL_REF
    if ref not in {item.id for item in credential_refs()}:
        raise CredentialError(f"Unknown credential ref: {ref}")
    ui_settings = {
        "checkpoint_db": checkpoint_db.strip() or str(DEFAULT_CHECKPOINT_DB),
        "output_root": output_root.strip() or str(DEFAULT_OUTPUT_ROOT),
        "active_key_ref": ref,
    }
    _write_json(STUDIO_SETTINGS_PATH, ui_settings)
    return load_settings()


def public_settings_payload() -> dict[str, Any]:
    settings = load_settings()
    return {
        "endpoint": settings.endpoint,
        "model": settings.model,
        "checkpoint_db": settings.checkpoint_db,
        "output_root": settings.output_root,
        "activeKeyRef": settings.active_key_ref,
        "credentialRefs": public_credential_refs(),
    }


def redact_secret_text(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered in {"api_key", "authorization", "token", "access_token"} or "secret" in lowered:
                clean[str(key)] = "<redacted>"
            else:
                clean[str(key)] = redact_secret_text(child)
        return clean
    if isinstance(value, list):
        return [redact_secret_text(item) for item in value]
    if isinstance(value, str) and ("Bearer " in value or "sk-" in value):
        return "<redacted>"
    return value
