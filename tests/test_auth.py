from datetime import UTC, datetime, timedelta

import pytest

from household.auth import Authentication
from household.config import Settings

EMAILS = ",".join(f"member{i}@example.com" for i in range(5))


def claims(i=0, **updates):
    return {
        "sub": f"google-{i}",
        "email": f"member{i}@example.com",
        "email_verified": True,
        "name": f"Member {i}",
        **updates,
    }


def test_allowlist_requires_five_distinct_addresses():
    for value in [
        "one@example.com",
        EMAILS + ",member0@example.com",
        EMAILS.replace("member1", "member0"),
    ]:
        with pytest.raises(ValueError):
            Settings(database_url="postgresql://unused", family_allowed_emails=value)


def test_google_identity_is_verified_allowed_and_cannot_be_rebound(app):
    auth = app.state.auth
    for values in [
        claims(email="outside@example.com"),
        claims(email_verified=False),
        claims(sub=""),
    ]:
        with pytest.raises(ValueError):
            auth.enroll(values)
    user = auth.enroll(claims())
    assert auth.enroll(claims())["id"] == user["id"]
    with pytest.raises(ValueError):
        auth.enroll(claims(sub="different-google-account"))


def test_session_expiry_logout_and_allowlist_revocation(app):
    auth = app.state.auth
    user = auth.enroll(claims())
    token = auth.new_session(user["id"])
    assert auth.lookup(token)["id"] == user["id"]
    auth.revoke(token)
    assert auth.lookup(token) is None
    token = auth.new_session(user["id"])
    with auth.db.connect() as conn:
        conn.execute(
            "UPDATE sessions SET expires_at=%s", (datetime.now(UTC) - timedelta(seconds=1),)
        )
    assert auth.lookup(token) is None
    token = auth.new_session(user["id"])
    changed = app.state.settings.model_copy(
        update={
            "family_allowed_emails": EMAILS.replace(
                "member0@example.com", "replacement@example.com"
            )
        }
    )
    assert Authentication(auth.db, changed).lookup(token) is None


def test_csrf_is_required_and_logout_revokes_cookie(client):
    assert client.get("/api/me").status_code == 200
    original = client.headers["X-CSRF-Token"]
    client.headers["X-CSRF-Token"] = "wrong"
    assert client.post("/api/conversations", json={"title": "No"}).status_code == 403
    client.headers["X-CSRF-Token"] = original
    client.headers["Origin"] = "https://attacker.example"
    assert client.post("/auth/logout").status_code == 403
    client.headers["Origin"] = "http://localhost:8001"
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/api/me").status_code == 401


def test_missing_or_invalid_google_callback_never_creates_session(app):
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="http://localhost:8001") as c:
        assert (
            c.get("/auth/callback?code=invalid&state=invalid", follow_redirects=False).status_code
            == 400
        )
        assert c.get("/api/me").status_code == 401


def test_oauth_authorization_codes_are_removed_from_access_logs():
    import logging

    from household.auth import OAuthAccessLogFilter

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        1,
        "%s %s %s %s %s",
        ("127.0.0.1", "GET", "/auth/callback?code=private-code&state=private-state", "1.1", 303),
        None,
    )
    assert OAuthAccessLogFilter().filter(record)
    assert "private-code" not in record.getMessage()
    assert "private-state" not in record.getMessage()


def test_failed_callback_logs_state_presence_without_credentials(app, caplog):
    import logging

    from fastapi.testclient import TestClient

    with caplog.at_level(logging.WARNING, logger="household.auth"):
        with TestClient(app, base_url="http://localhost:8001") as c:
            c.get("/auth/callback?code=sensitive-code&state=sensitive-state")
    assert "oauth_cookie_present=False" in caplog.text
    assert "stored_state_count=0" in caplog.text
    assert "state_matches=False" in caplog.text
    assert "sensitive-code" not in caplog.text
    assert "sensitive-state" not in caplog.text
