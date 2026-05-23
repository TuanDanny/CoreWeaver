"""Agent 2 V3 semantic RTL validators."""
from __future__ import annotations

import re
from typing import Any

from semiconductor_swarm.agents.agent2_rtl.semantic.findings import SemanticFinding


REQUIRED_APB_SIGNALS = {"paddr_i", "psel_i", "penable_i", "pwrite_i", "pwdata_i", "prdata_o", "pready_o", "pslverr_o"}
APB_DIRECTIONS = {"paddr_i": "input", "psel_i": "input", "penable_i": "input", "pwrite_i": "input", "pwdata_i": "input", "prdata_o": "output", "pready_o": "output", "pslverr_o": "output"}


def build_semantic_lint_report(spec: dict[str, Any], module_index: dict[str, Any]) -> dict[str, Any]:
    findings: list[SemanticFinding] = []
    findings.extend(_validate_top(spec, module_index))
    findings.extend(_validate_duplicate_modules(module_index))
    findings.extend(_validate_unresolved_instances(module_index))
    findings.extend(_validate_apb_ports(module_index))
    findings.extend(_validate_reset_ports(module_index))
    findings.extend(_validate_widths(module_index))
    finding_dicts = [finding.as_dict() for finding in findings]
    return {
        "schema_version": "agent2.semantic_lint_report.v1",
        "pass": not any(f["severity"] in {"error", "fatal"} for f in finding_dicts),
        "rules": ["top_exists", "duplicate_modules", "unresolved_instances", "apb_pinout", "reset_pinout", "declared_widths"],
        "finding_count": len(finding_dicts),
        "findings": finding_dicts,
        "module_count": module_index.get("module_count", 0),
    }


def build_semantic_review_report(spec: dict[str, Any], module_index: dict[str, Any]) -> dict[str, Any]:
    """Build V3.4 semantic APB/reset/width/X review report."""
    findings: list[SemanticFinding] = []
    findings.extend(_review_apb_protocol(module_index))
    findings.extend(_review_reset_coverage(module_index))
    findings.extend(_review_width_mismatches(module_index))
    findings.extend(_review_x_propagation(module_index))
    finding_dicts = [finding.as_dict() for finding in findings]
    return {
        "schema_version": "agent2.semantic_review_report.v1",
        "milestone": "AGENT_2_V3.4_ME",
        "pass": not any(f["severity"] in {"error", "fatal"} for f in finding_dicts),
        "reviewers": ["apb_protocol", "reset_coverage", "width_mismatch", "x_propagation"],
        "finding_count": len(finding_dicts),
        "findings": finding_dicts,
        "sva_targets": _apb_sva_targets(module_index),
        "coverage_matrix": _semantic_review_coverage_matrix(module_index),
        "reset_waiver_policy": _reset_waiver_policy(module_index),
        "module_count": module_index.get("module_count", 0),
    }


def _modules(module_index: dict[str, Any]) -> list[dict[str, Any]]:
    return list(module_index.get("modules", []))


def _validate_top(spec: dict[str, Any], module_index: dict[str, Any]) -> list[SemanticFinding]:
    project = spec.get("project_name") or spec.get("project") or "unknown"
    top = f"{project}_top"
    names = {module.get("module_name") for module in _modules(module_index)}
    if top in names:
        return []
    return [SemanticFinding("error", "semantic", "A2.V3 Semantic Validator", None, top, "top_exists", f"Missing expected top module {top}.", "Generate top-level module matching Agent 1 project name.", {"known_modules": sorted(names)})]


def _validate_duplicate_modules(module_index: dict[str, Any]) -> list[SemanticFinding]:
    findings: list[SemanticFinding] = []
    for duplicate in module_index.get("duplicate_modules", []):
        findings.append(SemanticFinding("error", "semantic", "A2.V3 Module Index Validator", None, duplicate.get("module"), "duplicate_modules", f"Duplicate module definition: {duplicate.get('module')}", "Keep one SystemVerilog module definition per module name.", duplicate))
    return findings


