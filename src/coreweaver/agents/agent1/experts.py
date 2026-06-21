from __future__ import annotations

from coreweaver.framework_types import make_idempotency_key, stable_hash
from coreweaver.models import ModelRouter
from pydantic import BaseModel, Field

class LeafExpertResponse(BaseModel):
    findings: list[str] = Field(description="List of concise architectural findings")
    risks: list[str] = Field(description="List of identified risks")
    assumptions: list[str] = Field(description="List of assumptions made")

from .models import ExpertResult, ExpertTask, RequirementPack
from .expert_parser import parse_expert_response
from .topology_contract import leaf_name


def build_expert_task(pack: RequirementPack, *, group_id: str, manager_id: str, expert_id: str, iteration: int = 1) -> ExpertTask:
    specialty = leaf_name(expert_id)
    prompt = (
        f"You are the {specialty} expert for CoreWeaver. Your task is to deeply analyze the following semiconductor architecture requirement.\n"
        f"Think step-by-step about the implications of the requirement on your specialty. What are the key architectural findings?\n"
        f"What are the integration risks? What implicit assumptions are being made?\n"
        f"CRITICAL: Be specific, technical, and accurate. Do not hallucinate or add features not explicitly requested or strongly implied by the domain.\n\n"
        f"REQUIREMENT:\n{pack.raw_text}"
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
            response_format=LeafExpertResponse,
        )
        findings, risks, assumptions = parse_expert_response(response.text)
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


