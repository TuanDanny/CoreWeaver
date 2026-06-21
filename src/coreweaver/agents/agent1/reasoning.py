from __future__ import annotations

from .intake import extract_requirement_signals
from .models import ArchitecturePlan, ManagerSummary, RegisterEntry, RequirementPack
import json
from coreweaver.models import ModelRouter


class ArchitectureReasoningEngine:
    def __init__(self, model_router: ModelRouter) -> None:
        self.model_router = model_router

    async def synthesize(self, pack: RequirementPack, summaries: tuple[ManagerSummary, ...], idempotency_key: str, feedback: str | None = None) -> ArchitecturePlan:
        context_parts = []
        for summary in summaries:
            accepted = []
            for res in summary.accepted_results:
                accepted.extend(res.findings)
            findings_text = "\n".join(f"- {f}" for f in accepted)
            context_parts.append(f"### {summary.manager_id} Report\n{summary.summary}\nFindings:\n{findings_text}")
        context_str = "\n\n".join(context_parts)

        prompt = (
            f"You are the Principal Architecture Engine for CoreWeaver.\n"
            f"Synthesize the following User Requirement and Manager Reports into a cohesive ArchitecturePlan.\n"
            f"You MUST use the provided context to fill out all fields. If details are missing, explicitly state open assumptions.\n"
            f"CRITICAL: You MUST respond in pure JSON format matching the ArchitecturePlan schema. Do not output any markdown text outside the JSON.\n\n"
            f"USER REQUIREMENT:\n{pack.raw_text}\n\n"
            f"MANAGER REPORTS:\n{context_str}\n"
        )
        if feedback:
            prompt += f"\nFEEDBACK FROM PREVIOUS RUN (MUST FIX):\n{feedback}\n"


        try:
            response, record = await self.model_router.complete(
                prompt=prompt,
                idempotency_key=idempotency_key,
                model_name="agent1-principal",
                response_format=ArchitecturePlan,
            )
            try:
                from .expert_parser import extract_json_block
                clean_text = extract_json_block(response.text)
                plan_data = json.loads(clean_text)
            except Exception:
                clean_text = response.text.strip()
                if clean_text.startswith("```json"): clean_text = clean_text[7:]
                if clean_text.startswith("```"): clean_text = clean_text[3:]
                if clean_text.endswith("```"): clean_text = clean_text[:-3]
                clean_text = clean_text.strip()
                plan_data = json.loads(clean_text)

            provenance = tuple(f"{summary.manager_id}:{summary.output_hash[:12]}" for summary in summaries)
            plan_data["provenance_refs"] = provenance
            plan_data["requirement_summary"] = pack.raw_text
            if not plan_data.get("title"):
                plan_data["title"] = f"{pack.project_name} Architecture Plan"
            return ArchitecturePlan(**plan_data)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._synthesize_fallback(pack, summaries, str(e))

    def _synthesize_fallback(self, pack: RequirementPack, summaries: tuple[ManagerSummary, ...], error_msg: str) -> ArchitecturePlan:
        provenance = tuple(f"{summary.manager_id}:{summary.output_hash[:12]}" for summary in summaries)
        return ArchitecturePlan(
            title="Failed Architecture Synthesis",
            requirement_summary=pack.raw_text,
            assumptions=(f"Synthesis failed due to JSON parse error: {error_msg}",),
            open_questions=pack.missing_fields,
            top_level_blocks=("ERROR: Fallback triggered",),
            interfaces=("ERROR: Fallback triggered",),
            memory_map=("ERROR: Fallback triggered",),
            registers=(),
            security_model=("ERROR: Fallback triggered",),
            datapath_control=("ERROR: Fallback triggered",),
            reset_clock_cdc=("ERROR: Fallback triggered",),
            interrupt_error_policy=("ERROR: Fallback triggered",),
            formal_intent=("ERROR: Fallback triggered",),
            dv_intent=("ERROR: Fallback triggered",),
            ppa_risks=("ERROR: Fallback triggered",),
            agent2_handoff_contract=("ERROR: Fallback triggered",),
            provenance_refs=provenance,
        )
