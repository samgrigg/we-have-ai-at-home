# Grocery-first Bridget

Date: 2026-11-23
Status: Written specification approved in chat; branding direction supplied by user.

## Visual direction

Use an original mid-century modern, retro-futuristic domestic style inspired by
the 1965 Sally Field Gidget series, Alice from The Brady Bunch, and Rosie from
The Jetsons. Cream, appliance blue, teal, and restrained coral create a sunny,
capable household mood. Bold rounded display lettering, oval controls, thin ink
outlines, and small atomic accents provide personality; readable grocery rows,
clear focus states, and accessible contrast remain central. Use CSS and vector
decoration rather than character likenesses or television artwork.

Reference research: Gidget imagery at https://www.tvinsider.com/show/gidget-1965/;
Alice costume at https://entertainment.ha.com/itm/movie-tv-memorabilia/ann-b-davis-alice-nelson-signature-maid-s-uniform-from-the-brady-bunch/a/997063-1107.s;
Jetsons archive at https://www.smithsonianmag.com/history/a-peek-into-the-jetsons-archive-at-warner-brothers-animation-25255023/.

## Product direction

Bridget, also called “We Have AI At Home,” is a household app of apps.
This increment makes Groceries the default workspace. Meal planning, homework,
and pantry inventory are future apps or capabilities, not navigation placeholders.
The experience must work as a grocery list without requiring a conversation.

## Workspace

The shell provides Bridget branding, a Groceries workspace label, account controls,
and a Chat button. The shared list occupies the main content area. Unchecked items
appear first; a collapsible Picked up section holds checked items. Checking is
persistent and reversible and does not create pantry inventory.

Each item supports checking, editing its name and quantity, removal, and opening
Smith’s product selection. Keep authorship and selected-product details available
without allowing them to overwhelm the ingredient itself. Quantity editing uses
the existing ingredient text and requirement parser, rather than introducing a
second independently editable quantity representation.

A prominent input accepts both short entries such as “milk” and semantic commands
such as “add ingredients for tacos for six.” Route input through the existing
agent pipeline initially; do not guess whether free text is an item or a command
with an ambiguous client-side heuristic. Direct item controls never require AI.

Command progress, response, errors, retry/skip controls, and recipe ingredient
previews are visible in the grocery workspace while chat is closed. Preserve the
input on submission failure and reuse its request ID on retry. Show the actual
agent response rather than inventing a success summary. Clarification responses
can be answered through the same input with retained command context.

## Chat and command context

Chat opens in a right-side panel on desktop and a full-screen sheet on mobile.
It retains personal conversations, Family chat, and the read-only archive.
Opening or closing chat does not replace the grocery workspace or change command
context. Provide an accessible close control, Escape handling, focus restoration,
and appropriate keyboard focus management for the mobile modal sheet.

Each member has one dedicated private grocery command conversation, created
idempotently by the server and uniquely identified by purpose and owner, not by
title. It uses the existing ownership checks and job processing. Ordinary chat
navigation excludes this conversation; commands and their recipe previews are
loaded separately from the selected chat. Commands are private; resulting grocery
changes are shared. Label that distinction near the input.

Pending command and chat submissions are tracked independently and bound to the
authenticated user and conversation. An unfinished chat request does not disable
direct list controls or a separate command conversation. Both surfaces show their
own recovery controls. Identity changes clear all private browser state and reject
outdated responses. No personal transcript is copied into Family chat.

## Data and direct actions

Add an additive migration for persistent checked state and a revision token on
shopping items, plus the dedicated command-conversation purpose and unique owner
constraint. Preserve existing items, accounts, messages, requirements, product
preferences, and selections. Existing items start unchecked.

Authenticated, CSRF-protected list endpoints support add, edit, check/uncheck,
and delete. Validate text with the same normalization and bounds as agent tools;
recompute requirement metadata on edits. All list writes, including worker tools
and recipe confirmation, use the existing shared list transaction lock.

Direct updates and deletion require the revision observed by the browser. A stale
revision returns a conflict, refreshes the list, and preserves the member’s draft
for review instead of silently overwriting newer edits. Include an incarnation
token so deleting and re-adding the same name cannot make an old edit valid again.
Prevent renaming into another existing normalized item rather than silently merging.

The existing name-based item key may remain for this increment. A name or quantity
edit invalidates dependent product searches and selections transactionally before
renaming because those records reference the original ingredient and requirement.
Explain the invalidation in the edit UI. Checking alone preserves product selection.
Remembered product preferences persist across edits and removal.

Agent list reads distinguish active items from picked-up items. Adding an item
already picked up reactivates it; adding an active duplicate retains one item.
Agent removal continues to remove the named item. Worker and recipe mutations
advance revisions whenever they change an item. Recipe additions follow the same
reactivation behavior; confirmation remains explicit and idempotent.

## Integration boundaries

Recipe previews appear alongside the command that produced them in the grocery
workspace, or within the originating chat panel for chat requests. Preserve owner
confirmation rules, source links, scaling warnings, and replay protections.
Smith’s search and selection remain grocery-workspace details, with existing
catalog validation and expiry rules. No ordering, checkout, or pantry replenishment
is introduced. Chat remains capable of shared list changes.

## Implementation boundaries

Keep shell/panel state, grocery rendering and mutations, command submission,
and chat navigation as separate responsibilities. Extract shared request and job
recovery logic where necessary rather than duplicating the existing app.js flow.
Preserve FastAPI, the worker, PostgreSQL, and the current authentication model.
No new frontend framework or generalized app/plugin registry is required.

## Verification

Use PostgreSQL integration tests for authorization and CSRF on new endpoints,
revision conflicts, delete/re-add conflicts, rename collisions, metadata updates,
product invalidation, picked-up reactivation, migration preservation, and concurrent
command-conversation creation. Verify worker/recipe paths share mutation semantics.

Browser tests cover a grocery-first initial view, commands with chat closed,
independent chat and command contexts, progress and failed submission recovery,
recipe confirmation, direct list editing, checked persistence, stale-response
protection, and account changes. Run existing account, recipe, product, and worker
regressions. Inspect desktop and mobile layouts, keyboard navigation, panel focus,
and errors visually before claiming completion. Do not use paid inference or live
family data for automated checks.

## Out of scope

Pantry quantities, automatic pantry transfers, meal planning, homework management,
multiple lists or households, store checkout, a new model, and public deployment.
