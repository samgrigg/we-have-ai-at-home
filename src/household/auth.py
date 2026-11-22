import hashlib
import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware

COOKIE = "household_session"
SESSION_SECONDS = 7 * 24 * 60 * 60
logger = logging.getLogger("household.auth")


class OAuthAccessLogFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            path = record.args[2]
            if isinstance(path, str) and path.startswith("/auth/callback?"):
                args = list(record.args)
                args[2] = "/auth/callback"
                record.args = tuple(args)
        return True


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Authentication:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    def enroll(self, claims):
        email = str(claims.get("email", "")).strip().lower()
        subject = claims.get("sub")
        if (
            claims.get("email_verified") is not True
            or email not in self.settings.family_emails
            or not isinstance(subject, str)
            or not subject
            or len(subject) > 255
        ):
            raise ValueError("Google identity is not approved")
        name = str(claims.get("name") or email.split("@")[0]).strip()[:100] or "Family member"
        with self.db.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(728346129)")
            rows = conn.execute(
                "SELECT * FROM users WHERE email=%s OR google_subject=%s", (email, subject)
            ).fetchall()
            if any(r["google_subject"] != subject or r["email"] != email for r in rows):
                raise ValueError("Google identity cannot be rebound")
            return conn.execute(
                "INSERT INTO users(id,google_subject,email,display_name) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (google_subject) DO UPDATE SET display_name=EXCLUDED.display_name "
                "RETURNING id,email,display_name",
                (uuid4(), subject, email, name),
            ).fetchone()

    def new_session(self, user_id):
        token = secrets.token_urlsafe(32)
        with self.db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at <= now()")
            conn.execute(
                "INSERT INTO sessions(token_hash,user_id,expires_at) VALUES (%s,%s,%s)",
                (digest(token), user_id, datetime.now(UTC) + timedelta(seconds=SESSION_SECONDS)),
            )
        return token

    def lookup(self, token):
        if not token or len(token) > 200:
            return None
        with self.db.connect() as conn:
            user = conn.execute(
                "SELECT u.id,u.email,u.display_name FROM sessions s JOIN users u ON u.id=s.user_id "
                "WHERE s.token_hash=%s AND s.expires_at>now()",
                (digest(token),),
            ).fetchone()
        return user if user and user["email"] in self.settings.family_emails else None

    def csrf(self, token):
        return hmac.new(
            self.settings.session_secret.get_secret_value().encode(), token.encode(), hashlib.sha256
        ).hexdigest()

    def current(self, request: Request):
        token = request.cookies.get(COOKIE, "")
        user = self.lookup(token)
        if not user:
            raise HTTPException(401, "Sign in required")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get(
                "origin"
            ) != self.settings.public_base_url or not secrets.compare_digest(
                request.headers.get("x-csrf-token", ""), self.csrf(token)
            ):
                raise HTTPException(403, "Invalid request origin or CSRF token")
        return user

    def revoke(self, token):
        with self.db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=%s", (digest(token),))


def configure_auth(app, db, settings):
    settings.require_web_auth()
    auth = Authentication(db, settings)
    app.state.auth = auth
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, OAuthAccessLogFilter) for f in access_logger.filters):
        access_logger.addFilter(OAuthAccessLogFilter())
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret.get_secret_value(),
        session_cookie="household_oauth",
        max_age=600,
        same_site="lax",
        https_only=settings.secure_cookies,
    )
    oauth = OAuth()
    oauth.register(
        "google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
    )
    app.state.oauth = oauth

    @app.get("/auth/login")
    async def login(request: Request):
        request.session.clear()
        return await oauth.google.authorize_redirect(
            request, settings.public_base_url + "/auth/callback", prompt="select_account"
        )

    @app.get("/auth/callback")
    async def callback(request: Request):
        # Capture only presence/counts before Authlib consumes the one-time state.
        state = request.query_params.get("state", "")
        stored_states = [key for key in request.session if key.startswith("_state_google_")]
        state_matches = bool(state) and "_state_google_" + state in stored_states
        stage = "token_validation"
        try:
            token = await oauth.google.authorize_access_token(request)
            # Authlib verifies state, nonce and signed OIDC claims before userinfo is returned.
            if not token.get("id_token") or not token.get("userinfo"):
                raise ValueError("Missing verified ID token")
            stage = "identity_enrollment"
            user = auth.enroll(token["userinfo"])
            stage = "session_creation"
            session = auth.new_session(user["id"])
        except Exception as exc:
            logger.warning(
                "google_signin_rejected error_type=%s stage=%s oauth_cookie_present=%s "
                "stored_state_count=%s state_matches=%s oauth_cookie_count=%s",
                type(exc).__name__,
                stage,
                "household_oauth" in request.cookies,
                len(stored_states),
                state_matches,
                sum(
                    part.strip().startswith("household_oauth=")
                    for part in request.headers.get("cookie", "").split(";")
                ),
            )
            request.session.clear()
            raise HTTPException(400, "Google sign-in failed or account is not approved") from None
        request.session.clear()
        old = request.cookies.get(COOKIE)
        if old:
            auth.revoke(old)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            COOKIE,
            session,
            max_age=SESSION_SECONDS,
            httponly=True,
            secure=settings.secure_cookies,
            samesite="lax",
            path="/",
        )
        return response

    @app.get("/api/me")
    def me(request: Request):
        user = auth.current(request)
        return {**user, "csrf_token": auth.csrf(request.cookies[COOKIE])}

    @app.post("/auth/logout", status_code=204)
    def logout(request: Request):
        auth.current(request)
        auth.revoke(request.cookies[COOKIE])
        request.session.clear()
        response = Response(status_code=204)
        response.delete_cookie(
            COOKIE, path="/", secure=settings.secure_cookies, httponly=True, samesite="lax"
        )
        return response

    return auth
