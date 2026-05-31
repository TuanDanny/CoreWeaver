from __future__ import annotations

from .models import Agent1ToAgent2Handoff, ArchitecturePlan, ChallengeSeverity, SignoffCertificate, content_id


class Agent2HandoffGate:
    def build(self, *, plan: ArchitecturePlan, certificate: SignoffCertificate, plan_ref: str, certificate_ref: str) -> Agent1ToAgent2Handoff:
        blockers = tuple(f"{finding.gate_id}:{finding.code}" for finding in certificate.findings if finding.severity == ChallengeSeverity.BLOCKER)
        return Agent1ToAgent2Handoff(
            handoff_id=content_id("handoff", [plan.title, certificate.certificate_id, blockers]),
            ready=certificate.passed and not blockers,
            architecture_plan_ref=plan_ref,
            signoff_certificate_ref=certificate_ref,
            locked_interfaces=plan.interfaces,
            locked_registers=plan.registers,
            blockers=blockers,
            trace_refs=plan.provenance_refs,
        )