def _validate_unresolved_instances(module_index: dict[str, Any]) -> list[SemanticFinding]:
    findings: list[SemanticFinding] = []
    for instance in module_index.get("unresolved_instances", []):
        findings.append(SemanticFinding("error", "semantic", "A2.V3 Module Index Validator", instance.get("filename"), instance.get("from"), "unresolved_instances", f"Unresolved module instance: {instance.get('module')} {instance.get('instance')}", "Generate referenced module or remove stale instance.", instance))
    return findings


def _validate_apb_ports(module_index: dict[str, Any]) -> list[SemanticFinding]:
    findings: list[SemanticFinding] = []
    for module in _modules(module_index):
        port_names = {port.get("name") for port in module.get("ports", [])}
        if not (port_names & REQUIRED_APB_SIGNALS):
            continue
        missing = sorted(REQUIRED_APB_SIGNALS - port_names)
        if missing:
            findings.append(SemanticFinding("error", "semantic", "A2.V3 APB Validator", module.get("filename"), module.get("module_name"), "apb_pinout", f"Missing APB ports: {missing}", "Keep APB_SLAVE_INTERFACE names unchanged.", {"missing": missing}))
    return findings


def _review_apb_protocol(module_index: dict[str, Any]) -> list[SemanticFinding]:
    findings = _validate_apb_ports(module_index)
    for module in _modules(module_index):
        ports = {port.get("name"): port for port in module.get("ports", [])}
        if not (set(ports) & REQUIRED_APB_SIGNALS):
            continue
        for name, expected in APB_DIRECTIONS.items():
            if name in ports and ports[name].get("direction") != expected:
                findings.append(SemanticFinding("error", "semantic", "A2.V3 APB Protocol Reviewer", module.get("filename"), module.get("module_name"), "apb_direction", f"APB port {name} direction is {ports[name].get('direction')}, expected {expected}.", "Keep APB_SLAVE_INTERFACE directions unchanged.", {"port": ports[name], "expected_direction": expected}))
        content = str(module.get("content", ""))
        if "pready_o" in ports and not re.search(r"pready_o\s*<=\s*1'b1|assign\s+pready_o\s*=\s*1'b1", content):
            findings.append(SemanticFinding("warning", "semantic", "A2.V3 APB Protocol Reviewer", module.get("filename"), module.get("module_name"), "apb_ready_default", "APB ready default behavior not statically obvious.", "Drive pready_o deterministically in setup/access path.", {"signal": "pready_o"}))
        if "pslverr_o" in ports and "default" not in content:
            findings.append(SemanticFinding("warning", "semantic", "A2.V3 APB Protocol Reviewer", module.get("filename"), module.get("module_name"), "apb_illegal_address_default", "APB illegal-address default response not statically obvious.", "Add default decode branch that raises pslverr_o for illegal address.", {"signal": "pslverr_o"}))
        if not _has_apb_setup_access_intent(content):
            findings.append(SemanticFinding("warning", "semantic", "A2.V3 APB Protocol Reviewer", module.get("filename"), module.get("module_name"), "apb_setup_access_intent", "APB setup/access phase intent not statically obvious.", "Gate register/decode side effects with psel_i && penable_i and expose SVA target apb_setup_to_access.", {"required_condition": "psel_i && penable_i"}))
    return findings


def _apb_sva_targets(module_index: dict[str, Any]) -> list[dict[str, Any]]:
    targets = []
    for module in _modules(module_index):
        ports = {port.get("name") for port in module.get("ports", [])}
        if REQUIRED_APB_SIGNALS <= ports:
            targets.append({"module": module.get("module_name"), "file": module.get("filename"), "properties": ["apb_setup_to_access", "apb_ready_known", "apb_error_known", "apb_illegal_address_errors"]})
    return targets


def _validate_reset_ports(module_index: dict[str, Any]) -> list[SemanticFinding]:
    findings: list[SemanticFinding] = []
    for module in _modules(module_index):
        ports = {port.get("name"): port for port in module.get("ports", [])}
        if "clk_i" in ports and "rst_ni" not in ports:
            findings.append(SemanticFinding("error", "semantic", "A2.V3 Reset Validator", module.get("filename"), module.get("module_name"), "reset_pinout", "Clocked module missing rst_ni reset port.", "Add active-low rst_ni reset port.", {"ports": sorted(ports)}))
    return findings


