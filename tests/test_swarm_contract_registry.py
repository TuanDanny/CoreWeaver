import pytest

from semiconductor_swarm.contracts import (
    AGENT1_TO_AGENT2_V1,
    AGENT2_TO_AGENT3_V1,
    AGENT2_TO_AGENT4_V1,
    AGENT2_TO_AGENT5_V1,
    AGENT3_RESULT_V1,
    AGENT4_RESULT_V1,
    AGENT5_RESULT_V1,
    PLANNED_V1_CONTRACTS,
    SWARM_ARTIFACT_INDEX_V1,
    SWARM_TO_DOCS_AGENT_V1,
    ContractEnvelope,
    ContractValidationError,
    get_contract_schema,
    list_contracts,
    validate_contract,
)
from semiconductor_swarm.contracts.handoffs import (
    build_agent2_to_agent3_contract,
    build_agent2_to_agent4_contract,
    build_agent2_to_agent5_contract,
    build_agent_result_contract,
    build_swarm_artifact_index,
    build_swarm_to_docs_agent_contract,
    validate_agent2_to_agent3_contract,
)


def test_registry_lists_all_planned_v1_contracts():
    assert list_contracts() == PLANNED_V1_CONTRACTS
    assert set(list_contracts()) == {
        AGENT1_TO_AGENT2_V1,
        AGENT2_TO_AGENT3_V1,
        AGENT2_TO_AGENT4_V1,
        AGENT2_TO_AGENT5_V1,
        AGENT3_RESULT_V1,
        AGENT4_RESULT_V1,
        AGENT5_RESULT_V1,
        SWARM_ARTIFACT_INDEX_V1,
        SWARM_TO_DOCS_AGENT_V1,
    }


def test_every_planned_contract_has_loadable_schema_with_matching_const():
    for contract_version in list_contracts():
        schema = get_contract_schema(contract_version)
        assert schema["type"] == "object"
        assert schema["properties"]["contract_version"]["const"] == contract_version
        assert "contract_version" in schema["required"]


@pytest.mark.parametrize(
    ("contract_version", "payload"),
    [
        (
            AGENT1_TO_AGENT2_V1,
            {
                "contract_version": AGENT1_TO_AGENT2_V1,
                "project_name": "demo",
                "modules": [],
                "interfaces": [],
                "requirements": {},
            },
        ),
        (
            AGENT2_TO_AGENT3_V1,
            {
                "contract_version": AGENT2_TO_AGENT3_V1,
                "project_name": "demo",
                "rtl_files": [],
                "test_targets": [],
                "artifacts": [],
            },
        ),
        (
            AGENT2_TO_AGENT4_V1,
            {
                "contract_version": AGENT2_TO_AGENT4_V1,
                "project_name": "demo",
                "top_module": "demo_top",
                "rtl_files": [],
                "constraints": {},
            },
        ),
        (
            AGENT2_TO_AGENT5_V1,
            {
                "contract_version": AGENT2_TO_AGENT5_V1,
                "project_name": "demo",
                "rtl_files": [],
                "formal_targets": [],
                "properties_requested": [],
            },
        ),
        (
            AGENT3_RESULT_V1,
            {
                "contract_version": AGENT3_RESULT_V1,
                "project_name": "demo",
                "pass_fail_status": "not_run",
                "coverage_summary": {},
                "failures": [],
                "tool_availability": {},
                "commands": [],
                "artifacts": [],
            },
        ),
        (
            AGENT4_RESULT_V1,
            {
                "contract_version": AGENT4_RESULT_V1,
                "project_name": "demo",
                "backend_used": "none",
                "pass_fail_status": "not_run",
                "timing_summary": {},
                "resource_summary": {},
                "constraints_generated": [],
                "commands": [],
                "tool_availability": {},
                "artifacts": [],
            },
        ),
        (
            AGENT5_RESULT_V1,
            {
                "contract_version": AGENT5_RESULT_V1,
                "project_name": "demo",
                "formal_targets": [],
                "properties_generated": [],
                "proof_results": [],
                "counterexamples": [],
                "engines": [],
                "bounded_depth": 0,
                "commands": [],
                "tool_availability": {},
                "artifacts": [],
            },
        ),
        (
            SWARM_ARTIFACT_INDEX_V1,
            {
                "contract_version": SWARM_ARTIFACT_INDEX_V1,
                "run_id": "run-1",
                "project_name": "demo",
                "created_at": "2026-01-01T00:00:00+00:00",
                "status": "partial",
                "agents": {},
                "contracts": [],
                "artifacts": [],
                "dependency_graph": [],
                "summary": {},
            },
        ),
        (
            SWARM_TO_DOCS_AGENT_V1,
            {
                "contract_version": SWARM_TO_DOCS_AGENT_V1,
                "run_id": "run-1",
                "project_name": "demo",
                "artifact_index": {},
                "docs_requested": [],
            },
        ),
    ],
)
def test_validate_contract_accepts_minimal_valid_payloads(contract_version, payload):
    assert validate_contract(contract_version, payload) is True


