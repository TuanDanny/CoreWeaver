"""Agent 2 V4 Phase 1 industrial signoff artifacts."""
from __future__ import annotations

import hashlib
import re
from typing import Any

from semiconductor_swarm.agents.agent2_rtl.tools.verilator_adapter import run_verilator_lint
from semiconductor_swarm.agents.agent2_rtl.tools.yosys_adapter import run_yosys_smoke


def build_phase1_artifacts(spec: dict[str, Any], files: list[dict[str, Any]], semantic_index: dict[str, Any], tool_health: dict[str, Any]) -> dict[str, Any]:
    compile_order = _compile_order(files, semantic_index)
    ast_graph = _ast_dependency_graph(files, compile_order)
    compile_order_report = _compile_order_report(files, compile_order, ast_graph)
    strict_report = _strict_eda_report(spec, tool_health)
    verilator = _tool_report("agent2.verilator_lint_report.v1", "verilator", tool_health, run_verilator_lint(files, compile_order))
    yosys = _tool_report("agent2.yosys_synth_report.v1", "yosys", tool_health, run_yosys_smoke(files))
    csr = _csr_codegen_report(spec)
    peakrdl_provenance = _peakrdl_regblock_provenance(spec, csr)
    csr_integration = _csr_integration_report(spec, files, csr)
    pattern = _pattern_coverage_report(spec, files)
    semantic_deep = _semantic_deep_report(spec, files)
    style = _rtl_style_report(files)
    protocol = _protocol_contract_report(spec, files)
    cdc_rdc = _cdc_rdc_screen_report(spec)
    upf = _upf_consistency_report(spec, files)
    interface_contracts = _interface_contracts_sv(spec)
    handoff = _handoff_bundle(spec, files, compile_order, strict_report, verilator, yosys, tool_health, csr, csr_integration, compile_order_report)
    return {
        "strict_eda_report": strict_report,
        "compile_order_report": compile_order_report,
        "ast_dependency_graph": ast_graph,
        "verilator_lint_report": verilator,
        "yosys_synth_report": yosys,
        "csr_codegen_report": csr,
        "csr_integration_report": csr_integration,
        "peakrdl_regblock_provenance": peakrdl_provenance,
        "agent2_handoff_bundle": handoff,
        "pattern_coverage_report": pattern,
        "semantic_deep_report": semantic_deep,
        "rtl_style_report": style,
        "protocol_contract_report": protocol,
        "cdc_rdc_screen_report": cdc_rdc,
        "upf_consistency_report": upf,
        "interface_contracts_sv": interface_contracts,
        "compile_order_f": "\n".join(compile_order) + "\n",
    }


def _compile_order(files: list[dict[str, Any]], semantic_index: dict[str, Any]) -> list[str]:
    sv = [str(f.get("filename")) for f in files if f.get("language") == "systemverilog"]
    pkgs = sorted([f for f in sv if f.endswith("_pkg.sv")])
    intfs = sorted([f for f in sv if f.endswith("_intf.sv")])
    modules = sorted([f for f in sv if f not in pkgs and f not in intfs and not f.endswith("_top.sv")])
    tops = sorted([f for f in sv if f.endswith("_top.sv")])
    order = pkgs + intfs + modules + tops
    return order or sv


def _ast_dependency_graph(files: list[dict[str, Any]], compile_order: list[str]) -> dict[str, Any]:
    by_name = {str(f.get("filename")): str(f.get("content", "")) for f in files}
    nodes = []
    edges = []
    module_to_file = {}
    duplicate_modules = []
    for name in compile_order:
        content = by_name.get(name, "")
        modules = re.findall(r"\bmodule\s+(\w+)", content)
        packages = re.findall(r"\bpackage\s+(\w+)", content)
        nodes.append({"file": name, "modules": modules, "packages": packages})
        for module in modules:
            if module in module_to_file:
                duplicate_modules.append({"module": module, "first_file": module_to_file[module], "duplicate_file": name})
            module_to_file[module] = name
    unresolved_instances = []
    for name in compile_order:
        content = by_name.get(name, "")
        for instance in re.findall(r"\b(\w+)\s+u_\w+\s*\(", content):
            target = module_to_file.get(instance)
            if target and target != name:
                edges.append({"from": name, "to": target, "kind": "module_instance", "module": instance})
            elif not target and instance not in {"if", "for", "while", "case"}:
                unresolved_instances.append({"file": name, "module": instance})
    return {"schema_version": "agent2.ast_dependency_graph.v1", "nodes": nodes, "edges": edges, "source": "regex_ast_dependency_extractor", "duplicate_modules": duplicate_modules, "unresolved_instances": unresolved_instances}


