# Household POC Implementation Plan

> **For agentic workers:** Execute inline using superpowers:executing-plans. Steps use checkboxes for tracking.

**Goal:** Deliver persistent conversational shopping-list management.

**Architecture:** FastAPI accepts durable requests; a separate LangGraph worker claims
them using PostgreSQL locks. A plain browser client polls authenticated endpoints.

**Tech Stack:** Python 3.12+, FastAPI, psycopg, LangGraph, langchain-openai, pytest.

**Spec:** `docs/superpowers/specs/2026-11-21-household-poc-design.md`

## Global Constraints

- One household and one shared password; HTTPS for public deployments.
- PostgreSQL is the source of truth; no in-memory production queue.
- No voice, SMS, calendar, allowance, or real money integration.
- External action replay must not duplicate effects.

### Task 1: Persistence and API

Files: `pyproject.toml`, `src/household/config.py`, `db.py`, `api.py`, `schema.sql`, `tests/test_poc.py`.
Interfaces: `Database.connect()`, `Database.setup()`, `create_app(settings)`.

- [x] Write integration tests for authentication, conversation persistence,
  request UUID deduplication, conflicting reuse, and single unfinished request.
- [x] Confirm missing implementation import; initial test run also identified missing database setup.
- [x] Implement schema with foreign keys, job states, and parameterized queries;
  return HTTP 409 for conflicting UUIDs or unfinished conversations.
- [x] Rerun tests against a real PostgreSQL database.

### Task 2: Agent and worker

Files: `src/household/agent.py`, `worker.py`, `tests/test_poc.py`.
Interfaces: `build_graph(db, job, model, checkpointer)`, `run_once(db, model=None)`.

- [x] Add behavioral tests using scripted model responses through the real graph:
  shared lists, removal, replay, crash recovery, failed jobs and explicit retries.
- [x] Observe regression failures for empty-answer retry and lost lock connection before fixing them.
- [x] Implement tool validation, transactional receipts, per-job checkpoints,
  conversation advisory locks, failure state, and usage aggregation.
- [x] Verify tests, including lock exclusion and a resumed checkpoint.

### Task 3: Browser and operations

Files: `src/household/static/index.html`, `app.js`, `style.css`, `Dockerfile`,
`compose.yaml`, `.env.example`, `.gitignore`, `README.md`.

- [x] Add endpoint tests for the UI and persisted conversation/job retrieval.
- [x] Build browser chat with selectable conversations, pending/error/retry states,
  shopping-list panel, and request UUID reuse on network failure.
- [x] Add database initialization CLI, container commands and deployment instructions.
- [x] Run complete tests, linter, Compose validation and HTTP smoke checks.
- [x] Record which checks require credentials or cloud provisioning.

## Execution notes

No repository or existing source was present initially. The selected GitHub remote
is `https://github.com/samgrigg/we-have-ai-at-home`; the selected Render workspace
is `griggware`. Docker Desktop did not respond to daemon
queries, so integration tests used a disposable PostgreSQL server under `/tmp`.
Compose configuration validated, and source/wheel builds succeeded. The selected
host is Render; `render.yaml` passed current published JSON Schema validation.
Render CLI is not installed, so platform-aware CLI validation remains outstanding.
Container image build/start, live-model inference and hosted deployment are not
yet verified. Deployment requires pushing source, reviewing the Render resource
plan, and supplying the model credential through Render's secret configuration.

Independent review found frontend resend/empty-conversation issues, terminal-empty
response recovery, and a lost-lock-connection race. Regression tests reproduced these
before fixes. All durable worker writes now use the claim connection, with synchronous
checkpoints. Browser tests also cover a conflicting submission from another tab.
