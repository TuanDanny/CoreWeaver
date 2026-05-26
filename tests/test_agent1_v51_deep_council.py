import json
import random
import threading
import time
from unittest.mock import Mock

from semiconductor_swarm.agents.agent1_planning.agent1_llm_client import Agent1CodexResult
from semiconductor_swarm.agents.agent1_planning.context_provider import build_agent1_context_package
from semiconductor_swarm.agents.agent1_planning.deep_expert_council import (
    LEAF_EXPERTS,
    MIDDLE_MANAGERS,
    Agent1CouncilConfig,
    cluster_map,
    execute_leaf_experts,
    execute_group_sessions,
    execute_middle_tasking,
    execute_middle_managers,
    execute_principal_charter,
    execute_principal_architect,
    load_topology_manifest,
    planned_calls_per_iteration,
    planned_minimum_calls,
    route_agent1_clusters,
    run_agent1_v51_council,
    topology_manifest,
    validate_topology,
    validate_topology_manifest,
)
from semiconductor_swarm.runtime_events import set_runtime_event_sink
from studio.backend.runtime_tracking import RuntimeTracker, build_runtime_invariant_report


def _legacy_config(**kwargs):
    return Agent1CouncilConfig(council_mode="legacy", **kwargs)


def _valid_response(summary="ok"):
    return json.dumps(
        {
            "summary": summary,
            "decisions": [{"decision": "preserve_requirement"}],
            "assumptions": [],
            "open_questions": [],
            "risks": [],
            "conflicts": [],
            "citations": [{"source": "raw_requirement"}],
            "confidence": 0.9,
            "needs_revision": False,
        }
    )


def _valid_response_with_candidate(candidate):
    payload = json.loads(_valid_response("principal candidate"))
    payload["selected_architecture_candidate"] = candidate
    payload["requirements_preserved"] = True
    payload["plan_ready_candidate"] = True
    return json.dumps(payload)


def test_agent1_v51_topology_has_24_leaf_7_middle_1_principal():
    report = validate_topology()
    manifest = topology_manifest()
    legacy_manifest = topology_manifest(_legacy_config())

    assert report["pass"], report["failures"]
    assert len(LEAF_EXPERTS) == 24
    assert len(MIDDLE_MANAGERS) == 7
    assert manifest["principal_architect"]["expert_id"] == "P01"
    assert manifest["council_mode"] == "group_session"
    assert manifest["max_concurrent_leaf_calls"] == 8
    assert manifest["max_concurrent_middle_calls"] == 4
    assert planned_calls_per_iteration() == 9
    assert legacy_manifest["planned_calls_per_iteration"] == 40
    assert planned_calls_per_iteration(_legacy_config()) == 40


def test_agent1_v51_cluster_map_covers_all_leaf_experts_once():
    leaf_ids = {expert.expert_id for expert in LEAF_EXPERTS}
    covered = [leaf_id for leaves in cluster_map().values() for leaf_id in leaves]

    assert set(covered) == leaf_ids
    assert len(covered) == len(set(covered)) == 24


def test_agent1_v51_context_provider_rag_disabled_local_sources():
    context = build_agent1_context_package(
        "Generate a 64-bit CPU architecture using an AHB bus with SPI",
        "cpu_soc",
        "normal",
        1,
        "L09",
        extracted_intents={"requested_bus_protocol": "AHB"},
    )

    assert context["schema_version"] == "agent1.context_package.v1"
    assert context["rag_enabled"] is False
    assert context["rag_provider"] is None
    assert context["rag_chunks"] == []
    assert context["source_hashes"]
    assert any(source["type"] == "local_doc" for source in context["context_sources"])
    assert "capability_assessment" in context


def test_agent1_v51_unwraps_common_llm_schema_wrappers():
    payload = json.loads(_valid_response("wrapped ok"))

    def charter_codex(_prompt):
        return Agent1CodexResult(content=json.dumps({"principal_charter": payload}), evidence={"model": "mock", "total_tokens": 1})

    charter = execute_principal_charter(
        "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
        "cpu32",
        charter_codex,
        config=_legacy_config(planning_mode="normal"),
    )

    assert charter["parse_status"] == "json_unwrapped:principal_charter"
    assert charter["output"]["summary"] == "wrapped ok"
    assert not any(conflict["type"] == "invalid_output_schema" for conflict in charter["conflicts"])

    def tasking_codex(_prompt):
        return Agent1CodexResult(content=json.dumps({"middle_tasking": payload}), evidence={"model": "mock", "total_tokens": 1})

    tasking = execute_middle_tasking(
        "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
        "cpu32",
        tasking_codex,
        charter,
        config=_legacy_config(planning_mode="normal", max_concurrent_middle_calls=3),
    )

    assert len(tasking) == len(MIDDLE_MANAGERS)
    assert all(record["parse_status"] == "json_unwrapped:middle_tasking" for record in tasking)
    assert not any(
        conflict["type"] == "invalid_output_schema"
        for record in tasking
        for conflict in record["conflicts"]
    )

def test_agent1_v51_normal_mode_exactly_40_calls():
    calls = []

    def fake_codex(prompt):
        calls.append(prompt)
        return Agent1CodexResult(content=_valid_response("normal ok"), evidence={"model": "mock", "total_tokens": 1})

    result = run_agent1_v51_council(
        "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
        "cpu32",
        fake_codex,
        config=_legacy_config(planning_mode="normal"),
    )

    assert len(calls) == 40
    assert planned_minimum_calls(_legacy_config(planning_mode="normal")) == 40
    assert len(result["iterations"]) == 1
    assert result["iterations"][0]["leaf_records"] == 24
    assert result["iterations"][0]["middle_records"] == 7
    leaf_trace = [json.loads(line) for line in result["artifacts"]["agent1_leaf_expert_trace.jsonl"].splitlines()]
    middle_trace = [json.loads(line) for line in result["artifacts"]["agent1_middle_manager_trace.jsonl"].splitlines()]
    assert [item["expert_id"] for item in leaf_trace] == [expert.expert_id for expert in LEAF_EXPERTS]
    assert [item["manager_id"] for item in middle_trace] == [manager.manager_id for manager in MIDDLE_MANAGERS]


