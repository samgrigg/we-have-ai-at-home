import unicodedata
from contextlib import nullcontext

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator

from household.db import Database
from household.recipe_import import RECIPE_TOOLS, RecipePreview, RecipeURL, recipe_tool
from household.telemetry import stage


class Items(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[str] = Field(min_length=1, max_length=30)

    @field_validator("items")
    @classmethod
    def normalize(cls, values):
        result = []
        for value in values:
            name = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
            if not name or len(name) > 120:
                raise ValueError("Each item must contain 1–120 characters")
            result.append(name)
        return list(dict.fromkeys(result))


TOOL_SCHEMAS = [
    *RECIPE_TOOLS,
    {
        "name": "list_items",
        "description": "Read the current shared household shopping list from the database.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    *[
        {
            "name": name,
            "description": description,
            "parameters": Items.model_json_schema(),
        }
        for name, description in [
            (
                "add_items",
                "Add named items to the shared shopping list. Existing items are kept once.",
            ),
            ("remove_items", "Remove named items from the shared shopping list."),
        ]
    ],
]


def execute_tool(
    db: Database, job_id, call_id: str, name: str, args: dict, connection=None, trace=None
):
    if name not in {
        "list_items",
        "add_items",
        "remove_items",
        "read_recipe",
        "prepare_recipe_import",
    }:
        raise ValueError("Unknown shopping-list tool")
    if name in {"read_recipe", "prepare_recipe_import"}:
        (RecipeURL if name == "read_recipe" else RecipePreview).model_validate(args)
        items = []
    elif name == "list_items":
        if args:
            raise ValueError("list_items takes no arguments")
        items = []
    else:
        items = Items.model_validate(args).items
    with (
        nullcontext(connection) if connection is not None else db.connect() as conn,
        stage(trace, "sql.tool_transaction"),
        conn.transaction(),
    ):

        def query(operation, sql, parameters=None):
            with stage(trace, operation):
                return conn.execute(sql, parameters)

        # Tool effects and receipts are atomic, including cross-conversation mutations.
        if name in {"read_recipe", "prepare_recipe_import"}:
            # Serialize replay of this call without holding the household list lock
            # across slow external networking.
            query(
                "sql.recipe_call_lock",
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,728346130))",
                (str(job_id) + ":" + call_id,),
            )
        else:
            query("sql.tool_lock", "SELECT pg_advisory_xact_lock(728346128)")
        receipt = query(
            "sql.receipt_lookup",
            "SELECT * FROM tool_receipts WHERE job_id = %s AND call_id = %s",
            (job_id, call_id),
        ).fetchone()
        if receipt:
            if receipt["tool_name"] != name or receipt["arguments"] != args:
                raise ValueError("Tool call ID reused with different arguments")
            return receipt["result"]
        if name in {"read_recipe", "prepare_recipe_import"}:
            result = recipe_tool(conn, job_id, name, args)
            query(
                "sql.receipt_save",
                (
                    "INSERT INTO "
                    "tool_receipts(job_id,call_id,tool_name,arguments,result) "
                    "VALUES (%s,%s,%s,%s,%s)"
                ),
                (job_id, call_id, name, Jsonb(args), Jsonb(result)),
            )
            return result
        if name in {"add_items", "remove_items"}:
            blocked = query(
                "sql.recipe_confirmation_check",
                "SELECT 1 FROM jobs j WHERE j.id=%s AND (j.content ~* 'https?://' OR EXISTS "
                "(SELECT 1 FROM recipe_imports r WHERE r.job_id=j.id)) ",
                (job_id,),
            ).fetchone()
            if blocked:
                raise ValueError(
                    "Review and confirm recipe ingredients in the app before changing the list"
                )
        if name == "add_items":
            for item in items:
                query(
                    "sql.item_insert",
                    "INSERT INTO shopping_items(name,added_by) VALUES "
                    "(%s,(SELECT submitted_by FROM jobs WHERE id=%s)) ON CONFLICT DO NOTHING",
                    (item, job_id),
                )
        elif name == "remove_items":
            query("sql.items_delete", "DELETE FROM shopping_items WHERE name = ANY(%s)", (items,))
        result = {
            "items": [
                r["name"]
                for r in query(
                    "sql.items_read", "SELECT name FROM shopping_items ORDER BY name"
                ).fetchall()
            ]
        }
        query(
            "sql.receipt_save",
            "INSERT INTO tool_receipts(job_id, call_id, tool_name, arguments, result) "
            "VALUES (%s, %s, %s, %s, %s)",
            (job_id, call_id, name, Jsonb(args), Jsonb(result)),
        )
        return result
