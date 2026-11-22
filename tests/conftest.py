import os
from uuid import uuid4

import psycopg
import pytest


@pytest.fixture
def database_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    schema = "test_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    # Each test gets a separate schema, including LangGraph checkpoints.
    from psycopg.conninfo import make_conninfo

    scoped = make_conninfo(url, options=f"-c search_path={schema}")
    yield scoped
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.fixture
def app(database_url):
    from household.api import create_app
    from household.config import Settings
    from household.db import Database

    settings = Settings(
        database_url=database_url,
        family_allowed_emails=",".join(f"member{i}@example.com" for i in range(5)),
        google_client_id="test-client",
        google_client_secret="test-secret",
        session_secret="test-session-secret-with-at-least-32-characters",
        public_base_url="http://localhost:8001",
    )
    Database(database_url).setup()
    return create_app(settings)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="http://localhost:8001") as client:
        from household.auth import COOKIE

        user = app.state.auth.enroll(
            {
                "sub": "google-0",
                "email": "member0@example.com",
                "email_verified": True,
                "name": "Member 0",
            }
        )
        token = app.state.auth.new_session(user["id"])
        client.cookies.set(COOKIE, token)
        client.headers.update(
            {"Origin": "http://localhost:8001", "X-CSRF-Token": app.state.auth.csrf(token)}
        )
        yield client
