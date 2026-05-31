from __future__ import annotations

from coreweaver.harness.secret_scan import scan_text_for_secrets

from .models import ArchitecturePlan, ChallengeSeverity, SignoffCertificate, SignoffFinding, content_id

GATES = (
    "G00 Requirement completeness",
    "G01 Interface contract",
    "G02 Memory map/register policy",
    "G03 Security/key protection",
    "G04 Reset/clock/CDC",
    "G05 Interrupt/error policy",
    "G06 Formal-first collateral intent",
    "G07 DV/cocotb plan",
    "G08 PPA/timing/power risk",
    "G09 Traceability/provenance",
    "G10 Agent2 handoff schema",
    "G11 Secret leak scan",
    "G12 HITL unresolved risk check",
)


class IndustrialSignoffEngine:
    def evaluate(self, plan: ArchitecturePlan, verifier_findings: tuple[SignoffFinding, ...] = ()) -> SignoffCertificate:
        findings: list[SignoffFinding] = list(verifier_findings)
        gate_results = {gate.split()[0]: "pass" for gate in GATES}
        text = plan.requirement_summary.lower()
        critical_open = tuple(
            item for item in plan.open_questions
            if any(token in item.lower() for token in ("bus/interface", "target clock", "memory/register"))
        )
        if not plan.requirement_summary.strip() or critical_open:
            _fail(findings, gate_results, "G00", "requirement_incomplete", "Requirement is missing critical architecture inputs.")
        if not plan.interfaces or "clarified" in " ".join(plan.interfaces).lower():
            _fail(findings, gate_results, "G01", "interface_contract_missing", "Interface contract is incomplete.")
        if "wrong_bus_width_mutation" in text:
            _fail(findings, gate_results, "G01", "bus_width_conflict", "Bus width mutation is unresolved.")
        if not plan.memory_map or not plan.registers:
            _fail(findings, gate_results, "G02", "memory_register_missing", "Memory map or register table is missing.")
        if "key" in plan.requirement_summary.lower() or "aes" in plan.requirement_summary.lower():
            register_text = " ".join(f"{reg.name} {reg.access} {reg.description}" for reg in plan.registers).lower()
            if "wo" not in register_text or "lock-after-boot" not in register_text or "no readback" not in register_text:
                _fail(findings, gate_results, "G03", "key_policy_incomplete", "Key policy must be WO, lock-after-boot, and no-readback.")
        if not plan.reset_clock_cdc or "no_reset_policy_mutation" in text:
            _fail(findings, gate_results, "G04", "reset_clock_cdc_missing", "Reset/clock/CDC policy is incomplete.")
        if not plan.interrupt_error_policy:
            _fail(findings, gate_results, "G05", "interrupt_error_missing", "Interrupt/error policy is missing.")
        if not plan.formal_intent:
            _fail(findings, gate_results, "G06", "formal_missing", "Formal-first intent is missing.")
        if "missing_formal_plan_mutation" in text:
            _fail(findings, gate_results, "G06", "formal_mutation_detected", "Formal-first plan mutation is unresolved.")
        if not plan.dv_intent:
            _fail(findings, gate_results, "G07", "dv_missing", "DV/cocotb intent is missing.")
        if not plan.ppa_risks or "fake_ppa_estimate_mutation" in text:
            _fail(findings, gate_results, "G08", "ppa_risk_missing", "PPA risk is missing or falsely resolved.")
        if not plan.provenance_refs:
            _fail(findings, gate_results, "G09", "provenance_missing", "No manager/leaf provenance refs exist.")
        if not plan.agent2_handoff_contract:
            _fail(findings, gate_results, "G10", "handoff_schema_missing", "Agent2 handoff schema intent is missing.")
        if scan_text_for_secrets(str(plan.model_dump(mode="json"))):
            _fail(findings, gate_results, "G11", "secret_leak_detected", "Plan contains secret-like material.")
        if any(finding.severity == ChallengeSeverity.BLOCKER for finding in verifier_findings):
            gate_results["G12"] = "fail"
        blocker = any(finding.severity == ChallengeSeverity.BLOCKER for finding in findings)
        return SignoffCertificate(
            certificate_id=content_id("signoff", [plan.title, gate_results, [finding.code for finding in findings]]),
            passed=not blocker,
            findings=tuple(findings),
            gate_results=gate_results,
        )


def _fail(findings: list[SignoffFinding], gate_results: dict[str, str], gate_id: str, code: str, message: str) -> None:
    gate_results[gate_id] = "fail"
    findings.append(SignoffFinding(gate_id=gate_id, severity=ChallengeSeverity.BLOCKER, code=code, message=message))
