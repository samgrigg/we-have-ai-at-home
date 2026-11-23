"""Shared grocery product suggestions and choices, without cart or purchase actions."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from household.kroger import KrogerError
from household.products import parse_requirement, rank_products


class Search(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_name: str = Field(min_length=1, max_length=120)
    search_term: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("search_term")
    @classmethod
    def clean_term(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Search term is blank")
        return " ".join(value.split()) if value else value


class Choice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search_id: UUID
    candidate_id: str = Field(min_length=1, max_length=100)
    packages: StrictInt = Field(ge=1, le=99)
    remember: bool = False


def configure_product_routes(app, db, authenticated):
    @app.post("/api/products/search")
    def search(body: Search, user=authenticated):
        with db.connect() as conn:
            item = conn.execute(
                "SELECT name,created_at FROM shopping_items WHERE name=%s", (body.item_name,)
            ).fetchone()
            if not item:
                raise HTTPException(404, "Grocery item not found")
        requirement = parse_requirement(item["name"])
        if body.search_term:
            requirement["term"] = body.search_term.lower()
        location = app.state.kroger.location_id
        with db.connect() as conn:
            preference = conn.execute(
                (
                    "SELECT product_id FROM product_preferences WHERE "
                    "search_term=%s AND location_id=%s"
                ),
                (requirement["term"], location),
            ).fetchone()
        try:
            products = app.state.kroger.search(requirement["term"])
            candidates = rank_products(
                requirement, products, preference["product_id"] if preference else None
            )
        except KrogerError as exc:
            raise HTTPException(503, str(exc)) from None
        except (ValueError, TypeError, KeyError, ArithmeticError):
            raise HTTPException(
                502, "Kroger returned unsupported product data. Try a more specific search."
            ) from None
        serial = {
            **requirement,
            "amount": str(requirement["amount"]) if requirement["amount"] is not None else None,
        }
        rid = uuid4()
        with db.connect() as conn:
            # Do not hold any transaction/list lock while contacting Kroger.
            conn.execute("SELECT pg_advisory_xact_lock(728346128)")
            current = conn.execute(
                "SELECT created_at FROM shopping_items WHERE name=%s", (body.item_name,)
            ).fetchone()
            if not current or current["created_at"] != item["created_at"]:
                raise HTTPException(409, "The grocery item changed. Search again.")
            conn.execute("DELETE FROM product_searches WHERE checked_at<now()-interval '1 day'")
            row = conn.execute(
                (
                    "INSERT INTO product_searches(id,item_name,item_created_at,lo"
                    "cation_id,search_term,requirement,candidates) VALUES "
                    "(%s,%s,%s,%s,%s,%s,%s) RETURNING *"
                ),
                (
                    rid,
                    body.item_name,
                    item["created_at"],
                    location,
                    requirement["term"],
                    Jsonb(serial),
                    Jsonb(candidates),
                ),
            ).fetchone()
        return row

    @app.post("/api/products/select")
    def select(body: Choice, user=authenticated):
        with db.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(728346128)")
            search = conn.execute(
                (
                    "SELECT s.*,i.created_at AS current_item_created_at FROM "
                    "product_searches s JOIN shopping_items i ON "
                    "i.name=s.item_name WHERE s.id=%s"
                ),
                (body.search_id,),
            ).fetchone()
            if not search:
                raise HTTPException(404, "Product search no longer exists. Search again.")
            if (
                search["checked_at"] < datetime.now(UTC) - timedelta(minutes=30)
                or search["item_created_at"] != search["current_item_created_at"]
                or search["location_id"] != app.state.kroger.location_id
            ):
                raise HTTPException(409, "Product search has expired or changed. Search again.")
            candidate = next(
                (p for p in search["candidates"] if p["candidate_id"] == body.candidate_id), None
            )
            if not candidate:
                raise HTTPException(422, "Choose a product returned by this search")
            if not candidate["selectable"]:
                raise HTTPException(
                    409, "This product was reported out of stock. Choose another product."
                )
            if candidate["packages"] and body.packages < candidate["packages"]:
                raise HTTPException(
                    422, "Choose enough packages to cover the ingredient requirement"
                )
            conn.execute(
                (
                    "INSERT INTO product_selections(item_name,location_id,product"
                    ",packages,checked_at,selected_by) VALUES (%s,%s,%s,%s,%s,%s)"
                    " ON CONFLICT(item_name) DO UPDATE SET location_id=EXCLUDED.l"
                    "ocation_id,product=EXCLUDED.product,packages=EXCLUDED.packag"
                    "es,checked_at=EXCLUDED.checked_at,selected_by=EXCLUDED.selec"
                    "ted_by,selected_at=now()"
                ),
                (
                    search["item_name"],
                    search["location_id"],
                    Jsonb(candidate),
                    body.packages,
                    search["checked_at"],
                    user["id"],
                ),
            )
            if body.remember:
                conn.execute(
                    (
                        "INSERT INTO product_preferences(search_term,location_id,prod"
                        "uct_id,updated_by) VALUES (%s,%s,%s,%s) ON "
                        "CONFLICT(search_term,location_id) DO UPDATE SET product_id=E"
                        "XCLUDED.product_id,updated_by=EXCLUDED.updated_by,updated_at"
                        "=now()"
                    ),
                    (
                        search["search_term"],
                        search["location_id"],
                        candidate["product_id"],
                        user["id"],
                    ),
                )
        return {"status": "selected"}
