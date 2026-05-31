from __future__ import annotations

from coreweaver.framework_types import make_idempotency_key, stable_hash
from coreweaver.models import ModelRouter

from .models import ExpertResult, ExpertTask, RequirementPack
from .expert_parser import parse_expert_response
from .topology_contract import leaf_name


def build_expert_task(pack: RequirementPack, *, group_id: str, manager_id: str, expert_id: str, iteration: int = 1) -> ExpertTask:
    specialty = leaf_name(expert_id)
    prompt = (
        f"You are {specialty}. Analyze this semiconductor architecture requirement for CoreWeaver.\n"
        f"Return concise findings, risks, assumptions, and evidence needs.\n"
        f"Requirement:\n{pack.raw_text}"
    )
    return ExpertTask(
        task_id=f"task:{pack.requirement_id}:{expert_id}:{iteration}",
        group_id=group_id,
        manager_id=manager_id,
        expert_id=expert_id,
        specialty=specialty,
        prompt=prompt,
        input_hash=stable_hash(prompt),
        idempotency_key=make_idempotency_key(pack.requirement_id, group_id, expert_id, iteration),
    )


class LeafExpertWorker:
    def __init__(self, model_router: ModelRouter) -> None:
        self.model_router = model_router

    async def run(self, task: ExpertTask, pack: RequirementPack) -> ExpertResult:
        response, record = await self.model_router.complete(
            prompt=task.prompt,
            idempotency_key=task.idempotency_key,
            model_name="agent1-leaf",
        )
        findings, risks, assumptions = _domain_findings(task.specialty, pack.raw_text)
        parsed_findings, parsed_risks, parsed_assumptions = parse_expert_response(response.text)
        findings = (*findings, *parsed_findings)
        risks = (*risks, *parsed_risks)
        assumptions = (*assumptions, *parsed_assumptions)
        return ExpertResult(
            task_id=task.task_id,
            group_id=task.group_id,
            manager_id=task.manager_id,
            expert_id=task.expert_id,
            specialty=task.specialty,
            status="passed",
            findings=tuple(findings),
            risks=tuple(risks),
            assumptions=tuple(assumptions),
            evidence_refs=(record.model_call_id,),
            model_call_id=record.model_call_id,
            latency_ms=record.latency_ms,
            prompt_tokens=record.prompt_tokens,
            completion_tokens=record.completion_tokens,
            cost_usd=record.cost_usd,
            output_hash=stable_hash([findings, risks, assumptions, record.output_hash]),
        )


def _domain_findings(specialty: str, requirement: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    text = requirement.lower()
    findings: list[str] = []
    risks: list[str] = []
    assumptions: list[str] = []
    if "axi" in specialty or "apb" in specialty:
        if "axi4" in text or "axi" in text:
            findings.append("Use AXI4 for high-throughput DMA/data movement and keep ordering/backpressure explicit.")
        if "apb" in text:
            findings.append("Use APB for low-bandwidth firmware configuration and CSR access.")
    if "dma" in specialty or "bandwidth" in specialty:
        findings.append("Bandwidth plan must account for image stream rate, NPU consumption rate, and SRAM refill latency.")
        if "500mhz" in text:
            risks.append("500MHz target requires careful DMA arbitration and timing-friendly buffering.")
    if "csr" in specialty or "register" in specialty:
        findings.append("CSR map must distinguish RW, RO, W1C, WO, and lock-after-boot fields.")
    if "sram" in specialty or "memory" in specialty:
        if "64kb" in text:
            findings.append("64KB SRAM buffer should be partitioned between DMA staging, MAC feed, and decrypted weight windows.")
        findings.append("Memory map must keep firmware CSRs separate from datapath SRAM windows.")
    if "crypto" in specialty:
        if "aes" in text:
            findings.append("AES-256 decrypt path must sit on the weight fetch path before MAC-array consumption.")
    if "key_protection" in specialty or "threat" in specialty:
        if "key" in text:
            findings.append("Secret key register must be write-only, no readback, and locked after boot.")
            risks.append("Readable or debug-visible key material is a blocker.")
    if "formal" in specialty:
        findings.append("Formal properties should cover key no-readback, lock monotonicity, APB access policy, and AXI handshake safety.")
    if "cocotb" in specialty or "coverage" in specialty:
        findings.append("DV should include APB CSR tests, AXI DMA stress, AES/key negative tests, and reset/clock coverage.")
    if "timing" in specialty:
        findings.append("500MHz requires pipeline boundaries around AES, SRAM, MAC feed, and AXI crossing points.")
    if "power" in specialty:
        if "< 2w" in text or "<2w" in text:
            findings.append("Power plan must include MAC-array clock gating, SRAM banking, and AES activity gating.")
            risks.append("<2W is a signoff risk until workload and process node are known.")
    if "handoff" in specialty or "traceability" in specialty:
        findings.append("Agent2 handoff must lock interface widths, reset/clock, register access types, and security invariants.")
    if not findings:
        findings.append(f"{specialty} found no blocker, but requires evidence in final plan.")
    if "reset" not in text:
        assumptions.append("Reset polarity and reset sequencing are not specified.")
    return tuple(findings), tuple(risks), tuple(assumptions)
