from importlib.resources import files
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from household.access import require_conversation
from household.auth import COOKIE, configure_auth
from household.config import Settings
from household.db import Database
from household.recipe_import import configure_recipe_routes


class ConversationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="New conversation", min_length=1, max_length=100)


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
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
    auth = configure_auth(app, db, settings)
    authenticated = Depends(auth.current)
    configure_recipe_routes(app, db, authenticated)
    static = files("household").joinpath("static")
    app.mount("/static", StaticFiles(directory=str(static), check_dir=False), name="static")

    @app.middleware("http")
    async def private_responses(request, call_next):
        # A host-only OAuth cookie must be created on the callback hostname.
        # Canonicalize browser entry points before generating any state.
        if request.url.path in {"/", "/signin", "/auth/login"} and (
            request.headers.get("host", "").lower()
            != urlsplit(settings.public_base_url).netloc.lower()
        ):
            response = RedirectResponse(
                settings.public_base_url + request.url.path, status_code=303
            )
        else:
            response = await call_next(request)
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/signin")
    def signin():
        return FileResponse(str(static.joinpath("signin.html")))

    @app.get("/")
    def index(request: Request):
        if not auth.lookup(request.cookies.get(COOKIE)):
            return RedirectResponse("/signin", status_code=303)
        return FileResponse(str(static.joinpath("index.html")))

    @app.get("/health")
    def health():
        try:
            with db.connect() as conn:
                conn.execute("SELECT 1 FROM users LIMIT 1")
        except Exception:
            raise HTTPException(503, "Database unavailable") from None
        return {"status": "ok"}

    @app.get("/api/conversations")
    def conversations(user=authenticated):
        with db.connect() as conn:
            return conn.execute(
                "SELECT * FROM conversations WHERE visibility IN ('family','legacy_shared') "
                "OR owner_user_id=%s ORDER BY created_at DESC",
                (user["id"],),
            ).fetchall()

    @app.post("/api/conversations", status_code=201)
    def create_conversation(body: ConversationInput, user=authenticated):
        with db.connect() as conn:
            return conn.execute(
                "INSERT INTO conversations(id,title,visibility,owner_user_id) "
                "VALUES (%s,%s,'private',%s) RETURNING *",
                (uuid4(), body.title, user["id"]),
            ).fetchone()

    @app.get("/api/conversations/{cid}/messages")
    def messages(cid: UUID, user=authenticated):
        with db.connect() as conn:
            require_conversation(conn, cid, user["id"])
            return conn.execute(
                "SELECT j.*,u.display_name AS author_name FROM jobs j LEFT JOIN users u "
                "ON u.id=j.submitted_by WHERE conversation_id=%s ORDER BY sequence",
                (cid,),
            ).fetchall()

    @app.post("/api/conversations/{cid}/messages", status_code=202)
    def send(cid: UUID, body: MessageInput, user=authenticated):
        with db.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(728346127)")
            require_conversation(conn, cid, user["id"], write=True)
            existing = conn.execute("SELECT * FROM jobs WHERE id=%s", (body.request_id,)).fetchone()
            if existing:
                if existing["submitted_by"] != user["id"]:
                    raise HTTPException(404, "Request not found")
                if existing["conversation_id"] != cid or existing["content"] != body.content:
                    raise HTTPException(409, "Request ID already used for a different message")
                return existing
            if conn.execute(
                "SELECT id FROM jobs WHERE conversation_id=%s "
                "AND status NOT IN ('completed','cancelled')",
                (cid,),
            ).fetchone():
                raise HTTPException(409, "Finish or retry the current request first")
            return conn.execute(
                "INSERT INTO jobs(id,conversation_id,content,submitted_by) VALUES (%s,%s,%s,%s) "
                "RETURNING *",
                (body.request_id, cid, body.content, user["id"]),
            ).fetchone()

    @app.post("/api/jobs/{jid}/retry", status_code=202)
    def retry(jid: UUID, user=authenticated):
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=%s FOR UPDATE", (jid,)).fetchone()
            if not row:
                raise HTTPException(404, "Request not found")
            require_conversation(conn, row["conversation_id"], user["id"], write=True)
            if row["status"] != "failed":
                raise HTTPException(409, "Only failed requests can be retried")
            return conn.execute(
                "UPDATE jobs SET status='queued',error=NULL,updated_at=now() "
                "WHERE id=%s RETURNING *",
                (jid,),
            ).fetchone()

    @app.get("/api/shopping-list")
    def shopping_list(user=authenticated):
        with db.connect() as conn:
            return conn.execute(
                "SELECT s.name,u.display_name AS added_by_name FROM shopping_items s "
                "LEFT JOIN users u ON u.id=s.added_by ORDER BY s.name"
            ).fetchall()

    @app.post("/api/jobs/{jid}/cancel", status_code=204)
    def cancel(jid: UUID, user=authenticated):
        from fastapi.responses import Response

        with db.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=%s FOR UPDATE", (jid,)).fetchone()
            if not row:
                raise HTTPException(404, "Request not found")
            require_conversation(conn, row["conversation_id"], user["id"], write=True)
            if row["status"] != "failed":
                raise HTTPException(409, "Only failed requests can be skipped")
            conn.execute("UPDATE jobs SET status='cancelled',updated_at=now() WHERE id=%s", (jid,))
        return Response(status_code=204)

    return app
