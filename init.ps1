$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "$PSScriptRoot\src;$env:PYTHONPATH"

python -m pytest -q tests
python scripts\harness_check.py --json
python scripts\run_benchmarks.py --cases benchmarks\cases --json