def test_validate_contract_rejects_missing_required_field():
    with pytest.raises(ContractValidationError, match="missing required field"):
        validate_contract(AGENT1_TO_AGENT2_V1, {"contract_version": AGENT1_TO_AGENT2_V1})


def test_validate_contract_rejects_const_mismatch():
    payload = {
        "contract_version": "wrong/v1",
        "project_name": "demo",
        "modules": [],
        "interfaces": [],
        "requirements": {},
    }
    with pytest.raises(ContractValidationError, match="invalid const"):
        validate_contract(AGENT1_TO_AGENT2_V1, payload)


def test_validate_contract_rejects_unexpected_top_level_field_when_schema_closes_object(tmp_path, monkeypatch):
    schema_path = tmp_path / "closed.schema.json"
    schema_path.write_text(
        """
        {
          "type": "object",
          "required": ["contract_version"],
          "additionalProperties": false,
          "properties": {
            "contract_version": {"type": "string", "const": "closed/v1"}
          }
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setitem(__import__("semiconductor_swarm.contracts.registry", fromlist=["SCHEMA_FILES"]).SCHEMA_FILES, "closed/v1", schema_path)
    __import__("semiconductor_swarm.contracts.registry", fromlist=["get_contract_schema"]).get_contract_schema.cache_clear()

    with pytest.raises(ContractValidationError, match="unexpected field"):
        validate_contract("closed/v1", {"contract_version": "closed/v1", "extra": True})


def test_validate_contract_rejects_nested_required_field_when_schema_defines_items(tmp_path, monkeypatch):
    schema_path = tmp_path / "nested.schema.json"
    schema_path.write_text(
        """
        {
          "type": "object",
          "required": ["contract_version", "items"],
          "properties": {
            "contract_version": {"type": "string", "const": "nested/v1"},
            "items": {
              "type": "array",
              "items": {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}}
              }
            }
          }
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setitem(__import__("semiconductor_swarm.contracts.registry", fromlist=["SCHEMA_FILES"]).SCHEMA_FILES, "nested/v1", schema_path)
    __import__("semiconductor_swarm.contracts.registry", fromlist=["get_contract_schema"]).get_contract_schema.cache_clear()

    with pytest.raises(ContractValidationError, match=r"missing required field: \$\.items\[0\]\.name"):
        validate_contract("nested/v1", {"contract_version": "nested/v1", "items": [{}]})


def test_contract_envelope_round_trip():
    envelope = ContractEnvelope(
        contract_version=AGENT1_TO_AGENT2_V1,
        payload={"contract_version": AGENT1_TO_AGENT2_V1},
        producer="agent1",
        consumer="agent2",
        run_id="run-1",
    )
    restored = ContractEnvelope.from_dict(envelope.to_dict())
    assert restored == envelope


