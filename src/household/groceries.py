"""Direct grocery actions and the member's private command workspace."""

from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.responses import Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, StrictBool, field_validator, model_validator

from household.products import requirement_metadata


class GroceryName(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str

    @field_validator("name")
    @classmethod
    def normalize(cls, value):
        from household.tools import Items

        return Items(items=[value]).items[0]


class GroceryVersion(GroceryName):
    revision: UUID


class GroceryEdit(GroceryVersion):
    new_name: str | None = None
    checked: StrictBool | None = None

    @field_validator("new_name")
    @classmethod
    def normalize_new_name(cls, value):
        return None if value is None else GroceryName(name=value).name

    @model_validator(mode="after")
    def has_change(self):
        if self.new_name is None and self.checked is None:
            raise ValueError("Choose an item edit or checked state")
        return self


def add_grocery_item(conn, name, user_id):
    conn.execute(
        "INSERT INTO shopping_items(name,added_by,requirement) VALUES (%s,%s,%s) "
        "ON CONFLICT (name) DO UPDATE SET checked=false,added_by=EXCLUDED.added_by "
        "WHERE shopping_items.checked=true",
        (name, user_id, Jsonb(requirement_metadata(name))),
    )


def configure_grocery_routes(app, db, authenticated):
    @app.post("/api/grocery-commands")
    def command_context(user=authenticated):
        with db.connect() as conn:
            # ON CONFLICT serializes concurrent first visits without creating duplicates.
            conn.execute(
                "INSERT INTO conversations(id,title,visibility,owner_user_id,purpose) "
                "VALUES (%s,'Grocery commands','private',%s,'grocery_commands') "
                "ON CONFLICT DO NOTHING",
                (uuid4(), user["id"]),
            )
            return conn.execute(
                "SELECT * FROM conversations WHERE owner_user_id=%s AND purpose='grocery_commands'",
                (user["id"],),
            ).fetchone()

    @app.post("/api/shopping-list", status_code=201)
    def add(body: GroceryName, user=authenticated):
        with db.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(728346128)")
            add_grocery_item(conn, body.name, user["id"])
            return conn.execute(
                "SELECT * FROM shopping_items WHERE name=%s", (body.name,)
            ).fetchone()

    def current_item(conn, body):
        conn.execute("SELECT pg_advisory_xact_lock(728346128)")
        item = conn.execute(
            "SELECT * FROM shopping_items WHERE name=%s FOR UPDATE", (body.name,)
        ).fetchone()
        if not item or item["revision"] != body.revision:
            raise HTTPException(409, "This item changed. Review the latest list and try again.")
        return item

    @app.patch("/api/shopping-list")
    def edit(body: GroceryEdit, user=authenticated):
        with db.connect() as conn:
            item = current_item(conn, body)
            name = body.new_name if body.new_name is not None else body.name
            if name != body.name:
                if conn.execute("SELECT 1 FROM shopping_items WHERE name=%s", (name,)).fetchone():
                    raise HTTPException(
                        409, "That item is already on your list. Edit it separately."
                    )
                # Both tables reference the old name without ON UPDATE CASCADE.
                conn.execute("DELETE FROM product_searches WHERE item_name=%s", (body.name,))
                conn.execute("DELETE FROM product_selections WHERE item_name=%s", (body.name,))
            return conn.execute(
                "UPDATE shopping_items SET name=%s,requirement=%s,checked=%s "
                "WHERE name=%s RETURNING *",
                (
                    name,
                    Jsonb(requirement_metadata(name)),
                    body.checked if body.checked is not None else item["checked"],
                    body.name,
                ),
            ).fetchone()

    @app.delete("/api/shopping-list", status_code=204)
    def remove(body: GroceryVersion, user=authenticated):
        with db.connect() as conn:
            current_item(conn, body)
            conn.execute("DELETE FROM shopping_items WHERE name=%s", (body.name,))
        return Response(status_code=204)