def test_agent1_v51_downgrades_out_of_scope_spi_conflict_for_uart_requirement():
    def fake_codex(prompt):
        payload = json.loads(_valid_response("uart-only ok"))
        if "Leaf L12" in prompt:
            payload["needs_revision"] = True
            payload["conflicts"] = [
                {
                    "severity": "critical",
                    "conflict": "Leaf title asks for SPI external peripheral behavior, but project requirement declares UART as only external peripheral.",
                    "resolution": "Do not add SPI. Treat SPI work as out of scope unless user explicitly updates external_peripherals.",
                }
            ]
        if "Middle Manager M04" in prompt:
            payload["needs_revision"] = True
            payload["conflicts"] = [
                {
                    "severity": "critical",
                    "conflict": "L12 targets SPI while project requirement declares UART as only external peripheral.",
                    "resolution": "Reject SPI additions; keep UART only.",
                }
            ]
        return Agent1CodexResult(content=json.dumps(payload), evidence={"model": "mock", "total_tokens": 1})

    result = run_agent1_v51_council(
        "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
        "cpu32",
        fake_codex,
        config=_legacy_config(planning_mode="normal"),
    )
    conflict_matrix = json.loads(result["artifacts"]["agent1_conflict_matrix.json"])

    assert result["status"] == "READY_FOR_DETERMINISTIC_GUARDRAILS"
    assert not conflict_matrix["critical_conflicts"]
    assert any(item.get("resolved") for item in conflict_matrix["noncritical_conflicts"])


def test_agent1_v51_downgrades_leaf_task_spi_conflict_for_uart_only_requirement():
    def fake_codex(prompt):
        payload = json.loads(_valid_response("uart-only exact mismatch ok"))
        if "Leaf L12" in prompt:
            payload["needs_revision"] = True
            payload["conflicts"] = [
                {
                    "severity": "critical",
                    "conflict": "Leaf asks for SPI external peripheral planning, but project requirement and deterministic intents declare UART external peripheral only",
                    "needed_decision": "Confirm SPI addition or retask leaf to UART",
                    "resolution_status": "open",
                }
            ]
        return Agent1CodexResult(content=json.dumps(payload), evidence={"model": "mock", "total_tokens": 1})

    result = run_agent1_v51_council(
        "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
        "cpu32",
        fake_codex,
        config=_legacy_config(planning_mode="normal"),
    )
    conflict_matrix = json.loads(result["artifacts"]["agent1_conflict_matrix.json"])

    assert result["status"] == "READY_FOR_DETERMINISTIC_GUARDRAILS"
    assert not conflict_matrix["critical_conflicts"]
    assert any(
        item.get("source") == "L12"
        and item.get("resolved") is True
        and item.get("resolution_status") == "resolved_for_iteration"
        for item in conflict_matrix["noncritical_conflicts"]
    )


def test_agent1_v51_downgrades_defaultable_cpu_map_gaps_for_minimum_requirement():
    def fake_codex(prompt):
        payload = json.loads(_valid_response("defaultable open items ok"))
        if "M02" in prompt and "CPU/Memory Manager" in prompt:
            payload["needs_revision"] = True
            payload["conflicts"] = [
                {
                    "severity": "critical",
                    "description": "Reset/trap vector addresses missing.",
                    "domain": "reset_boot_trap",
                },
                {
                    "severity": "critical",
                    "description": "boot_rom, single_port_sram, uart_apb_controller base addresses/sizes missing.",
                    "domain": "memory_map",
                },
            ]
        return Agent1CodexResult(content=json.dumps(payload), evidence={"model": "mock", "total_tokens": 1})

    result = run_agent1_v51_council(
        "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
        "cpu32",
        fake_codex,
        config=_legacy_config(planning_mode="normal"),
    )
    conflict_matrix = json.loads(result["artifacts"]["agent1_conflict_matrix.json"])

    assert result["status"] == "READY_FOR_DETERMINISTIC_GUARDRAILS"
    assert not conflict_matrix["critical_conflicts"]
    assert any(
        item.get("source") == "M02"
        and item.get("type") == "defaultable_architecture_open_item"
        and item.get("requires_plan_review") is True
        for item in conflict_matrix["noncritical_conflicts"]
    )


def test_agent1_v51_deep_mode_minimum_120_calls_and_three_iterations():
    calls = []

    def fake_codex(prompt):
        calls.append(prompt)
        return Agent1CodexResult(content=_valid_response("deep ok"), evidence={"model": "mock", "total_tokens": 1})

    result = run_agent1_v51_council(
        "Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral",
        "cpu_soc",
        fake_codex,
        config=_legacy_config(planning_mode="deep_planning", min_iterations=3, max_iterations=3),
    )

    assert len(calls) == 120
    assert planned_minimum_calls(_legacy_config(planning_mode="deep_planning", min_iterations=3)) == 120
    assert len(result["iterations"]) == 3
    assert result["status"] == "READY_FOR_DETERMINISTIC_GUARDRAILS"


def test_agent1_v51_leaf_calls_are_bounded_parallel_not_sequential():
    active = 0
    max_active = 0
    lock = threading.Lock()
    completion_order = []

    def fake_codex(prompt):
        nonlocal active, max_active
        expert_id = prompt.split("Leaf ")[1].split(":")[0]
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.02)
        with lock:
            active -= 1
            completion_order.append(expert_id)
        return Agent1CodexResult(content=_valid_response(expert_id), evidence={"model": "mock", "total_tokens": 1})

    records = execute_leaf_experts(
        "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
        "cpu32",
        fake_codex,
        config=_legacy_config(max_concurrent_leaf_calls=4),
    )

    assert max_active > 1
    assert max_active <= 4
    assert len(completion_order) == 24
    assert [record["expert_id"] for record in records] == [expert.expert_id for expert in LEAF_EXPERTS]


def test_agent1_v51_leaf_invalid_output_becomes_conflict():
    def fake_codex(_prompt):
        return Agent1CodexResult(content=json.dumps({"summary": "missing fields"}), evidence={"model": "mock"})

    records = execute_leaf_experts(
        "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
        "cpu32",
        fake_codex,
        config=_legacy_config(max_concurrent_leaf_calls=8),
    )

    assert len(records) == 24
    assert all(record["parse_status"] == "repair_failed_invalid_schema" for record in records)
    assert all(record["repair_attempted"] for record in records)
    assert all(any(conflict["type"] == "invalid_output_schema" for conflict in record["conflicts"]) for record in records)


