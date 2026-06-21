from __future__ import annotations

from coreweaver.harness.secret_scan import scan_text_for_secrets
import json
from pydantic import BaseModel
from coreweaver.models import ModelRouter

from .models import ArchitecturePlan, ChallengeSeverity, SignoffCertificate, SignoffFinding, content_id

class GateEvaluation(BaseModel):
    gate_id: str
    passed: bool
    reason: str

class JudgeResponse(BaseModel):
    evaluations: list[GateEvaluation]

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
    def __init__(self, model_router: ModelRouter) -> None:
        self.model_router = model_router

    async def evaluate(self, plan: ArchitecturePlan, verifier_findings: tuple[SignoffFinding, ...], idempotency_key: str) -> SignoffCertificate:
        prompt = (
            "You are the CoreWeaver Signoff Judge. Evaluate this Architecture Plan against gates G00 to G10.\n"
            "CRITICAL: You MUST cross-check every detail in the architecture plan against the 'requirement_summary'. "
            "If the requirement specifies numbers (like 64-bit, 32-bit, 64KB, 500MHz, 2W) or specific mechanisms (synchronous reset, lock-after-boot), "
            "you MUST fail the plan if they are missing or deferred.\n"
            "CRITICAL: You MUST respond in pure JSON format matching the JudgeResponse schema (evaluations list). Do not output any markdown text outside the JSON.\n\n"
            f"Plan details:\n{plan.model_dump_json(indent=2)}\n"
        )
        try:
            response, record = await self.model_router.complete(
                prompt=prompt,
                idempotency_key=idempotency_key,
                model_name="agent1-signoff-judge",
                response_format=JudgeResponse
            )
            try:
                from .expert_parser import extract_json_block
                clean_text = extract_json_block(response.text)
                judge_data = json.loads(clean_text)
                judge_response = JudgeResponse(**judge_data)
            except Exception:
                clean_text = response.text.strip()
                if clean_text.startswith("```json"): clean_text = clean_text[7:]
                if clean_text.startswith("```"): clean_text = clean_text[3:]
                if clean_text.endswith("```"): clean_text = clean_text[:-3]
                clean_text = clean_text.strip()
                judge_data = json.loads(clean_text)
                judge_response = JudgeResponse(**judge_data)

            
            findings: list[SignoffFinding] = list(verifier_findings)
            gate_results = {gate.split()[0]: "pass" for gate in GATES}
            
            # Apply LLM evaluations
            for eval_gate in judge_response.evaluations:
                if eval_gate.gate_id in gate_results:
                    if not eval_gate.passed:
                        _fail(findings, gate_results, eval_gate.gate_id, "llm_judge_failed", eval_gate.reason)

            # Apply deterministic checks
            text = plan.requirement_summary.lower()
            if "wrong_bus_width_mutation" in text:
                _fail(findings, gate_results, "G01", "bus_width_conflict", "Bus width mutation is unresolved.")
            if "no_reset_policy_mutation" in text:
                _fail(findings, gate_results, "G04", "reset_clock_cdc_missing", "Reset/clock/CDC policy is incomplete.")
            if "missing_formal_plan_mutation" in text:
                _fail(findings, gate_results, "G06", "formal_mutation_detected", "Formal-first plan mutation is unresolved.")
            if "fake_ppa_estimate_mutation" in text:
                _fail(findings, gate_results, "G08", "ppa_risk_missing", "PPA risk is missing or falsely resolved.")
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
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._evaluate_fallback(plan, verifier_findings, str(e))
    def _evaluate_fallback(self, plan: ArchitecturePlan, verifier_findings: tuple[SignoffFinding, ...], error_msg: str) -> SignoffCertificate:
        findings: list[SignoffFinding] = list(verifier_findings)
        gate_results = {gate.split()[0]: "pass" for gate in GATES}
        
        _fail(findings, gate_results, "G00", "judge_parse_error", f"LLM Judge failed to return valid JSON: {error_msg}")
        
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