def _golden_spec_and_rtl():
    spec = {
        "project_name": "demo",
        "top_module": "demo_top",
        "ip_blocks": [{"name": "timer"}],
        "clock_domains": [{"clock": "clk_i", "reset": "rst_ni", "frequency_mhz": 125}],
        "target_backend": "quartus",
    }
    rtl_files = [
        {"filename": "timer_pkg.sv", "language": "systemverilog"},
        {"filename": "timer_intf.sv", "language": "systemverilog"},
        {"filename": "timer.sv", "language": "systemverilog"},
        {"filename": "demo_top.sv", "language": "systemverilog"},
        {"filename": "notes.md", "language": "markdown"},
    ]
    return spec, rtl_files


def test_agent2_fanout_contract_builders_emit_valid_semantic_payloads():
    spec, rtl_files = _golden_spec_and_rtl()

    a23 = build_agent2_to_agent3_contract(spec, rtl_files)
    a24 = build_agent2_to_agent4_contract(spec, rtl_files)
    a25 = build_agent2_to_agent5_contract(spec, rtl_files)

    assert a23["contract_version"] == AGENT2_TO_AGENT3_V1
    assert a24["contract_version"] == AGENT2_TO_AGENT4_V1
    assert a25["contract_version"] == AGENT2_TO_AGENT5_V1
    assert a23["compile_order"] == ["timer_pkg.sv", "timer_intf.sv", "timer.sv", "demo_top.sv"]
    assert a24["target_backend"] == "quartus"
    assert a25["bounded_depth"] == 20
    assert all(file["language"] == "systemverilog" for file in a23["rtl_files"])


def test_agent2_to_agent3_semantic_validator_rejects_missing_top_file():
    payload = {
        "contract_version": AGENT2_TO_AGENT3_V1,
        "project_name": "demo",
        "top_module": "demo_top",
        "rtl_files": [{"filename": "timer.sv", "language": "systemverilog"}],
        "compile_order": ["timer.sv"],
        "test_targets": ["timer", "demo_top"],
        "clock_constraints": {"frequency_mhz": 100},
        "artifacts": [],
    }
    with pytest.raises(ContractValidationError, match="top_module file missing"):
        validate_agent2_to_agent3_contract(payload)


def test_agent_result_contract_builder_emits_schema_valid_result_contracts():
    artifacts = [{"filename": "fv_timer.sv", "language": "systemverilog"}, {"filename": "timer.sby"}]

    dv = build_agent_result_contract(AGENT3_RESULT_V1, "demo", "agent3", True, artifacts, {"coverage_summary": {"line": 100}, "commands": ["pytest"]})
    phy = build_agent_result_contract(AGENT4_RESULT_V1, "demo", "agent4", True, artifacts, {"backend_used": "quartus", "metrics": {"fmax_mhz": 150}})
    fv = build_agent_result_contract(AGENT5_RESULT_V1, "demo", "agent5", True, artifacts, {"bounded_depth": 32})

    assert dv["pass"] is True and dv["pass_fail_status"] == "pass"
    assert phy["backend_used"] == "quartus" and phy["timing_summary"]["fmax_mhz"] == 150
    assert fv["bounded_depth"] == 32 and fv["formal_targets"] == ["timer"]


def test_swarm_artifact_index_builder_emits_agent6_ready_index():
    state = {
        "run_id": "run-42",
        "rtl_files": [{"filename": "demo_top.sv", "language": "systemverilog"}],
        "dv_files": [{"filename": "tb_demo.sv", "language": "systemverilog"}],
        "agent3_result_contract": {"pass": True},
        "agent4_result_contract": {"pass": True},
        "agent5_result_contract": {"pass": True},
        "reports": {"summary": "ok"},
    }

    index = build_swarm_artifact_index("demo", state)

    assert index["contract_version"] == SWARM_ARTIFACT_INDEX_V1
    assert index["run_id"] == "run-42"
    assert index["status"] == "pass"
    assert index["summary"]["artifact_count"] == 2
    assert index["summary"]["stage_counts"] == {"rtl": 1, "dv": 1, "formal": 0, "physical": 0}
    assert index["artifacts"][0]["trace_id"] == "rtl:demo_top.sv"
    assert index["artifacts"][0]["producer_agent"] == "agent2"
    assert index["artifacts"][0]["consumer_agents"] == ["agent3", "agent4", "agent5"]
    assert index["artifacts"][0]["path"] == "rtl/demo_top.sv"
    assert index["artifacts"][0]["sha256"] is None
    assert index["artifacts"][0]["exists"] is False
    assert "agent3_result_contract" in index["artifacts"][1]["contract_refs"]
    assert {edge["to"] for edge in index["dependency_graph"]} == {"agent3_result_contract", "agent4_result_contract", "agent5_result_contract", "swarm_artifact_index"}


