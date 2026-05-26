"""Random verification + tracking UAT for Agent1 V7.2 signoff.

This script builds synthetic Agent1 outputs, applies deterministic random
mutations, runs the real V7.2 signoff/handoff path, and records latency plus
debug-issue coverage. It is intentionally local: no Codex/LLM calls.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from semiconductor_swarm.agents.agent1_planning.architect import (
    generate_architecture_plan_markdown,
    generate_architecture_spec,
)
from semiconductor_swarm.agents.agent1_planning.signoff_benchmark import ensure_default_benchmark_report
from semiconductor_swarm.agents.agent1_planning.signoff_engine import (
    enforce_agent1_to_agent2_handoff,
    run_agent1_signoff_pipeline,
)
from semiconductor_swarm.agents.agent1_planning.signoff_models import (
    SIGNOFF_CERTIFICATE_SCHEMA_VERSION,
    SIGNOFF_GATES,
)
from semiconductor_swarm.agents.agent1_planning.spec_schema import (
    attach_agent1_contract_manifest,
    attach_tool_provenance,
)
from semiconductor_swarm.tracing import secret_leaks, sha256_text

HASH = "a" * 64
NOW = "2026-05-25T00:00:00+00:00"

def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            items.append(item)
    return items


def _full_spec(project: str) -> dict[str, Any]:
    spec = generate_architecture_spec(
        "Generate APB UART peripheral with formal-first register checks",
        project,
    )
    spec.update(
        {
            "power_intent": {"domains": ["core"], "low_power": False},
            "cdc_rdc_plan": {"clock_crossings": [], "reset_crossings": []},
            "interconnect_qos": {"starvation_policy": "round_robin"},
            "memory_hierarchy": {"levels": ["APB register file"]},
            "dft_plan": {"test_modes": ["scan_enable", "test_reset"]},
            "safety_security": {"threat_model": ["APB software access"], "protected_registers": []},
            "ip_reuse_cost": {"reuse_candidates": ["uart"], "buy_vs_build": ["build"]},
            "io_packaging": {"pins": ["pclk", "presetn", "uart_tx", "uart_rx"]},
        }
    )
    spec = attach_tool_provenance(spec)
    return attach_agent1_contract_manifest(spec)


def _build_clean_run(root: Path, *, profile: str, approval: bool = True) -> None:
    reports = root / "reports"
    agent1 = reports / "agent1"
    traces = reports / "traces"
    agent1.mkdir(parents=True)
    traces.mkdir(parents=True)
    project = "uart_signoff"
    run_manifest = {
        "schema_version": "studio.run_manifest.v1",
        "run_id": "run-001",
        "thread_id": "thread-001",
        "project_name": project,
        "output_dir": str(root),
        "planning_mode": "normal",
        "user_approval_ref": "approval-ok-001" if approval else "",
    }
    _write_json(root / "studio_run_manifest.json", run_manifest)

    spec = _full_spec(project)
    plan = generate_architecture_plan_markdown(spec)
    (reports / "architecture_plan.md").write_text(plan, encoding="utf-8")
    _write_json(agent1 / "agent1_final_architecture_spec.json", spec)
    _write_json(agent1 / "agent1_contract_manifest.json", spec["agent1_contract_manifest"])
    _write_json(agent1 / "agent1_memory_interface_plan.json", {"memory_map": spec["memory_map"]})
    (agent1 / "agent1_register_map.rdl").write_text("addrmap agent1_register_map { reg ctrl; };\n", encoding="utf-8")
    (agent1 / "fw_uart_signoff_regs.h").write_text("#define UART_SIGNOFF_UART_CTRL_OFFSET 0x00u\n", encoding="utf-8")
    (agent1 / "tb_uart_signoff_reg_model.py").write_text("class UartSignoffRegModel: pass\n", encoding="utf-8")
    _write_json(agent1 / "agent1_validation_decisions.json", {"decisions": [{"validator": "RDL_vs_CHeader_Validator", "decision": "ACCEPT"}]})
    _write_json(agent1 / "agent1_safety_security_plan.json", {"threat_model": ["APB software access"]})
    _write_json(agent1 / "agent1_clock_power_plan.json", {"clock_domains": spec["clock_domains"]})
    _write_json(agent1 / "agent1_independent_critic_report.json", {"findings": []})
    ensure_default_benchmark_report(root, profile=profile, force=True)
    (traces / "agent1_council_trace.jsonl").write_text(
        json.dumps({"node_id": "agent1_v51_council", "event_type": "agent1_group_session_done", "status": "pass"}) + "\n",
        encoding="utf-8",
    )

    plan_hash = sha256_text((reports / "architecture_plan.md").read_text(encoding="utf-8"))
    spec_hash = sha256_text((agent1 / "agent1_final_architecture_spec.json").read_text(encoding="utf-8"))
    fingerprint = {
        "schema_version": "agent1.artifact_fingerprint_manifest.v1",
        "revision_id": "rev-001",
        "artifact_count": 2,
        "artifacts": [
            {
                "artifact": "architecture_plan.md",
                "sha256": plan_hash,
                "status": "current",
                "requirement_revision_id": "rev-001",
                "spec_revision_id": "rev-001",
            },
            {
                "artifact": "agent1_final_architecture_spec.json",
                "sha256": spec_hash,
                "status": "current",
                "requirement_revision_id": "rev-001",
                "spec_revision_id": "rev-001",
            },
        ],
    }
    _write_json(agent1 / "agent1_artifact_fingerprint_manifest.json", fingerprint)
    _write_json(
        agent1 / "agent1_final_signoff_certificate.json",
        {
            "schema_version": SIGNOFF_CERTIFICATE_SCHEMA_VERSION,
            "run_id": "run-001",
            "revision_id": "rev-001",
            "project": project,
            "profile": profile,
            "decision": "PASS",
            "handoff_allowed": True,
            "score": 100.0,
            "gate_results": {gate: {"status": "PASS", "finding_codes": []} for gate in SIGNOFF_GATES},
            "finding_summary": {"total": 0},
            "waiver_summary": {"used": 0},
            "benchmark_summary": {
                "case_count": 110,
                "false_pass_count": 0,
                "must_not_pass_violation_count": 0,
            },
            "artifact_hashes": {
                "architecture_plan.md": plan_hash,
                "agent1_final_architecture_spec.json": spec_hash,
            },
            "topology_hash": HASH,
            "config_hash": HASH,
            "prompt_pack_hash": HASH,
            "model_ref_hash": HASH,
            "user_approval_ref": "approval-ok-001" if approval else None,
            "created_at": NOW,
        },
    )


def _mutate_none(root: Path) -> tuple[bool, set[str]]:
    return True, set()


def _mutate_missing_approval(root: Path) -> tuple[bool, set[str]]:
    path = root / "studio_run_manifest.json"
    data = _read_json(path)
    data["user_approval_ref"] = ""
    _write_json(path, data)
    return False, {"USER_APPROVAL_MISSING"}


def _mutate_stale_plan(root: Path) -> tuple[bool, set[str]]:
    (root / "reports" / "architecture_plan.md").write_text("# stale mutation\n", encoding="utf-8")
    return False, {"ARTIFACT_HASH_MISMATCH", "CERTIFICATE_ARTIFACT_HASH_MISMATCH"}


def _mutate_missing_spec(root: Path) -> tuple[bool, set[str]]:
    (root / "reports" / "agent1" / "agent1_final_architecture_spec.json").unlink()
    return False, {"MISSING_ARTIFACT", "REQUIREMENT_SPEC_MISSING"}


def _mutate_missing_register(root: Path) -> tuple[bool, set[str]]:
    (root / "reports" / "agent1" / "agent1_register_map.rdl").unlink()
    return False, {"REGISTER_ARTIFACT_MISSING"}


def _mutate_council_failed(root: Path) -> tuple[bool, set[str]]:
    trace = root / "reports" / "traces" / "agent1_council_trace.jsonl"
    with trace.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"node_id": "M06", "event_type": "agent1_group_session_failed", "status": "failed"}) + "\n")
    return False, {"COUNCIL_GROUP_FAILED"}


def _mutate_critic_high(root: Path) -> tuple[bool, set[str]]:
    _write_json(
        root / "reports" / "agent1" / "agent1_independent_critic_report.json",
        {"findings": [{"severity": "high", "message": "forced critic blocker"}]},
    )
    return False, {"INDEPENDENT_CRITIC_HIGH_FINDING"}


def _mutate_benchmark_false_pass(root: Path) -> tuple[bool, set[str]]:
    path = root / "reports" / "agent1" / "agent1_signoff_benchmark_report.json"
    data = _read_json(path)
    data["false_pass_count"] = 1
    _write_json(path, data)
    return False, {"BENCHMARK_FALSE_PASS"}


def _mutate_benchmark_hash(root: Path) -> tuple[bool, set[str]]:
    path = root / "reports" / "agent1" / "agent1_signoff_case_results.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"tamper": True}) + "\n")
    return False, {"BENCHMARK_ARTIFACT_HASH_MISMATCH"}


def _mutate_secret_raw_issue(root: Path) -> tuple[bool, set[str]]:
    issue = {
        "type": "debug_issue",
        "severity": "warning",
        "source": "uat",
        "code": "SECRET_TEST_INPUT",
        "message": "forced redaction sensor",
        "details": {"token": "api_key=TESTSECRET12345"},
    }
    with (root / "reports" / "traces" / "debug_issues.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(issue) + "\n")
    return False, {"SECRET_LEAK"}


MUTATIONS: dict[str, Callable[[Path], tuple[bool, set[str]]]] = {
    "clean": _mutate_none,
    "missing_approval": _mutate_missing_approval,
    "stale_plan": _mutate_stale_plan,
    "missing_spec": _mutate_missing_spec,
    "missing_register": _mutate_missing_register,
    "council_failed": _mutate_council_failed,
    "critic_high": _mutate_critic_high,
    "benchmark_false_pass": _mutate_benchmark_false_pass,
    "benchmark_hash": _mutate_benchmark_hash,
    "secret_raw_issue": _mutate_secret_raw_issue,
}


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[index]


def _issue_secret_leak(issues: list[dict[str, Any]]) -> bool:
    # Ignore the deliberately injected raw issue in the secret mutation case.
    # Generated signoff/handoff issues must still be clean.
    generated = [issue for issue in issues if issue.get("source") != "uat"]
    return bool(secret_leaks(generated))


def run_random_uat(*, iterations: int, seed: int, profile: str, work_root: Path) -> dict[str, Any]:
    rng = random.Random(seed)
    case_results: list[dict[str, Any]] = []
    pipeline_latencies: list[float] = []
    handoff_latencies: list[float] = []
    false_pass_count = 0
    false_block_count = 0
    missing_expected_codes = 0
    tracking_miss_count = 0
    secret_leak_count = 0

    names = list(MUTATIONS)
    for index in range(iterations):
        mutation_name = names[index % len(names)] if index < len(names) else rng.choice(names)
        root = work_root / f"case_{index + 1:03d}_{mutation_name}"
        _build_clean_run(root, profile=profile)
        expected_allowed, expected_codes = MUTATIONS[mutation_name](root)

        start = time.perf_counter()
        pipeline = run_agent1_signoff_pipeline(root, profile=profile, user_approval_ref=None)
        pipeline_latency = time.perf_counter() - start

        start = time.perf_counter()
        handoff = enforce_agent1_to_agent2_handoff(root, profile=profile, user_approval_ref=None)
        handoff_latency = time.perf_counter() - start

        pipeline_latencies.append(pipeline_latency)
        handoff_latencies.append(handoff_latency)

        actual_allowed = bool(handoff.allowed)
        codes = {finding.code for finding in pipeline.gate_report.findings} | set(handoff.blocking_codes)
        missing = sorted(code for code in expected_codes if code not in codes)
        false_pass = (not expected_allowed) and actual_allowed
        false_block = expected_allowed and not actual_allowed
        issues = _read_jsonl(root / "reports" / "traces" / "debug_issues.jsonl")
        tracked_codes = {str(issue.get("code") or "") for issue in issues}
        expected_tracking = sorted(code for code in codes if code and code not in tracked_codes)
        secret_leak = _issue_secret_leak(issues)

        false_pass_count += int(false_pass)
        false_block_count += int(false_block)
        missing_expected_codes += len(missing)
        tracking_miss_count += len(expected_tracking)
        secret_leak_count += int(secret_leak)
        case_results.append(
            {
                "case": index + 1,
                "mutation": mutation_name,
                "expected_allowed": expected_allowed,
                "actual_allowed": actual_allowed,
                "decision": pipeline.certificate.decision,
                "finding_count": len(pipeline.gate_report.findings),
                "debug_issue_count": len(issues),
                "codes": sorted(codes),
                "missing_expected_codes": missing,
                "missing_tracking_codes": expected_tracking,
                "false_pass": false_pass,
                "false_block": false_block,
                "secret_leak_in_debug": secret_leak,
                "pipeline_latency_s": round(pipeline_latency, 6),
                "handoff_latency_s": round(handoff_latency, 6),
            }
        )

    return {
        "schema_version": "agent1_v72_random_perf_uat/v1",
        "seed": seed,
        "iterations": iterations,
        "profile": profile,
        "mutation_names": names,
        "summary": {
            "false_pass_count": false_pass_count,
            "false_block_count": false_block_count,
            "missing_expected_code_count": missing_expected_codes,
            "tracking_miss_count": tracking_miss_count,
            "secret_leak_count": secret_leak_count,
            "pipeline_latency_s": _latency_summary(pipeline_latencies),
            "handoff_latency_s": _latency_summary(handoff_latencies),
        },
        "cases": case_results,
    }


def _latency_summary(values: list[float]) -> dict[str, float]:
    return {
        "min": round(min(values), 6),
        "p50": round(statistics.median(values), 6),
        "p95": round(_percentile(values, 95), 6),
        "max": round(max(values), 6),
        "mean": round(statistics.fmean(values), 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Agent1 V7.2 random verification and performance tracking UAT.")
    parser.add_argument("--iterations", type=int, default=80)
    parser.add_argument("--seed", type=int, default=7202026)
    parser.add_argument("--profile", choices=("balanced", "strict", "nightly"), default="strict")
    parser.add_argument("--output", default="outputs/uat/agent1_v72_random_perf_report.json")
    parser.add_argument("--keep-cases", action="store_true")
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.keep_cases:
        work_root = output.parent / f"{output.stem}_cases"
        work_root.mkdir(parents=True, exist_ok=True)
        report = run_random_uat(iterations=args.iterations, seed=args.seed, profile=args.profile, work_root=work_root)
    else:
        with tempfile.TemporaryDirectory(prefix="agent1_v72_random_perf_") as temp:
            report = run_random_uat(iterations=args.iterations, seed=args.seed, profile=args.profile, work_root=Path(temp))
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"output": str(output), **report["summary"]}, sort_keys=True))
    return 0 if all(value == 0 for key, value in report["summary"].items() if key.endswith("_count")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
