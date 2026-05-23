"""AI-first Agent 1 expert council orchestration."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

from semiconductor_swarm.agents.agent1_planning.architect import requirement_needs_clarification
from semiconductor_swarm.agents.agent1_planning.capability_registry import assess_requirement_capability
from semiconductor_swarm.runtime_events import emit_runtime_event

EXPERTS = (
    ("requirement_intake", "Requirement Intake Expert", "Extract explicit requirements, assumptions, and unknowns."),
    ("protocol_interconnect", "Protocol And Interconnect Expert", "Select bus/interconnect topology and bridge strategy."),
    ("cpu_memory", "CPU And Memory Expert", "Select CPU width, ISA, reset, memory hierarchy, and boot assumptions."),
    ("peripheral_register", "Peripheral And Register Expert", "Define requested peripherals and register intent only."),
    ("verification_formal", "Verification And Formal Expert", "Define acceptance criteria for selected protocol and IP."),
    ("downstream_compatibility", "Downstream Compatibility Expert", "Assess Agent 2/3/4/5 capability compatibility."),
)

CodexCall = Callable[..., Any]


def run_agent1_expert_council(requirement: str, project_name: str, codex_call: CodexCall) -> dict[str, Any]:
    """Run compact expert calls and synthesize a decision-complete analysis."""
    base_intents = _extract_intents(requirement)
    expert_outputs = []
    trace_lines = []
    for expert_id, title, mission in EXPERTS:
        prompt = _expert_prompt(expert_id, title, mission, requirement, project_name, base_intents)
        emit_runtime_event(
            {
                "type": "agent_action",
                "agent": "agent1",
                "label": "Agent 1 Architect",
                "phase": "planning",
                "action": f"{title} started",
                "status": "running",
                "summary": mission,
            }
        )
        result = codex_call(prompt)
        parsed = _parse_expert_content(result.content, expert_id, title, requirement, base_intents)
        evidence = _safe_evidence(getattr(result, "evidence", {}), prompt, result.content, expert_id)
        expert_record = {"expert_id": expert_id, "title": title, "mission": mission, "output": parsed, "evidence": evidence}
        expert_outputs.append(expert_record)
        trace_lines.append(json.dumps({"expert_id": expert_id, "title": title, "evidence": evidence, "output_hash": _sha256(json.dumps(parsed, sort_keys=True))}, sort_keys=True))
        emit_runtime_event(
            {
                "type": "agent_action",
                "agent": "agent1",
                "label": "Agent 1 Architect",
                "phase": "planning",
                "action": f"{title} completed",
                "status": "pass",
                "summary": parsed.get("summary", f"{title} completed."),
                "metric": {"total_tokens": evidence.get("total_tokens")},
            }
        )

    selected = _synthesize_architecture(requirement, project_name, base_intents, expert_outputs)
    analysis: dict[str, Any] = {
        "schema_version": "agent1.ai_requirement_analysis.v1",
        "project_name": project_name,
        "raw_requirement": requirement,
        "extracted_intents": base_intents,
        "expert_outputs": expert_outputs,
        "selected_architecture": selected,
        "rejected_alternatives": _rejected_alternatives(base_intents),
        "assumptions": _assumptions(base_intents),
        "open_questions": _open_questions(base_intents),
        "citations": _citations(requirement, base_intents),
        "confidence": _confidence(base_intents),
    }
    capability = assess_requirement_capability(analysis)
    selected["compatibility_mode"] = capability["mode"]
    selected["bridge"] = capability.get("bridge")
    selected["capability_gaps"] = capability["capability_gaps"]
    analysis["capability_assessment"] = capability
    analysis["expert_trace_jsonl"] = "\n".join(trace_lines) + "\n"
    return analysis


def _expert_prompt(expert_id: str, title: str, mission: str, requirement: str, project_name: str, base_intents: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# Agent 1 V5 {title}",
            mission,
            "Return JSON only with fields: summary, decisions, assumptions, open_questions, citations.",
            "Citations must quote or paraphrase exact user requirement fragments.",
            "Do not calculate numeric PPA or bandwidth.",
            "Do not replace an explicit bus protocol with another protocol without naming a bridge/capability gap.",
            f"Expert ID: {expert_id}",
            f"Project: {project_name}",
            f"Requirement: {requirement}",
            f"Deterministic extraction seed: {json.dumps(base_intents, sort_keys=True)}",
        ]
    )


def _parse_expert_content(content: str, expert_id: str, title: str, requirement: str, base_intents: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict) and parsed.get("summary"):
            parsed.setdefault("parse_status", "json")
            return parsed
    except json.JSONDecodeError:
        pass
    return {
        "summary": f"{title} evidence captured; deterministic extraction used because response was not structured JSON.",
        "decisions": _fallback_decisions(base_intents),
        "assumptions": _assumptions(base_intents),
        "open_questions": _open_questions(base_intents),
        "citations": _citations(requirement, base_intents),
        "parse_status": "deterministic_fallback_from_unstructured_codex",
        "raw_response_sha256": _sha256(content),
        "expert_id": expert_id,
    }


def _safe_evidence(evidence: dict[str, Any], prompt: str, response: str, expert_id: str) -> dict[str, Any]:
    clean = dict(evidence) if isinstance(evidence, dict) else {}
    if "api_key" in clean:
        clean["api_key"] = "<redacted>"
    clean.setdefault("prompt_sha256", _sha256(prompt))
    clean.setdefault("response_sha256", _sha256(response))
    clean["expert_id"] = expert_id
    return clean


def _extract_intents(requirement: str) -> dict[str, Any]:
    text = requirement.lower()
    bus = _extract_bus(text)
    cpu_width = _extract_cpu_width(text)
    peripherals = [name for name in ("uart", "spi", "i2c", "gpio") if re.search(rf"\b{name}\b", text)]
    return {
        "cpu_requested": bool(re.search(r"\b(cpu|processor|core|risc-v|rv32|rv64)\b", text)),
        "cpu_width_bits": cpu_width,
        "requested_bus_protocol": bus,
        "external_peripherals": peripherals,
        "frequency_mhz": _extract_int_before(text, "mhz"),
        "target_node": "12nm" if "12nm" in text else ("28nm" if "28nm" in text else None),
        "power_budget_mw": _extract_power_budget_mw(text),
        "explicit_constraints": _explicit_constraints(text),
        "unknowns": _unknowns(text, bus, cpu_width, peripherals),
    }


def _extract_bus(text: str) -> str | None:
    for bus in ("ahb", "apb", "axi", "wishbone"):
        if re.search(rf"\b{bus}\b", text):
            return bus.upper()
    return None


def _extract_cpu_width(text: str) -> int | None:
    if re.search(r"\brv32\b|\brv32i\b|\brv32imc\b", text):
        return 32
    if re.search(r"\brv64\b|\brv64i\b|\brv64gc\b|\brv64imc\b", text):
        return 64
    match = re.search(r"(\d+)\s*[- ]?bit\s+(?:cpu|processor|core|architecture)", text)
    if match:
        return int(match.group(1))
    match = re.search(r"(?:cpu|processor|core).{0,24}?(\d+)\s*[- ]?bit", text)
    return int(match.group(1)) if match else None


def _extract_int_before(text: str, unit: str) -> int | None:
    match = re.search(rf"(\d+)\s*{re.escape(unit)}", text)
    return int(match.group(1)) if match else None


def _extract_power_budget_mw(text: str) -> int | None:
    watt_match = re.search(r"<\s*(\d+(?:\.\d+)?)\s*w", text)
    if watt_match:
        return int(float(watt_match.group(1)) * 1000)
    mw_match = re.search(r"<\s*(\d+)\s*mw", text)
    return int(mw_match.group(1)) if mw_match else None


def _explicit_constraints(text: str) -> list[str]:
    constraints = []
    if "no apb" in text or "without apb" in text or "pure ahb" in text or "ahb only" in text:
        constraints.append("no_apb_bridge")
    if "external peripheral" in text:
        constraints.append("external_peripheral_declared")
    return constraints


def _unknowns(text: str, bus: str | None, cpu_width: int | None, peripherals: list[str]) -> list[str]:
    unknowns = []
    if bus is None:
        unknowns.append("bus_protocol")
    if re.search(r"\b(cpu|processor|core)\b", text) and cpu_width is None:
        unknowns.append("cpu_width_bits")
    if not peripherals:
        unknowns.append("external_peripherals")
    if "mhz" not in text:
        unknowns.append("frequency_mhz")
    if "nm" not in text:
        unknowns.append("target_node")
    if "mw" not in text and "w" not in text:
        unknowns.append("power_budget_mw")
    return unknowns


def _synthesize_architecture(requirement: str, project_name: str, intents: dict[str, Any], experts: list[dict[str, Any]]) -> dict[str, Any]:
    if requirement_needs_clarification(requirement):
        return {
            "project_name": project_name,
            "status": "requires_clarification",
            "summary": "No architecture selected because Project Requirement contains no actionable chip-design intent.",
            "cpu_width_bits": None,
            "isa": None,
            "primary_protocol": None,
            "peripheral_protocol": None,
            "bridges": [],
            "external_peripherals": [],
            "source_experts": [item["expert_id"] for item in experts],
            "required_user_clarifications": [
                "chip purpose",
                "CPU/peripheral/IP intent",
                "bus protocol",
                "frequency or constraints",
            ],
        }
    requested_bus = intents.get("requested_bus_protocol") or "APB"
    cpu_width = intents.get("cpu_width_bits") or 32
    peripheral_protocol = "APB" if requested_bus in {"AHB", "APB"} else requested_bus
    bridges = []
    if requested_bus == "AHB":
        bridges.append({"name": "ahb_to_apb_bridge", "from_protocol": "AHB", "to_protocol": "APB", "boundary": "peripheral_subsystem"})
    return {
        "project_name": project_name,
        "summary": f"{cpu_width}-bit CPU architecture using {requested_bus} primary bus with {', '.join(intents.get('external_peripherals') or ['no declared external peripheral'])}.",
        "cpu_width_bits": cpu_width,
        "isa": "rv32imc" if cpu_width == 32 else f"rv{cpu_width}imc",
        "primary_protocol": requested_bus,
        "peripheral_protocol": peripheral_protocol,
        "bridges": bridges,
        "external_peripherals": intents.get("external_peripherals", []),
        "source_experts": [item["expert_id"] for item in experts],
    }


def _fallback_decisions(intents: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"decision": "cpu_width", "value": intents.get("cpu_width_bits"), "source": "raw_requirement_extraction"},
        {"decision": "primary_bus", "value": intents.get("requested_bus_protocol"), "source": "raw_requirement_extraction"},
        {"decision": "external_peripherals", "value": intents.get("external_peripherals", []), "source": "raw_requirement_extraction"},
    ]


def _rejected_alternatives(intents: dict[str, Any]) -> list[dict[str, Any]]:
    requested = intents.get("requested_bus_protocol") or "APB"
    alternatives = []
    if requested != "APB":
        alternatives.append({"name": "APB-only baseline", "reason": f"Rejected because user requested {requested} as the primary bus."})
    if requested == "AHB":
        alternatives.append({"name": "Pure native AHB end-to-end", "reason": "Rejected for current practical run because downstream Agent 2/3/5 full AHB support is not complete; bridge strategy keeps flow executable."})
    if not intents.get("external_peripherals"):
        alternatives.append({"name": "External peripheral subsystem", "reason": "Rejected because no external peripheral was explicitly requested."})
    return alternatives


def _assumptions(intents: dict[str, Any]) -> list[str]:
    assumptions = []
    if intents.get("frequency_mhz") is None:
        assumptions.append("No explicit frequency provided; use 50 MHz until user or tool constraints say otherwise.")
    if intents.get("target_node") is None:
        assumptions.append("No process node provided; use 28nm as deterministic estimation default.")
    if intents.get("power_budget_mw") is None:
        assumptions.append("No power budget provided; record power as unspecified instead of inventing a limit.")
    if intents.get("requested_bus_protocol") is None:
        assumptions.append("No bus protocol declared; APB is a fallback only after clarification or explicit compatibility decision.")
    return assumptions


def _open_questions(intents: dict[str, Any]) -> list[str]:
    questions = []
    if intents.get("frequency_mhz") is None:
        questions.append("Confirm target operating frequency before timing signoff.")
    if intents.get("power_budget_mw") is None:
        questions.append("Confirm power budget before power optimization signoff.")
    if intents.get("requested_bus_protocol") == "AHB":
        questions.append("Confirm whether an AHB-to-APB peripheral bridge is acceptable for current downstream RTL/DV/formal capability.")
    return questions


def _citations(requirement: str, intents: dict[str, Any]) -> list[dict[str, Any]]:
    citations = []
    for label, value in (
        ("cpu_width_bits", intents.get("cpu_width_bits")),
        ("requested_bus_protocol", intents.get("requested_bus_protocol")),
    ):
        if value:
            citations.append({"field": label, "source": "raw_requirement", "evidence_snippet": _snippet_for(requirement, str(value))})
    for peripheral in intents.get("external_peripherals", []):
        citations.append({"field": "external_peripherals", "source": "raw_requirement", "evidence_snippet": _snippet_for(requirement, peripheral)})
    return citations


def _snippet_for(requirement: str, token: str) -> str:
    lower = requirement.lower()
    index = lower.find(token.lower())
    if index < 0:
        return requirement[:120]
    return requirement[max(0, index - 32) : min(len(requirement), index + len(token) + 32)]


def _confidence(intents: dict[str, Any]) -> float:
    score = 0.55
    if intents.get("requested_bus_protocol"):
        score += 0.15
    if intents.get("cpu_width_bits"):
        score += 0.15
    if intents.get("external_peripherals"):
        score += 0.15
    return min(score, 0.98)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