def test_agent1_v51_leaf_parallel_transient_failures_retry_and_track_invariants(tmp_path):
    failing_experts = set(random.Random(20260525).sample([expert.expert_id for expert in LEAF_EXPERTS], 3))
    attempts: dict[str, int] = {}
    events: list[dict[str, object]] = []

    def flaky_codex(prompt):
        expert_id = prompt.split("Leaf ")[1].split(":")[0]
        attempts[expert_id] = attempts.get(expert_id, 0) + 1
        if expert_id in failing_experts:
            if attempts[expert_id] == 1:
                raise RuntimeError("HTTP Error 502: Bad Gateway")
            raise TimeoutError("Agent 1 Codex API timed out")
        return Agent1CodexResult(content=_valid_response(expert_id), evidence={"model": "mock", "total_tokens": 1})

    mocked_codex = Mock(side_effect=flaky_codex)

    set_runtime_event_sink(events.append)
    try:
        records = execute_leaf_experts(
            "Generate a 32-bit CPU architecture using APB UART with secure boot and a locked memory map",
            "leaf_concurrency_resilience",
            mocked_codex,
            config=_legacy_config(max_concurrent_leaf_calls=8, leaf_transient_max_retries=1, leaf_retry_backoff_s=0.001),
        )
    finally:
        set_runtime_event_sink(None)

    failed = [record for record in records if any(conflict.get("type") == "codex_call_failed" for conflict in record["conflicts"])]
    passed = [record for record in records if record not in failed]
    retry_events = [event for event in events if event.get("type") == "agent1_leaf_expert_retry"]
    failed_events = [event for event in events if event.get("type") == "agent1_leaf_expert_failed"]
    done_events = [event for event in events if event.get("type") == "agent1_leaf_expert_done"]

    assert len(records) == 24
    assert {record["expert_id"] for record in failed} == failing_experts
    assert len(failed) == 3
    assert len(passed) == 21
    assert sum(attempts.values()) == 27
    assert mocked_codex.call_count == 27
    assert all(record["retry_attempted"] and record["retry_count"] == 1 for record in failed)
    assert all(not record["retry_attempted"] for record in passed)
    assert {str(event["expert_id"]) for event in retry_events} == failing_experts
    assert {str(event["expert_id"]) for event in failed_events} == failing_experts
    assert all(float(event["backoff_s"]) == 0.001 for event in retry_events)
    assert len(done_events) == 21

    output_dir = tmp_path / "outputs" / "leaf_concurrency_resilience"
    tracker = RuntimeTracker(root=tmp_path)
    state = {
        "run_id": "run-leaf-concurrency",
        "status": "running",
        "project_name": "leaf_concurrency_resilience",
        "output_dir": str(output_dir),
    }
    tracker.initialize_run(state)
    for event in events:
        tracker.record_source_event(event, state)
    invariant = build_runtime_invariant_report(output_dir)
    manifest = json.loads((output_dir / "reports" / "traces" / "runtime_session_manifest.json").read_text(encoding="utf-8"))
    leaf_manifest = manifest["agent1_cluster_council"]["leaf_experts"]

    assert invariant["ok"] is True
    assert invariant["agent1_leaf_resilience"]["leaf_count"] == 24
    assert invariant["agent1_leaf_resilience"]["failed_count"] == 3
    assert invariant["agent1_leaf_resilience"]["retried_count"] == 3
    assert set(invariant["agent1_leaf_resilience"]["failed_expert_ids"]) == failing_experts
    assert set(invariant["agent1_leaf_resilience"]["retried_expert_ids"]) == failing_experts
    assert {expert_id for expert_id, item in leaf_manifest.items() if item["status"] == "failed"} == failing_experts
    assert sum(1 for item in leaf_manifest.values() if item["status"] == "passed") == 21
    assert all(leaf_manifest[expert_id]["retry_count"] == 1 for expert_id in failing_experts)

def test_agent1_v51_middle_calls_are_bounded_parallel_not_sequential_and_cover_leaf_once():
    active = 0
    max_active = 0
    lock = threading.Lock()
    leaf_records = [
        {
            "record_type": "leaf",
            "expert_id": expert.expert_id,
            "title": expert.title,
            "domain": expert.domain,
            "iteration": 1,
            "output": json.loads(_valid_response(expert.expert_id)),
            "conflicts": [],
        }
        for expert in LEAF_EXPERTS
    ]

    def fake_codex(prompt):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return Agent1CodexResult(content=_valid_response("middle ok"), evidence={"model": "mock", "total_tokens": 1})

    records = execute_middle_managers(
        "Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral",
        "cpu_soc",
        fake_codex,
        leaf_records,
        config=_legacy_config(max_concurrent_middle_calls=3),
    )

    assert max_active > 1
    assert max_active <= 3
    assert [record["manager_id"] for record in records] == [manager.manager_id for manager in MIDDLE_MANAGERS]
    covered = [leaf_id for record in records for leaf_id in record["covered_experts"]]
    assert sorted(covered) == sorted(expert.expert_id for expert in LEAF_EXPERTS)
    assert len(covered) == len(set(covered))
    assert all("accepted_decisions" in record["output"] for record in records)
    assert all("feedback_to_leaf_experts" in record["output"] for record in records)


def test_agent1_v51_middle_missing_leaf_output_is_critical_conflict():
    leaf_records = [
        {
            "record_type": "leaf",
            "expert_id": expert.expert_id,
            "title": expert.title,
            "domain": expert.domain,
            "iteration": 1,
            "output": json.loads(_valid_response(expert.expert_id)),
            "conflicts": [],
        }
        for expert in LEAF_EXPERTS
        if expert.expert_id != "L09"
    ]

    records = execute_middle_managers(
        "Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral",
        "cpu_soc",
        lambda _prompt: Agent1CodexResult(content=_valid_response("middle ok"), evidence={"model": "mock"}),
        leaf_records,
    )

    protocol_manager = next(record for record in records if record["manager_id"] == "M03")
    assert any(conflict["type"] == "missing_leaf_outputs" and conflict["severity"] == "critical" for conflict in protocol_manager["conflicts"])


def test_agent1_v51_principal_architect_emits_synthesis_contract():
    middle_records = [
        {
            "record_type": "middle",
            "manager_id": manager.manager_id,
            "title": manager.title,
            "domain": manager.domain,
            "covered_experts": list(manager.leaf_expert_ids),
            "iteration": 1,
            "output": {"summary": manager.title, "decisions": [], "conflicts": []},
            "conflicts": [],
        }
        for manager in MIDDLE_MANAGERS
    ]

    record = execute_principal_architect(
        "Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral",
        "cpu_soc",
        lambda _prompt: Agent1CodexResult(content=_valid_response("principal ok"), evidence={"model": "mock"}),
        middle_records,
    )

    assert record["principal_id"] == "P01"
    assert "selected_architecture_candidate" in record["output"]
    assert "feedback_to_middle_managers" in record["output"]
    assert "plan_ready_candidate" in record["output"]


