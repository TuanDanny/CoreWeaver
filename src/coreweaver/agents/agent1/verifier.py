from __future__ import annotations

from coreweaver.messages import BlackboardSnapshot

from .models import ChallengeSeverity, SignoffFinding


class ReadOnlyVerifier:
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
