from __future__ import annotations

from typing import Any

from coreweaver.messages import BlackboardEntry, BlackboardSnapshot, MessageKind

from .models import ChallengeSeverity, SignoffFinding


class ReadOnlyVerifier:
    def __init__(self, *, expected_manager_count: int = 7) -> None:
        self.expected_manager_count = expected_manager_count

    def verify(self, snapshot: BlackboardSnapshot) -> tuple[SignoffFinding, ...]:
        findings: list[SignoffFinding] = []
        if not snapshot.entries:
            findings.append(
                SignoffFinding(
                    gate_id="V00",
                    severity=ChallengeSeverity.BLOCKER,
                    code="empty_blackboard",
                    message="Verifier found no blackboard entries.",
                )
            )
            return tuple(findings)
        if snapshot.conflicts:
            findings.append(
                SignoffFinding(
                    gate_id="V02",
                    severity=ChallengeSeverity.BLOCKER,
                    code="blackboard_conflict_unresolved",
                    message="Verifier found unresolved blackboard conflicts.",
                    evidence_refs=tuple(conflict.conflict_id for conflict in snapshot.conflicts),
                )
            )
        requirement_entries = [entry for entry in snapshot.entries if entry.message.kind == MessageKind.USER_REQUIREMENT]
        if len(requirement_entries) != 1:
            findings.append(
                SignoffFinding(
                    gate_id="V03",
                    severity=ChallengeSeverity.BLOCKER,
                    code="requirement_entry_invalid",
                    message="Verifier requires exactly one user requirement entry.",
                    evidence_refs=tuple(entry.entry_id for entry in requirement_entries),
                )
            )
        manager_entries = [entry for entry in snapshot.entries if entry.message.kind == MessageKind.MANAGER_SUMMARY]
        manager_ids = [str(_payload(entry).get("manager_id") or entry.group_id or "") for entry in manager_entries]
        if len(manager_entries) != self.expected_manager_count:
            findings.append(
                SignoffFinding(
                    gate_id="V04",
                    severity=ChallengeSeverity.BLOCKER,
                    code="manager_summary_count_invalid",
                    message=f"Verifier expected {self.expected_manager_count} manager summaries.",
                    evidence_refs=tuple(entry.entry_id for entry in manager_entries),
                )
            )
        duplicates = tuple(sorted({manager_id for manager_id in manager_ids if manager_id and manager_ids.count(manager_id) > 1}))
        if duplicates:
            findings.append(
                SignoffFinding(
                    gate_id="V05",
                    severity=ChallengeSeverity.BLOCKER,
                    code="duplicate_manager_summary",
                    message="Verifier found duplicate manager summaries.",
                    evidence_refs=duplicates,
                )
            )
        for entry in manager_entries:
            payload = _payload(entry)
            accepted = payload.get("accepted_results")
            if not isinstance(accepted, list) or not accepted:
                findings.append(
                    SignoffFinding(
                        gate_id="V06",
                        severity=ChallengeSeverity.BLOCKER,
                        code="manager_summary_without_accepted_evidence",
                        message=f"Manager summary {entry.entry_id} has no accepted expert evidence.",
                        evidence_refs=(entry.entry_id,),
                    )
                )
                continue
            for result in accepted:
                if not isinstance(result, dict):
                    findings.append(_expert_evidence_finding(entry, "expert_result_malformed", "Accepted expert result is malformed."))
                    continue
                missing = [
                    field
                    for field in ("model_call_id", "output_hash", "evidence_refs")
                    if not result.get(field)
                ]
                if missing:
                    findings.append(
                        _expert_evidence_finding(
                            entry,
                            "expert_result_missing_evidence",
                            f"Accepted expert result is missing evidence fields: {', '.join(missing)}.",
                        )
                    )
        for entry in snapshot.entries:
            if not entry.evidence_refs and entry.message.kind.value in {"expert_result", "manager_summary"}:
                findings.append(
                    SignoffFinding(
                        gate_id="V01",
                        severity=ChallengeSeverity.WARN,
                        code="missing_evidence_ref",
                        message=f"Entry {entry.entry_id} has no explicit evidence refs.",
                        evidence_refs=(entry.entry_id,),
                    )
                )
        return tuple(findings)


def _payload(entry: BlackboardEntry) -> dict[str, Any]:
    if not entry.message.blocks:
        return {}
    content = entry.message.blocks[0].content
    return content if isinstance(content, dict) else {}


def _expert_evidence_finding(entry: BlackboardEntry, code: str, message: str) -> SignoffFinding:
    return SignoffFinding(
        gate_id="V07",
        severity=ChallengeSeverity.BLOCKER,
        code=code,
        message=message,
        evidence_refs=(entry.entry_id,),
    )