def test_agent1_v51_deep_mode_continues_on_critical_conflict_and_hits_hitl_at_cap():
    calls = []

    def failing_leaf_only(prompt):
        calls.append(prompt)
        if "Leaf L01" in prompt:
            raise RuntimeError("requirement intake endpoint down")
        return Agent1CodexResult(content=_valid_response("ok"), evidence={"model": "mock", "total_tokens": 1})

    result = run_agent1_v51_council(
        "Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral",
        "cpu_soc",
        failing_leaf_only,
        config=_legacy_config(planning_mode="deep_planning", min_iterations=3, max_iterations=4, max_concurrent_leaf_calls=8),
    )

    assert len(result["iterations"]) == 4
    assert len(calls) == 160
    assert result["status"] == "HITL_REQUIRED"
    assert all(item["status"] == "conflict" for item in result["iterations"])


def test_agent1_v51_deep_mode_continues_when_guardrail_fails_after_min_iterations():
    calls = []

    def bad_principal(prompt):
        calls.append(prompt)
        if "Principal Architect" in prompt:
            return Agent1CodexResult(
                content=_valid_response_with_candidate(
                    {
                        "summary": "Incorrect APB-only candidate",
                        "primary_protocol": "APB",
                        "cpu_width_bits": 64,
                        "external_peripherals": ["spi"],
                    }
                ),
                evidence={"model": "mock"},
            )
        return Agent1CodexResult(content=_valid_response("ok"), evidence={"model": "mock"})

    result = run_agent1_v51_council(
        "Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral",
        "cpu_soc",
        bad_principal,
        config=_legacy_config(planning_mode="deep_planning", min_iterations=3, max_iterations=5),
    )

    assert len(result["iterations"]) == 5
    assert len(calls) == 200
    assert result["status"] == "HITL_REQUIRED"
    guardrail_trace = [json.loads(line) for line in result["artifacts"]["agent1_v51_guardrail_trace.jsonl"].splitlines()]
    assert len(guardrail_trace) == 5
    assert all(not item["pass"] for item in guardrail_trace)


def test_agent1_v51_deep_mode_stops_after_min_iterations_when_conflicts_resolved():
    calls = []

    def first_two_iterations_conflict(prompt):
        calls.append(prompt)
        if ("Leaf L01" in prompt or "Middle M01" in prompt or "Principal Architect" in prompt) and "Iteration: 1" in prompt:
            return Agent1CodexResult(
                content=json.dumps(
                    {
                        "summary": "critical conflict",
                        "decisions": [],
                        "assumptions": [],
                        "open_questions": [],
                        "risks": [],
                        "conflicts": [{"severity": "critical", "type": "requirement_conflict"}],
                        "citations": [],
                        "confidence": 0.4,
                        "needs_revision": True,
                    }
                ),
                evidence={"model": "mock"},
            )
        return Agent1CodexResult(content=_valid_response("resolved"), evidence={"model": "mock", "total_tokens": 1})

    result = run_agent1_v51_council(
        "Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral",
        "cpu_soc",
        first_two_iterations_conflict,
        config=_legacy_config(planning_mode="deep_planning", min_iterations=3, max_iterations=5),
    )

    assert len(result["iterations"]) == 3
    assert len(calls) == 120
    assert result["status"] == "READY_FOR_DETERMINISTIC_GUARDRAILS"


def test_agent1_v51_guardrails_emit_spec_plan_and_reports_for_ahb_spi():
    def fake_codex(prompt):
        if "Principal Architect" in prompt:
            return Agent1CodexResult(
                content=_valid_response_with_candidate(
                    {
                        "summary": "64-bit CPU with AHB primary and SPI APB peripheral via bridge",
                        "primary_protocol": "AHB",
                        "peripheral_protocol": "APB",
                        "cpu_width_bits": 64,
                        "external_peripherals": ["spi"],
                        "bridges": [{"name": "ahb_to_apb_bridge", "from_protocol": "AHB", "to_protocol": "APB"}],
                    }
                ),
                evidence={"model": "mock", "total_tokens": 1},
            )
        return Agent1CodexResult(content=_valid_response("ok"), evidence={"model": "mock", "total_tokens": 1})

    result = run_agent1_v51_council(
        "Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral",
        "cpu_soc",
        fake_codex,
        config=_legacy_config(planning_mode="normal"),
    )

    guardrail = json.loads(result["artifacts"]["agent1_v51_guardrail_report.json"])
    spec = json.loads(result["artifacts"]["agent1_v51_architecture_spec.json"])
    plan = result["artifacts"]["architecture_plan.md"]

    assert result["status"] == "READY_FOR_DETERMINISTIC_GUARDRAILS"
    assert guardrail["pass"], guardrail["failures"]
    assert guardrail["reports"]["requirement_preservation"]["pass"]
    assert guardrail["reports"]["plan_quality_report"]["pass"]
    assert guardrail["reports"]["requirement_consistency_report"]["pass"]
    assert spec["bus_architecture"]["primary_protocol"] == "AHB"
    assert spec["cpu_subsystem"]["data_width_bits"] == 64
    assert spec["cpu_subsystem"]["bus_role"] == "AHB master"
    assert "spi" in spec["memory_map"]
    assert "AHB primary system bus" in plan
    assert "SPI External Peripheral" in plan
    assert "UART `baud_div`" not in plan
    assert "rv32" not in plan.lower()


