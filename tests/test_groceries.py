from concurrent.futures import ThreadPoolExecutor

from test_accounts import member
from test_poc import ScriptedModel, answer, submit, tool_call, work

from household.db import Database


def add(client, name="milk"):
    response = client.post("/api/shopping-list", json={"name": name})
    assert response.status_code == 201
    return response.json()


def patch(client, item, **changes):
    return client.patch(
        "/api/shopping-list", json={"name": item["name"], "revision": item["revision"], **changes}
    )


def test_direct_actions_and_stale_edits(client):
    milk = add(client, " MILK ")
    assert milk["name"] == "milk" and milk["checked"] is False
    checked = patch(client, milk, checked=True)
    assert checked.status_code == 200 and checked.json()["checked"] is True
    assert patch(client, milk, new_name="oat milk").status_code == 409
    renamed = patch(client, checked.json(), new_name="2 c oat milk")
    assert renamed.status_code == 200
    assert renamed.json()["requirement"]["term"] == "oat milk"
    assert (
        client.request(
            "DELETE",
            "/api/shopping-list",
            json={"name": renamed.json()["name"], "revision": renamed.json()["revision"]},
        ).status_code
        == 204
    )
    assert client.get("/api/shopping-list").json() == []


def test_duplicate_rename_and_readded_item_conflict(client):
    milk = add(client)
    add(client, "eggs")
    assert patch(client, milk, new_name=" EGGS ").status_code == 409
    assert (
        client.request(
            "DELETE",
            "/api/shopping-list",
            json={"name": milk["name"], "revision": milk["revision"]},
        ).status_code
        == 204
    )
    add(client)
    assert patch(client, milk, checked=True).status_code == 409
    assert client.post("/api/shopping-list", json={"name": " "}).status_code == 422


def test_command_context_is_private_stable_and_not_in_chat_navigation(client, app):
    response = client.post("/api/grocery-commands")
    assert response.status_code == 200
    cid = response.json()["id"]
    assert client.post("/api/grocery-commands").json()["id"] == cid
    assert cid not in {c["id"] for c in client.get("/api/conversations").json()}
    with member(app, 1) as other:
        assert other.get(f"/api/conversations/{cid}/messages").status_code == 404
        assert other.post("/api/grocery-commands").json()["id"] != cid


def test_parallel_command_context_creation(client, app):
    def create(_):
        return client.post("/api/grocery-commands").json()["id"]

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert len(set(pool.map(create, range(3)))) == 1


def test_worker_reopens_picked_up_item_and_preserves_revision_on_duplicate(client, app):
    milk = add(client)
    assert add(client)["revision"] == milk["revision"]
    checked = patch(client, milk, checked=True).json()
    cid = client.post("/api/grocery-commands").json()["id"]
    submit(client, cid, "Add milk")
    work(app, ScriptedModel(tool_call("add_items", {"items": ["milk"]}), answer("Added.")))
    active = client.get("/api/shopping-list").json()[0]
    assert active["checked"] is False and active["revision"] != checked["revision"]


def test_mutations_require_csrf_and_auth(client):
    client.headers.pop("X-CSRF-Token")
    assert client.post("/api/shopping-list", json={"name": "milk"}).status_code == 403
    assert client.post("/api/grocery-commands").status_code == 403
    client.cookies.clear()
    assert client.get("/api/shopping-list").status_code == 401


def test_migration_preserves_checked_state(client, app):
    milk = add(client)
    patch(client, milk, checked=True)
    Database(app.state.settings.database_url).setup()
    assert client.get("/api/shopping-list").json()[0]["checked"] is True


def test_recipe_confirmation_reopens_picked_up_item_only_once(client, app, monkeypatch):
    from test_recipe_import import preview

    item = add(client, "2 lb chicken")
    patch(client, item, checked=True)
    _, _, draft = preview(client, app, monkeypatch)
    path = f"/api/recipe-imports/{draft['recipe_id']}/confirm"
    assert client.post(path, json={"selected_indices": [0]}).status_code == 200
    active = client.get("/api/shopping-list").json()[0]
    assert active["checked"] is False
    checked = patch(client, active, checked=True).json()
    assert client.post(path, json={"selected_indices": [0]}).status_code == 200
    assert client.get("/api/shopping-list").json()[0]["revision"] == checked["revision"]


def test_edit_invalidates_product_choice_but_check_preserves_it(client, app, monkeypatch):
    from test_product_selection import lookup

    search = lookup(client, app, monkeypatch)
    choice = {"search_id": search["id"], "candidate_id": "cream:0", "packages": 1, "remember": True}
    assert client.post("/api/products/select", json=choice).status_code == 200
    item = client.get("/api/shopping-list").json()[0]
    assert patch(client, item, checked=True).status_code == 200
    checked = client.get("/api/shopping-list").json()[0]
    assert checked["product_selection"] is not None
    assert patch(client, checked, new_name="1 cup heavy cream").status_code == 200
    assert client.get("/api/shopping-list").json()[0]["product_selection"] is None
    assert client.post("/api/products/select", json=choice).status_code == 404
    with app.state.auth.db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM product_preferences").fetchone()["n"] == 1


def test_list_tool_distinguishes_picked_up_items_and_shared_edits(client, app):
    import json

    item = add(client)
    with member(app, 1) as other:
        assert patch(other, item, checked=True).status_code == 200
    cid = client.post("/api/grocery-commands").json()["id"]
    submit(client, cid, "What do we need?")
    model = ScriptedModel(tool_call("list_items", {}), answer("All picked up."))
    work(app, model)
    result = next(m for m in model.seen[1] if m.type == "tool")
    assert json.loads(result.content) == {"items": [], "picked_up": ["milk"]}


def test_edit_and_delete_require_csrf(client):
    item = add(client)
    client.headers.pop("X-CSRF-Token")
    assert patch(client, item, checked=True).status_code == 403
    assert (
        client.request(
            "DELETE",
            "/api/shopping-list",
            json={"name": item["name"], "revision": item["revision"]},
        ).status_code
        == 403
    )
