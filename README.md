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

## Smith's product selection (POV)

Each shared grocery item offers **Find products at Smith’s**. Review the search term,
product, package size, reported stock and price observation time. Whole-package
recommendations cover compatible ingredient quantities; you can choose a larger
package or increase the count. **Select product** saves the choice alongside the
original ingredient, attributed to the selecting family member. **Remember as our
usual product** makes that product a preferred candidate for the same ingredient
search at this store. Any family member can replace a shared list choice.

This is product selection only: there are no cart, ordering, checkout or customer
account integrations. Selecting a product does not mark it purchased or replenish
pantry inventory. Costco catalog and persisted pantry tracking remain future work.

Kroger configuration belongs on the API only:

```dotenv
KROGER_CLIENT_ID=
KROGER_CLIENT_SECRET=
KROGER_LOCATION_ID=70600153
```

Location `70600153` was verified through the API as Smith’s at 10305 S 1300 E, Sandy.
Credentials need the public product API; the client uses client-credentials with
`product.compact`. It caches the token in memory and contacts only Kroger's fixed
token and product endpoints. The worker never receives Kroger credentials.
Without configuration, the ordinary grocery list still works and product searches
show a setup message. Existing Render services need these optional API variables
set manually; `sync: false` does not prompt again when syncing an existing service.

Matching is deliberately conservative, using ingredient words and food-form filters.
It is not an allergy or ingredient-label verifier. No mass-to-volume or weight-to-count
conversions are guessed. Unknown sizes, package/container wording and incompatible
units require manual quantity review. A missing stock signal remains unknown;
reported-out-of-stock products cannot be selected. Prices are observations, not
checkout quotes. Missing/zero promo prices do not override valid regular prices.
Searches expire after 30 minutes. Product metadata/prices are selected from persisted
server results rather than accepted from the browser. Removed items lose their
searches/choices; remembered product preferences persist. No pantry quantities are
assumed or modified.


Grocery items now persist parsed `requirement` metadata alongside their original
list text: ingredient search term, normalized amount, dimension and base unit.
For example, “1 c chicken broth” retains that display text while storing the term
“chicken broth” and a volume requirement of 8 fl oz. Chat additions and confirmed
recipe ingredients both populate this metadata; migration setup backfills older
items. Product search reads the persisted requirement. Common abbreviations such
as c/c., tbs/tbsp, tsp, oz and lb are recognized; unknown quantities remain marked
for review. An edited product search also strips a recognized quantity prefix.

## Bridget: groceries first

Bridget ("We Have AI At Home") now opens to the shared grocery workspace.
Use **Tell Bridget** for a quick entry such as “milk”, a semantic request, or a
recipe link. Results, progress, recipe review and retry controls appear beside
the list. Each member has a dedicated private grocery command context; opening
or switching personal/Family chat does not change that context. Grocery changes
remain shared. **Chat with Bridget** opens the optional conversation panel.

Check items off into **Picked up**, uncheck them to put them back, or use **Edit**
to change the ingredient and quantity (for example, “2 cups milk”). These direct
controls do not call the model. Checking does not add pantry inventory. Adding a
picked-up item again puts it back on the active list. Confirming the same recipe
preview twice remains safe and does not reapply changes after its first confirmation.
Name/quantity edits clear that item's product searches and selected product;
check-off preserves them. Remembered usual products persist.

Edits and removal use revision tokens. If another member changes an item, the app
preserves your draft and asks you to review the latest state before saving again.
Migration `005_grocery_workspace.sql` preserves existing list data and adds
checked state, revision tracking, and private command contexts. Apply through
`python -m household.db` before serving the updated API/worker. Rebuild both
containers for local use; no hosted deployment is included in this change.

Additional browser-state verification:

```sh
node --check src/household/static/groceries.js
node tests/grocery-browser.test.cjs
```

The visual direction uses original mid-century domestic styling inspired by
Gidget, Alice from The Brady Bunch and Rosie from The Jetsons: cream, appliance
blue, teal, restrained coral and rounded controls. Television artwork and character
likenesses are not shipped with the app. Meal planning, homework and pantry
inventory remain future work.