def test_agent1_v51_guardrails_block_principal_rewriting_requested_bus():
    def fake_codex(prompt):
        if "Principal Architect" in prompt:
            return Agent1CodexResult(
                content=_valid_response_with_candidate(
                    {
                        "summary": "Wrongly rewrite to APB-only",
                        "primary_protocol": "APB",
                        "cpu_width_bits": 64,
                        "external_peripherals": ["spi"],
                    }
                ),
                evidence={"model": "mock"},
            )
        return Agent1CodexResult(content=_valid_response("ok"), evidence={"model": "mock"})

    result = run_agent1_v51_council(
        "Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral",
        "cpu_soc",
        fake_codex,
        config=_legacy_config(planning_mode="normal"),
    )

    guardrail = json.loads(result["artifacts"]["agent1_v51_guardrail_report.json"])
    conflict_matrix = json.loads(result["artifacts"]["agent1_conflict_matrix.json"])

    assert result["status"] == "HITL_REQUIRED"
    assert not guardrail["pass"]
    assert "principal_candidate_rewrites_bus:AHB->APB" in guardrail["failures"]
    assert any(conflict["type"] == "deterministic_guardrail_failed" for conflict in conflict_matrix["critical_conflicts"])


def test_agent1_v51_guardrails_block_principal_dropping_requested_peripheral():
    def fake_codex(prompt):
        if "Principal Architect" in prompt:
            return Agent1CodexResult(
                content=_valid_response_with_candidate(
                    {
                        "summary": "Drops UART despite requirement",
                        "primary_protocol": "APB",
                        "cpu_width_bits": 32,
                        "external_peripherals": ["gpio"],
                    }
                ),
                evidence={"model": "mock"},
            )
        return Agent1CodexResult(content=_valid_response("ok"), evidence={"model": "mock"})

    result = run_agent1_v51_council(
        "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
        "cpu32",
        fake_codex,
        config=_legacy_config(planning_mode="normal"),
    )

    guardrail = json.loads(result["artifacts"]["agent1_v51_guardrail_report.json"])

    assert result["status"] == "HITL_REQUIRED"
    assert not guardrail["pass"]
    assert any(failure.startswith("principal_candidate_drops_peripherals") for failure in guardrail["failures"])


def test_agent1_v51_guardrails_block_principal_rewriting_cpu_width():
    def fake_codex(prompt):
        if "Principal Architect" in prompt:
            return Agent1CodexResult(
                content=_valid_response_with_candidate(
                    {
                        "summary": "Wrongly chooses 32-bit CPU",
                        "primary_protocol": "AHB",
                        "cpu_width_bits": 32,
                        "external_peripherals": ["spi"],
                    }
                ),
                evidence={"model": "mock"},
            )
        return Agent1CodexResult(content=_valid_response("ok"), evidence={"model": "mock"})

    result = run_agent1_v51_council(
        "Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral",
        "cpu_soc",
        fake_codex,
        config=_legacy_config(planning_mode="normal"),
    )

    guardrail = json.loads(result["artifacts"]["agent1_v51_guardrail_report.json"])

    assert result["status"] == "HITL_REQUIRED"
    assert not guardrail["pass"]
    assert "principal_candidate_rewrites_cpu_width:64->32" in guardrail["failures"]


def test_agent1_v51_runtime_events_cover_batches_principal_conflicts_and_guardrails():
    events = []
    set_runtime_event_sink(events.append)
    try:
        result = run_agent1_v51_council(
            "Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral",
            "cpu_soc",
            lambda _prompt: Agent1CodexResult(content=_valid_response("event ok"), evidence={"model": "mock", "total_tokens": 1}),
            config=_legacy_config(planning_mode="normal", max_concurrent_leaf_calls=4, max_concurrent_middle_calls=3),
        )
    finally:
        set_runtime_event_sink(None)

    assert result["status"] == "READY_FOR_DETERMINISTIC_GUARDRAILS"
    actions = [event for event in events if event.get("type") == "agent_action"]
    discussions = [event for event in events if event.get("type") == "agent_discussion"]
    handoffs = [event for event in events if event.get("type") == "agent_handoff"]

    assert any(event.get("action") == "V5.1 Leaf Experts batch started" for event in actions)
    assert any(event.get("action") == "V5.1 Leaf Experts batch completed" for event in actions)
    assert any(event.get("action") == "V5.1 Middle Managers batch started" for event in actions)
    assert any(event.get("action") == "V5.1 Middle Managers batch completed" for event in actions)
    assert any(event.get("action") == "Principal Architect started" for event in actions)
    assert any(event.get("action") == "Principal Architect completed" for event in actions)
    assert any(event.get("action") == "V5.1 deterministic guardrails completed" for event in actions)
    assert any(event.get("rollup_stage") == "Leaf Experts" and event.get("metric", {}).get("max_workers") == 4 for event in actions)
    assert any(event.get("rollup_stage") == "Middle Managers" and event.get("metric", {}).get("max_workers") == 3 for event in actions)
    assert any(event.get("speaker") == "agent1" and event.get("audience") == "principal_architect" for event in discussions)
    assert any(event.get("from_agent") == "agent1" and event.get("to_agent") == "agent1_guardrails" for event in handoffs)
    assert not any("Context package:" in json.dumps(event) for event in events)
    assert not any("Requirement:" in json.dumps(event) for event in events)

def test_agent1_v51_council_events_expose_middle_synthesis_without_raw_prompts():
    events = []
    set_runtime_event_sink(events.append)
    try:
        run_agent1_v51_council(
            "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
            "cpu32",
            lambda _prompt: Agent1CodexResult(content=_valid_response("council ok"), evidence={"model": "mock", "total_tokens": 7}),
            config=_legacy_config(planning_mode="normal", max_concurrent_leaf_calls=4, max_concurrent_middle_calls=3),
        )
    finally:
        set_runtime_event_sink(None)

    council_nodes = [event for event in events if event.get("type") == "agent1_council_node"]
    middle_nodes = [event for event in council_nodes if event.get("layer") == "middle" and event.get("status") == "pass"]
    leaf_nodes = [event for event in council_nodes if event.get("layer") == "leaf" and event.get("status") == "pass"]
    principal_nodes = [event for event in council_nodes if event.get("layer") == "principal" and event.get("status") == "pass"]
    guardrail_nodes = [event for event in council_nodes if event.get("layer") == "guardrail"]
    edge_events = [event for event in events if event.get("type") == "agent1_council_edge"]

    assert len(leaf_nodes) == 24
    assert len(middle_nodes) == 14
    assert principal_nodes
    assert guardrail_nodes
    assert edge_events
    protocol_manager = next(event for event in middle_nodes if event.get("node_id") == "M03")
    assert protocol_manager["child_ids"]
    assert "accepted_decisions" in protocol_manager
    assert "rejected_decisions" in protocol_manager
    assert "conflicts" in protocol_manager
    assert "feedback_digest" in protocol_manager
    assert "handoff_digest" in protocol_manager
    assert protocol_manager["phase_seq"]
    assert all(len(json.dumps(event).encode("utf-8")) < 64 * 1024 for event in events)
    assert not any("Context package:" in json.dumps(event) for event in events)
    assert not any("Requirement:" in json.dumps(event) for event in events)


