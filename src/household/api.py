import secrets
from importlib.resources import files
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from household.config import Settings
from household.db import Database


class ConversationInput(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=100)


class MessageInput(BaseModel):
    request_id: UUID
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Message cannot be blank")
        return value.strip()


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    db = Database(settings.database_url)
    app = FastAPI(title="Household assistant", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    security = HTTPBasic()

    def authenticated(credentials: Annotated[HTTPBasicCredentials, Depends(security)]):
        valid_user = secrets.compare_digest(credentials.username.encode(), b"family")
        valid_password = secrets.compare_digest(
            credentials.password.encode(), settings.household_password.get_secret_value().encode()
        )
        if not (valid_user and valid_password):
            raise HTTPException(
                401, "Authentication required", headers={"WWW-Authenticate": "Basic"}
            )

    protected = [Depends(authenticated)]
    static = files("household").joinpath("static")
    # Static assets contain no household data or credentials.
    app.mount("/static", StaticFiles(directory=str(static), check_dir=False), name="static")

    @app.get("/", dependencies=protected)
    def index():
        return FileResponse(str(static.joinpath("index.html")))

    @app.get("/health")
    def health():
        try:
            with db.connect() as conn:
                conn.execute("SELECT 1 FROM conversations LIMIT 1")
        except Exception:
            raise HTTPException(503, "Database unavailable") from None
        return {"status": "ok"}

    @app.get("/api/conversations", dependencies=protected)
    def conversations():
        with db.connect() as conn:
            return conn.execute("SELECT * FROM conversations ORDER BY created_at DESC").fetchall()

    @app.post("/api/conversations", dependencies=protected, status_code=201)
    def create_conversation(body: ConversationInput):
        with db.connect() as conn:
            return conn.execute(
                "INSERT INTO conversations(id, title) VALUES (%s, %s) RETURNING *",
                (uuid4(), body.title),
            ).fetchone()

    def require_conversation(conn, cid):
        row = conn.execute("SELECT id FROM conversations WHERE id = %s", (cid,)).fetchone()
        if not row:
            raise HTTPException(404, "Conversation not found")

    @app.get("/api/conversations/{cid}/messages", dependencies=protected)
    def messages(cid: UUID):
        with db.connect() as conn:
            require_conversation(conn, cid)
            return conn.execute(
                "SELECT * FROM jobs WHERE conversation_id = %s ORDER BY sequence", (cid,)
            ).fetchall()

    @app.post("/api/conversations/{cid}/messages", dependencies=protected, status_code=202)
    def send(cid: UUID, body: MessageInput):
        with db.connect() as conn:
            # Serialize submissions, including conflicting UUID use across conversations.
            conn.execute("SELECT pg_advisory_xact_lock(728346127)")
            require_conversation(conn, cid)
            existing = conn.execute(
                "SELECT * FROM jobs WHERE id = %s", (body.request_id,)
            ).fetchone()
            if existing:
                if existing["conversation_id"] != cid or existing["content"] != body.content:
                    raise HTTPException(409, "Request ID already used for a different message")
                return existing
            unfinished = conn.execute(
                "SELECT id FROM jobs WHERE conversation_id = %s AND status <> 'completed'", (cid,)
            ).fetchone()
            if unfinished:
                raise HTTPException(409, "Finish or retry the current request first")
            return conn.execute(
                "INSERT INTO jobs(id, conversation_id, content) VALUES (%s, %s, %s) RETURNING *",
                (body.request_id, cid, body.content),
            ).fetchone()

    @app.post("/api/jobs/{jid}/retry", dependencies=protected, status_code=202)
    def retry(jid: UUID):
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = %s FOR UPDATE", (jid,)).fetchone()
            if not row:
                raise HTTPException(404, "Request not found")
            if row["status"] != "failed":
                raise HTTPException(409, "Only failed requests can be retried")
            return conn.execute(
                "UPDATE jobs SET status = 'queued', error = NULL, updated_at = now() "
                "WHERE id = %s RETURNING *",
                (jid,),
            ).fetchone()

    @app.get("/api/shopping-list", dependencies=protected)
    def shopping_list():
        with db.connect() as conn:
            return conn.execute("SELECT name FROM shopping_items ORDER BY name").fetchall()

    return app
