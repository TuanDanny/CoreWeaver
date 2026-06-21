from __future__ import annotations

import json
from typing import Any

from coreweaver.harness.secret_scan import scan_text_for_secrets


def extract_json_block(text: str) -> str:
    """Extracts a pure JSON string from text, ignoring markdown blocks and conversational text."""
    start_idx_dict = text.find('{')
    start_idx_list = text.find('[')
    
    start_idx = -1
    if start_idx_dict != -1 and start_idx_list != -1:
        start_idx = min(start_idx_dict, start_idx_list)
    elif start_idx_dict != -1:
        start_idx = start_idx_dict
    else:
        start_idx = start_idx_list
        
    end_idx_dict = text.rfind('}')
    end_idx_list = text.rfind(']')
    
    end_idx = -1
    if end_idx_dict != -1 and end_idx_list != -1:
        end_idx = max(end_idx_dict, end_idx_list)
    elif end_idx_dict != -1:
        end_idx = end_idx_dict
    else:
        end_idx = end_idx_list

    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        return text[start_idx:end_idx + 1]
    return text.strip()


def parse_expert_response(text: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Normalize optional structured model output without requiring live LLM support."""

    if scan_text_for_secrets(text):
        raise ValueError("model_response_secret")

    clean_text = extract_json_block(text)

    try:
        parsed = json.loads(clean_text)
    except json.JSONDecodeError:
        return ((f"model observation: {text}",), (), ())
    if not isinstance(parsed, dict):
        return ((f"model observation: {text}",), (), ())
    findings = _string_tuple(parsed.get("findings"))
    risks = _string_tuple(parsed.get("risks"))
    assumptions = _string_tuple(parsed.get("assumptions"))
    if not findings and not risks and not assumptions:
        return ((f"model observation: {text}",), (), ())
    return findings, risks, assumptions


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()
