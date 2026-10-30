"""JSON API used by the web app (cookie-authenticated)."""

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from . import db, services as S, units
from .auth import require_session

router = APIRouter(prefix="/api", dependencies=[Depends(require_session)])

Payload = dict[str, Any]


def run(fn):
    try:
        with db.session() as conn:
            return fn(conn)
    except S.ServiceError as e:
        raise HTTPException(400, str(e))


# --------------------------------------------------------------------------- misc

@router.get("/bootstrap")
def bootstrap():
    return run(lambda c: {
        "settings": S.get_settings(c),
        "categories": S.list_categories(c),
        "units": units.tables(),
        "today": S.today().isoformat(),
        "open_requests": len(S.list_requests(c, "open")),
    })


@router.get("/settings")
def get_settings():
    return run(S.get_settings)


@router.put("/settings")
def put_settings(data: Payload = Body(...)):
    return run(lambda c: S.update_settings(c, data))


@router.get("/categories")
def categories():
    return run(S.list_categories)


@router.patch("/categories/{key}")
def patch_category(key: str, data: Payload = Body(...)):
    return run(lambda c: S.update_category(c, key, data))


@router.get("/ingredients")
def ingredients(q: str = ""):
    return run(lambda c: S.list_ingredients(c, q))


@router.patch("/ingredients/{ing_id}")
def patch_ingredient(ing_id: int, data: Payload = Body(...)):
    return run(lambda c: S.update_ingredient(c, ing_id, data))


@router.get("/expiry-suggestion")
def expiry_suggestion(name: str, location: str, start: str | None = None):
    def go(c):
        ing = S.find_ingredient(c, name)
        days = S.shelf_life_days(c, ing, None, location)
        return {"days": days, "expires_at": S.expiry_from(start or S.today(), days)}
    return run(go)


@router.get("/export")
def export():
    tables = ["settings", "categories", "ingredients", "recipes", "recipe_ingredients", "recipe_steps", "weeks",
              "meals", "ratings", "dislikes", "change_requests", "trips", "shopping_items", "pantry_items"]
    return run(lambda c: {t: db.rows(c.execute(f"SELECT * FROM {t}")) for t in tables})


# --------------------------------------------------------------------------- plan

@router.get("/plan")
def plan(start: str | None = None):
    return run(lambda c: S.get_week(c, start))


@router.post("/meals")
def add_meal(data: Payload = Body(...)):
    return run(lambda c: S.add_meal(c, data))


@router.patch("/meals/{meal_id}")
def patch_meal(meal_id: int, data: Payload = Body(...)):
    return run(lambda c: S.update_meal(c, meal_id, data))


@router.post("/meals/{meal_id}/move")
def move_meal(meal_id: int, data: Payload = Body(...)):
    return run(lambda c: S.move_meal(c, meal_id, data.get("date"), data.get("slot"), data.get("swap", True)))


@router.delete("/meals/{meal_id}")
def delete_meal(meal_id: int):
    return run(lambda c: S.delete_meal(c, meal_id) or {"ok": True})


@router.get("/meals/{meal_id}/deductions")
def deductions(meal_id: int):
    return run(lambda c: S.deduction_proposals(c, meal_id))


@router.post("/meals/{meal_id}/cooked")
def cooked(meal_id: int, data: Payload = Body(default={})):
    return run(lambda c: S.mark_cooked(c, meal_id, data.get("deductions")))


# --------------------------------------------------------------------------- ratings, dislikes, requests

@router.get("/ratings")
def ratings(recipe_id: int | None = None):
    return run(lambda c: S.list_ratings(c, recipe_id))


@router.post("/ratings")
def add_rating(data: Payload = Body(...)):
    return run(lambda c: S.add_rating(c, data))


@router.patch("/ratings/{rating_id}")
def patch_rating(rating_id: int, data: Payload = Body(...)):
    return run(lambda c: S.update_rating(c, rating_id, data))


