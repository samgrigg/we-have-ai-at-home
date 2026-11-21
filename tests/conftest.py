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

    settings = Settings(database_url=database_url, household_password="test-password-123")
    Database(database_url).setup()
    return create_app(settings)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        client.auth = ("family", "test-password-123")
        yield client
