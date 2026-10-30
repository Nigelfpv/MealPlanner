"""Full weekly cycle: Claude plans via MCP, Miguel shops, stores, cooks, rates and rejects via the web API."""

from datetime import timedelta

from oauth_flow import tool

from app import services as S, units


def next_monday():
    return S.monday_of(S.today()) + timedelta(days=7)


CHILI = {
    "title": "Beef chili with rice",
    "description": "Mild chili, cooks once and gives a second portion for lunch.",
    "servings": 2, "prep_minutes": 15, "cook_minutes": 35, "tags": ["beef", "batch"],
    "ingredients": [
        {"name": "minced beef", "quantity": 300, "unit": "g", "name_nl": "rundergehakt", "category": "meat"},
        {"name": "onion", "quantity": 1, "unit": "pc", "prep": "finely chopped", "category": "vegetables",
         "name_nl": "ui"},
        {"name": "kidney beans", "quantity": 1, "unit": "can", "category": "canned", "name_nl": "kidneybonen"},
        {"name": "salt", "quantity": 1, "unit": "tsp", "category": "spices", "name_nl": "zout"},
        {"name": "rice", "quantity": 150, "unit": "g", "category": "grains", "name_nl": "rijst"},
    ],
    "steps": [
        {"text": "Fry [[2]] on heat 6 until soft.", "timers": [{"label": "Soften onion", "minutes": 5}]},
        {"text": "Add [[1]] and brown it.", "timers": [{"label": "Brown beef", "minutes": 6}]},
        {"text": "Add the beans and [[4]], simmer.", "timers": [{"label": "Simmer", "minutes": 20}]},
    ],
}

PASTA = {
    "title": "Pasta with cheese sauce",
    "servings": 1,
    "ingredients": [
        {"name": "pasta", "quantity": 120, "unit": "g", "category": "grains"},
        {"name": "grated cheese", "quantity": 50, "unit": "g", "category": "cheese"},
        {"name": "milk", "quantity": 0.5, "unit": "cup", "category": "dairy"},
    ],
    "steps": [{"text": "Boil the pasta.", "timers": [{"label": "Pasta", "seconds": 600}]}],
}


def test_units():
    assert units.norm_unit("Tablespoons") == "tbsp"
    assert round(units.convert(1, "tbsp", "g", units.default_density("salt")), 1) == 18.0
    assert units.convert(1, "cup", "ml") == 240
    assert units.convert(500, "ml", "kg", 1.03) == 0.515
    assert units.convert(2, "pc", "g", None, units.default_unit_weight("eggs")) == 120
    assert units.convert(1, "can", "g") is None


def test_web_requires_login():
    from fastapi.testclient import TestClient

    from app.main import app
    anon = TestClient(app, base_url="http://localhost", follow_redirects=False)
    assert anon.get("/api/plan").status_code == 401
    assert anon.get("/").status_code == 303


