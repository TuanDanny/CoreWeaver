import json

from debug_runners.test_agent6_wiki_isolated import render_agent6_docs, run_agent6_isolated
from semiconductor_swarm.contracts import SWARM_ARTIFACT_INDEX_V1, SWARM_TO_DOCS_AGENT_V1


def _docs_contract():
    index = {
        "contract_version": SWARM_ARTIFACT_INDEX_V1,
        "run_id": "run-agent6",
        "project_name": "demo",
        "created_at": "2026-01-01T00:00:00+00:00",
        "status": "partial",
        "agents": {"agent1": {"status": "pass"}, "agent2": {"status": "pass"}},
        "contracts": [{"key": "agent5_result_contract", "path": "contracts/agent5_result.json", "exists": False}],
        "artifacts": [
            {
                "trace_id": "rtl:demo_top.sv",
                "producer_agent": "agent2",
                "consumer_agents": ["agent3", "agent4", "agent5"],
                "contract_refs": ["agent2_to_agent3_contract"],
                "stage": "rtl",
                "name": "demo_top.sv",
                "path": "rtl/demo_top.sv",
                "exists": False,
            }
        ],
        "dependency_graph": [],
        "summary": {"stage_counts": {"rtl": 1}, "traceability_complete": True},
    }
    return {
        "contract_version": SWARM_TO_DOCS_AGENT_V1,
        "run_id": "run-agent6",
        "project_name": "demo",
        "artifact_index": index,
        "docs_requested": ["run_summary", "formal_proof_report", "traceability_matrix", "known_limitations"],
    }


def test_agent6_mock_consumes_contract_and_handles_missing_optional_results():
    pages = render_agent6_docs(_docs_contract())

    assert set(pages) == {"run_summary.md", "formal_proof_report.md", "traceability_matrix.md", "known_limitations.md"}
    assert "Status: not_available" in pages["formal_proof_report.md"]
    assert "not_available: contracts/agent5_result.json" in pages["known_limitations.md"]
    assert "rtl:demo_top.sv" in pages["traceability_matrix.md"]


def test_agent6_isolated_runner_writes_docs_from_contract_file_only(tmp_path):
    contract_path = tmp_path / "swarm_to_docs_agent.json"
    contract_path.write_text(json.dumps(_docs_contract(), indent=2), encoding="utf-8")

    written = run_agent6_isolated(contract_path, tmp_path / "docs")

    assert len(written) == 4
    assert (tmp_path / "docs" / "run_summary.md").is_file()
    assert "Project: demo" in (tmp_path / "docs" / "run_summary.md").read_text(encoding="utf-8")