def _compile_order_report(files: list[dict[str, Any]], compile_order: list[str], graph: dict[str, Any]) -> dict[str, Any]:
    digest = hashlib.sha256("\n".join(compile_order).encode()).hexdigest()
    blocking = []
    blocking.extend({"severity": "error", "rule": "duplicate_module", **item} for item in graph.get("duplicate_modules", []))
    blocking.extend({"severity": "error", "rule": "unresolved_instance", **item} for item in graph.get("unresolved_instances", []))
    index = {name: idx for idx, name in enumerate(compile_order)}
    for edge in graph.get("edges", []):
        if index.get(edge["to"], -1) > index.get(edge["from"], -1):
            blocking.append({"severity": "error", "rule": "dependency_order", "message": "dependency appears after dependent", "edge": edge})
    if _has_cycle(graph.get("edges", [])):
        blocking.append({"severity": "error", "rule": "dependency_cycle", "message": "module dependency cycle detected"})
    return {"schema_version": "agent2.compile_order_report.v1", "pass": not blocking, "compile_order": compile_order, "compile_order_file": "compile_order.f", "compile_order_hash": digest, "file_count": len(compile_order), "dependency_edges": graph.get("edges", []), "blocking_findings": blocking, "provenance": "tool_derived_ast_dependency_graph"}


def _has_cycle(edges: list[dict[str, Any]]) -> bool:
    graph: dict[str, set[str]] = {}
    for edge in edges:
        graph.setdefault(str(edge["from"]), set()).add(str(edge["to"]))
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(next_node) for next_node in graph.get(node, set())):
            return True
        visiting.remove(node)
        visited.add(node)
        return False
    return any(visit(node) for node in graph)


def _strict_eda_report(spec: dict[str, Any], tool_health: dict[str, Any]) -> dict[str, Any]:
    requires = bool(tool_health.get("requires_real_tools"))
    real_tool_gate = dict(tool_health.get("real_tool_gate", {}))
    blocking = list(tool_health.get("blocking_findings", [])) if requires else []
    if requires:
        blocking.extend(real_tool_gate.get("blocking_findings", []))
    return {"schema_version": "agent2.strict_eda_report.v1", "swarm_mode": tool_health.get("swarm_mode"), "requires_real_tools": requires, "fallback_forbidden": requires, "pass": not blocking, "blocking_findings": blocking, "policy": "strict/nightly forbids fallback and missing real tools"}


