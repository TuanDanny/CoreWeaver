## Summary

- 

## Checks

- [ ] `python -m pytest -q tests`
- [ ] `python scripts/harness_check.py --json`
- [ ] `python scripts/run_benchmarks.py --cases benchmarks/cases --json`
- [ ] `npm run test --prefix studio/frontend` if Studio/frontend changed
- [ ] `npm run build --prefix studio/frontend` if Studio/frontend changed

## Safety

- [ ] No secrets, private plans, generated outputs, Studio build output, or local settings are committed.
- [ ] Agent outputs remain typed, traceable, replayable, and gate-checked.
- [ ] Agent2 handoff remains blocked unless Agent1 signoff and handoff gates pass.

## Reviewer Notes

- 
