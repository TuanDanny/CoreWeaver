# Benchmarks

Framework runner executes public, non-secret Agent1 smoke and mutation cases
through `mock_swarm`. Cases are validated against
`benchmarks/schemas/benchmark_case.schema.json`; datasheet-backed private cases
can be added locally later.

Run:

```bash
python scripts/run_benchmarks.py --cases benchmarks/cases
```
