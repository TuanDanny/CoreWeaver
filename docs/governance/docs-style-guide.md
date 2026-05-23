---
title: Docs Style Guide
status: active
owner: docs-governance
type: governance
last_reviewed: 2026-05-17
source_of_truth: true
---

# Docs Style Guide

## Required Frontmatter
Every maintained Markdown doc under `docs/` should start with YAML frontmatter:

```yaml
---
title: Short Title
status: active
owner: docs-governance
type: design|product-spec|exec-plan|prompt|generated|reference|governance|agent-task-card
last_reviewed: YYYY-MM-DD
source_of_truth: true|false
---
```

## Writing Rules
- Keep top-level map files short.
- Prefer bullets, tables, and checklists.
- Put decisions in exec plans.
- Put stable contracts in product specs.
- Put process rules in governance docs.
- Put routing metadata in `docs/knowledge-map.yaml`.

## File Naming
- Use lowercase kebab-case for new docs.
- Keep legacy filenames for compatibility.
- Do not create duplicate canonical prompt files.

## Links
- Use repo-relative paths.
- Link to source-of-truth docs, not screenshots or chat.
- Keep indexes updated when adding docs.

## Done Criteria For Docs Changes
- Frontmatter exists.
- Index updated.
- Related plan updated.
- Docs health check passes.