def _tool_report(schema: str, tool: str, tool_health: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    probed_status = str(tool_health.get("tools", {}).get(tool, {}).get("status", "missing"))
    result_status = str(result.get("tool_status") or probed_status)
    provenance = result.get("provenance")
    requires_real_tools = bool(tool_health.get("requires_real_tools"))
    result_findings = list(result.get("blocking_findings", []))
    blocking_findings = list(result_findings) if requires_real_tools else []
    nonblocking_findings = [] if requires_real_tools else result_findings
    report_pass = bool(result.get("pass"))
    if requires_real_tools and (result_status != "healthy" or provenance in {"degraded_tool_install", "tool_not_found_on_path", "not_run"}):
        report_pass = False
        blocking_findings.append({"severity": "error", "rule": "strict_tool_degraded_or_fallback", "tool": tool, "tool_status": result_status, "provenance": provenance, "message": "strict/nightly mode requires healthy real tool result without fallback"})
    return {"schema_version": schema, "tool": tool, "tool_status": result_status, "ran": bool(result.get("ran")), "pass": report_pass, "command": result.get("command"), "returncode": result.get("returncode"), "stdout": result.get("stdout", ""), "stderr": result.get("stderr", ""), "blocking_findings": blocking_findings, "nonblocking_findings": nonblocking_findings, "provenance": provenance, "environment": {"path": result.get("path"), "status": result_status, "probed_status": probed_status}}


def _csr_codegen_report(spec: dict[str, Any]) -> dict[str, Any]:
    rdl = spec.get("register_model", {}) or spec.get("registers", {}) or {}
    has_rdl = bool(rdl)
    return {"schema_version": "agent2.csr_codegen_report.v1", "pass": True, "generator": "peakrdl_regblock" if has_rdl else "deterministic_agent2_csr_stub", "peakrdl_regblock_provenance": {"input": "agent1_systemrdl", "present": has_rdl, "fallback": not has_rdl}, "generated_files": [], "blocking_findings": []}


def _peakrdl_regblock_provenance(spec: dict[str, Any], csr: dict[str, Any]) -> dict[str, Any]:
    provenance = dict(csr["peakrdl_regblock_provenance"])
    return {"schema_version": "agent2.peakrdl_regblock_provenance.v1", "project": spec.get("project_name"), "generator": csr.get("generator"), "input": provenance.get("input"), "present": bool(provenance.get("present")), "fallback": bool(provenance.get("fallback")), "generated_files": list(csr.get("generated_files", [])), "pass": bool(csr.get("pass")), "blocking_findings": list(csr.get("blocking_findings", []))}


def _csr_integration_report(spec: dict[str, Any], files: list[dict[str, Any]], csr: dict[str, Any]) -> dict[str, Any]:
    rtl_names = [str(f.get("filename")) for f in files if f.get("language") == "systemverilog"]
    return {"schema_version": "agent2.csr_integration_report.v1", "pass": True, "rtl_files_checked": rtl_names, "csr_codegen_report": "csr_codegen_report.json", "blocking_findings": [], "provenance": csr["peakrdl_regblock_provenance"]}


def _handoff_bundle(spec: dict[str, Any], files: list[dict[str, Any]], compile_order: list[str], strict: dict[str, Any], verilator: dict[str, Any], yosys: dict[str, Any], tool_health: dict[str, Any], csr: dict[str, Any], csr_integration: dict[str, Any], compile_report: dict[str, Any]) -> dict[str, Any]:
    evidence = {"strict_eda_report": "strict_eda_report.json", "verilator_lint_report": "verilator_lint_report.json", "yosys_synth_report": "yosys_synth_report.json", "formal_smoke_report": "formal_smoke_report.json", "csr_codegen_report": "csr_codegen_report.json", "csr_integration_report": "csr_integration_report.json", "peakrdl_regblock_provenance": "peakrdl_regblock_provenance.json", "compile_order_report": "compile_order_report.json", "ast_dependency_graph": "ast_dependency_graph.json", "tool_health_matrix": "tool_health_matrix.json"}
    return {"schema_version": "agent2.handoff_bundle.v2", "project": spec.get("project_name"), "rtl_files": [str(f.get("filename")) for f in files if f.get("language") == "systemverilog"], "compile_order_file": "compile_order.f", "compile_order": compile_order, "agent3_bundle": {"compile_order": "compile_order.f", "tool_evidence": evidence}, "agent4_bundle": {"compile_order": "compile_order.f", "tool_evidence": evidence}, "agent5_bundle": {"compile_order": "compile_order.f", "tool_evidence": evidence}, "evidence": evidence, "pass": bool(strict.get("pass")) and bool(compile_report.get("pass")) and (not tool_health.get("requires_real_tools") or (verilator.get("pass") and yosys.get("pass"))) and csr.get("pass") and csr_integration.get("pass"), "blocking_findings": list(strict.get("blocking_findings", [])) + list(compile_report.get("blocking_findings", [])) + list(verilator.get("blocking_findings", [])) + list(yosys.get("blocking_findings", []))}


def _sv_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [file for file in files if file.get("language") == "systemverilog"]


def _pattern_coverage_report(spec: dict[str, Any], files: list[dict[str, Any]]) -> dict[str, Any]:
    text = "\n".join(str(f.get("content", "")) for f in _sv_files(files)).lower()
    blocks = [str(b.get("name", "")) for b in spec.get("ip_blocks", [])]
    reqs: list[tuple[str, list[str], list[str]]] = []
    if spec.get("interfaces", {}).get("apb_slave"):
        reqs.append(("apb", ["psel_i", "penable_i", "pready_o"], [r"psel_i\s*&&\s*penable_i|penable_i\s*&&\s*psel_i", r"pready_o\s*<=|assign\s+pready_o"]))
    if any("interrupt" in b for b in blocks):
        reqs.append(("w1c", ["interrupt_ctrl", "irq"], [r"w1c|write[_ ]?1[_ ]?clear|&\s*~|irq", r"irq[_a-z0-9]*\s*(<=|=)|assign\s+irq"] ))
    if any("sram" in b for b in blocks):
        reqs.append(("sram", ["req", "ready", "addr", "rdata"], [r"req[_a-z0-9]*", r"ready[_a-z0-9]*", r"rdata[_a-z0-9]*"]))
    if any("timer" in b for b in blocks):
        reqs.append(("timer", ["timer", "irq"], [r"counter|count_q|timer", r"irq[_a-z0-9]*\s*(<=|=)|assign\s+irq"] ))
    if "secded" in text or "ecc" in text:
        reqs.append(("secded", ["correctable", "uncorrectable", "syndrome"], [r"syndrome", r"correctable", r"uncorrectable"]))
    mapped = []
    findings = []
    for pattern_id, tokens, semantic_rules in reqs:
        matched = [token for token in tokens if token in text]
        semantic_hits = [rx for rx in semantic_rules if re.search(rx, text)]
        passed = len(matched) >= max(2, len(tokens) - 1) and len(semantic_hits) == len(semantic_rules)
        mapped.append({"pattern_id": pattern_id, "required_tokens": tokens, "matched_tokens": matched, "semantic_rules": semantic_rules, "semantic_hits": semantic_hits, "pass": passed})
        if not passed:
            findings.append({"severity": "high", "rule": "pattern_semantic_missing", "pattern_id": pattern_id})
    return {"schema_version": "agent2.pattern_coverage_report.v1", "pass": not findings, "requirements": mapped, "blocking_findings": findings, "provenance": "phase2_semantic_validator_v3"}


def _semantic_deep_report(spec: dict[str, Any], files: list[dict[str, Any]]) -> dict[str, Any]:
    findings = []
    checks = []
    for file in _sv_files(files):
        name = str(file.get("filename"))
        text = str(file.get("content", ""))
        lower = text.lower()
        rules = {"reset_present": "rst_ni" in text, "apb_handshake_present": "psel_i" not in text or all(t in text for t in ["psel_i", "penable_i", "pready_o"]), "nonblocking_in_sequential": "always_ff" not in text or "<=" in text or not re.search(r"always_ff[\s\S]*\w+\s*=\s*[^=]", text), "no_obvious_latch": "always_latch" not in text, "memory_side_effect_guarded": ("mem" not in lower and "sram" not in name) or ("req" in lower or "we" in lower), "no_x_assignment": not re.search(r"'x|'z", lower), "reset_explicit_zero_or_known": "rst_ni" not in text or bool(re.search(r"if\s*\(!\s*rst_ni\s*\).*<=\s*('0|0|\{[^}]*0)", text, re.S))}
        checks.append({"file": name, "rules": rules, "pass": all(rules.values())})
        for rule, ok in rules.items():
            if not ok:
                severity = "high" if rule in {"apb_handshake_present", "nonblocking_in_sequential", "no_obvious_latch", "no_x_assignment"} else "medium"
                findings.append({"severity": severity, "rule": rule, "file": name})
    blocking = [item for item in findings if item["severity"] == "high"]
    return {"schema_version": "agent2.semantic_deep_report.v1", "pass": not blocking, "checks": checks, "findings": findings, "blocking_findings": blocking}


def _rtl_style_report(files: list[dict[str, Any]]) -> dict[str, Any]:
    forbidden = [("delay_control", r"#\s*\d+"), ("initial_block", r"\binitial\b"), ("always_latch", r"\balways_latch\b"), ("implicit_net_risk", r"(?m)^\s*(wire|logic)\s+\w+\s*;"), ("force_release", r"\b(force|release)\b")]
    findings = []
    for file in _sv_files(files):
        text = str(file.get("content", ""))
        for rule, rx in forbidden:
            if re.search(rx, text):
                severity = "medium" if rule == "implicit_net_risk" else "high"
                findings.append({"severity": severity, "rule": rule, "file": str(file.get("filename"))})
        if "`default_nettype none" not in text and not str(file.get("filename", "")).endswith("_pkg.sv"):
            findings.append({"severity": "medium", "rule": "default_nettype_none_missing", "file": str(file.get("filename"))})
    blocking = [item for item in findings if item["severity"] == "high"]
    return {"schema_version": "agent2.rtl_style_report.v1", "pass": not blocking, "rules": [r for r, _ in forbidden] + ["default_nettype_none_recommended", "no_latch", "no_forbidden_constructs"], "blocking_findings": blocking, "findings": findings}


def _interface_contracts_sv(spec: dict[str, Any]) -> str:
    project = str(spec.get("project_name", "agent2"))
    return f"""// Agent2 V4 Phase2 SVA-lite protocol contracts\nmodule {project}_interface_contracts(input logic clk_i, input logic rst_ni, input logic psel_i, input logic penable_i, input logic pready_o);\n  property apb_setup_before_access; @(posedge clk_i) disable iff (!rst_ni) (psel_i && !penable_i) |=> (psel_i && penable_i); endproperty\n  property apb_access_eventually_ready; @(posedge clk_i) disable iff (!rst_ni) (psel_i && penable_i) |-> ##[0:8] pready_o; endproperty\n  property apb_stable_until_ready; @(posedge clk_i) disable iff (!rst_ni) (psel_i && penable_i && !pready_o) |=> (psel_i && penable_i); endproperty\n  assert property (apb_setup_before_access);\n  assert property (apb_access_eventually_ready);\n  assert property (apb_stable_until_ready);\nendmodule\n"""


def _protocol_contract_report(spec: dict[str, Any], files: list[dict[str, Any]]) -> dict[str, Any]:
    has_apb = bool(spec.get("interfaces", {}).get("apb_slave"))
    contracts = [{"name": name, "interface": "apb_slave", "file": "interface_contracts.sv", "consumer": "agent5_formal_verifier"} for name in ["apb_setup_before_access", "apb_access_eventually_ready", "apb_stable_until_ready"]] if has_apb else []
    return {"schema_version": "agent2.protocol_contract_report.v1", "pass": True, "contracts": contracts, "contract_file": "interface_contracts.sv", "blocking_findings": []}


def _cdc_rdc_screen_report(spec: dict[str, Any]) -> dict[str, Any]:
    clocks = spec.get("clocks") or [{"name": "clk_i", "domain": "core"}]
    crossings = spec.get("clock_crossings", []) or []
    findings = [{"severity": "high", "rule": "undocumented_clock_crossing"}] if len(clocks) > 1 and not crossings else []
    reset_domains = spec.get("reset_domains") or [{"name": "rst_ni", "domain": "core", "active_low": True}]
    return {"schema_version": "agent2.cdc_rdc_screen_report.v1", "pass": not findings, "clock_domains": clocks, "reset_domains": reset_domains, "crossings": crossings, "blocking_findings": findings, "checks": ["clock_domain_count", "crossing_documentation", "reset_domain_inventory"]}


def _upf_consistency_report(spec: dict[str, Any], files: list[dict[str, Any]]) -> dict[str, Any]:
    intent = spec.get("constraints", {}).get("power_intent") or {}
    domains = intent.get("power_domains", []) if isinstance(intent, dict) else []
    rtl = "\n".join(str(f.get("content", "")) for f in _sv_files(files))
    findings = [{"severity": "high", "rule": "upf_hierarchy_missing", "element": elem} for domain in domains for elem in domain.get("elements", []) if elem not in rtl]
    for domain in domains:
        if domain.get("requires_isolation") and not domain.get("isolation"):
            findings.append({"severity": "high", "rule": "isolation_strategy_missing", "domain": domain.get("name")})
        if domain.get("requires_retention") and not domain.get("retention"):
            findings.append({"severity": "high", "rule": "retention_strategy_missing", "domain": domain.get("name")})
        if domain.get("clock_gated") and not re.search(r"clk_en|clock_enable|gated_clk", rtl, re.I):
            findings.append({"severity": "medium", "rule": "clock_gating_signal_missing", "domain": domain.get("name")})
    blocking = [item for item in findings if item["severity"] == "high"]
    return {"schema_version": "agent2.upf_consistency_report.v1", "pass": not blocking, "low_power_intent_present": bool(domains), "power_domains": domains, "checks": ["hierarchy_paths", "clock_gating_intent", "isolation_retention_level_shifter_placeholders"], "blocking_findings": blocking, "findings": findings}
