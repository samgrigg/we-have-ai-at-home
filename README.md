# Household assistant · family accounts POV

FastAPI browser chat, a separate LangGraph worker, and PostgreSQL. Five approved
Google identities have private personal conversations, one shared Family chat,
and a shared shopping list. Source: [we-have-ai-at-home](https://github.com/samgrigg/we-have-ai-at-home).

## Google configuration

Create a Google OAuth **Web application** client for this app. Request identity
scopes only (`openid email profile`); no calendar permission is requested.
Register these redirect URIs as appropriate:

- Local: `http://localhost:8001/auth/callback`
- Hosted: `https://household-poc-api-pqc7.onrender.com/auth/callback`

Configure the OAuth consent audience and add the five accounts as test users if
Google's app is in testing mode. Do not copy the homework dashboard's credentials
into checked-in files. Credentials and real family addresses belong only in ignored
`.env` files or Render environment settings.

Copy `.env.example` to `.env` for a new checkout and set:

- `FAMILY_ALLOWED_EMAILS`: exactly five distinct comma-separated email addresses.
- `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`: this app's OAuth client.
- `SESSION_SECRET`: random secret, at least 32 characters, generated once.
- `PUBLIC_BASE_URL`: the exact browser origin, including a non-default local port.
- `OPENAI_API_KEY`: used only by the worker.

Google identity is pinned to its verified `sub` and our application user ID.
Signing in with an arbitrary Google account does not grant household access.
Sessions use opaque cookies, database-hashed tokens and a seven-day absolute
lifetime. Logout revokes the session. Removing an email from configuration denies
existing sessions on subsequent requests once the updated API configuration is live.
No shared-password authentication fallback is included.

## Run locally

Docker Engine/Desktop and Docker Compose are required. For an existing POC database,
read the migration section before starting this release.

```sh
docker compose up --build -d
```

Open [localhost:8001](http://localhost:8001) and choose **Continue with Google**.
If that port is in use, change both `API_PORT` and `PUBLIC_BASE_URL` in `.env`,
and register the corresponding Google callback. PostgreSQL is loopback-only on
port 5433, with a persistent named volume. Local database credentials in Compose
are disposable development credentials.

Try personal chat, Family chat, and adding an item to the shopping list. A list
change made from a personal chat is visible to all members, including attribution.
Personal conversation history is not copied to Family chat. The family chat allows
one unfinished request at a time; another member waits until it finishes or is retried.
Failed requests can also be skipped to unblock the conversation. Skipping keeps
any list changes already committed and excludes that exchange from future model
history. This lets remaining members recover Family chat after removing a member.

The image has no source bind mount. Rebuild it after changing Python code.
Settings changes require recreating the appropriate container with `compose up`.
The worker gets the family allowlist and model key; Google credentials and the
session signing secret are passed only to the API.

## Migration from the POC

The first numbered migration runs transactionally, once. It:

- Preserves existing conversations as a shared, read-only **POC archive**.
- Leaves legacy authors unknown rather than guessing who wrote a message.
- Resets the disposable shopping list, as approved for this POV.
- Creates users, sessions, ownership fields, author fields and a new Family chat.
- Preserves historical job/checkpoint/receipt data.

Migration refuses to run while jobs are queued, processing or failed. Resolve
unfinished jobs first. Stop the old API and worker during migration; an old Basic
Auth API must never serve traffic after private chats become available.

For the hosted upgrade, back up PostgreSQL, configure all new API variables and
the worker allowlist, schedule a maintenance window, stop the old services, apply
`python -m household.db`, and bring up the compatible API/worker together. Schema
migration is not backwards-compatible with continued use of the old API. Do not
roll back to a Basic Auth build against this database. Review the tested release
and Render plan before applying it.

`docker compose down` preserves data; adding `-v` deletes the database volume.

## Debugging

```sh
docker compose logs -f api worker
docker compose exec postgres psql -U household -d household -c \
  "SELECT id,status,attempts,error,updated_at FROM jobs ORDER BY sequence DESC LIMIT 10;"
```

Logs identify the job, model/tool calls, individual SQL operations, checkpoint
operations and final persistence. Structured events give elapsed milliseconds and
success/error outcomes. A separate thread logs `job_progress` every five seconds,
including all active stages. Stages older than ten seconds trigger warnings.
`PROGRESS_LOG_SECONDS` and `SLOW_STAGE_SECONDS` configure those thresholds.
A 60-second thread-stack dump diagnoses hangs; it does not cancel work. Logs exclude
prompts, item names, SQL parameters, credentials and provider exception messages.

Tools and checkpoint persistence share the same connection and pipeline lock.
The lock spans an entire tool transaction, including commit, preventing concurrent
pipeline contexts from interfering with tool SQL. Lock waits are labeled
`sql.connection_lock_wait`. Tool effects and replay receipts commit atomically.

For breakpoints, keep PostgreSQL/API in Docker and run the worker on your host:

```sh
docker compose stop worker
uv sync --frozen
uv run python -m household.worker
```

Your local `DATABASE_URL` points to localhost:5433. Models time out after 30 seconds
with one provider retry. Graph runs have a recursion limit of 16 and use the last
40 completed exchanges from the authorized conversation. Checkpoints are per job.

## Verification

Tests use isolated schemas on real PostgreSQL and synthetic identities. They do
not use real Google credentials, family addresses or paid inference.

```sh
uv sync --frozen
TEST_DATABASE_URL=postgresql://household:household-local-only@localhost:5433/household uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
node --check src/household/static/app.js
node tests/browser.test.cjs
```

Controlled OIDC endpoints exercise real Authlib state/nonce/signature/issuer/
audience/expiry validation and PKCE. A real Google handshake was verified locally with the configured OAuth client. Tests cover cross-member access denial, private
history isolation, shared authorship, session expiry/logout/revocation, CSRF,
POC migration, replay recovery, connection fencing and checkpoint/tool exclusion.

## Render deployment

`render.yaml` retains the API, worker and PostgreSQL in Oregon. New Google settings
are API-only; the worker references the API's family allowlist. `sync: false` prompts
apply on initial Blueprint creation, so existing services require manual setup of
new variables. After syncing, omitted old variables can remain in Render: remove
the obsolete `HOUSEHOLD_PASSWORD` and unused old environment group after the cutover.
Automatic deployments remain off. Review any group-removal/resource changes before
applying a Blueprint update. Google sign-in is verified locally; the hosted account migration requires a
maintenance cutover before deployment.

The API serves `/health`; this checks the database/schema, not worker or provider
health. Deploy verification also requires worker logs and a real authorized request.
Use direct PostgreSQL connections or session pooling, never transaction pooling.

`MODEL_NAME` remains configurable. The existing POC default is `gpt-4.1-mini`;
its replacement is a separate change requiring compatible client settings and evals.
Successful jobs record token usage. Optional `INPUT_USD_PER_MILLION` and
`OUTPUT_USD_PER_MILLION` worker settings enable an approximate cost estimate.
Voice, calendars, SMS, allowance and multiple households remain outside this increment.


## Recipe links (POV)

Paste a public HTTPS recipe link into a personal or Family chat. For example:
“Import this recipe, double it, and leave out the seasonings we already have: URL”.
The assistant reads structured Recipe data, then prepares an ingredient preview.
Review the quantities, uncheck pantry items, and press **Confirm ingredients**.
Nothing from a recipe request is added until its requesting member confirms.
Other Family chat members can view a shared preview and continue unrelated list edits.
Use **Dismiss recipe** to discard a preview. Repeated confirmation does not add twice.

Quantities stay in the item text (for example, “2 cups chicken broth”). Simple leading
quantities, fractions and ranges can be scaled. Package sizes and unclear quantities
are flagged for review; items are not merged by quantity. Possible overlaps are
highlighted, and exact normalized duplicate strings are kept once. Pantry omissions
apply to this request only; the app does not maintain an inventory of pantry supplies.

This first version reads JSON-LD Recipe ingredients, without running page scripts,
following page instructions or performing general web search. Use clean recipe
permalinks without query parameters. Login-protected/blocked sites, pages without
structured ingredients, more than 60 ingredients or lines longer than 120 characters
fall back to pasting ingredients into chat. That existing pasted-text flow remains a
normal shopping request; the new confirmation preview applies to recipe URLs.

The reader permits public HTTPS only on port 443, validates every redirect and all
DNS results, and pins the checked destination IP while verifying TLS against the
original hostname. Fetching runs in a credential-free subprocess killed after 25
seconds, with bounded redirects and a 2 MB response cap. It holds no shared shopping
list lock while contacting a recipe site. Tool traces include fetch timing without
logging URLs or page contents. A numbered additive migration stores recipe previews.
