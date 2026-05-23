import json
import threading
import time

from semiconductor_swarm.agents.agent1_planning.agent1_llm_client import Agent1CodexResult
from semiconductor_swarm.agents.agent1_planning.context_provider import build_agent1_context_package
from semiconductor_swarm.agents.agent1_planning.deep_expert_council import (
    LEAF_EXPERTS,
    MIDDLE_MANAGERS,
    Agent1CouncilConfig,
    cluster_map,
    execute_leaf_experts,
    execute_middle_tasking,
    execute_middle_managers,
    execute_principal_charter,
    execute_principal_architect,
    planned_calls_per_iteration,
    planned_minimum_calls,
    run_agent1_v51_council,
    topology_manifest,
    validate_topology,
)
from semiconductor_swarm.runtime_events import set_runtime_event_sink


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

    assert report["pass"], report["failures"]
    assert len(LEAF_EXPERTS) == 24
    assert len(MIDDLE_MANAGERS) == 7
    assert manifest["principal_architect"]["expert_id"] == "P01"
    assert manifest["max_concurrent_leaf_calls"] == 8
    assert manifest["max_concurrent_middle_calls"] == 4
    assert planned_calls_per_iteration() == 40


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
        config=Agent1CouncilConfig(planning_mode="normal"),
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
        config=Agent1CouncilConfig(planning_mode="normal", max_concurrent_middle_calls=3),
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
        config=Agent1CouncilConfig(planning_mode="normal"),
    )

    assert len(calls) == 40
    assert planned_minimum_calls(Agent1CouncilConfig(planning_mode="normal")) == 40
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
        config=Agent1CouncilConfig(planning_mode="normal"),
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
        config=Agent1CouncilConfig(planning_mode="normal"),
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
        config=Agent1CouncilConfig(planning_mode="normal"),
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
        config=Agent1CouncilConfig(planning_mode="deep_planning", min_iterations=3, max_iterations=3),
    )

    assert len(calls) == 120
    assert planned_minimum_calls(Agent1CouncilConfig(planning_mode="deep_planning", min_iterations=3)) == 120
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
        config=Agent1CouncilConfig(max_concurrent_leaf_calls=4),
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
        config=Agent1CouncilConfig(max_concurrent_leaf_calls=8),
    )

    assert len(records) == 24
    assert all(record["parse_status"] == "repair_failed_invalid_schema" for record in records)
    assert all(record["repair_attempted"] for record in records)
    assert all(any(conflict["type"] == "invalid_output_schema" for conflict in record["conflicts"]) for record in records)


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
        config=Agent1CouncilConfig(max_concurrent_middle_calls=3),
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
        config=Agent1CouncilConfig(planning_mode="deep_planning", min_iterations=3, max_iterations=4, max_concurrent_leaf_calls=8),
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
        config=Agent1CouncilConfig(planning_mode="deep_planning", min_iterations=3, max_iterations=5),
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
        config=Agent1CouncilConfig(planning_mode="deep_planning", min_iterations=3, max_iterations=5),
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
        config=Agent1CouncilConfig(planning_mode="normal"),
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
        config=Agent1CouncilConfig(planning_mode="normal"),
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
        config=Agent1CouncilConfig(planning_mode="normal"),
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
        config=Agent1CouncilConfig(planning_mode="normal"),
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
            config=Agent1CouncilConfig(planning_mode="normal", max_concurrent_leaf_calls=4, max_concurrent_middle_calls=3),
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
            config=Agent1CouncilConfig(planning_mode="normal", max_concurrent_leaf_calls=4, max_concurrent_middle_calls=3),
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
            config=Agent1CouncilConfig(planning_mode="normal", max_concurrent_leaf_calls=4, max_concurrent_middle_calls=3),
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
            config=Agent1CouncilConfig(planning_mode="normal"),
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
        config=Agent1CouncilConfig(planning_mode="normal"),
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
        config=Agent1CouncilConfig(planning_mode="deep_planning", min_iterations=3, max_iterations=3),
    )

    principal_prompts = [prompt for prompt in prompts if "Principal Architect" in prompt]
    assert len(principal_prompts) == 3
    assert "Previous principal and deterministic gate context" in principal_prompts[1]
    assert "previous_principal_decision" in principal_prompts[1]
    assert "previous_deterministic_gate_report" in principal_prompts[1]
