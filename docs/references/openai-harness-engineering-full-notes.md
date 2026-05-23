---
title: OpenAI Harness Engineering Full Notes
status: active
owner: docs-governance
type: reference
last_reviewed: 2026-05-20
source_of_truth: false
external_url: https://openai.com/index/harness-engineering/
capture_level: official-live-summary
---

# OpenAI Harness Engineering Full Notes

## Source
External article: https://openai.com/index/harness-engineering/

## Capture Rule
This file records local, non-verbatim implementation notes from the official article. It does not mirror article text and remains a reference, not a semiconductor source of truth.

## Practical Principles Applied
- Repository knowledge is the durable system of record.
- Agents should receive a concise map rather than a long manual.
- `AGENTS.md` should stay short and route to deeper files.
- Deeper knowledge belongs in structured documentation.
- Documentation should be maintainable and checkable.
- Prompt/context sources should be explicit and stable.
- Source-of-truth order should be clear.
- Plans and execution state should be versioned, with active/completed/superseded routes unambiguous.
- Legacy knowledge should be preserved until migrated or marked superseded.
- Checks/evals should protect agent behavior from docs drift.
- Generated/manual indexes must not become trusted stale maps.
- Task context should be recoverable from repo files without relying on chat history.
- Docs cleanup should be recurring and cheap enough to run often.
- Runtime prompts/code should not be changed by documentation compliance work unless separately approved.

## Non-Binding Rule
This reference does not override code, tests, product specs, prompt contracts, or semiconductor workflow constraints.