def test_agent1_v51_middle_event_tolerates_dict_domain_conflicts():
    events = []

    def fake_codex(prompt):
        payload = json.loads(_valid_response("schema variant ok"))
        if "M06" in prompt:
            payload["domain_conflicts"] = {
                "severity": "noncritical",
                "type": "clock_power_open_item",
                "message": "Clock and power closure remains open.",
            }
            payload["accepted_decisions"] = {"decision": "keep single clock assumption"}
            payload["rejected_decisions"] = {"decision": "do not lock power intent yet"}
        return Agent1CodexResult(content=json.dumps(payload), evidence={"model": "mock", "total_tokens": 1})

    set_runtime_event_sink(events.append)
    try:
        result = run_agent1_v51_council(
            "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
            "cpu32",
            fake_codex,
            config=_legacy_config(planning_mode="normal", max_concurrent_leaf_calls=4, max_concurrent_middle_calls=3),
        )
    finally:
        set_runtime_event_sink(None)

    assert result["status"] == "READY_FOR_DETERMINISTIC_GUARDRAILS"
    m06 = next(
        event
        for event in events
        if event.get("type") == "agent1_council_node"
        and event.get("node_id") == "M06"
        and event.get("status") in {"pass", "conflict"}
    )
    assert isinstance(m06["conflicts"], list)
    assert any(item.get("type") == "clock_power_open_item" for item in m06["conflicts"])
    assert isinstance(m06["accepted_decisions"], list)
    assert isinstance(m06["rejected_decisions"], list)


def test_agent1_v51_runtime_events_report_guardrail_failure_without_large_payloads():
    events = []
    set_runtime_event_sink(events.append)
    try:
        run_agent1_v51_council(
            "Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral",
            "cpu_soc",
            lambda prompt: Agent1CodexResult(
                content=_valid_response_with_candidate(
                    {
                        "summary": "Wrong APB",
                        "primary_protocol": "APB",
                        "cpu_width_bits": 64,
                        "external_peripherals": ["spi"],
                    }
                )
                if "Principal Architect" in prompt
                else _valid_response("ok"),
                evidence={"model": "mock"},
            ),
            config=_legacy_config(planning_mode="normal"),
        )
    finally:
        set_runtime_event_sink(None)

    guardrail_events = [event for event in events if event.get("type") == "agent_action" and event.get("action") == "V5.1 deterministic guardrails completed"]
    assert guardrail_events
    assert guardrail_events[-1]["status"] == "fail"
    assert all(len(json.dumps(event).encode("utf-8")) < 4096 for event in events)


def test_agent1_v51_endpoint_unstable_conflict_recorded_when_leaf_failures_exceed_threshold():
    def fail_many_leaf_calls(prompt):
        if "Leaf L" in prompt and any(f"Leaf L{index:02d}" in prompt for index in range(1, 8)):
            raise RuntimeError("endpoint overloaded")
        return Agent1CodexResult(content=_valid_response("ok"), evidence={"model": "mock"})

    result = run_agent1_v51_council(
        "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
        "cpu32",
        fail_many_leaf_calls,
        config=_legacy_config(planning_mode="normal"),
    )
    conflict_matrix = json.loads(result["artifacts"]["agent1_conflict_matrix.json"])

    assert result["status"] == "HITL_REQUIRED"
    assert any(conflict["type"] == "endpoint_unstable" for conflict in conflict_matrix["critical_conflicts"])


def test_agent1_v51_principal_prompt_receives_previous_principal_and_guardrail_context():
    prompts = []

    def capture_prompt(prompt):
        prompts.append(prompt)
        return Agent1CodexResult(content=_valid_response("ok"), evidence={"model": "mock"})

    run_agent1_v51_council(
        "Generate a 64-bit CPU architecture using an AHB bus, with SPI as the external peripheral",
        "cpu_soc",
        capture_prompt,
        config=_legacy_config(planning_mode="deep_planning", min_iterations=3, max_iterations=3),
    )

    principal_prompts = [prompt for prompt in prompts if "Principal Architect" in prompt]
    assert len(principal_prompts) == 3
    assert "Previous principal and deterministic gate context" in principal_prompts[1]
    assert "previous_principal_decision" in principal_prompts[1]
    assert "previous_deterministic_gate_report" in principal_prompts[1]

def test_agent1_v71_topology_manifest_loads_default_7_groups_24_leaf():
    manifest = load_topology_manifest()
    report = validate_topology_manifest(manifest)

    assert report["pass"], report["failures"]
    assert report["topology_version"] == "v7.1-default"
    assert len(manifest["groups"]) == 7
    assert len(manifest["leaf_experts"]) == 24
    assert manifest["principal"]["expert_id"] == "P01"

def test_agent1_v71_topology_manifest_rejects_duplicate_leaf_ids():
    manifest = load_topology_manifest()
    duplicate = json.loads(json.dumps(manifest))
    duplicate["leaf_experts"][1]["expert_id"] = duplicate["leaf_experts"][0]["expert_id"]

    report = validate_topology_manifest(duplicate)

    assert report["pass"] is False
    assert "duplicate_leaf_ids" in report["failures"]

def test_agent1_v71_router_assigns_cross_domain_guest_experts():
    assignment = route_agent1_clusters(
        "Build an I2C APB controller with formal checks and timing constraints",
        config=Agent1CouncilConfig(planning_mode="normal", council_mode="group_session"),
    )
    groups = {group["group_id"]: group for group in assignment["groups"]}

    assert assignment["schema_version"] == "agent1.cluster_assignment.v1"
    assert len(groups) == 7
    assert "L18" in groups["M04"]["guest_expert_ids"]
    assert "L17" in groups["M04"]["guest_expert_ids"]
    assert groups["M04"]["score"] > 0
    assert assignment["cluster_assignment_hash"]

