from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class HandoffValidationError(ValueError):
    """Raised when Agent1 handoff artifacts are not ready for Agent2."""


def validate_agent1_to_agent2_handoff(path: str | Path) -> dict[str, Any]:
    handoff_path = Path(path)
    try:
        handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HandoffValidationError("agent1_to_agent2 contract is required before Agent2") from exc
    except json.JSONDecodeError as exc:
        raise HandoffValidationError("agent1_to_agent2 contract is malformed JSON") from exc
    if not isinstance(handoff, dict):
        raise HandoffValidationError("agent1_to_agent2 contract must be a JSON object")
    blockers = tuple(str(item) for item in handoff.get("blockers") or ())
    if handoff.get("ready") is not True:
        raise HandoffValidationError("agent1_to_agent2 contract is not ready")
    if blockers:
        raise HandoffValidationError(f"agent1_to_agent2 contract has blockers: {', '.join(blockers)}")
    certificate_ref = str(handoff.get("signoff_certificate_ref") or "")
    if not certificate_ref:
        raise HandoffValidationError("agent1_to_agent2 contract is missing signoff_certificate_ref")
    certificate_path = Path(certificate_ref)
    if not certificate_path.is_absolute() and not certificate_path.exists():
        certificate_path = handoff_path.parent.parent / certificate_path
    try:
        certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HandoffValidationError("signoff certificate referenced by handoff is missing") from exc
    except json.JSONDecodeError as exc:
        raise HandoffValidationError("signoff certificate referenced by handoff is malformed JSON") from exc
    if not isinstance(certificate, dict) or certificate.get("passed") is not True:
        raise HandoffValidationError("signoff certificate does not pass")
    failed_gates = tuple(gate for gate, status in (certificate.get("gate_results") or {}).items() if status != "pass")
    if failed_gates:
        raise HandoffValidationError(f"signoff certificate has failed gates: {', '.join(sorted(failed_gates))}")
    return handoff
