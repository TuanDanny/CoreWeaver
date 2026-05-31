from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from coreweaver.agents.agent1.evidence_report import generate_agent1_evidence_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--profile", default="mock_swarm")
    parser.add_argument("--benchmark-case")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    benchmark_case = None
    if args.benchmark_case:
        benchmark_case = json.loads(Path(args.benchmark_case).read_text(encoding="utf-8"))
    report = generate_agent1_evidence_report(args.run_dir, profile=args.profile, benchmark_case=benchmark_case)
    payload = report.model_dump(mode="json")
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(payload["verdict"])
        print(payload["artifacts"]["report_path"])
    return 0 if report.verdict == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
