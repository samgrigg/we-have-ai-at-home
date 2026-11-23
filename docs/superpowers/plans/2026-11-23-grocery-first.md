# Grocery-first Bridget Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task in the current session. Steps use checkbox syntax for tracking.

**Goal:** Make the shared grocery list Bridget’s main workspace, with semantic commands and optional chat.

**Architecture:** Retain FastAPI, PostgreSQL and the LangGraph worker. Add list mutation routes and a private, dedicated command conversation. Separate grocery controls and command state from existing chat state in the browser.

**Tech Stack:** Python 3.12+, FastAPI, psycopg, plain JavaScript, HTML, CSS, pytest and Node.

**Spec:** docs/superpowers/specs/2026-11-23-grocery-first-design.md

## Global constraints

- Preserve accounts, private chat ownership, family sharing and existing list data.
- No new frontend framework or generalized app/plugin registry is required.
- No ordering, checkout, or pantry replenishment is introduced.
- Direct item controls never require AI.
- Use original mid-century domestic styling: cream, appliance blue, teal and coral.
- Work in the current checkout if sandbox isolation cannot be established; do not deploy.

## Task 1: Persistent grocery actions and command identity

**Files:** Create migration 005_grocery_workspace.sql, src/household/groceries.py, tests/test_groceries.py. Modify api.py, tools.py, recipe_import.py, agent.py.

**Interfaces:** POST /api/grocery-commands returns the authenticated member’s dedicated private conversation. GET /api/shopping-list includes revision UUID and checked boolean. POST /api/shopping-list accepts {name}; PATCH /api/shopping-list accepts {name,revision,new_name?,checked?}; DELETE accepts {name,revision}.

- [ ] Write integration tests asserting direct add/check/edit/delete, stale revision rejection, delete/re-add fencing, rename conflicts, blank validation, CSRF/auth, command privacy and stable identity. For example: add milk; PATCH checked=true using its revision; repeat with the old revision and assert 409; delete/re-add and assert old revision still yields 409.
- [ ] Run `TEST_DATABASE_URL=postgresql://household:household-local-only@localhost:5433/household .venv/bin/pytest tests/test_groceries.py -q`; verify failures identify absent routes.
- [ ] Add checked BOOLEAN DEFAULT false and revision UUID DEFAULT gen_random_uuid(); create a BEFORE UPDATE trigger rotating revision for every write; add conversation purpose with a partial unique owner index. Add authenticated routes using the existing shared transaction lock. Normalize names via Items; recompute requirement metadata; delete stale product dependencies on rename; return 409 on revision or normalized-name conflict.
- [ ] Share add/reopen semantics through `add_grocery_item(conn,name,user_id)`: INSERT ON CONFLICT DO UPDATE SET checked=false only when checked=true. Use it from direct routes, tools and recipe confirmation. Read only active items in list_items and expose picked-up names separately. Brand the system prompt Bridget and document checked behavior.
- [ ] Add tests for picked-up reactivation by worker and recipe confirmation, migration idempotence and parallel command creation; run targeted grocery/account/recipe/product tests.

## Task 2: Grocery-first shell and direct controls

**Files:** Modify static/index.html, static/style.css, static/app.js, static/signin.html; create static/groceries.js and tests/grocery-browser.test.cjs.

**Interfaces:** groceries.js exposes renderGroceryItems(items), loadCommandConversation(), refreshCommands(), clearGroceryState(), setChatOpen(open). Existing app.js retains chat and calls these hooks.