def _validate_widths(module_index: dict[str, Any]) -> list[SemanticFinding]:
    findings: list[SemanticFinding] = []
    for module in _modules(module_index):
        for port in module.get("ports", []):
            width = str(port.get("width", "1"))
            if width != "1" and not (width.startswith("[") and width.endswith("]")):
                findings.append(SemanticFinding("warning", "semantic", "A2.V3 Width Validator", module.get("filename"), module.get("module_name"), "declared_widths", f"Suspicious width on {port.get('name')}: {width}", "Use SystemVerilog packed width syntax [MSB:LSB].", {"port": port}))
    return findings


def _review_reset_coverage(module_index: dict[str, Any]) -> list[SemanticFinding]:
    findings: list[SemanticFinding] = []
    state_like = re.compile(r"\blogic\s+(?:\[[^\]]+\]\s*)?(?P<name>[A-Za-z_][A-Za-z0-9_]*(?:_q|_state|state_q|ctrl_q|control_q|count_q|counter_q|status_q))\b")
    for module in _modules(module_index):
        content = str(module.get("content", ""))
        ports = {port.get("name") for port in module.get("ports", [])}
        if "rst_ni" in ports and re.search(r"posedge\s+rst_ni|if\s*\(\s*rst_ni\s*\)", content):
            findings.append(SemanticFinding("warning", "semantic", "A2.V3 Reset Reviewer", module.get("filename"), module.get("module_name"), "reset_polarity_consistency", "rst_ni active-low polarity usage not consistent.", "Use negedge rst_ni and if (!rst_ni) reset branches consistently.", {"reset": "rst_ni", "expected_polarity": "active_low"}))
        for match in state_like.finditer(content):
            name = match.group("name")
            if re.search(rf"if\s*\(!\s*rst_ni\s*\).*?\b{name}\s*<=", content, re.S):
                continue
            findings.append(SemanticFinding("warning", "semantic", "A2.V3 Reset Reviewer", module.get("filename"), module.get("module_name"), "reset_coverage", f"State/control register {name} reset assignment not statically obvious.", "Assign state/control registers in rst_ni branch or add waiver.", {"register": name}))
    return findings


def _review_width_mismatches(module_index: dict[str, Any]) -> list[SemanticFinding]:
    findings = _validate_widths(module_index)
    for module in _modules(module_index):
        content = str(module.get("content", ""))
        widths = {port.get("name"): port.get("width") for port in module.get("ports", []) if port.get("width") != "1"}
        widths.update(_declared_signal_widths(content))
        for param in module.get("parameters", []):
            default = str(param.get("default", ""))
            if re.search(r"[A-Za-z_][A-Za-z0-9_]*", default) and not re.search(r"\$clog2|\+|-|\*|/|:", default):
                findings.append(SemanticFinding("warning", "semantic", "A2.V3 Width Reviewer", module.get("filename"), module.get("module_name"), "param_width_propagation", f"Parameter {param.get('name')} default depends on symbolic width without expression guard.", "Use explicit parameter expression/cast or document propagated width intent.", {"parameter": param}))
        for enum_match in re.finditer(r"typedef\s+enum\s+(?:logic\s+)?(?P<width>\[[^\]]+\])?", content):
            if not enum_match.group("width"):
                findings.append(SemanticFinding("warning", "semantic", "A2.V3 Width Reviewer", module.get("filename"), module.get("module_name"), "enum_packed_width_risk", "Enum typedef missing explicit packed width.", "Declare enum logic [N:0] to freeze state encoding width.", {}))
        for struct_match in re.finditer(r"typedef\s+struct\s+packed\s*\{(?P<body>.*?)\}", content, re.S):
            if re.search(r"\blogic\s+[A-Za-z_][A-Za-z0-9_]*\s*;", struct_match.group("body")):
                findings.append(SemanticFinding("warning", "semantic", "A2.V3 Width Reviewer", module.get("filename"), module.get("module_name"), "packed_struct_width_risk", "Packed struct contains implicit 1-bit field width.", "Make packed struct field widths explicit where bus packing matters.", {}))
        for lhs, rhs in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:<=|=)\s*([A-Za-z_][A-Za-z0-9_]*)\s*;", content):
            if lhs in widths and rhs in widths and widths[lhs] != widths[rhs]:
                findings.append(SemanticFinding("warning", "semantic", "A2.V3 Width Reviewer", module.get("filename"), module.get("module_name"), "width_mismatch", f"Assignment {lhs} <= {rhs} crosses widths {widths[lhs]} vs {widths[rhs]}.", "Add explicit cast/slice/extension for intentional width crossing.", {"lhs": lhs, "rhs": rhs, "lhs_width": widths[lhs], "rhs_width": widths[rhs]}))
    return findings


