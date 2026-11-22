# Recipe Import Implementation Plan

> Execute inline using superpowers:executing-plans.

**Goal:** Paste a recipe URL and confirm selected ingredients onto the shared list.
**Architecture:** Pinned HTTPS reader, bounded JSON-LD parser, persisted recipe drafts,
LangGraph read/prepare tools and access-checked browser confirmation.
**Tech Stack:** Python standard library, PostgreSQL, FastAPI, LangGraph, JavaScript.
**Spec:** docs/superpowers/specs/2026-11-22-recipe-import-design.md

## Constraints
No arbitrary network access, no list additions before authenticated confirmation,
no credential/page-content logging, no quantity merging or persistent pantry.

- [x] Write failing extraction, fetch security and scaling tests; implement recipes.py.
- [x] Add migration, recipe read/prepare tools, receipts and mutation guard; verify replay.
- [x] Add authorized preview/confirmation endpoints and atomic additions; test access and CSRF.
- [x] Add preview checkboxes/source/overlap display to browser; verify stale response fencing.
- [x] Review, full regression checks, Docker build and local smoke; document limitations.

## Validation

67 Python tests passed, plus the browser privacy/recovery and recipe-preview checks.
Ruff, formatting, JavaScript syntax and diff checks passed. Docker images built and
a container smoke test verified migration, preview, omission, confirmation replay,
attribution and public recipe fetching in an isolated schema. A real Budget Bytes
recipe returned eight ingredients from both host and container. Review findings
were resolved and rechecked. Local app restarted with additive migration; Render
remains on the account release. No paid model calls were needed for validation.
