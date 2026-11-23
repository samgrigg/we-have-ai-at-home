# Smith's product selection POV

Approved scope: product suggestions and persisted choices, explicitly no cart features.
Preferred store is the API-verified Smith's at 10305 S 1300 E, location 70600153.

Each shared grocery item offers Find products. A server-side Kroger client uses
client-credentials product.compact only, cached in memory until shortly before expiry.
Only fixed Kroger token, locations and product GET endpoints are permitted; no cart
or customer account APIs. Credentials stay API-only; provider errors never include
response bodies, authorization headers or secret values in app errors/logs.

A deterministic parser extracts leading quantities and ingredient terms from list
text. It retains original wording. Compatible volume, mass and count units use exact
conversion factors. Numeric ranges use their upper bound. Ambiguous package counts,
compound units, and missing quantities require review rather than guessed conversion.
Product size parsing supports ordinary single-unit sizes and explicit N x size packs.
Mass is never converted to volume and count is never guessed from weight.

An authenticated CSRF-protected search request accepts an existing item name and
optional edited search term. Search results are filtered conservatively by ingredient
words and explicit attributes (e.g. heavy cream excludes creme fraiche and dairy-free
alternatives unless requested). Matches are suggestions, never guaranteed substitutes.
Reported out-of-stock candidates remain visible but cannot be selected. Missing stock
or package quantities are labeled unknown. Rank: remembered suitable product first,
then adequate compatible package/price options. Missing prices are not zero prices.
Package counts cover the recipe requirement; remaining amount is displayed in its
base unit. User can pick a larger package/count; saving a preferred product remembers
that household choice. We do not claim any pantry stock or purchase has occurred.

Persist bounded searches with item instance, store, candidate snapshots and checked
at time. Selection uses a returned search/candidate identifier, never browser-supplied
prices or metadata. Reject stale (>30 minutes) or removed/re-added item searches.
Use a transaction to save the selection and optional preference, with actual actor
attribution. Every family member may choose products for the shared list. Selection
is replaceable; repeated identical submission is harmless. Show original grocery
requirement plus the chosen product/count and price observation time. Item removal
cascades selection/search cleanup; remembered household preference persists.

UI renders safe text and maintains account-generation fencing. Search/results are
not reset by ordinary list polling; choices are shown after refresh. Failed searches
leave original grocery items unchanged. Unsupported/no results allow manual shopping
from original item text. Optional Kroger configuration keeps the app usable without
credentials. No pantry updates, orders, cart writes, customer OAuth or Costco live
integration are part of this increment.

Validation: read-only live Kroger smoke, deterministic matching/unit tests, HTTP
mock tests of token caching/failures and GET-only catalog access, PostgreSQL tests
of saved searches/choices/stale access/CSRF/preferences, browser interaction/privacy
checks, regression suite, independent review and Docker/local verification.
