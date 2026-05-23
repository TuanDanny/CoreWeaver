"""Agent 1 V4 replay/debug CLI helpers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from semiconductor_swarm.agents.agent1_planning.audit_v4 import stable_hash, validate_audit_cross_checks
from semiconductor_swarm.agents.agent1_planning.spec_schema import validate_agent1_v4_spec_schema
from semiconductor_swarm.tools.bandwidth_calculator import calculate_bandwidth
from semiconductor_swarm.tools.ppa_calculator import calculate_ppa

V64_REQUIRED_AGENT1_ARTIFACTS = (
    "agent1_intake_router_report.json",
    "agent1_requirement_citation_ledger.json",
    "agent1_policy_matrix.json",
    "agent1_prompt_pack_manifest.json",
)

V64_OPTIONAL_DESIGN_ARTIFACTS = (
    "agent1_leaf_expert_trace.jsonl",
    "agent1_middle_manager_trace.jsonl",
    "agent1_principal_trace.jsonl",
    "agent1_conflict_matrix.json",
    "agent1_v51_guardrail_report.json",
)


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_replay_bundle(bundle_path: str | Path, trace_path: str | Path, ledger_path: str | Path, spec_path: str | Path | None = None) -> dict[str, Any]:
    bundle = load_json(bundle_path)
    trace_records = load_jsonl(trace_path)
    ledger_records = load_jsonl(ledger_path)
    artifacts = {
        "agent1_v4_replay_bundle.json": json.dumps(bundle, sort_keys=True),
        "agent1_v4_trace.jsonl": "".join(json.dumps(record, sort_keys=True) + "\n" for record in trace_records),
        "agent1_v4_tool_ledger.jsonl": "".join(json.dumps(record, sort_keys=True) + "\n" for record in ledger_records),
    }
    cross_check = validate_audit_cross_checks(artifacts)
    failures = list(cross_check.get("failures", []))
    if bundle.get("tool_ledger_hash") != stable_hash(ledger_records):
        failures.append("replay_tool_ledger_hash_mismatch")
    if any(record.get("trace_id") != bundle.get("trace_id") for record in trace_records):
        failures.append("replay_trace_id_mismatch")
    failures.extend(_verify_tool_ledger_recomputes(ledger_records))
    if spec_path is not None:
        spec = load_json(spec_path)
        try:
            validate_agent1_v4_spec_schema(spec)
        except ValueError as exc:
            failures.append(f"spec_schema_invalid:{exc}")
        if bundle.get("spec_hashes", {}).get("final") != stable_hash(spec):
            failures.append("replay_spec_hash_mismatch")
    return {
        "pass": not failures,
        "failures": failures,
        "trace_spans": len(trace_records),
        "tool_entries": len(ledger_records),
        "trace_id": bundle.get("trace_id"),
        "run_id": bundle.get("run_id"),
    }

def verify_agent1_v64_replay_output(output_dir: str | Path) -> dict[str, Any]:
    """Verify Agent1 V6.4 artifact hashes/versions without making Codex calls."""
    root = Path(output_dir)
    reports = root / "reports"
    agent1 = reports / "agent1"
    failures: list[str] = []
    artifact_hashes: dict[str, str] = {}
    for name in V64_REQUIRED_AGENT1_ARTIFACTS:
        path = agent1 / name
        if not path.is_file():
            failures.append(f"missing_required_artifact:{name}")
            continue
        artifact_hashes[name] = stable_hash(path.read_text(encoding="utf-8"))
    for name in V64_OPTIONAL_DESIGN_ARTIFACTS:
        path = agent1 / name
        if path.is_file():
            artifact_hashes[name] = stable_hash(path.read_text(encoding="utf-8"))

    versions = _load_v64_versions(agent1, failures)
    if (reports / "architecture_plan.md").is_file() and not all((agent1 / name).is_file() for name in V64_OPTIONAL_DESIGN_ARTIFACTS[:3]):
        failures.append("architecture_plan_without_required_council_traces")
    signoff_claimed = False
    if not failures and (reports / "architecture_plan.md").is_file():
        signoff_claimed = True
    return {
        "pass": not failures,
        "failures": failures,
        "artifact_hashes": artifact_hashes,
        "schema_versions": versions,
        "codex_calls": 0,
        "signoff_claimed": signoff_claimed,
    }

def _load_v64_versions(agent1_dir: Path, failures: list[str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    expected = {
        "agent1_intake_router_report.json": "agent1.intake_router_report.v1",
        "agent1_requirement_citation_ledger.json": "agent1.requirement_citation_ledger.v1",
        "agent1_policy_matrix.json": "agent1.policy_matrix.v1",
        "agent1_prompt_pack_manifest.json": "agent1.prompt_pack_manifest.v1",
    }
    for name, expected_version in expected.items():
        path = agent1_dir / name
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            failures.append(f"invalid_json:{name}")
            continue
        version = str(payload.get("schema_version", ""))
        versions[name] = version
        if version != expected_version:
            failures.append(f"schema_version_mismatch:{name}:{version}")
    return versions


def _verify_tool_ledger_recomputes(ledger_records: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    tools = {
        "calculate_ppa": calculate_ppa,
        "calculate_bandwidth": calculate_bandwidth,
    }
    for index, record in enumerate(ledger_records):
        tool_name = record.get("tool")
        if tool_name not in tools:
            continue
        args = record.get("args")
        if not isinstance(args, dict):
            failures.append(f"tool_ledger_{index}_args_invalid")
            continue
        normalized_args = _normalize_tool_args(tool_name, args)
        try:
            recomputed = tools[tool_name](**normalized_args)
        except Exception as exc:  # pragma: no cover - error text varies
            failures.append(f"tool_ledger_{index}_{tool_name}_recompute_error:{exc}")
            continue
        if record.get("output") != recomputed:
            failures.append(f"tool_ledger_{index}_{tool_name}_output_mismatch")
        if record.get("input_hash") != stable_hash(args):
            failures.append(f"tool_ledger_{index}_{tool_name}_input_hash_mismatch")
        if record.get("output_hash") != stable_hash(record.get("output")):
            failures.append(f"tool_ledger_{index}_{tool_name}_output_hash_mismatch")
    return failures


def _normalize_tool_args(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Map stable Agent1 contract names onto current Python tool signatures."""
    normalized = dict(args)
    if tool_name in {"calculate_ppa", "calculate_bandwidth"} and "frequency_mhz" in normalized and "freq_mhz" not in normalized:
        normalized["freq_mhz"] = normalized.pop("frequency_mhz")
    return normalized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Agent 1 V4 replay/debug bundle")
    parser.add_argument("--v64-output", help="Path to Studio output dir for Agent 1 V6.4 artifact replay verification")
    parser.add_argument("--bundle", help="Path to agent1_v4_replay_bundle.json")
    parser.add_argument("--trace", help="Path to agent1_v4_trace.jsonl")
    parser.add_argument("--ledger", help="Path to agent1_v4_tool_ledger.jsonl")
    parser.add_argument("--spec", help="Optional spec.json for V4 schema and hash check")
    args = parser.parse_args(argv)
    if args.v64_output:
        result = verify_agent1_v64_replay_output(args.v64_output)
    else:
        if not (args.bundle and args.trace and args.ledger):
            parser.error("--bundle, --trace, and --ledger are required unless --v64-output is used")
        result = verify_replay_bundle(args.bundle, args.trace, args.ledger, args.spec)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["pass"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