@router.delete("/ratings/{rating_id}")
def delete_rating(rating_id: int):
    return run(lambda c: S.delete_rating(c, rating_id) or {"ok": True})


@router.get("/dislikes")
def dislikes():
    return run(S.list_dislikes)


@router.post("/dislikes")
def add_dislike(data: Payload = Body(...)):
    return run(lambda c: S.upsert_dislike(c, data.get("item"), data.get("severity", 2), data.get("note")))


@router.delete("/dislikes/{dislike_id}")
def delete_dislike(dislike_id: int):
    return run(lambda c: S.delete_dislike(c, dislike_id) or {"ok": True})


@router.get("/requests")
def requests(status: str | None = "open"):
    return run(lambda c: S.list_requests(c, status or None))


@router.post("/requests")
def add_request(data: Payload = Body(...)):
    return run(lambda c: S.create_request(c, data))


@router.patch("/requests/{req_id}")
def patch_request(req_id: int, data: Payload = Body(...)):
    return run(lambda c: S.resolve_request(c, req_id, data.get("status", "dismissed"), data.get("resolution")))


# --------------------------------------------------------------------------- recipes

@router.get("/recipes")
def recipes(q: str = "", archived: bool = False):
    return run(lambda c: S.list_recipes(c, q, archived))


@router.get("/recipes/{rid}")
def recipe(rid: int):
    return run(lambda c: S.get_recipe(c, rid))


@router.post("/recipes")
def add_recipe(data: Payload = Body(...)):
    return run(lambda c: S.get_recipe(c, S.save_recipe(c, {k: v for k, v in data.items() if k != "id"}, "user")))


@router.patch("/recipes/{rid}")
def patch_recipe(rid: int, data: Payload = Body(...)):
    return run(lambda c: S.get_recipe(c, S.save_recipe(c, {**data, "id": rid}, "user")))


@router.delete("/recipes/{rid}")
def delete_recipe(rid: int):
    return run(lambda c: S.delete_recipe(c, rid) or {"ok": True})


# --------------------------------------------------------------------------- shopping

@router.get("/shopping")
def shopping():
    return run(S.get_shopping)


@router.post("/shopping/items")
def add_item(data: Payload = Body(...)):
    return run(lambda c: S.add_shopping_item(c, data, "user"))


@router.patch("/shopping/items/{item_id}")
def patch_item(item_id: int, data: Payload = Body(...)):
    return run(lambda c: S.update_shopping_item(c, item_id, data))


@router.delete("/shopping/items/{item_id}")
def delete_item(item_id: int):
    return run(lambda c: S.delete_shopping_item(c, item_id) or {"ok": True})


@router.post("/shopping/complete")
def complete(data: Payload = Body(default={})):
    return run(lambda c: S.complete_trip(c, data.get("keep_unchecked", True), data.get("store"),
                                         data.get("total_spent"), data.get("note")))


@router.get("/trips")
def trips():
    return run(S.list_trips)


@router.get("/trips/{trip_id}")
def trip(trip_id: int):
    return run(lambda c: S.get_trip(c, trip_id))


# --------------------------------------------------------------------------- pantry

@router.get("/pantry")
def pantry(all: bool = False):
    return run(lambda c: S.list_pantry(c, all))


@router.post("/pantry")
def add_pantry(data: Payload = Body(...)):
    return run(lambda c: S.add_pantry_item(c, data))


@router.patch("/pantry/{pid}")
def patch_pantry(pid: int, data: Payload = Body(...)):
    return run(lambda c: S.update_pantry_item(c, pid, data))


@router.delete("/pantry/{pid}")
def delete_pantry(pid: int):
    return run(lambda c: S.delete_pantry_item(c, pid) or {"ok": True})


@router.post("/pantry/{pid}/restock")
def restock(pid: int):
    return run(lambda c: S.pantry_to_shopping(c, pid))
