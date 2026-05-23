---
title: Stale Docs Policy
status: active
owner: docs-governance
type: governance
last_reviewed: 2026-05-17
source_of_truth: true
---

# Stale Docs Policy

## Stale Signals
- Broken links.
- Missing frontmatter.
- Old `last_reviewed` date.
- Product spec disagrees with tests/code.
- Legacy plan looks active but lacks index entry.

## Stale Handling
- Prefer update over delete.
- If superseded, add pointer to replacement doc.
- If historical, mark in legacy docs index.
- If duplicate prompt, keep only index pointer unless migration approved.

## Review Cadence
- Review source-of-truth docs when changing related code.
- Review all active plans before major releases.
- Review legacy docs during migration phases.