def test_swarm_to_docs_agent_contract_wraps_artifact_index():
    index = build_swarm_artifact_index("demo", {"run_id": "run-docs"})

    payload = build_swarm_to_docs_agent_contract("demo", index)

    assert payload["contract_version"] == SWARM_TO_DOCS_AGENT_V1
    assert payload["run_id"] == "run-docs"
    assert payload["artifact_index"] == index
    assert "traceability_matrix" in payload["docs_requested"]


def test_write_outputs_persists_contracts_index_and_agent6_docs_input(tmp_path):
    pytest.importorskip("langgraph")
    from semiconductor_swarm.swarm_graph import write_outputs

    spec, rtl_files = _golden_spec_and_rtl()
    rtl_files = [dict(file, content=f"// {file['filename']}\n") for file in rtl_files if file["language"] == "systemverilog"]
    a23 = build_agent2_to_agent3_contract(spec, rtl_files)
    a24 = build_agent2_to_agent4_contract(spec, rtl_files)
    a25 = build_agent2_to_agent5_contract(spec, rtl_files)
    dv_contract = build_agent_result_contract(AGENT3_RESULT_V1, "demo", "agent3", True, [{"filename": "tb_demo.sv", "content": "// tb\n", "language": "systemverilog"}], {"coverage_summary": {}, "commands": []})
    phy_contract = build_agent_result_contract(AGENT4_RESULT_V1, "demo", "agent4", True, [{"filename": "demo.sdc", "content": "create_clock\n", "language": "sdc"}], {"backend_used": "quartus", "metrics": {}})
    fv_contract = build_agent_result_contract(AGENT5_RESULT_V1, "demo", "agent5", True, [{"filename": "fv_timer.sv", "content": "// fv\n", "language": "systemverilog"}], {"bounded_depth": 20})

    write_outputs(
        {
            "spec": spec,
            "project_name": "demo",
            "rtl_files": rtl_files,
            "dv_files": [{"filename": "tb_demo.sv", "content": "// tb\n", "language": "systemverilog"}],
            "physical_files": [{"filename": "demo.sdc", "content": "create_clock\n", "language": "sdc"}],
            "formal_files": [{"filename": "fv_timer.sv", "content": "// fv\n", "language": "systemverilog"}],
            "agent2_to_agent3_contract": a23,
            "agent2_to_agent4_contract": a24,
            "agent2_to_agent5_contract": a25,
            "agent3_result_contract": dv_contract,
            "agent4_result_contract": phy_contract,
            "agent5_result_contract": fv_contract,
            "reports": {"agent2": {"pass": True}, "agent3": {"pass": True}, "agent4": {"pass": True}, "agent5": {"pass": True}},
            "status": "SIGNOFF_READY",
        },
        tmp_path,
    )

    index = __import__("json").loads((tmp_path / "contracts" / "swarm_artifact_index.json").read_text(encoding="utf-8"))
    docs = __import__("json").loads((tmp_path / "contracts" / "swarm_to_docs_agent.json").read_text(encoding="utf-8"))
    assert (tmp_path / "contracts" / "agent2_to_agent3.json").is_file()
    assert (tmp_path / "swarm_artifact_index.json").is_file()
    assert index["summary"]["traceability_complete"] is True
    assert all(item["exists"] for item in index["artifacts"])
    assert all(contract["exists"] for contract in index["contracts"])
    assert docs["artifact_index"] == index
