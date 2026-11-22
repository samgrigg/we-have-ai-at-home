# Recipe link grocery import

The household approved a recipe-link preview and confirmation flow in chat on November 22.
This extends the existing LangGraph shopping tools, FastAPI and plain browser app.

A read_recipe tool fetches one public HTTPS recipe page and returns only extracted
Recipe JSON-LD ingredients, title and yield as untrusted data. A prepare_recipe_import
tool takes the returned recipe ID, multiplier and omitted ingredient indices and
persists a preview attached to the initiating job/conversation/member. Ingredients
retain quantities as plain strings. Scaling handles leading numeric quantities and
ranges; uncertain lines remain unchanged and are flagged. No pantry is inferred or saved.
The model uses the read result to choose omissions requested in this message.

The browser shows the preview in its authorized conversation, with checkboxes,
source link, quantities, omitted items and possible overlaps with the existing list.
Only the initiating member can confirm; other Family chat members can see the shared
preview. Confirmation uses CSRF and a row lock, inserts selected items and attribution
in the same transaction, and is idempotent. Empty selection or unavailable jobs are
rejected. Existing list operations remain available, but a job which reads or prepares
a recipe cannot mutate the list through the model: confirmation is a server gate.

Fetches use a pinned public DNS address with TLS hostname verification, no proxy,
HTTPS only on port 443, no credentials or query-string credentials, no IP literals,
redirect validation at every hop, bounded response size, redirects and timeouts.
A credential-free reader subprocess is killed after 25 seconds, covering DNS, TLS,
headers and body; fetching never holds the shared list mutation lock.
All DNS answers must be public; loopback/private/link-local/metadata destinations are
rejected. Browser rendering and general web search are out of scope. Recipe pages
without valid structured ingredients fail safely and ask for pasted ingredients.
Page instructions never become system instructions. Only bounded ingredients are
returned to the model; title and yield are bounded too. Source URLs are not logged.

Tests cover private-network/redirect/DNS blocking, extraction, scaling and errors,
preview replay, cross-member access, mandatory confirmation, atomic/idempotent adds,
omissions, attribution and UI session/navigation fencing. Production deploy is a
separate step after local review and validation.
