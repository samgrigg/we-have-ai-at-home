# Household assistant · POC

A browser conversation, a hosted-model LangGraph worker, and PostgreSQL.
The first capability is a household shopping list shared across conversations.

## Run locally

Requires Docker Desktop/Engine with Compose and an OpenAI API key with access to
the configured model. No API credentials are included or read from unrelated projects.

```sh
cp .env.example .env
# Edit .env: set HOUSEHOLD_PASSWORD and OPENAI_API_KEY.
docker compose up --build -d
```

Open [localhost:8000](http://localhost:8000). Sign in as `family` using
`HOUSEHOLD_PASSWORD`. This is a shared POC account: every user can read every
conversation. The application deliberately does not identify individual family members.
If port 8000 is occupied, set `API_PORT=8001` in `.env` and open localhost:8001 instead.

Try:

1. “Add milk and eggs to the shopping list.”
2. “What’s on the list?”
3. Start a new conversation; ask “Remove eggs.”
4. Refresh the page and select the previous conversation.
5. Restart the worker and API; check that the list and conversations remain.

```sh
docker compose restart api worker
docker compose logs --tail=50 worker
```

Stopping Compose preserves the named database volume. `docker compose down -v`
**deletes** the local database. The fixed local database credentials in Compose
are for this loopback-only development database, not cloud deployment.

## Python development

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --frozen
docker compose up postgres -d
uv run python -m household.db
uv run uvicorn household.api:create_app --factory --reload
# In another terminal:
uv run python -m household.worker
```

For debugging a stuck request, follow worker stage logs and inspect the saved job:

```sh
docker compose logs -f api worker
docker compose exec postgres psql -U household -d household -c \
  "SELECT id, status, attempts, error, updated_at FROM jobs ORDER BY sequence DESC LIMIT 10;"
```

Worker logs identify `job_started`, `model_started`, `model_finished`,
`tool_started`, `tool_finished`, and `job_completed`/`job_failed`. A job running
for 60 seconds emits thread stacks for diagnosis; this does not cancel it.
Structured JSON events add a correlated `job_id`, `stage`, elapsed milliseconds,
and success/error outcome around model calls, tools, individual SQL operations,
checkpoint loads/saves, conversation-history loading and final job persistence.
For example, `sql.receipt_save` identifies saving the tool's replay receipt.

While a request is running, a separate thread emits `job_progress` every five
seconds with total elapsed time and every active stage's elapsed time. Stages
lasting ten seconds trigger warning-level progress logs. Configure
`PROGRESS_LOG_SECONDS` and `SLOW_STAGE_SECONDS` in `.env`; recreate the worker
after changing them. These are diagnostics, not deadlines or automatic retries.
Prompts, shopping item names, SQL parameters, keys and exception messages are
excluded from the new timing events. Overlapping checkpoint operations can appear
as separate active stages because LangGraph persists work in background threads.

For Python breakpoints, stop the container worker and run the worker on the host
using the command above. The local `.env` database URL points to localhost:5433.
The Compose image has no source bind mount or automatic code reload; rebuild it
with `docker compose up --build -d` after changing Python code.

The API needs `DATABASE_URL` and `HOUSEHOLD_PASSWORD`; only the worker requires
`OPENAI_API_KEY`. Settings are read from environment variables or a local `.env`.
`MODEL_NAME` defaults to `gpt-4.1-mini` and can be changed to a compatible OpenAI
tool-calling model. Personality instructions live in `src/household/agent.py`.

## Verification

Tests run against real PostgreSQL, isolating every test in a temporary schema.
Use a disposable database with schema-creation permissions. They script model
responses, so tests consume no model credits and do not prove live model quality.

```sh
TEST_DATABASE_URL=postgresql://household:household-local-only@localhost:5433/household uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
node --check src/household/static/app.js
node tests/browser.test.cjs
```

Tests cover authentication, persisted chat, request deduplication and conflicts,
shared-list changes through the real LangGraph graph, worker lock exclusion,
reclaiming interrupted jobs, and resuming checkpoints after inference failure.

## Deploy to Render

`render.yaml` defines a POC project with one paid web API, one paid background
worker, and managed PostgreSQL 17 in Oregon. It uses internal database connections,
blocks external database access, generates a shared household password, and asks
for the worker's `OPENAI_API_KEY` during initial Blueprint creation. Retrieve the
generated password privately from the environment group in the Render Dashboard.
The login username is `family`.

Both services initialize the database in a serialized, idempotent pre-deploy step.
Automatic service deploys are off; use explicit reviewed deploys for the POC.
Review current costs in Render before applying the resource plan.

The project repository is [samgrigg/we-have-ai-at-home](https://github.com/samgrigg/we-have-ai-at-home).
Create the Render Blueprint from that repository. Render reads the remote
`render.yaml`, not the local file, so local changes must be committed and pushed first.
If Render CLI is installed, run `render blueprints validate render.yaml` before
creating the Blueprint. Schema validation alone does not verify account limits,
Git access, resource availability, builds, or runtime health.

## Other public clouds

The same image runs as two services, with a managed PostgreSQL database.

1. Create PostgreSQL 17 with backups and private networking where available.
   Use the provider's connection string and TLS settings.
2. Build this Dockerfile from a repository or publish its image to your registry.
3. Set `DATABASE_URL` and a random `HOUSEHOLD_PASSWORD` as secrets for both services.
   Set `OPENAI_API_KEY` and `MODEL_NAME` for the worker only.
4. Run `python -m household.db` once as a release/init job before starting services.
5. Start the API with
   `uvicorn household.api:create_app --factory --host 0.0.0.0 --port 8000`.
   If the host supplies `PORT`, configure the command to use that port.
6. Start a continuously running worker with `python -m household.worker`.
   Give it no public ingress. Do not use a request-only function for the polling worker.
7. Put the API behind managed HTTPS. Use `/health` for database/API readiness.
   It does not report worker health. Inspect worker logs and request progress separately.

Start with one API and one worker. Worker session advisory locks need direct
PostgreSQL connections or a **session-mode** pooler; transaction-mode poolers are
not supported.

HTTP Basic must be served over HTTPS outside localhost. There is no password
reset or individual authorization in this POC. Configure platform request/body
limits and authentication rate limiting before sharing a public URL broadly.

## Reliability and limits

- The browser creates a request UUID and preserves it in the current tab across a
  failed submission/refresh. Resubmission with that UUID returns the original job.
- One unfinished request is allowed per conversation. Failed requests block new
  messages until explicitly retried; another conversation can still be started.
- PostgreSQL holds jobs. Workers acquire a session lock per conversation. A dead
  worker loses its connection/lock; another worker can reclaim its processing job.
- Checkpoints, tool mutations and job completion use that same lock-owning
  connection. Losing the connection prevents a stale worker from continuing writes.
  Checkpoints are saved synchronously before the next graph step starts.
- Tool transactions also acquire the checkpoint saver's connection lock. Psycopg's
  per-query synchronization alone does not exclude a tool transaction from a
  background checkpoint pipeline context on the shared connection. The shared
  lock covers the complete tool transaction, including commit; logs label any wait
  as `sql.connection_lock_wait`.
- LangGraph checkpoints are per request. A retry resumes the last persisted step.
  Tool receipts and shopping changes commit atomically, so replaying a committed
  tool call returns its saved result without repeating the mutation.
- A failed request may have already changed the shopping list. The UI explains
  this. Multi-tool requests are not all-or-nothing transactions.
- Shopping items are normalized by Unicode, whitespace, and case. There are no
  quantities, categories, or semantic deduplication (e.g. “egg” versus “eggs”).
- Model calls time out after 30 seconds, use one provider retry, and cap generated
  tokens. Graph runs have a recursion limit of 16. Conversation context uses the
  last 40 completed exchanges; the full displayed history remains in PostgreSQL.
- Logs include job IDs, exception types, timing and successful-run token usage.
  They deliberately exclude message bodies and provider exception text.
- Successful requests record model token usage. Set `INPUT_USD_PER_MILLION` and
  `OUTPUT_USD_PER_MILLION` on the worker for an estimate; unset rates yield `null`.
  Estimates exclude cached-token discounts, failed provider calls and infrastructure.
  A provider response lost before checkpointing may be billed without being counted.
- The first schema setup is idempotent. Introduce versioned migrations before
  evolving the deployed schema. No schema upgrade framework is included yet.

Voice, SMS, calendars, meal planning, allowance, and automatic reminders are out
of scope. The next validation is live-model testing and a hosted smoke test, then
household use to decide what earns a place in the proof of value.
