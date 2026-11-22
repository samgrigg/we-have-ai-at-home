# Family Accounts Implementation Plan

> **For agentic workers:** Execute inline using superpowers:executing-plans.

**Goal:** Google-authenticated personal chats and a shared family chat for five approved identities.
**Architecture:** Google OIDC establishes identity; opaque database sessions protect FastAPI endpoints. Conversation ownership is checked on every route and worker run. Existing conversations become a read-only archive; the approved disposable shopping list is reset once by migration.
**Tech Stack:** FastAPI, Authlib, PostgreSQL migrations, LangGraph, plain JavaScript.
**Spec:** `docs/superpowers/specs/2026-11-21-family-accounts-design.md`

## Global Constraints
- Five configured approved email addresses; no actual addresses or credentials committed.
- Private chat ownership never inferred from prompts or trusted from request JSON.
- No Basic Auth fallback; Google credentials are API-only.
- Local verification precedes a real Google handshake and a reviewed maintenance-window deployment.

### Task 1: Schema and authentication
Files: `migrations/001_family_accounts.sql`, `db.py`, `config.py`, `auth.py`, `tests/test_auth.py`.
- [x] Write failing allowlist, stable-identity, session and old-schema migration tests.
- [x] Introduce transactional numbered migrations; reset the disposable list once; archive old conversations and seed Family chat.
- [x] Implement maintained-library OIDC, opaque hashed sessions, CSRF, logout, expiration and allowlist revocation.
- [x] Verify against real PostgreSQL and controlled provider fixtures.

### Task 2: Authorization and agent context
Files: `api.py`, `worker.py`, `agent.py`, `tools.py`, `tests/conftest.py`, `tests/test_poc.py`, `tests/test_accounts.py`.
- [x] Write cross-account read/write/retry/deduplication isolation tests.
- [x] Apply owner checks and author attribution; enforce read-only archive.
- [x] Validate job author/visibility in worker and isolate loaded history.
- [x] Preserve recovery, replay receipts and the connection-lock regression tests.

### Task 3: Browser and deployment configuration
Files: `static/*`, `.env.example`, `compose.yaml`, `render.yaml`, `README.md`, `tests/browser.test.cjs`.
- [x] Implement login/logout, My chats/Family chat/POC archive, author labels and session-expiry clearing.
- [x] Update Docker and Render secret configuration without copying private credentials.
- [x] Run complete tests, lint, browser state tests, package build and container smoke checks.
- [x] Record actual Google handshake and hosted rollout as requiring external credentials; do not migrate the running hosted database automatically.

## Validation recorded

- 43 PostgreSQL/Python tests and 8 browser checks passed.
- Ruff, formatting, diff checks, wheel/source builds, and Docker image builds passed.
- Built image migrated an isolated schema and passed health, sign-in, and unauthorized-access smoke checks.
- Review findings resolved: stale account responses, empty logout response handling, and skipping failed shared jobs.
- Real Google sign-in verified locally by the household on November 22. Local migration and restart completed; hosted migration remains pending the maintenance cutover.