def test_agent1_v71_group_session_mode_uses_nine_calls_and_artifacts():
    calls = []

    def fake_codex(prompt):
        calls.append(prompt)
        return Agent1CodexResult(content=_valid_response("group ok"), evidence={"model": "mock", "total_tokens": 3, "estimated_cost_usd": 0.01})

    result = run_agent1_v51_council(
        "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
        "cpu32",
        fake_codex,
        config=Agent1CouncilConfig(planning_mode="normal", council_mode="group_session"),
    )
    group_trace = [json.loads(line) for line in result["artifacts"]["agent1_group_session_trace.jsonl"].splitlines()]
    assignment = json.loads(result["artifacts"]["agent1_cluster_assignment.json"])

    assert result["status"] == "READY_FOR_DETERMINISTIC_GUARDRAILS"
    assert len(calls) == 9
    assert result["config"]["planned_calls_per_iteration"] == 9
    assert result["iterations"][0]["group_session_records"] == 7
    assert len(group_trace) == 7
    assert assignment["topology_version"] == "v7.1-default"
    assert "agent1_cross_group_challenge_matrix.json" in result["artifacts"]

def test_agent1_v71_group_session_runtime_events_are_zero_loss_without_prompts():
    events = []
    set_runtime_event_sink(events.append)
    try:
        run_agent1_v51_council(
            "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
            "cpu32",
            lambda _prompt: Agent1CodexResult(content=_valid_response("event ok"), evidence={"model": "mock", "total_tokens": 5}),
            config=Agent1CouncilConfig(planning_mode="normal", council_mode="group_session", max_concurrent_group_calls=2),
        )
    finally:
        set_runtime_event_sink(None)

    starts = [event for event in events if event.get("type") == "agent1_group_session_start"]
    dones = [event for event in events if event.get("type") == "agent1_group_session_done"]
    mode_events = [event for event in events if event.get("type") == "agent1_council_mode_selected"]
    assignment_events = [event for event in events if event.get("type") == "agent1_cluster_assignment"]

    assert len(starts) == 7
    assert len(dones) == 7
    assert mode_events and mode_events[-1]["mode"] == "group_session"
    assert assignment_events and assignment_events[-1]["cluster_assignment_hash"]
    assert all(event.get("span_id") for event in starts + dones)
    assert not any("Context package:" in json.dumps(event) for event in events)
    assert not any("Requirement:" in json.dumps(event) for event in events)

def test_agent1_v71_group_session_retries_target_group_only():
    calls_by_group: dict[str, int] = {}

    def fake_codex(prompt):
        if "Group Session M04" in prompt:
            calls_by_group["M04"] = calls_by_group.get("M04", 0) + 1
            if calls_by_group["M04"] == 1:
                payload = json.loads(_valid_response("m04 low confidence"))
                payload["needs_retry"] = True
                payload["confidence"] = 0.2
                return Agent1CodexResult(content=json.dumps(payload), evidence={"model": "mock", "total_tokens": 1})
        return Agent1CodexResult(content=_valid_response("ok"), evidence={"model": "mock", "total_tokens": 1})

    result = run_agent1_v51_council(
        "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
        "cpu32",
        fake_codex,
        config=Agent1CouncilConfig(planning_mode="normal", council_mode="group_session"),
    )
    retry_trace = [json.loads(line) for line in result["artifacts"]["agent1_group_retry_trace.jsonl"].splitlines()]

    assert result["status"] == "READY_FOR_DETERMINISTIC_GUARDRAILS"
    assert calls_by_group["M04"] == 2
    assert len(retry_trace) == 1
    assert retry_trace[0]["manager_id"] == "M04"
    assert result["iterations"][0]["retry_records"] == 1

def test_agent1_v71_group_session_suppresses_retry_storm_on_codex_timeout():
    calls_by_group: dict[str, int] = {}

    def fake_codex(prompt):
        if "Group Session M04" in prompt:
            calls_by_group["M04"] = calls_by_group.get("M04", 0) + 1
            raise RuntimeError("Agent 1 Codex API unavailable at http://localhost:20128/v1: timed out")
        return Agent1CodexResult(content=_valid_response("ok"), evidence={"model": "mock", "total_tokens": 1})

    events = []
    set_runtime_event_sink(events.append)
    try:
        result = run_agent1_v51_council(
            "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
            "cpu32",
            fake_codex,
            config=Agent1CouncilConfig(planning_mode="normal", council_mode="group_session"),
        )
    finally:
        set_runtime_event_sink(None)

    retry_trace = [json.loads(line) for line in result["artifacts"]["agent1_group_retry_trace.jsonl"].splitlines()]
    skipped_retries = [event for event in events if event.get("type") == "agent1_group_retry" and event.get("status") == "skipped"]

    assert result["status"] == "HITL_REQUIRED"
    assert calls_by_group["M04"] == 1
    assert retry_trace == []
    assert skipped_retries
    assert skipped_retries[-1]["reason"] == "codex_infra_failure"

def test_agent1_v71_group_session_infra_hard_stop_skips_remaining_groups():
    calls_by_group: dict[str, int] = {}

    def fake_codex(prompt):
        for group_id in ("M01", "M02", "M03"):
            if f"Group Session {group_id}" in prompt:
                calls_by_group[group_id] = calls_by_group.get(group_id, 0) + 1
                raise RuntimeError("Agent 1 Codex API unavailable at http://localhost:20128/v1: timed out")
        return Agent1CodexResult(content=_valid_response("ok"), evidence={"model": "mock", "total_tokens": 1})

    events = []
    set_runtime_event_sink(events.append)
    try:
        result = run_agent1_v51_council(
            "Design an RV32IMC SoC with secure boot, APB peripherals, SRAM, formal-first SVA plus cocotb",
            "secure_soc",
            fake_codex,
            config=Agent1CouncilConfig(
                planning_mode="normal",
                council_mode="group_session",
                max_concurrent_group_calls=1,
                group_infra_failure_hitl_threshold=2,
            ),
        )
    finally:
        set_runtime_event_sink(None)

    group_trace = [json.loads(line) for line in result["artifacts"]["agent1_group_session_trace.jsonl"].splitlines()]
    aborted = [record for record in group_trace if record.get("parse_status") == "infra_aborted"]
    issue_codes = [event.get("code") for event in events if event.get("type") == "debug_issue"]

    assert result["status"] == "HITL_REQUIRED"
    assert calls_by_group == {"M01": 1, "M02": 1}
    assert {record["manager_id"] for record in aborted} == {"M03", "M04", "M05", "M06", "M07"}
    assert "agent1_group_infra_hard_stop" in issue_codes