def _review_x_propagation(module_index: dict[str, Any]) -> list[SemanticFinding]:
    findings: list[SemanticFinding] = []
    for module in _modules(module_index):
        content = str(module.get("content", ""))
        if re.search(r"'x|1'bx|\bx\b", content, re.I):
            findings.append(SemanticFinding("error", "semantic", "A2.V3 X-Propagation Reviewer", module.get("filename"), module.get("module_name"), "unsafe_x_assignment", "Unsafe X assignment detected.", "Use deterministic 0/1/default value in synthesizable RTL.", {}))
        for block in re.findall(r"always_comb\s*begin(?P<body>.*?)end", content, re.S):
            has_case = re.search(r"\bcase\b", block) is not None
            has_default_assignment = re.search(r"^[ \t]*[A-Za-z_][A-Za-z0-9_]*\s*=", block, re.M) is not None
            has_default_case = re.search(r"\bdefault\s*:", block) is not None
            if (has_case and not has_default_case) or not has_default_assignment:
                findings.append(SemanticFinding("warning", "semantic", "A2.V3 X-Propagation Reviewer", module.get("filename"), module.get("module_name"), "always_comb_default", "always_comb default assignment/default case risk detected.", "Add default assignments before conditionals and default case branches.", {"has_case": has_case, "has_default_case": has_default_case, "has_default_assignment": has_default_assignment}))
    return findings


def _has_apb_setup_access_intent(content: str) -> bool:
    return re.search(r"psel_i\s*&&\s*penable_i|penable_i\s*&&\s*psel_i", content) is not None


def _declared_signal_widths(content: str) -> dict[str, str]:
    widths: dict[str, str] = {}
    for match in re.finditer(r"\blogic\s+(?P<width>\[[^\]]+\])\s*(?P<names>[A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*)\s*;", content):
        for name in match.group("names").replace(" ", "").split(","):
            widths[name] = match.group("width")
    return widths


def _reset_waiver_policy(module_index: dict[str, Any]) -> dict[str, Any]:
    waivers = []
    for finding in _review_reset_coverage(module_index):
        if finding.rule == "reset_coverage":
            waivers.append({"module": finding.module, "file": finding.file, "register": finding.evidence.get("register"), "status": "required_if_not_reset", "required_fields": ["module", "register", "reason", "owner", "expiry_or_signoff"]})
    return {"schema_version": "agent2.reset_waiver_policy.v1", "policy": "unreset state/control registers require explicit waiver with owner and signoff", "waiver_count": len(waivers), "waivers_required": waivers}


def _semantic_review_coverage_matrix(module_index: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "agent2.semantic_review_coverage_matrix.v1",
        "apb_protocol": ["pinout", "direction", "ready_default", "illegal_address_default", "setup_access_intent", "sva_targets"],
        "reset_coverage": ["reset_pinout", "state_control_register_reset", "polarity_consistency", "unreset_register_waiver_policy"],
        "width_mismatch": ["declared_widths", "assignment_width_crossing", "param_width_propagation", "enum_packed_width_risk", "packed_struct_width_risk"],
        "x_propagation": ["unsafe_x_assignment", "always_comb_default_assignment", "default_case_policy"],
        "module_count": module_index.get("module_count", 0),
    }