- [ ] Write a Node VM test harness that evaluates both scripts and asserts grocery items can be checked/edited/removed through direct endpoints using revision tokens, with draft preservation on 409. Assert an unchanged poll does not discard an in-progress edit.
- [ ] Run `node tests/grocery-browser.test.cjs` and verify absent grocery rendering fails.
- [ ] Replace main layout with a spacious grocery workspace, command area, product details and picked-up section; put existing conversation navigation/transcript/composer in a hidden chat panel. Add responsive modal semantics, close/Escape controls, focus trap and restoration. Keep static script loading ordered so shared globals are initialized before hooks run.
- [ ] Implement safe DOM item rendering, native checkboxes, inline ingredient/quantity text editing, explicit removal and per-item errors. Preserve current editor during polls; on conflict refresh data and keep draft. Render keyed/signature-based rows rather than rebuilding focused controls every poll.
- [ ] Apply the user’s branding with an original SVG/CSS atomic mark, bold italic Bridget wordmark, cream paper-like list, blue/teal appliance controls and restrained coral accents. Use system fonts, no remote font dependencies. Update sign-in naming consistently.
- [ ] Run Node syntax and existing browser regressions; inspect with a real browser at desktop and mobile sizes.

## Task 3: Independent semantic commands and recipe previews

**Files:** Modify static/groceries.js, static/app.js, tests/grocery-browser.test.cjs, tests/browser.test.cjs.

**Interfaces:** Command requests retain existing POST /api/conversations/{cid}/messages schema. Session storage key household-command-pending is independent of household-pending. renderRecipes accepts an optional target and per-target signature/selection state.

- [ ] Add browser assertions for command submission while chat is closed, selected-chat changes not changing command cid, response/status visibility, retry request ID reuse, account-bound recovery, and recipe previews rendering into their originating surface.
- [ ] Run browser tests; confirm the added behavior initially fails.
- [ ] Initialize the command conversation idempotently after identity load. Submit commands independently of chat busy/pending; preserve failed submissions in session storage with owner/cid/request UUID; expose retry and keep-editing controls. Show latest actual response and active/failed job controls with safe text nodes. Retain command context for clarification.
- [ ] Poll command jobs and recipes separately from selected chat. Parameterize recipe rendering by target so signatures and checkbox selections remain isolated. Clear every command draft, recipe selection and response on identity change; fence late responses with identity epoch.
- [ ] Verify command/chat recovery coexist, Family chat privacy remains intact, and direct controls stay usable while AI work is queued.

## Task 4: Regression, visual QA and delivery

**Files:** README.md, design/plan status; test files as required by discovered regressions.

- [ ] Run full pytest suite against disposable test schemas, Ruff lint/format, both Node browser suites and JavaScript syntax checks.
- [ ] Use a browser with synthetic API responses for desktop/mobile visual QA without paid inference or family data. Check list-first hierarchy, panel focus/closure, long item text, picked-up items, empty state, recipe previews and errors. Fix observed issues and rerun affected checks only.
- [ ] Document direct grocery interactions, command privacy, check-off versus pantry boundary and migration requirements. Record actual verification results and any unavailable checks.
- [ ] Review final diff for scope, accidental secrets and private-state leaks. Leave code reviewable in this checkout; commit only if sandbox permits Git writes. No deployment is authorized.

## Plan self-review

All spec areas map to tasks: data/concurrency and agent behavior (1), list/shell/branding (2), command context/recovery/recipes (3), integration regressions and QA (4). Names and endpoint shapes are consistent. No new dependencies are required.

## Execution record — 2026-11-23

Tasks 1–3 implemented. Task 4 automated regression and documentation complete;
visual QA remains unverified. No deployment or commit was performed.

- PostgreSQL regression suite: 97 passed, using disposable schemas and synthetic identities.
- Node browser-state suites passed, including private state cleanup, retries,
  separate recipe surfaces, chat-failure independence, conflicts, and edit drafts
  surviving both related and unrelated check-off actions.
- Both JavaScript syntax checks, Ruff lint/format, and git diff --check passed.
- Independent review found draft loss during check-off; reproduced with failing
  tests and fixed. Subsequent focused review exposed the same-item variant, also
  reproduced and fixed with a passing regression.
- In-app browser could not reach the local synthetic preview; native-browser
  inspection failed in the tool. Desktop/mobile screenshots and real keyboard
  navigation have not been verified.
- Git index writes were blocked by the filesystem sandbox. Files remain in the
  existing feature checkout, uncommitted.
- The local ninth-house skill's prescribed review models (4.8 Fast and Claude
  Code 5.5) are unavailable in this runtime. That model-specific review was not
  performed; the independent code review above used the available agent runtime.
