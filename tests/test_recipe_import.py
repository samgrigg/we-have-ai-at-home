import pytest
from test_accounts import member
from test_poc import conversation, submit

from household.tools import execute_tool


def preview(client, app, monkeypatch, family=False):
    monkeypatch.setattr(
        "household.recipe_import.fetch_recipe",
        lambda url: {
            "source_url": url,
            "title": "Soup",
            "yield": "4 servings",
            "ingredients": ["1 lb chicken", "1/2 tsp salt", "1 cup corn"],
        },
    )
    cid = (
        next(
            c["id"] for c in client.get("/api/conversations").json() if c["visibility"] == "family"
        )
        if family
        else conversation(client)
    )
    job = submit(client, cid, "Import https://recipe.example/soup without salt").json()
    db = app.state.auth.db
    source = execute_tool(
        db, job["id"], "read", "read_recipe", {"url": "https://recipe.example/soup"}
    )
    result = execute_tool(
        db,
        job["id"],
        "preview",
        "prepare_recipe_import",
        {"recipe_id": source["recipe_id"], "multiplier": 2, "omit_indices": [1]},
    )
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET status='completed',response='Review the ingredients' WHERE id=%s",
            (job["id"],),
        )
    return cid, job, result


def test_preview_confirmation_is_required_replay_safe_and_attributed(client, app, monkeypatch):
    cid, job, draft = preview(client, app, monkeypatch)
    assert client.get("/api/shopping-list").json() == []
    with pytest.raises(ValueError, match="confirm"):
        execute_tool(
            app.state.auth.db, job["id"], "bypass", "add_items", {"items": ["2 lb chicken"]}
        )
    listed = client.get(f"/api/conversations/{cid}/recipe-imports").json()
    assert listed[0]["ingredients"][1]["selected"] is False
    assert listed[0]["ingredients"][0]["text"] == "2 lb chicken"
    path = f"/api/recipe-imports/{draft['recipe_id']}/confirm"
    assert client.post(path, json={"selected_indices": [0, 2]}).status_code == 200
    assert client.post(path, json={"selected_indices": [0, 2]}).status_code == 200
    items = client.get("/api/shopping-list").json()
    assert [x["name"] for x in items] == ["2 cup corn", "2 lb chicken"]
    assert all(x["added_by_name"] == "Member 0" for x in items)
    assert client.post(path, json={"selected_indices": [1]}).status_code == 409


def test_other_member_cannot_read_private_or_confirm_family_preview(client, app, monkeypatch):
    cid, job, draft = preview(client, app, monkeypatch)
    with member(app, 1) as other:
        assert other.get(f"/api/conversations/{cid}/recipe-imports").status_code == 404
        assert (
            other.post(
                f"/api/recipe-imports/{draft['recipe_id']}/confirm", json={"selected_indices": [0]}
            ).status_code
            == 404
        )
    # Clear pending preview before preparing in the shared chat.
    assert client.post(f"/api/recipe-imports/{draft['recipe_id']}/dismiss").status_code == 204
    cid, job, draft = preview(client, app, monkeypatch, family=True)
    with member(app, 1) as other:
        assert other.get(f"/api/conversations/{cid}/recipe-imports").status_code == 200
        assert (
            other.post(
                f"/api/recipe-imports/{draft['recipe_id']}/confirm", json={"selected_indices": [0]}
            ).status_code
            == 403
        )


def test_confirm_rejects_csrf_invalid_selection_and_failed_job(client, app, monkeypatch):
    cid, job, draft = preview(client, app, monkeypatch)
    path = f"/api/recipe-imports/{draft['recipe_id']}/confirm"
    assert client.post(path, json={"selected_indices": []}).status_code == 422
    assert client.post(path, json={"selected_indices": [99]}).status_code == 422
    assert (
        client.post(
            path, json={"selected_indices": [0]}, headers={"X-CSRF-Token": "wrong"}
        ).status_code
        == 403
    )
    with app.state.auth.db.connect() as conn:
        conn.execute("UPDATE jobs SET status='failed' WHERE id=%s", (job["id"],))
    assert client.post(path, json={"selected_indices": [0]}).status_code == 409
    assert client.get("/api/shopping-list").json() == []


