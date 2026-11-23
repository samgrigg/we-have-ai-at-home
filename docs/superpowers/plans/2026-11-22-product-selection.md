# Product Selection Implementation Plan

> Execute inline using superpowers:executing-plans.

**Goal:** Suggest and remember purchasable Smith's products for existing grocery items.
**Architecture:** API-only Kroger catalog client, deterministic unit/matching logic,
persisted search snapshots and choices, authenticated browser selection.
**Tech Stack:** FastAPI, httpx, PostgreSQL, vanilla JavaScript.
**Spec:** docs/superpowers/specs/2026-11-22-product-selection-design.md

## Constraints
No cart APIs, orders, customer OAuth, automatic purchases or pantry mutations.
Credentials and token values must never appear in output. Store 70600153.

- [x] Unit/matching and mocked Kroger client tests, then implementation.
- [x] Migration/search/selection/preference endpoints with auth, stale and CSRF tests.
- [x] Browser product panel and saved choice display; regression and identity tests.
- [x] API-only Docker/Render configuration and documentation.
- [ ] Review, full tests, image build, read-only live catalog smoke and local restart.

## Verification results

- Full Python/PostgreSQL regression suite: 84 passed, using private temporary Unix-socket PostgreSQL schemas.
- Browser privacy/recovery, recipe and product rendering/stale-response checks passed.
- Ruff, formatting, JavaScript syntax and diff checks passed; source and wheel builds passed.
- Live Smith’s API smoke verified matching and whole-package recommendations.
- Live catalog plus authenticated API search, selection, replay, attribution and preference smoke passed in a disposable synthetic schema.
- Independent review findings (container counts, prepared substitutes, nut butter and promo/malformed data) resolved and rechecked.
- Docker engine is unresponsive. Image build and local restart remain pending Docker recovery; existing app data/volumes were not changed.
- No Render configuration changes or deployment performed for this feature. No cart functionality added.
