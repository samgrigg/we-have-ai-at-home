from datetime import UTC, datetime, timedelta

from test_accounts import member
from test_poc import conversation, submit
from test_products import product

from household.tools import execute_tool


def lookup(client, app, monkeypatch):
    monkeypatch.setattr(
        app.state.kroger,
        "search",
        lambda term: [
            product("cream", "Heavy Whipping Cream", "1 pt"),
            product("large", "Heavy Whipping Cream", "1 qt", 5),
        ],
    )
    job = submit(client, conversation(client), "Add cream").json()
    execute_tool(
        app.state.auth.db, job["id"], "add", "add_items", {"items": ["1/2 cup heavy cream"]}
    )
    response = client.post("/api/products/search", json={"item_name": "1/2 cup heavy cream"})
    assert response.status_code == 200
    return response.json()


def test_suggestions_are_read_only_and_selected_product_is_persisted(client, app, monkeypatch):
    result = lookup(client, app, monkeypatch)
    assert result["location_id"] == "70600153"
    assert result["candidates"][0]["packages"] == 1
    assert client.get("/api/shopping-list").json()[0]["product_selection"] is None
    data = {"search_id": result["id"], "candidate_id": "cream:0", "packages": 1, "remember": True}
    assert client.post("/api/products/select", json=data).status_code == 200
    assert client.post("/api/products/select", json=data).status_code == 200
    item = client.get("/api/shopping-list").json()[0]
    assert item["name"] == "1/2 cup heavy cream"
    assert item["product_selection"]["product"]["product_id"] == "cream"
    assert item["product_selection"]["selected_by_name"] == "Member 0"
    again = client.post("/api/products/search", json={"item_name": item["name"]}).json()
    assert again["candidates"][0]["preferred"] is True


def test_selection_checks_csrf_snapshot_stock_and_age(client, app, monkeypatch):
    result = lookup(client, app, monkeypatch)
    data = {"search_id": result["id"], "candidate_id": "invented", "packages": 1}
    assert client.post("/api/products/select", json=data).status_code == 422
    data["candidate_id"] = "cream:0"
    assert (
        client.post(
            "/api/products/select", json=data, headers={"X-CSRF-Token": "wrong"}
        ).status_code
        == 403
    )
    with app.state.auth.db.connect() as conn:
        conn.execute(
            "UPDATE product_searches SET checked_at=%s", (datetime.now(UTC) - timedelta(hours=1),)
        )
    assert client.post("/api/products/select", json=data).status_code == 409
    assert client.get("/api/shopping-list").json()[0]["product_selection"] is None


def test_shared_selection_and_removed_item_search_are_checked(client, app, monkeypatch):
    result = lookup(client, app, monkeypatch)
    with member(app, 1) as other:
        assert (
            other.post(
                "/api/products/select",
                json={"search_id": result["id"], "candidate_id": "large:0", "packages": 1},
            ).status_code
            == 200
        )
    with app.state.auth.db.connect() as conn:
        conn.execute("DELETE FROM shopping_items")
    assert (
        client.post(
            "/api/products/select",
            json={"search_id": result["id"], "candidate_id": "large:0", "packages": 1},
        ).status_code
        == 404
    )
    assert client.post("/api/products/search", json={"item_name": "not on list"}).status_code == 404


def test_out_of_stock_and_insufficient_package_count_are_rejected(client, app, monkeypatch):
    lookup(client, app, monkeypatch)
    monkeypatch.setattr(
        app.state.kroger,
        "search",
        lambda term: [product("out", "Heavy Cream", "1 pt", stock="TEMPORARILY_OUT_OF_STOCK")],
    )
    result = client.post("/api/products/search", json={"item_name": "1/2 cup heavy cream"}).json()
    assert (
        client.post(
            "/api/products/select",
            json={"search_id": result["id"], "candidate_id": "out:0", "packages": 1},
        ).status_code
        == 409
    )
    with app.state.auth.db.connect() as conn:
        conn.execute(
            "INSERT INTO shopping_items(name,added_by) "
            "SELECT '3 cups heavy cream',added_by FROM shopping_items LIMIT 1"
        )
    monkeypatch.setattr(
        app.state.kroger, "search", lambda term: [product("small", "Heavy Cream", "1 pt")]
    )
    result = client.post("/api/products/search", json={"item_name": "3 cups heavy cream"}).json()
    assert result["candidates"][0]["packages"] == 2
    assert (
        client.post(
            "/api/products/select",
            json={"search_id": result["id"], "candidate_id": "small:0", "packages": 1},
        ).status_code
        == 422
    )
