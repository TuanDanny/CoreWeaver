from __future__ import annotations
import json
from pydantic import BaseModel

from coreweaver.framework_types import stable_hash

from .client import ModelResponse


class MockModelClient:
    async def complete(self, *, prompt: str, idempotency_key: str, response_format: type[BaseModel] | None = None) -> ModelResponse:
        if response_format:
            schema = response_format.model_json_schema()
            if response_format.__name__ == "JudgeResponse":
                dummy_data = {
                    "evaluations": [
                        {"gate_id": f"G{i:02d}", "passed": True, "reason": "mock pass", "evidence_refs": []}
                        for i in range(12)
                    ]
                }
            elif response_format.__name__ == "ArchitecturePlan":
                dummy_data = {
                    "title": "Secure Edge AI Vision NPU",
                    "requirement_summary": "Design a Secure Edge AI Vision NPU. AXI4 DMA APB AES-256",
                    "assumptions": ["mock assumption"],
                    "open_questions": [],
                    "top_level_blocks": ["mock top level"],
                    "interfaces": ["64-bit AXI4", "32-bit APB"],
                    "memory_map": ["64KB SRAM at 0x0"],
                    "registers": [{"name": "KEY", "offset": "0x100", "access": "WO", "reset": "0x0", "description": "lock-after-boot no readback"}],
                    "security_model": ["mock security"],
                    "datapath_control": ["mock datapath"],
                    "reset_clock_cdc": ["synchronous reset", "500MHz"],
                    "interrupt_error_policy": ["error policy"],
                    "formal_intent": ["formal intent"],
                    "dv_intent": ["cocotb intent"],
                    "ppa_risks": ["power < 2W"],
                    "agent2_handoff_contract": ["mock handoff"],
                    "provenance_refs": ["M00", "M01"]
                }
            else:
                def _generate_mock(schema_def: dict, root_defs: dict) -> object:
                    if schema_def.get("type") == "string":
                        return "mock_string"
                    if schema_def.get("type") == "integer":
                        return 0
                    if schema_def.get("type") == "boolean":
                        return True
                    if schema_def.get("type") == "array":
                        items = schema_def.get("items", {})
                        return [_generate_mock(items, root_defs)]
                    if "$ref" in schema_def:
                        ref_name = schema_def["$ref"].split("/")[-1]
                        return _generate_mock(root_defs.get(ref_name, {}), root_defs)
                    if schema_def.get("type") == "object" or "properties" in schema_def:
                        return {k: _generate_mock(v, root_defs) for k, v in schema_def.get("properties", {}).items()}
                    return "mock_unknown"
                dummy_data = _generate_mock(schema, schema.get("$defs", {}))
            text = json.dumps(dummy_data)
        else:
            text = f"mock:{stable_hash({'prompt': prompt, 'key': idempotency_key})[:12]}"
        return ModelResponse(text=text, output_hash=stable_hash(text), prompt_tokens=len(prompt.split()), completion_tokens=len(text.split()))
