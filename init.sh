#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/src:${PYTHONPATH:-}"

python -m pytest -q tests
python scripts/harness_check.py --json
python scripts/run_benchmarks.py --cases benchmarks/cases --json
