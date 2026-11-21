# Household assistant POC

Approved scope: persistent browser chat and one shared shopping list for one household.

Use Python 3.12+, FastAPI, LangGraph, PostgreSQL, and a hosted tool-calling model.
API and worker are separate processes. PostgreSQL holds durable jobs, conversation
records, shopping items, tool receipts, and LangGraph checkpoints. The browser polls.
One shared household password protects all data; individual identity is deferred.
Use HTTP Basic over HTTPS in public deployments. Do not include secrets in source.

Each conversation allows one unfinished request. Client-generated request UUIDs
deduplicate submission. Failed requests can be retried explicitly. A worker holds
a PostgreSQL session advisory lock while processing a conversation; lost workers
release locks automatically. Checkpoints, tool writes, and job completion use the
lock-owning connection; checkpoint durability is synchronous. Jobs left processing
can be reclaimed after restart.
Each request has its own checkpoint thread, seeded with completed conversation
history. Tool receipts keyed by request and tool-call ID make checkpoint replay
safe. Tool writes and receipts commit together. Shopping list names are normalized
and unique across the household. Graph execution is bounded.

Acceptance: add/show/remove items; a second conversation sees the same list;
history survives refresh; database state and checkpoints survive process restart;
duplicate submission and tool replay do not duplicate effects; failures are visible
and recoverable; logs identify jobs without recording message bodies or secrets;
token usage and configurable estimated model cost are recorded.

Deliver source, locked dependencies, tests against real PostgreSQL, Docker Compose,
and provider-neutral deployment/run instructions. Actual cloud provisioning requires
a selected host, repository destination, and model credentials. Voice, SMS, calendar,
allowance, individual accounts, and automated scheduling are outside this POC.
