from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from coreweaver.agents.agent1.models import Agent1ToAgent2Handoff, ChallengeSeverity, SignoffCertificate

REQUIRED_SIGNOFF_GATES = tuple(f"G{i:02d}" for i in range(13))


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
    try:
        parsed_handoff = Agent1ToAgent2Handoff.model_validate(handoff)
    except ValidationError as exc:
        raise HandoffValidationError("agent1_to_agent2 contract does not match schema") from exc
    blockers = tuple(str(item) for item in parsed_handoff.blockers)
    if parsed_handoff.ready is not True:
        raise HandoffValidationError("agent1_to_agent2 contract is not ready")
    if blockers:
        raise HandoffValidationError(f"agent1_to_agent2 contract has blockers: {', '.join(blockers)}")
    if not parsed_handoff.architecture_plan_ref:
        raise HandoffValidationError("agent1_to_agent2 contract is missing architecture_plan_ref")
    if not parsed_handoff.signoff_certificate_ref:
        raise HandoffValidationError("agent1_to_agent2 contract is missing signoff_certificate_ref")
    if not parsed_handoff.locked_interfaces:
        raise HandoffValidationError("agent1_to_agent2 contract is missing locked_interfaces")
    if not parsed_handoff.locked_memory_map:
        raise HandoffValidationError("agent1_to_agent2 contract is missing locked_memory_map")
    if not parsed_handoff.locked_registers:
        raise HandoffValidationError("agent1_to_agent2 contract is missing locked_registers")
    if not parsed_handoff.locked_reset_clock_cdc:
        raise HandoffValidationError("agent1_to_agent2 contract is missing locked_reset_clock_cdc")
    if tuple(sorted(parsed_handoff.signoff_gate_results)) != REQUIRED_SIGNOFF_GATES:
        raise HandoffValidationError("agent1_to_agent2 contract is missing complete signoff_gate_results")
    if any(status != "pass" for status in parsed_handoff.signoff_gate_results.values()):
        raise HandoffValidationError("agent1_to_agent2 contract contains failed signoff gates")
    plan_path = _resolve_artifact_ref(handoff_path, parsed_handoff.architecture_plan_ref)
    if not plan_path.exists():
        raise HandoffValidationError("architecture plan referenced by handoff is missing")
    certificate_path = _resolve_artifact_ref(handoff_path, parsed_handoff.signoff_certificate_ref)
    try:
        certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HandoffValidationError("signoff certificate referenced by handoff is missing") from exc
    except json.JSONDecodeError as exc:
        raise HandoffValidationError("signoff certificate referenced by handoff is malformed JSON") from exc
    try:
        parsed_certificate = SignoffCertificate.model_validate(certificate)
    except ValidationError as exc:
        raise HandoffValidationError("signoff certificate referenced by handoff does not match schema") from exc
    if parsed_certificate.passed is not True:
        raise HandoffValidationError("signoff certificate does not pass")
    if tuple(sorted(parsed_certificate.gate_results)) != REQUIRED_SIGNOFF_GATES:
        raise HandoffValidationError("signoff certificate is missing complete G00-G12 gate results")
    if any(finding.severity == ChallengeSeverity.BLOCKER for finding in parsed_certificate.findings):
        raise HandoffValidationError("signoff certificate contains blocker findings")
    failed_gates = tuple(gate for gate, status in parsed_certificate.gate_results.items() if status != "pass")
    if failed_gates:
        raise HandoffValidationError(f"signoff certificate has failed gates: {', '.join(sorted(failed_gates))}")
    if parsed_certificate.gate_results != parsed_handoff.signoff_gate_results:
        raise HandoffValidationError("handoff signoff_gate_results do not match certificate")
    return parsed_handoff.model_dump(mode="json")


def _resolve_artifact_ref(handoff_path: Path, artifact_ref: str) -> Path:
    path = Path(artifact_ref)
    if path.is_absolute() or path.exists():
        return path
    return handoff_path.parent.parent / path