def test_agent1_v75_default_group_circuit_breaker_uses_two_group_budget():
    calls_by_group: dict[str, int] = {}

    def fake_codex(prompt):
        for group_id in ("M01", "M02", "M03"):
            if f"Group Session {group_id}" in prompt:
                calls_by_group[group_id] = calls_by_group.get(group_id, 0) + 1
                raise RuntimeError("Agent 1 Codex API unavailable at http://localhost:20128/v1: timed out")
        return Agent1CodexResult(content=_valid_response("ok"), evidence={"model": "mock", "total_tokens": 1})

    result = run_agent1_v51_council(
        "Design an APB4 sensor-control peripheral with lock registers, IRQ, formal-first SVA, and cocotb.",
        "sensor_ctrl",
        fake_codex,
        config=Agent1CouncilConfig(planning_mode="normal", council_mode="group_session"),
    )

    group_trace = [json.loads(line) for line in result["artifacts"]["agent1_group_session_trace.jsonl"].splitlines()]
    aborted = [record for record in group_trace if record.get("parse_status") == "infra_aborted"]

    assert result["status"] == "HITL_REQUIRED"
    assert calls_by_group == {"M01": 1, "M02": 1}
    assert {record["manager_id"] for record in aborted} == {"M03", "M04", "M05", "M06", "M07"}

def test_agent1_v71_unresolved_cross_group_challenge_blocks_release():
    def fake_codex(prompt):
        payload = json.loads(_valid_response("ok"))
        if "Group Session M04" in prompt:
            payload["internal_challenges"] = [
                {
                    "severity": "critical",
                    "source_expert_id": "L14",
                    "target_group_id": "M05",
                    "reason": "Formal coverage must prove register interrupt clear behavior.",
                    "proposed_resolution": "M05 must add SVA for IRQ clear.",
                    "resolution_status": "open",
                }
            ]
        return Agent1CodexResult(content=json.dumps(payload), evidence={"model": "mock", "total_tokens": 1})

    result = run_agent1_v51_council(
        "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
        "cpu32",
        fake_codex,
        config=Agent1CouncilConfig(planning_mode="normal", council_mode="group_session"),
    )
    matrix = json.loads(result["artifacts"]["agent1_cross_group_challenge_matrix.json"])

    assert result["status"] == "HITL_REQUIRED"
    assert matrix["unresolved_count"] == 1
    assert matrix["challenges"][0]["target_group_id"] == "M05"

def test_agent1_v71_group_session_hard_caps_m06_m07_unresolvable_pingpong():
    calls = []

    def hard_cap_codex(prompt):
        calls.append(prompt)
        payload = json.loads(_valid_response("hard cap pingpong"))
        payload["selected_architecture_candidate"] = {
            "summary": "APB CPU/security subsystem candidate retained while M06/M07 conflict remains open.",
            "primary_protocol": "APB",
            "external_peripherals": ["uart"],
            "cpu_width_bits": 32,
        }
        payload["requirements_preserved"] = True
        payload["plan_ready_candidate"] = True
        if "Group Session M06" in prompt:
            payload["summary"] = "M06 security rejects M07 memory-map exposure policy."
            payload["accepted_decisions"] = ["lock secret registers as privileged and non-readable"]
            payload["rejected_decisions"] = [
                {"target_group_id": "M07", "decision": "M07 maps OTP/debug registers as readable at user privilege"}
            ]
            payload["internal_challenges"] = [
                {
                    "severity": "critical",
                    "source_expert_id": "L21",
                    "target_group_id": "M07",
                    "reason": "M06 says security policy forbids readable OTP/debug windows in the memory map.",
                    "proposed_resolution": "M07 must remove user-readable secret/debug windows.",
                    "resolution_status": "open",
                }
            ]
        elif "Group Session M07" in prompt:
            payload["summary"] = "M07 memory-map contract rejects M06 security mask because firmware access breaks."
            payload["accepted_decisions"] = ["keep firmware-visible debug/OTP windows for boot diagnostics"]
            payload["rejected_decisions"] = [
                {"target_group_id": "M06", "decision": "M06 masks all OTP/debug registers from firmware"}
            ]
            payload["internal_challenges"] = [
                {
                    "severity": "critical",
                    "source_expert_id": "L23",
                    "target_group_id": "M06",
                    "reason": "M07 says the memory-map contract requires firmware-visible debug/OTP diagnostics.",
                    "proposed_resolution": "M06 must permit controlled firmware diagnostics.",
                    "resolution_status": "open",
                }
            ]
        return Agent1CodexResult(content=json.dumps(payload), evidence={"model": "mock", "total_tokens": 1})

    events = []
    set_runtime_event_sink(events.append)
    try:
        result = run_agent1_v51_council(
            "Generate a 32-bit CPU architecture using APB UART with secure boot, OTP, debug protection, and a locked memory map.",
            "security_memory_hardcap",
            hard_cap_codex,
            config=Agent1CouncilConfig(
                planning_mode="deep_planning",
                council_mode="group_session",
                min_iterations=3,
                max_iterations=3,
                max_concurrent_group_calls=2,
            ),
        )
    finally:
        set_runtime_event_sink(None)

    group_trace = [json.loads(line) for line in result["artifacts"]["agent1_group_session_trace.jsonl"].splitlines()]
    matrix = json.loads(result["artifacts"]["agent1_cross_group_challenge_matrix.json"])
    failed_challenge_events = [event for event in events if event.get("type") == "agent1_cross_group_challenge" and event.get("status") == "fail"]

    assert result["status"] == "HITL_REQUIRED"
    assert len(result["iterations"]) == 3
    assert [item["iteration"] for item in result["iterations"]] == [1, 2, 3]
    assert all(item["status"] == "conflict" for item in result["iterations"])
    assert all(item["unresolved_challenges"] for item in result["iterations"])
    assert len(calls) == planned_calls_per_iteration(Agent1CouncilConfig(council_mode="group_session")) * 3
    assert {item["manager_id"] for item in group_trace if item["manager_id"] in {"M06", "M07"}} == {"M06", "M07"}
    assert sum(1 for item in group_trace if item["manager_id"] == "M06") == 3
    assert sum(1 for item in group_trace if item["manager_id"] == "M07") == 3
    assert matrix["iteration"] == 3
    assert matrix["unresolved_count"] == 2
    assert {item["source_group_id"] for item in matrix["challenges"]} == {"M06", "M07"}
    assert {item["target_group_id"] for item in matrix["challenges"]} == {"M06", "M07"}
    assert len(failed_challenge_events) == 6