def test_full_week(client, token):
    mon = next_monday()
    d = lambda i: (mon + timedelta(days=i)).isoformat()  # noqa: E731

    # --- Claude: context, recipes, plan
    ctx = tool(client, token, "get_planning_context")
    assert any(x["item"] == "cucumber" for x in ctx["dislikes"])
    saved = tool(client, token, "save_recipes", {"recipes": [CHILI, PASTA]})["saved"]
    chili_id, pasta_id = saved[0]["id"], saved[1]["id"]
    wk = tool(client, token, "set_week_plan", {
        "week_start": d(0), "summary": "Test week",
        "meals": [
            {"date": d(0), "slot": "dinner", "recipe_id": chili_id, "servings": 2},
            {"date": d(1), "slot": "lunch", "recipe_id": chili_id, "is_leftover": True},
            {"date": d(1), "slot": "dinner", "recipe_title": "Pasta with cheese sauce"},
            {"date": d(2), "slot": "dinner", "title": "Eat out"},
        ]})
    assert len(wk["meals"]) == 4 and wk["summary"] == "Test week"
    assert wk["meals"][1]["display_title"] == "Leftovers: Beef chili with rice"

    totals = tool(client, token, "get_week_ingredient_totals", {"week_start": d(0)})
    by = {i["name"]: i for i in totals["ingredients"]}
    assert by["minced beef"]["needed"] == ["300 g"]
    assert by["salt"]["needed"] == ["6 g"]  # 1 tsp * 5 ml * 1.2 g/ml

    shop = tool(client, token, "update_shopping_list", {"clear_unchecked": True, "add": [
        {"name": "minced beef", "name_nl": "rundergehakt", "quantity": 500, "unit": "g", "category": "meat",
         "store": "Lidl", "offer": "1+1", "price": 4.5, "location": "fridge", "shelf_life_days": 2,
         "storage_advice": "Freeze 200 g flat in a bag"},
        {"name": "kidney beans", "quantity": 1, "unit": "can", "category": "canned", "store": "Lidl"},
        {"name": "grated cheese", "quantity": 150, "unit": "g", "category": "cheese"},
        {"name": "rice", "quantity": 1, "unit": "kg", "category": "grains"},
    ]})
    assert len(shop["items"]) == 4
    # aisle order: meat before cheese before grains before canned
    assert [i["category"] for i in shop["items"]] == ["meat", "cheese", "grains", "canned"]

    # --- Miguel: edits quantities while shopping, ticks, completes
    items = {i["name"]: i for i in client.get("/api/shopping").json()["items"]}
    r = client.patch(f"/api/shopping/items/{items['grated cheese']['id']}", json={"quantity": 200, "checked": True})
    assert r.status_code == 200 and r.json()["quantity"] == 200
    for n in ("minced beef", "rice"):
        client.patch(f"/api/shopping/items/{items[n]['id']}", json={"checked": True})
    trip = client.post("/api/shopping/complete", json={"keep_unchecked": True, "store": "Lidl"}).json()
    assert trip["status"] == "done" and len(trip["pantry_items"]) == 3
    pantry = {p["name"]: p for p in trip["pantry_items"]}
    assert pantry["minced beef"]["expires_at"] == (S.today() + timedelta(days=2)).isoformat()
    assert pantry["minced beef"]["storage_advice"] == "Freeze 200 g flat in a bag"
    assert pantry["rice"]["location"] == "pantry"
    assert pantry["grated cheese"]["expires_at"] == (S.today() + timedelta(days=21)).isoformat()
    # the unticked can stays on the list for next time
    left = client.get("/api/shopping").json()["items"]
    assert [i["name"] for i in left] == ["kidney beans"]

    # freezer move restarts expiry from the freezer shelf life
    moved = client.patch(f"/api/pantry/{pantry['minced beef']['id']}", json={"location": "freezer"}).json()
    assert moved["expires_at"] == (S.today() + timedelta(days=120)).isoformat()

    # --- cooking deducts from pantry
    week = client.get(f"/api/plan?start={d(0)}").json()
    chili_meal = week["meals"][0]
    props = client.get(f"/api/meals/{chili_meal['id']}/deductions").json()
    beef = next(p for p in props if p["pantry_name"] == "minced beef")
    assert beef["deduct"] == 300 and beef["left_after"] == 200
    rice = next(p for p in props if p["pantry_name"] == "rice")
    assert rice["deduct"] == 0.15 and rice["unit"] == "kg"
    done = client.post(f"/api/meals/{chili_meal['id']}/cooked", json={"deductions": props}).json()
    assert done["status"] == "cooked"
    p_now = {p["name"]: p for p in client.get("/api/pantry").json()}
    assert p_now["minced beef"]["quantity"] == 200

    # --- move / swap
    pasta_meal = week["meals"][2]
    eat_out = week["meals"][3]
    client.post(f"/api/meals/{pasta_meal['id']}/move", json={"date": d(2), "slot": "dinner"})
    week = client.get(f"/api/plan?start={d(0)}").json()
    where = {m["display_title"]: (m["date"], m["slot"]) for m in week["meals"]}
    assert where["Pasta with cheese sauce"] == (d(2), "dinner")
    assert where["Eat out"] == (d(1), "dinner")
    assert eat_out["id"]

    # --- rating and rejection
    client.post("/api/ratings", json={"meal_id": chili_meal["id"], "stars": 4, "would_repeat": "yes",
                                      "portion": "too_big", "comment": "Tasty, a bit much rice"})
    req = client.post("/api/requests", json={
        "meal_id": pasta_meal["id"], "kind": "swap_ingredients", "ingredients": ["milk"],
        "reason": "Use cream instead", "dislikes": [{"item": "low-fat milk", "severity": 1}]}).json()
    assert req["status"] == "open"

    ctx = tool(client, token, "get_planning_context")
    assert ctx["open_change_requests"][0]["ingredients"] == ["milk"]
    assert any(x["item"] == "low-fat milk" and x["severity"] == 1 for x in ctx["dislikes"])
    assert ctx["recent_ratings"][0]["stars"] == 4
    lib = {r["title"]: r for r in ctx["recipe_library"]}
    assert lib["Beef chili with rice"]["avg_stars"] == 4

    res = tool(client, token, "resolve_change_requests", {"resolutions": [{"id": req["id"], "note": "Swapped"}]})
    assert res[0]["status"] == "done"

    # --- recipe page data has converted-ready info
    rec = client.get(f"/api/recipes/{chili_id}").json()
    salt = next(i for i in rec["ingredients"] if i["name"] == "salt")
    assert salt["density"] == 1.2
    assert rec["steps"][2]["timers"][0]["seconds"] == 1200

    # --- replacing the plan keeps cooked/rated history
    wk = tool(client, token, "set_week_plan", {"week_start": d(0), "meals": [
        {"date": d(3), "slot": "lunch", "recipe_id": pasta_id}]})
    titles = sorted(m["display_title"] for m in wk["meals"])
    assert "Beef chili with rice" in titles and "Pasta with cheese sauce" in titles and "Eat out" not in titles


def test_tool_errors_are_readable(client, token):
    import pytest
    with pytest.raises(RuntimeError, match="not found"):
        tool(client, token, "edit_meals", {"operations": [{"action": "add", "date": "2026-11-02",
                                                           "slot": "dinner", "recipe_id": 99999}]})
