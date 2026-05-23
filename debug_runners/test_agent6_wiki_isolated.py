"""Agent 6 Wiki/Docs isolated mock runner.

Phase 6 proof: consume only stable swarm contracts, emit docs/wiki pages, and
print AGENT6_WIKI_ISOLATED_PASS project=<project_name> docs=<count>.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from semiconductor_swarm.contracts import SWARM_ARTIFACT_INDEX_V1, SWARM_TO_DOCS_AGENT_V1, validate_contract


DOCS = {
    "run_summary": "run_summary.md",
    "architecture_summary": "architecture_summary.md",
    "rtl_module_index": "rtl_module_index.md",
    "dv_report": "dv_report.md",
    "physical_signoff_report": "physical_signoff_report.md",
    "formal_proof_report": "formal_proof_report.md",
    "traceability_matrix": "traceability_matrix.md",
    "known_limitations": "known_limitations.md",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_status(value: Any) -> str:
    return str(value or "not_available")


def _agent_status(index: dict[str, Any], agent: str) -> str:
    agents = index.get("agents", {})
    if not isinstance(agents, dict):
        return "not_available"
    item = agents.get(agent, {})
    return _safe_status(item.get("status") if isinstance(item, dict) else None)


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join([head, sep, *body]) + "\n"


def render_agent6_docs(docs_contract: dict[str, Any]) -> dict[str, str]:
    validate_contract(SWARM_TO_DOCS_AGENT_V1, docs_contract)
    index = docs_contract.get("artifact_index", {})
    validate_contract(SWARM_ARTIFACT_INDEX_V1, index)

    project = docs_contract.get("project_name", "unknown")
    run_id = docs_contract.get("run_id", "unknown")
    requested = docs_contract.get("docs_requested") or list(DOCS)
    artifacts = index.get("artifacts", []) if isinstance(index.get("artifacts", []), list) else []
    contracts = index.get("contracts", []) if isinstance(index.get("contracts", []), list) else []
    summary = index.get("summary", {}) if isinstance(index.get("summary", {}), dict) else {}

    rendered: dict[str, str] = {}
    for doc in requested:
        if doc == "run_summary":
            rendered[DOCS[doc]] = f"# Run Summary\n\nProject: {project}\n\nRun: {run_id}\n\nStatus: {index.get('status', 'not_available')}\n\nArtifacts: {len(artifacts)}\n\nContracts: {len(contracts)}\n"
        elif doc == "traceability_matrix":
            rows = [[a.get("trace_id", "not_available"), a.get("producer_agent", "not_available"), a.get("path", "not_available"), ",".join(a.get("contract_refs", []) or []) or "not_available"] for a in artifacts]
            rendered[DOCS[doc]] = "# Traceability Matrix\n\n" + _md_table(["Trace ID", "Producer", "Path", "Contracts"], rows)
        elif doc == "known_limitations":
            missing = [c.get("path", c.get("key", "unknown")) for c in contracts if not c.get("exists", False)]
            rendered[DOCS[doc]] = "# Known Limitations\n\n" + ("\n".join(f"- not_available: {item}" for item in missing) if missing else "- none\n")
        elif doc in {"dv_report", "physical_signoff_report", "formal_proof_report"}:
            agent = {"dv_report": "agent3", "physical_signoff_report": "agent4", "formal_proof_report": "agent5"}[doc]
            rendered[DOCS[doc]] = f"# {doc.replace('_', ' ').title()}\n\nStatus: {_agent_status(index, agent)}\n"
        elif doc == "rtl_module_index":
            rtl = [a for a in artifacts if a.get("stage") == "rtl"]
            rows = [[a.get("name", "not_available"), a.get("path", "not_available"), a.get("exists", False)] for a in rtl]
            rendered[DOCS[doc]] = "# RTL Module Index\n\n" + _md_table(["Name", "Path", "Exists"], rows)
        elif doc == "architecture_summary":
            rendered[DOCS[doc]] = f"# Architecture Summary\n\nProject: {project}\n\nStage counts: {summary.get('stage_counts', 'not_available')}\n"
    return rendered


def run_agent6_isolated(contract_path: Path, output_dir: Path) -> dict[str, Path]:
    docs_contract = _load_json(contract_path)
    pages = render_agent6_docs(docs_contract)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name, content in pages.items():
        path = output_dir / name
        path.write_text(content, encoding="utf-8")
        written[name] = path
    return written


def _mock_contract() -> dict[str, Any]:
    index = {
        "contract_version": SWARM_ARTIFACT_INDEX_V1,
        "run_id": "agent6-isolated-run",
        "project_name": "agent6_demo",
        "created_at": "2026-01-01T00:00:00+00:00",
        "status": "partial",
        "agents": {"agent1": {"status": "pass"}, "agent2": {"status": "pass"}, "agent3": {"status": "not_available"}, "agent4": {"status": "not_available"}, "agent5": {"status": "not_available"}},
        "contracts": [{"key": "agent3_result_contract", "path": "contracts/agent3_result.json", "exists": False}],
        "artifacts": [{"trace_id": "rtl:demo_top.sv", "producer_agent": "agent2", "consumer_agents": ["agent3", "agent4", "agent5"], "contract_refs": ["agent2_to_agent3_contract"], "stage": "rtl", "name": "demo_top.sv", "path": "rtl/demo_top.sv", "exists": False}],
        "dependency_graph": [],
        "summary": {"artifact_count": 1, "contract_count": 1, "stage_counts": {"rtl": 1}, "traceability_complete": True},
    }
    return {"contract_version": SWARM_TO_DOCS_AGENT_V1, "run_id": "agent6-isolated-run", "project_name": "agent6_demo", "artifact_index": index, "docs_requested": list(DOCS)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--out", type=Path, default=Path("outputs/agent6_wiki_isolated/docs"))
    args = parser.parse_args()

    if args.contract is None:
        with tempfile.TemporaryDirectory() as tmp:
            contract_path = Path(tmp) / "swarm_to_docs_agent.json"
            contract_path.write_text(json.dumps(_mock_contract(), indent=2), encoding="utf-8")
            written = run_agent6_isolated(contract_path, args.out)
    else:
        written = run_agent6_isolated(args.contract, args.out)

    project = _load_json(args.contract)["project_name"] if args.contract else "agent6_demo"
    print(f"AGENT6_WIKI_ISOLATED_PASS project={project} docs={len(written)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())