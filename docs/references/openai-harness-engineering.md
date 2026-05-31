# OpenAI Harness Engineering Reference

Source: https://openai.com/index/harness-engineering/

## Local Interpretation
CoreWeaver should optimize the working environment around the agent:
- Maintain repo-local knowledge.
- Make app state, logs, traces, and outputs legible.
- Keep architecture constraints executable.
- Build feedback loops through tests, evals, and review gates.
- Clean entropy before it accumulates.

This repo implements that as `src/coreweaver/harness/` before rebuilding Agent1.
