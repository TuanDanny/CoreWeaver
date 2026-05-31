from __future__ import annotations

import json
from typing import Any

from coreweaver.harness.secret_scan import scan_text_for_secrets


def parse_expert_response(text: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Normalize optional structured model output without requiring live LLM support."""

    if scan_text_for_secrets(text):
        raise ValueError("model_response_secret")
    try:
        parsed = json.loads(text)
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
