# POV increment: Google accounts and conversation privacy

Status: proposed design for user review; no implementation changes yet.

## Confirmed requirements

- One household with five members, each with a Google account.
- Approved family email addresses are supplied through configuration/environment,
  never committed to the repository.
- Personal conversations are private to their owner.
- One explicit family conversation is visible to all five members.
- The shopping list remains shared.
- Keep the existing FastAPI, LangGraph worker, Render PostgreSQL and Docker stack.

## Authentication

Use direct Google OpenID Connect sign-in through a maintained Python OAuth/OIDC
library. Request only `openid email profile`; calendar authorization is a separate
future feature. Use a separate OAuth client for this application rather than
copying the homework dashboard's credentials.

Configure `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SESSION_SECRET`,
`PUBLIC_BASE_URL`, and `FAMILY_ALLOWED_EMAILS` on the API. The email list contains
five unique normalized addresses. The worker does not receive Google credentials
or the session secret. Localhost and the Render site have explicit callback URLs.

The sign-in flow validates state, nonce, PKCE and the provider's ID-token signature,
issuer, audience, expiration and verified email. A valid Google account is not
sufficient: the email must be approved for this household. Pin an enrolled account
to Google's stable `sub` and an application-generated user UUID; never silently
rebind an existing approved email to a different Google identity.

After sign-in, issue an opaque random session cookie. Store only its hash and
expiry in PostgreSQL. Cookies are HttpOnly and SameSite=Lax, Secure on HTTPS,
with a seven-day absolute lifetime. State-changing endpoints enforce CSRF
protection. Logout revokes the stored session. Removing a member from the allowlist
denies their existing sessions on subsequent requests. No production Basic Auth
fallback or authentication bypass remains.

## Application data and authorization

Introduce versioned database migrations, users and sessions. Add conversation
visibility and owner fields, and the submitting user to jobs. Attribute new
shopping-list items to their creator without changing attribution on duplicate
inserts. Existing shopping items have unknown original authors.

- New personal conversations belong to the authenticated user.
- One canonical Family chat is created separately and visible to all members.
- Conversation listing, reads, submissions, request-ID deduplication, retry and
  job lookup all enforce conversation access on the server. Guessing UUIDs does
  not grant access. Unauthorized resource lookups return 404.
- The authenticated user is set server-side on every new job. Request bodies
  cannot choose a different user, owner or household.
- The worker loads history from the job's authorized conversation only. Graph
  checkpoints remain scoped to each job. User IDs and membership are trusted
  execution context, not inferred from a prompt.
- Shared-chat messages show their actual sender. Private-chat owners see only
  their own conversations, plus the shared Family chat and shared legacy archive.
- There is no parent/administrator override to read private chats in this increment.
  Household administration stays in deployment configuration for now.

Privacy applies to conversational history and access. Actions against shared tools
are shared effects: an item added in a private chat appears on the household list,
with attribution. Conversation text is not automatically copied into family chat
or stored as cross-conversation model memory.

## Existing POC data

Existing POC conversations were shared. Preserve them as a clearly labeled shared
POC archive, without guessing ownership or assigning private authors. Make this
archive read-only. Preserve the current shopping list. Start a new Family chat and
new personal conversations after migration. Do not delete checkpoint or receipt data.

## Browser changes

Replace the browser Basic Auth prompt with a Google sign-in page, current-user
identity and logout. Separate My chats, Family chat and POC archive in navigation.
Make the shared nature of Family chat and shopping-list actions explicit. Clear
the previous user's rendered state on logout/session expiration. The local-storage
conversation selection is validated against the current user's permitted list.

## Verification

Use five synthetic identities in tests. Verify allowlist rejection, identity
binding, session expiry/logout/revocation and CSRF enforcement. Exercise OAuth
validation against controlled provider fixtures; separately verify the actual
Google handshake once credentials and callbacks are configured.

Database/API tests must prove that one member cannot list, read, post to or retry
another member's private conversation, including reused request UUIDs. Verify all
five members can participate in Family chat and update the shared list, with correct
attribution. Test private-to-shared history isolation through the real graph, and
preserve queue/checkpoint replay and connection-lock regression tests.

Migration tests start from the current POC schema and data, preserve archive/list
contents, and verify repeatable initialization. Browser tests cover sign-in/session
expiration, account switching and private/shared navigation without real family
credentials. Existing data requires an explicit migration policy, not CREATE TABLE
IF NOT EXISTS alone.

## Rollout

Build and validate locally first, then perform a real Google sign-in. Before hosted
rollout, back up the database, resolve unfinished POC jobs and use a maintenance
window to stop old API/worker instances. Apply migrations and deploy the Google-only
API and compatible worker together. Old Basic Auth instances must not serve traffic
while new private conversations exist. Review the tested release before deployment.

Out of scope: calendars, SMS, voice, allowance, additional households, admin UI,
parental access overrides and migration to a different model provider/model.
