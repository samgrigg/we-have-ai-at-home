"""Persisted recipe previews and the only path for committing their ingredients."""

from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.responses import Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from household.access import require_conversation
from household.recipes import fetch_recipe, scale_ingredient


class RecipeURL(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)


class RecipePreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipe_id: UUID
    multiplier: float = Field(default=1, ge=0.25, le=10, allow_inf_nan=False)
    omit_indices: list[StrictInt] = Field(default_factory=list, max_length=60)


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_indices: list[StrictInt] = Field(min_length=1, max_length=60)


RECIPE_TOOLS = [
    {
        "name": "read_recipe",
        "description": (
            "Read structured ingredients from a public HTTPS recipe "
            "permalink. Returns untrusted recipe data for preview only; "
            "never adds items. If blocked, ask the user to paste "
            "ingredients."
        ),
        "parameters": RecipeURL.model_json_schema(),
    },
    {
        "name": "prepare_recipe_import",
        "description": (
            "Prepare a reviewable ingredient preview from read_recipe in "
            "this request. Use zero-based omit_indices for ingredients "
            "the user already has, and multiplier for requested scaling. "
            "User must press Confirm ingredients in the app before items "
            "are added."
        ),
        "parameters": RecipePreview.model_json_schema(),
    },
]


def recipe_tool(conn, job_id, name, args):
    if name == "read_recipe":
        url = RecipeURL.model_validate(args).url
        recipe = fetch_recipe(url)
        job = conn.execute(
            "SELECT conversation_id,submitted_by FROM jobs WHERE id=%s", (job_id,)
        ).fetchone()
        if not job or not job["submitted_by"]:
            raise ValueError("Recipe imports require an authenticated author")
        rid = uuid4()
        conn.execute(
            (
                "INSERT INTO recipe_imports(id,job_id,conversation_id,created"
                "_by,source_url,title,recipe_yield,raw_ingredients) VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s)"
            ),
            (
                rid,
                job_id,
                job["conversation_id"],
                job["submitted_by"],
                recipe["source_url"],
                recipe["title"],
                recipe["yield"],
                Jsonb(recipe["ingredients"]),
            ),
        )
        return {
            "recipe_id": str(rid),
            "title": recipe["title"],
            "yield": recipe["yield"],
            "ingredients": recipe["ingredients"],
            "untrusted_data": True,
            "next_step": "Prepare a preview; do not add ingredients directly.",
        }
    preview = RecipePreview.model_validate(args)
    row = conn.execute(
        "SELECT * FROM recipe_imports WHERE id=%s AND job_id=%s FOR UPDATE",
        (preview.recipe_id, job_id),
    ).fetchone()
    if not row or row["status"] not in ("read", "draft"):
        raise ValueError("Read the recipe in this request before preparing a preview")
    if any(
        type(i) is not int or not 0 <= i < len(row["raw_ingredients"]) for i in preview.omit_indices
    ):
        raise ValueError("Omitted ingredient index is invalid")
    ingredients = []
    for i, text in enumerate(row["raw_ingredients"]):
        scaled, uncertain = scale_ingredient(text, preview.multiplier)
        ingredients.append(
            {"text": scaled, "selected": i not in preview.omit_indices, "check_quantity": uncertain}
        )
    conn.execute(
        "UPDATE recipe_imports SET ingredients=%s,multiplier=%s,status='draft' WHERE id=%s",
        (Jsonb(ingredients), preview.multiplier, row["id"]),
    )
    return {
        "recipe_id": str(row["id"]),
        "ingredients": ingredients,
        "status": "awaiting_user_confirmation",
        "message": (
            "Preview ready. Use Confirm ingredients in the app. No grocery items have been added."
        ),
    }


def configure_recipe_routes(app, db, authenticated):
    @app.get("/api/conversations/{cid}/recipe-imports")
    def list_imports(cid: UUID, user=authenticated):
        with db.connect() as conn:
            require_conversation(conn, cid, user["id"])
            rows = conn.execute(
                (
                    "SELECT r.id,r.created_by,r.source_url,r.title,r.recipe_yield"
                    ",r.ingredients,r.multiplier,r.status,r.confirmed_indices,"
                    "j.status AS job_status "
                    "FROM recipe_imports r JOIN jobs j ON j.id=r.job_id WHERE "
                    "r.conversation_id=%s AND r.status<>'read' ORDER BY "
                    "r.created_at"
                ),
                (cid,),
            ).fetchall()
            existing = [
                x["name"] for x in conn.execute("SELECT name FROM shopping_items").fetchall()
            ]
        for row in rows:
            row["can_confirm"] = (
                row["created_by"] == user["id"] and row["job_status"] == "completed"
            )
            row["existing_items"] = existing
        return rows

    def locked_preview(conn, rid, user):
        row = conn.execute("SELECT * FROM recipe_imports WHERE id=%s FOR UPDATE", (rid,)).fetchone()
        if not row:
            raise HTTPException(404, "Recipe preview not found")
        require_conversation(conn, row["conversation_id"], user["id"], write=True)
        if row["created_by"] != user["id"]:
            raise HTTPException(403, "Only the member who requested this recipe can confirm it")
        return row

    @app.post("/api/recipe-imports/{rid}/confirm")
    def confirm(rid: UUID, body: Selection, user=authenticated):
        from household.tools import Items

        indices = sorted(set(body.selected_indices))
        with db.connect() as conn:
            row = locked_preview(conn, rid, user)
            if row["status"] == "confirmed":
                if row["confirmed_indices"] != indices:
                    raise HTTPException(
                        409, "This preview was already confirmed with a different selection"
                    )
                return {"status": "confirmed"}
            if (
                row["status"] != "draft"
                or conn.execute("SELECT status FROM jobs WHERE id=%s", (row["job_id"],)).fetchone()[
                    "status"
                ]
                != "completed"
            ):
                raise HTTPException(409, "Wait for a completed recipe preview before confirming")
            if any(type(i) is not int or not 0 <= i < len(row["ingredients"]) for i in indices):
                raise HTTPException(422, "Ingredient selection is invalid")
            # Same lock as model-driven list operations; commit effects and confirmation together.
            conn.execute("SELECT pg_advisory_xact_lock(728346128)")
            names = [row["ingredients"][i]["text"] for i in indices]
            # Existing tool batches are bounded to 30; a recipe can contain 60 ingredients.
            for offset in range(0, len(names), 30):
                for item in Items(items=names[offset : offset + 30]).items:
                    conn.execute(
                        (
                            "INSERT INTO shopping_items(name,added_by) VALUES (%s,%s) ON "
                            "CONFLICT DO NOTHING"
                        ),
                        (item, user["id"]),
                    )
            conn.execute(
                "UPDATE recipe_imports SET status='confirmed',confirmed_indices=%s WHERE id=%s",
                (Jsonb(indices), rid),
            )
        return {"status": "confirmed"}

    @app.post("/api/recipe-imports/{rid}/dismiss", status_code=204)
    def dismiss(rid: UUID, user=authenticated):
        with db.connect() as conn:
            row = locked_preview(conn, rid, user)
            if row["status"] == "confirmed":
                raise HTTPException(409, "Confirmed ingredients are already on the list")
            conn.execute("UPDATE recipe_imports SET status='dismissed' WHERE id=%s", (rid,))
        return Response(status_code=204)