def test_real_graph_prepares_recipe_and_replays_without_refetch(client, app, monkeypatch):
    from langchain_core.messages import AIMessage
    from test_poc import ScriptedModel, answer, tool_call, work

    fetched = []

    def fetch(url):
        fetched.append(url)
        return {
            "source_url": url,
            "title": "Dinner",
            "yield": "2",
            "ingredients": ["1 cup rice", "salt to taste"],
        }

    monkeypatch.setattr("household.recipe_import.fetch_recipe", fetch)
    cid = conversation(client)
    job = submit(client, cid, "Import https://recipe.example/dinner without salt").json()

    class RecipeModel(ScriptedModel):
        def invoke(self, messages):
            if len(self.seen) == 1:
                import json

                source = json.loads(messages[-1].content)
                self.responses = iter(
                    [
                        AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "name": "prepare_recipe_import",
                                    "args": {"recipe_id": source["recipe_id"], "omit_indices": [1]},
                                    "id": "prepare",
                                    "type": "tool_call",
                                }
                            ],
                        ),
                        answer("Review and confirm the ingredients below."),
                    ]
                )
            return super().invoke(messages)

    work(
        app, RecipeModel(tool_call("read_recipe", {"url": "https://recipe.example/dinner"}, "read"))
    )
    rows = client.get(f"/api/conversations/{cid}/recipe-imports").json()
    assert len(rows) == 1 and rows[0]["can_confirm"]
    replay = execute_tool(
        app.state.auth.db,
        job["id"],
        "read",
        "read_recipe",
        {"url": "https://recipe.example/dinner"},
    )
    assert replay["recipe_id"] == rows[0]["id"]
    assert len(fetched) == 1
    assert client.get("/api/shopping-list").json() == []


def test_recipe_read_in_same_tool_batch_prevents_earlier_mutation(client, app, monkeypatch):
    from langchain_core.messages import AIMessage
    from test_poc import ScriptedModel, answer, work

    monkeypatch.setattr(
        "household.recipe_import.fetch_recipe",
        lambda url: {"source_url": url, "title": "Recipe", "yield": "1", "ingredients": ["milk"]},
    )
    cid = conversation(client)
    submit(client, cid, "Please import a recipe for dinner")
    work(
        app,
        ScriptedModel(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "add_items",
                        "args": {"items": ["unconfirmed milk"]},
                        "id": "early",
                        "type": "tool_call",
                    },
                    {
                        "name": "read_recipe",
                        "args": {"url": "https://recipe.example/dinner"},
                        "id": "read",
                        "type": "tool_call",
                    },
                ],
            ),
            answer("Please review the recipe."),
        ),
    )
    assert client.get("/api/shopping-list").json() == []


def test_family_draft_does_not_block_other_members_unrelated_shopping(client, app, monkeypatch):
    cid, job, draft = preview(client, app, monkeypatch, family=True)
    with member(app, 1) as other:
        next_job = submit(other, cid, "Add apples").json()
        execute_tool(
            app.state.auth.db, next_job["id"], "apples", "add_items", {"items": ["apples"]}
        )
    assert client.get("/api/shopping-list").json()[0]["name"] == "apples"


def test_fetch_does_not_hold_shared_list_lock(client, app, monkeypatch):
    def fetch(url):
        with app.state.auth.db.connect(autocommit=True) as conn:
            assert conn.execute("SELECT pg_try_advisory_lock(728346128) AS acquired").fetchone()[
                "acquired"
            ]
            conn.execute("SELECT pg_advisory_unlock(728346128)")
        return {"source_url": url, "title": "Recipe", "yield": "1", "ingredients": ["milk"]}

    monkeypatch.setattr("household.recipe_import.fetch_recipe", fetch)
    job = submit(client, conversation(client), "Read https://recipe.example/recipe").json()
    execute_tool(
        app.state.auth.db,
        job["id"],
        "read",
        "read_recipe",
        {"url": "https://recipe.example/recipe"},
    )
