from importlib.resources import files
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_poc import ScriptedModel, answer, conversation, submit, tool_call, work

from household.auth import COOKIE
from household.db import Database


def member(app, index):
    c = TestClient(app, base_url="http://localhost:8001")
    user = app.state.auth.enroll(
        {
            "sub": f"google-{index}",
            "email": f"member{index}@example.com",
            "email_verified": True,
            "name": f"Member {index}",
        }
    )
    token = app.state.auth.new_session(user["id"])
    c.cookies.set(COOKIE, token)
    c.headers.update(
        {"Origin": "http://localhost:8001", "X-CSRF-Token": app.state.auth.csrf(token)}
    )
    return c


def test_private_conversation_read_write_retry_and_request_id_are_isolated(client, app):
    cid = conversation(client)
    job = submit(client, cid, "Private request").json()
    work(app, ScriptedModel(RuntimeError("provider unavailable")))
    with member(app, 1) as other:
        assert cid not in {r["id"] for r in other.get("/api/conversations").json()}
        assert other.get(f"/api/conversations/{cid}/messages").status_code == 404
        assert submit(other, cid).status_code == 404
        assert other.post(f"/api/jobs/{job['id']}/retry").status_code == 404
        assert submit(other, conversation(other), "Private request", job["id"]).status_code == 404
        assert (
            other.post(
                "/api/conversations", json={"title": "Stolen", "owner_user_id": job["submitted_by"]}
            ).status_code
            == 422
        )


def test_all_five_members_can_use_family_chat_and_shared_list(client, app):
    family = next(c for c in client.get("/api/conversations").json() if c["visibility"] == "family")
    for index in range(5):
        with member(app, index) as c:
            assert submit(c, family["id"], f"Add item {index}").status_code == 202
            work(
                app,
                ScriptedModel(
                    tool_call("add_items", {"items": [f"item {index}"]}), answer("Added.")
                ),
            )
    jobs = client.get(f"/api/conversations/{family['id']}/messages").json()
    assert [j["author_name"] for j in jobs] == [f"Member {i}" for i in range(5)]
    items = client.get("/api/shopping-list").json()
    assert [i["added_by_name"] for i in items] == [f"Member {i}" for i in range(5)]


def test_private_history_does_not_enter_family_or_other_private_graph(client, app):
    private = conversation(client)
    submit(client, private, "Private history sentinel")
    work(app, ScriptedModel(answer("Private reply sentinel")))
    with member(app, 1) as other:
        family = next(
            c for c in other.get("/api/conversations").json() if c["visibility"] == "family"
        )
        for cid in [family["id"], conversation(other)]:
            submit(other, cid, "Hello")
            model = ScriptedModel(answer("Hello"))
            work(app, model)
            assert all("sentinel" not in m.content for m in model.seen[0])


def test_migration_archives_poc_and_resets_list_only_once(database_url):
    db = Database(database_url)
    cid = uuid4()
    with db.connect() as conn:
        conn.execute(files("household").joinpath("schema.sql").read_text())
        conn.execute("INSERT INTO conversations(id,title) VALUES (%s,'POC')", (cid,))
        conn.execute("INSERT INTO shopping_items(name) VALUES ('old disposable item')")
    db.setup()
    with db.connect() as conn:
        assert (
            conn.execute("SELECT visibility FROM conversations WHERE id=%s", (cid,)).fetchone()[
                "visibility"
            ]
            == "legacy_shared"
        )
        assert conn.execute("SELECT count(*) AS n FROM shopping_items").fetchone()["n"] == 0
        conn.execute("INSERT INTO shopping_items(name) VALUES ('new item')")
    db.setup()
    with db.connect() as conn:
        assert conn.execute("SELECT name FROM shopping_items").fetchone()["name"] == "new item"


def test_migration_refuses_unfinished_poc_jobs(database_url):
    db = Database(database_url)
    cid = uuid4()
    with db.connect() as conn:
        conn.execute(files("household").joinpath("schema.sql").read_text())
        conn.execute("INSERT INTO conversations(id,title) VALUES (%s,'POC')", (cid,))
        conn.execute(
            "INSERT INTO jobs(id,conversation_id,content) VALUES (%s,%s,'queued')", (uuid4(), cid)
        )
    with pytest.raises(Exception, match="Resolve unfinished POC jobs"):
        db.setup()


def test_archive_is_read_only_and_worker_rejects_tampered_private_owner(client, app):
    cid = conversation(client)
    db = Database(app.state.settings.database_url)
    with db.connect() as conn:
        conn.execute(
            "UPDATE conversations SET visibility='legacy_shared',owner_user_id=NULL WHERE id=%s",
            (cid,),
        )
    assert submit(client, cid).status_code == 409
    private = conversation(client)
    submit(client, private)
    with member(app, 1) as other:
        other_id = other.get("/api/me").json()["id"]
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET submitted_by=%s WHERE conversation_id=%s", (other_id, private)
        )
    model = ScriptedModel(answer("Must not run"))
    work(app, model)
    assert not model.seen
    assert client.get(f"/api/conversations/{private}/messages").json()[0]["status"] == "failed"


def test_removed_member_failed_request_can_be_skipped_without_blocking_family(client, app):
    family = next(c for c in client.get("/api/conversations").json() if c["visibility"] == "family")
    job = submit(client, family["id"]).json()
    app.state.settings.family_allowed_emails = app.state.settings.family_allowed_emails.replace(
        "member0@example.com", "replacement@example.com"
    )
    model = ScriptedModel(answer("Must not run"))
    work(app, model)
    assert not model.seen
    with member(app, 1) as other:
        assert other.post(f"/api/jobs/{job['id']}/cancel").status_code == 204
        assert submit(other, family["id"], "New request").status_code == 202
        work(app, ScriptedModel(answer("Handled.")))
        statuses = [
            j["status"] for j in other.get(f"/api/conversations/{family['id']}/messages").json()
        ]
        assert statuses == ["cancelled", "completed"]


def test_skipping_failed_request_preserves_completed_tool_effects(client, app):
    cid = conversation(client)
    job = submit(client, cid).json()
    work(
        app,
        ScriptedModel(
            tool_call("add_items", {"items": ["milk"]}), RuntimeError("inference failed")
        ),
    )
    with member(app, 1) as other:
        assert other.post(f"/api/jobs/{job['id']}/cancel").status_code == 404
    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 204
    assert client.get("/api/shopping-list").json()[0]["name"] == "milk"
    assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 409
