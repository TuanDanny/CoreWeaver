from __future__ import annotations

from typing import Any

from coreweaver.framework_types import StrictCoreModel, stable_hash


class ReplayResumeState(StrictCoreModel):
    schema_version: str = "coreweaver.agent1.resume_state.v1"
    run_id: str
    revision_id: str
    latest_stage: str
    latest_checkpoint_ref: str
    latest_checkpoint_hash: str
    action_required: str | None = None
    terminal_event_type: str | None = None
    blackboard_revision: int | None = None
    event_count: int
    checkpoint_count: int
    reconstructable: bool


class ReplayResumeValidationResult(StrictCoreModel):
    passed: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    resume_state: ReplayResumeState | None = None


def build_replay_resume_state(replay_bundle: dict[str, Any]) -> ReplayResumeState:
    events = replay_bundle.get("events") if isinstance(replay_bundle.get("events"), list) else []
    checkpoints = replay_bundle.get("checkpoints") if isinstance(replay_bundle.get("checkpoints"), list) else []
    latest = _latest_checkpoint(checkpoints)
    latest_payload = latest.get("payload") if isinstance(latest.get("payload"), dict) else {}
    terminal_event = _terminal_event(events)
    terminal_payload = terminal_event.get("payload") if isinstance(terminal_event.get("payload"), dict) else {}
    snapshot = replay_bundle.get("blackboard_snapshot") if isinstance(replay_bundle.get("blackboard_snapshot"), dict) else {}

    revision_id = _text(latest.get("revision_id")) or _first_event_text(events, "revision_id") or "unknown"
    action_required = _text(terminal_payload.get("action_required")) or _action_from_terminal_event(terminal_event)
    blackboard_revision = _int(snapshot.get("revision")) or _int(latest_payload.get("blackboard_revision"))
    checkpoint_hash = _text(latest.get("checkpoint_hash")) or stable_hash(_checkpoint_without_hash(latest))
    latest_stage = _text(latest.get("stage")) or "unknown"
    latest_ref = _text(latest.get("checkpoint_ref")) or "unknown"

    return ReplayResumeState(
        run_id=str(replay_bundle.get("run_id") or _first_event_text(events, "run_id") or "unknown"),
        revision_id=revision_id,
        latest_stage=latest_stage,
        latest_checkpoint_ref=latest_ref,
        latest_checkpoint_hash=checkpoint_hash,
        action_required=action_required,
        terminal_event_type=_text(terminal_event.get("event_type")),
        blackboard_revision=blackboard_revision,
        event_count=len(events),
        checkpoint_count=len(checkpoints),
        reconstructable=bool(checkpoints and latest_stage != "unknown" and action_required),
    )


def validate_replay_resume_state(replay_bundle: dict[str, Any]) -> ReplayResumeValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    if not replay_bundle:
        return ReplayResumeValidationResult(passed=False, errors=("replay_resume_bundle_missing",))

    actual = replay_bundle.get("resume")
    expected = build_replay_resume_state(replay_bundle)
    if not isinstance(actual, dict):
        return ReplayResumeValidationResult(
            passed=False,
            errors=("replay_resume_missing",),
            resume_state=expected,
        )

    for field in (
        "schema_version",
        "run_id",
        "revision_id",
        "latest_stage",
        "latest_checkpoint_ref",
        "latest_checkpoint_hash",
        "action_required",
        "terminal_event_type",
        "blackboard_revision",
        "event_count",
        "checkpoint_count",
        "reconstructable",
    ):
        if actual.get(field) != getattr(expected, field):
            errors.append(f"replay_resume_mismatch:{field}")

    if not expected.reconstructable:
        errors.append("replay_resume_not_reconstructable")
    if expected.latest_checkpoint_ref != "checkpoints/latest.json":
        warnings.append(f"replay_resume_latest_ref_not_canonical:{expected.latest_checkpoint_ref}")

    return ReplayResumeValidationResult(
        passed=not errors,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
        resume_state=expected,
    )


def _latest_checkpoint(checkpoints: list[Any]) -> dict[str, Any]:
    objects = [checkpoint for checkpoint in checkpoints if isinstance(checkpoint, dict)]
    for checkpoint in objects:
        if checkpoint.get("checkpoint_ref") == "checkpoints/latest.json":
            return checkpoint
    return objects[-1] if objects else {}


def _terminal_event(events: list[Any]) -> dict[str, Any]:
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        payload = event.get("payload")
        if isinstance(payload, dict) and payload.get("action_required"):
            return event
        if event.get("event_type") in {"agent1_handoff_ready", "agent1_handoff_blocked", "hitl_required"}:
            return event
    return {}


def _action_from_terminal_event(event: dict[str, Any]) -> str | None:
    event_type = event.get("event_type")
    if event_type == "agent1_handoff_ready":
        return "PLAN_REVIEW"
    if event_type == "agent1_handoff_blocked":
        return "HITL_REQUIRED"
    return None


def _first_event_text(events: list[Any], field: str) -> str | None:
    for event in events:
        if isinstance(event, dict) and event.get(field):
            return str(event[field])
    return None


def _checkpoint_without_hash(checkpoint: dict[str, Any]) -> dict[str, Any]:
    clean = dict(checkpoint)
    clean.pop("checkpoint_hash", None)
    return clean


def _text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
