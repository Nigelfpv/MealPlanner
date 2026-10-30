"""MCP server: the tools Claude uses through the custom connector."""

import json
from typing import Literal

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from . import config, db, services as S
from .auth import SCOPE, OAuthProvider

INSTRUCTIONS = """Miguel's self-hosted meal planner (menus, recipes, shopping list, pantry with expiry dates,
ratings and dislikes). Start every planning session with get_planning_context — it returns everything
(profile, dislikes with severity, pantry, ratings, open change requests, recipe library, current lists) plus a
step-by-step planning guide in `how_to_plan`. Write the whole week in one session: recipes, plan, shopping list
(with Dutch names, store/offers, storage location, shelf life and storage advice)."""

Slot = Literal["breakfast", "lunch", "dinner", "snack"]
Location = Literal["fridge", "freezer", "pantry"]


def _out(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _run(fn):
    try:
        with db.session() as conn:
            return _out(fn(conn))
    except S.ServiceError as e:
        raise ToolError(str(e))


# --------------------------------------------------------------------------- input models

class TimerIn(BaseModel):
    label: str = Field("Timer", description="Short label, e.g. 'Simmer sauce'")
    minutes: float | None = Field(None, description="Duration in minutes (or give seconds)")
    seconds: int | None = None


class StepIn(BaseModel):
    text: str = Field(..., description="Instruction. [[n]] inserts ingredient n (1-based) with its scaled amount.")
    timers: list[TimerIn] = Field(default_factory=list, description="Timers for this step (any waiting/cooking)")


class RecipeIngredientIn(BaseModel):
    name: str = Field(..., description="Ingredient name in English, singular where natural, e.g. 'minced beef'")
    quantity: float | None = None
    unit: str | None = Field(None, description="g, kg, ml, l, tsp, tbsp, cup, pc, clove, can, pack, pinch...")
    prep: str | None = Field(None, description="e.g. 'finely chopped'")
    group: str | None = Field(None, description="Optional sub-heading, e.g. 'For the sauce'")
    optional: bool = False
    name_nl: str | None = Field(None, description="Dutch name (stored in the ingredient catalogue)")
    category: str | None = Field(None, description="Category key (see categories in the planning context)")


class RecipeIn(BaseModel):
    id: int | None = Field(None, description="Give an id to update an existing recipe; omit to create")
    title: str | None = None
    description: str | None = None
    servings: float | None = Field(None, description="Portions the ingredient amounts make")
    prep_minutes: int | None = None
    cook_minutes: int | None = None
    tags: list[str] | None = None
    equipment: list[str] | None = None
    notes: str | None = Field(None, description="Tips, substitutions, what to watch out for")
    storage_notes: str | None = Field(None, description="How to store and reheat leftovers")
    ingredients: list[RecipeIngredientIn] | None = Field(None, description="Full list (replaces existing)")
    steps: list[StepIn] | None = Field(None, description="Full list (replaces existing)")
    archived: bool | None = None


class MealIn(BaseModel):
    date: str = Field(..., description="YYYY-MM-DD")
    slot: Slot
    recipe_id: int | None = None
    recipe_title: str | None = Field(None, description="Alternative to recipe_id: exact title of a saved recipe")
    title: str | None = Field(None, description="Free-text title for meals without a recipe")
    servings: float | None = Field(None, description="Portions to cook (include portions kept as leftovers)")
    is_leftover: bool = Field(False, description="True if this meal is eating leftovers of a recipe cooked earlier")
    notes: str | None = None


class MealOp(BaseModel):
    action: Literal["add", "update", "move", "delete"]
    meal_id: int | None = Field(None, description="Required for update/move/delete")
    date: str | None = None
    slot: Slot | None = None
    recipe_id: int | None = None
    recipe_title: str | None = None
    title: str | None = None
    servings: float | None = None
    is_leftover: bool | None = None
    notes: str | None = None
    status: Literal["planned", "cooked", "eaten", "skipped"] | None = None


class ShopItemIn(BaseModel):
    name: str = Field(..., description="English name, same as used in recipes")
    name_nl: str | None = Field(None, description="Dutch name as on the shelf label")
    quantity: float | None = Field(None, description="Amount to buy, matching a real package size")
    unit: str | None = None
    category: str | None = Field(None, description="Category key, decides the aisle grouping")
    store: str | None = Field(None, description="Lidl / Albert Heijn / Dirk, or empty for any")
    offer: str | None = Field(None, description="Offer details, e.g. '2e halve prijs t/m 9 nov'")
    price: float | None = Field(None, description="Estimated price in EUR")
    for_meals: str | None = Field(None, description="Which meals it is for, e.g. 'Chili (Mon), Wraps (Thu)'")
    location: Location | None = Field(None, description="Where to store it at home")
    shelf_life_days: int | None = Field(None, description="Days it keeps in that location from purchase")
    storage_advice: str | None = Field(None, description="What to do with it when getting home (portion/freeze...)")
    note: str | None = None


class ShopItemUpdate(BaseModel):
    id: int
    name: str | None = None
    name_nl: str | None = None
    quantity: float | None = None
    unit: str | None = None
    category: str | None = None
    store: str | None = None
    offer: str | None = None
    price: float | None = None
    for_meals: str | None = None
    location: Location | None = None
    shelf_life_days: int | None = None
    storage_advice: str | None = None
    note: str | None = None
    checked: bool | None = None


class PantryIn(BaseModel):
    name: str
    quantity: float | None = Field(None, description="Leave empty for 'some' (e.g. spices)")
    unit: str | None = None
    location: Location | None = None
    purchased_at: str | None = Field(None, description="YYYY-MM-DD, default today")
    expires_at: str | None = Field(None, description="YYYY-MM-DD, default computed from the category")
    category: str | None = None
    note: str | None = None
    low: bool = False


class PantryUpdate(BaseModel):
    id: int
    quantity: float | None = None
    unit: str | None = None
    location: Location | None = None
    expires_at: str | None = None
    note: str | None = None
    low: bool | None = None
    status: Literal["active", "used", "discarded"] | None = None


class IngredientIn(BaseModel):
    name: str
    name_nl: str | None = None
    category: str | None = None
    default_unit: str | None = None
    density: float | None = Field(None, description="Grams per millilitre (for spoon/cup <-> gram conversion)")
    unit_weight: float | None = Field(None, description="Grams per piece")
    location: Location | None = Field(None, description="Default storage location after purchase")
    shelf_life_days: int | None = Field(None, description="Default shelf life in that location")
    opened_days: int | None = Field(None, description="Shelf life once opened")
    storage_advice: str | None = None


class DislikeIn(BaseModel):
    item: str = Field(..., description="Ingredient, dish or trait, e.g. 'cucumber', 'very spicy food'")
    severity: Literal[1, 2, 3] = Field(2, description="1 mild (ok small/hidden), 2 avoid, 3 never")
    note: str | None = None


class Resolution(BaseModel):
    id: int
    status: Literal["done", "dismissed"] = "done"
    note: str | None = Field(None, description="What was changed")


# --------------------------------------------------------------------------- server

def build_mcp() -> FastMCP:
    mcp = FastMCP(
        "Meal Planner",
        instructions=INSTRUCTIONS,
        auth_server_provider=OAuthProvider(),
        auth=AuthSettings(
            issuer_url=config.BASE_URL,
            resource_server_url=f"{config.BASE_URL}/mcp",
            validate_token_resource=False,
            required_scopes=[SCOPE],
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]),
            revocation_options=RevocationOptions(enabled=True),
        ),
        host="0.0.0.0",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    # ------------------------------------------------------------------ reading

    @mcp.tool()
    def get_planning_context(weeks_back: int = 4) -> str:
        """Everything needed to plan meals: profile, dislikes, pantry & expiry, ratings, past meals,
        recipe library, this/next week, shopping list, open change requests and the planning guide."""
        return _run(lambda c: S.planning_context(c, weeks_back))

    @mcp.tool()
    def get_week(week_start: str | None = None) -> str:
        """Meal plan of the week containing week_start (YYYY-MM-DD, default this week), with ratings."""
        return _run(lambda c: S.get_week(c, week_start))

    @mcp.tool()
    def get_week_ingredient_totals(week_start: str) -> str:
        """Total ingredient amounts the still-planned meals of a week need, next to what is in the pantry."""
        return _run(lambda c: S.week_ingredient_totals(c, week_start))

    @mcp.tool()
    def search_recipes(query: str = "", include_archived: bool = False) -> str:
        """Search saved recipes by title, tag or ingredient. Returns ratings and how often each was cooked."""
        return _run(lambda c: S.list_recipes(c, query, include_archived))

    @mcp.tool()
    def get_recipe(recipe_id: int) -> str:
        """Full recipe: ingredients, steps with timers, ratings."""
        return _run(lambda c: S.get_recipe(c, recipe_id))

    @mcp.tool()
    def get_shopping_list() -> str:
        """The current shopping list (ticked and unticked items)."""
        return _run(lambda c: S.get_shopping(c))

    @mcp.tool()
    def get_pantry(include_used: bool = False) -> str:
        """Food at home with quantity left, location and expiry date (soonest first)."""
        return _run(lambda c: S.list_pantry(c, include_used))

    @mcp.tool()
    def get_ratings(recipe_id: int | None = None, limit: int = 50) -> str:
        """Ratings Miguel gave (stars, would repeat, effort, portion size, comment), newest first."""
        return _run(lambda c: S.list_ratings(c, recipe_id, limit))

    @mcp.tool()
    def list_change_requests(status: Literal["open", "done", "dismissed"] | None = "open") -> str:
        """Meals Miguel rejected or wants changed (swap ingredients / replace the meal) from the app."""
        return _run(lambda c: S.list_requests(c, status))

    @mcp.tool()
    def get_shopping_history(limit: int = 10) -> str:
        """Past shopping trips (date, store, amount spent) with what was bought."""
        def go(c):
            return [S.get_trip(c, t["id"]) for t in S.list_trips(c, limit)]
        return _run(go)

    # ------------------------------------------------------------------ writing

    @mcp.tool()
    def save_recipes(recipes: list[RecipeIn]) -> str:
        """Create recipes (omit id) or update them (give id; only the fields you send change, and
        ingredients/steps lists are replaced when sent). Returns ids to use in set_week_plan."""
        def go(c):
            out = []
            for r in recipes:
                data = r.model_dump(exclude_unset=True)
                if "ingredients" in data:
                    data["ingredients"] = [i.model_dump() for i in r.ingredients or []]
                if "steps" in data:
                    data["steps"] = [{"text": s.text, "timers": [t.model_dump() for t in s.timers]}
                                     for s in r.steps or []]
                try:
                    rid = S.save_recipe(c, data, source="claude")
                except S.ServiceError as e:
                    raise S.ServiceError(f"Recipe {r.title or r.id!r}: {e}")
                out.append({"id": rid, "title": r.title or S.get_recipe(c, rid)["title"]})
            return {"saved": out}
        return _run(go)

    @mcp.tool()
    def set_week_plan(week_start: str, meals: list[MealIn], summary: str | None = None,
                      replace: bool = True) -> str:
        """Write the plan for a week (Monday-based). With replace=true, existing planned meals of that week are
        removed first (cooked/rated meals are kept). summary: short notes shown on the plan page (theme,
        offers used, batch-cooking tips, estimated cost)."""
        return _run(lambda c: S.set_week_plan(c, week_start, [m.model_dump() for m in meals], summary, replace))

    @mcp.tool()
    def edit_meals(operations: list[MealOp]) -> str:
        """Add, update, move (swaps if one meal is in the target slot) or delete individual meals."""
        def go(c):
            results = []
            for op in operations:
                d = op.model_dump(exclude_unset=True, exclude={"action", "meal_id"})
                if op.action == "add":
                    results.append(S.add_meal(c, d))
                elif not op.meal_id:
                    raise S.ServiceError(f"meal_id is required for {op.action}")
                elif op.action == "update":
                    results.append(S.update_meal(c, op.meal_id, d))
                elif op.action == "move":
                    results.append(S.move_meal(c, op.meal_id, op.date, op.slot))
                else:
                    S.delete_meal(c, op.meal_id)
                    results.append({"deleted": op.meal_id})
            return results
        return _run(go)

    @mcp.tool()
    def update_shopping_list(add: list[ShopItemIn] | None = None, update: list[ShopItemUpdate] | None = None,
                             remove_ids: list[int] | None = None, clear_unchecked: bool = False) -> str:
        """Change the shopping list. clear_unchecked=true first removes every item not yet ticked off
        (use it to replace last week's list). Returns the full list."""
        def go(c):
            if clear_unchecked:
                S.clear_unchecked(c)
            for i in remove_ids or []:
                S.delete_shopping_item(c, i)
            for u in update or []:
                S.update_shopping_item(c, u.id, u.model_dump(exclude_unset=True, exclude={"id"}))
            for a in add or []:
                S.add_shopping_item(c, a.model_dump(exclude_none=True), added_by="claude")
            return S.get_shopping(c)
        return _run(go)

    @mcp.tool()
    def update_pantry(add: list[PantryIn] | None = None, update: list[PantryUpdate] | None = None,
                      remove_ids: list[int] | None = None) -> str:
        """Add food to the pantry log, change quantity/location/expiry, or remove entries."""
        def go(c):
            for i in remove_ids or []:
                S.delete_pantry_item(c, i)
            for u in update or []:
                S.update_pantry_item(c, u.id, u.model_dump(exclude_unset=True, exclude={"id"}))
            for a in add or []:
                S.add_pantry_item(c, a.model_dump(exclude_none=True))
            return S.list_pantry(c)
        return _run(go)

    @mcp.tool()
    def upsert_ingredients(items: list[IngredientIn]) -> str:
        """Set catalogue details for ingredients: Dutch name, category, density, piece weight, default storage
        location, shelf life and storage advice. These drive unit conversion and automatic expiry dates."""
        def go(c):
            return [S.upsert_ingredient(c, i.name, overwrite=True,
                                        **i.model_dump(exclude_none=True, exclude={"name"})) for i in items]
        return _run(go)

    @mcp.tool()
    def update_taste_profile(dislikes: list[DislikeIn] | None = None, remove_dislikes: list[str] | None = None,
                             profile: str | None = None) -> str:
        """Add/update disliked items with severity, remove dislikes, or replace the free-text food profile."""
        def go(c):
            for d in dislikes or []:
                S.upsert_dislike(c, d.item, d.severity, d.note)
            for item in remove_dislikes or []:
                S.delete_dislike_by_item(c, item)
            if profile is not None:
                S.update_settings(c, {"profile": profile})
            return {"dislikes": S.list_dislikes(c), "profile": S.get_settings(c)["profile"]}
        return _run(go)

    @mcp.tool()
    def resolve_change_requests(resolutions: list[Resolution]) -> str:
        """Mark change requests as done (say what you changed) or dismissed."""
        return _run(lambda c: [S.resolve_request(c, r.id, r.status, r.note) for r in resolutions])

    return mcp
