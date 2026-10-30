"""Domain logic shared by the web API and the Claude (MCP) tools."""

import json
from datetime import date, datetime, timedelta

from . import config, units
from .db import now_iso, row, rows

SLOTS = ["breakfast", "lunch", "dinner", "snack"]
LOCATIONS = ["fridge", "freezer", "pantry"]
MEAL_STATUSES = ["planned", "cooked", "eaten", "skipped"]
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class ServiceError(ValueError):
    """A user-facing validation error."""


# --------------------------------------------------------------------------- helpers

def today() -> date:
    return datetime.now(config.TIMEZONE).date()


def parse_date(value, field: str = "date") -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise ServiceError(f"{field} must be a date in YYYY-MM-DD format, got {value!r}")


def monday_of(d) -> date:
    d = parse_date(d)
    return d - timedelta(days=d.weekday())


def _json(value):
    return json.dumps(value, ensure_ascii=False) if value is not None else None


def _load(value, default=None):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _clean(data: dict, allowed) -> dict:
    return {k: v for k, v in data.items() if k in allowed}


def _num(value, field):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ServiceError(f"{field} must be a number, got {value!r}")


def _round(x, nd=2):
    if x is None:
        return None
    r = round(x, nd)
    return int(r) if r == int(r) else r


def day_label(d) -> str:
    d = parse_date(d)
    return f"{DAY_NAMES[d.weekday()]} {d.day} {d.strftime('%b')}"


# --------------------------------------------------------------------------- settings

def get_settings(conn) -> dict:
    s = {r["key"]: r["value"] for r in rows(conn.execute("SELECT key, value FROM settings"))}
    return {
        "profile": s.get("profile", ""),
        "stores": _load(s.get("stores"), []),
        "default_servings": float(s.get("default_servings") or 1),
    }


def update_settings(conn, data: dict) -> dict:
    if "profile" in data and data["profile"] is not None:
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('profile',?)", (str(data["profile"]),))
    if "stores" in data and data["stores"] is not None:
        stores = [str(s).strip() for s in data["stores"] if str(s).strip()]
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('stores',?)", (_json(stores),))
    if "default_servings" in data and data["default_servings"] is not None:
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('default_servings',?)",
                     (str(_num(data["default_servings"], "default_servings")),))
    return get_settings(conn)


# --------------------------------------------------------------------------- categories

CATEGORY_FIELDS = ["label", "label_nl", "sort_order", "default_location", "fridge_days",
                   "freezer_days", "pantry_days", "opened_days", "advice"]


def list_categories(conn) -> list[dict]:
    return rows(conn.execute("SELECT * FROM categories ORDER BY sort_order, label"))


def category(conn, key: str | None) -> dict:
    c = None
    if key:
        c = row(conn.execute("SELECT * FROM categories WHERE key=?", (key,)))
    return c or row(conn.execute("SELECT * FROM categories WHERE key='other'")) or {
        "key": "other", "label": "Other", "default_location": "pantry", "sort_order": 999}


def category_keys(conn) -> list[str]:
    return [r["key"] for r in rows(conn.execute("SELECT key FROM categories"))]


def check_category(conn, key):
    if key in (None, ""):
        return None
    if key not in category_keys(conn):
        raise ServiceError(f"Unknown category {key!r}. Valid: {', '.join(category_keys(conn))}")
    return key


def update_category(conn, key: str, data: dict) -> dict:
    data = _clean(data, CATEGORY_FIELDS)
    if "default_location" in data and data["default_location"] not in LOCATIONS:
        raise ServiceError(f"default_location must be one of {LOCATIONS}")
    if data:
        sets = ", ".join(f"{k}=?" for k in data)
        conn.execute(f"UPDATE categories SET {sets} WHERE key=?", (*data.values(), key))
    return category(conn, key)


# --------------------------------------------------------------------------- ingredients

INGREDIENT_FIELDS = ["name_nl", "category", "default_unit", "density", "unit_weight", "location",
                     "shelf_life_days", "opened_days", "storage_advice"]


def _variants(name: str) -> list[str]:
    n = units.norm_name(name)
    v = [n]
    if n.endswith("es"):
        v.append(n[:-2])
    if n.endswith("s"):
        v.append(n[:-1])
    else:
        v += [n + "s", n + "es"]
    return v


def find_ingredient(conn, name: str) -> dict | None:
    for v in _variants(name):
        r = row(conn.execute("SELECT * FROM ingredients WHERE name=? COLLATE NOCASE", (v,)))
        if r:
            return r
    return None


def upsert_ingredient(conn, name: str, overwrite: bool = False, **hints) -> dict:
    """Find an ingredient by name (creating it if needed) and fill in details.

    With overwrite=False only empty fields are filled, so Claude's earlier
    edits and the user's edits are not clobbered by casual mentions.
    """
    name = (name or "").strip()
    if not name:
        raise ServiceError("Ingredient name is required")
    hints = {k: v for k, v in _clean(hints, INGREDIENT_FIELDS).items() if v not in (None, "")}
    if "category" in hints:
        check_category(conn, hints["category"])
    if "location" in hints and hints["location"] not in LOCATIONS:
        raise ServiceError(f"location must be one of {LOCATIONS}")
    if "default_unit" in hints:
        hints["default_unit"] = units.norm_unit(hints["default_unit"])
    ing = find_ingredient(conn, name)
    ts = now_iso()
    if ing is None:
        cols = ["name", *hints.keys(), "created_at", "updated_at"]
        cur = conn.execute(
            f"INSERT INTO ingredients({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
            (name, *hints.values(), ts, ts),
        )
        return row(conn.execute("SELECT * FROM ingredients WHERE id=?", (cur.lastrowid,)))
    updates = {k: v for k, v in hints.items() if overwrite or ing.get(k) in (None, "")}
    if updates:
        sets = ", ".join(f"{k}=?" for k in updates)
        conn.execute(f"UPDATE ingredients SET {sets}, updated_at=? WHERE id=?", (*updates.values(), ts, ing["id"]))
        ing = row(conn.execute("SELECT * FROM ingredients WHERE id=?", (ing["id"],)))
    return ing


def list_ingredients(conn, q: str = "") -> list[dict]:
    if q:
        return rows(conn.execute(
            "SELECT * FROM ingredients WHERE name LIKE ? OR name_nl LIKE ? ORDER BY name LIMIT 50",
            (f"%{q}%", f"%{q}%")))
    return rows(conn.execute("SELECT * FROM ingredients ORDER BY name"))


def update_ingredient(conn, ing_id: int, data: dict) -> dict:
    ing = row(conn.execute("SELECT * FROM ingredients WHERE id=?", (ing_id,)))
    if not ing:
        raise ServiceError(f"Ingredient {ing_id} not found")
    data = _clean(data, INGREDIENT_FIELDS + ["name"])
    if "category" in data:
        check_category(conn, data["category"])
    if data.get("location") not in (None, *LOCATIONS):
        raise ServiceError(f"location must be one of {LOCATIONS}")
    if data:
        sets = ", ".join(f"{k}=?" for k in data)
        conn.execute(f"UPDATE ingredients SET {sets}, updated_at=? WHERE id=?", (*data.values(), now_iso(), ing_id))
    return row(conn.execute("SELECT * FROM ingredients WHERE id=?", (ing_id,)))


def conv_info(ing: dict | None, name: str) -> tuple[float | None, float | None]:
    """(density g/ml, unit weight g/pc) for an ingredient, with keyword fallbacks."""
    density = (ing or {}).get("density") or units.default_density(name)
    unit_weight = (ing or {}).get("unit_weight") or units.default_unit_weight(name)
    return density, unit_weight


# --------------------------------------------------------------------------- expiry

def default_location(conn, ing: dict | None, category_key: str | None) -> str:
    if ing and ing.get("location"):
        return ing["location"]
    return category(conn, category_key or (ing or {}).get("category"))["default_location"]


def shelf_life_days(conn, ing: dict | None, category_key: str | None, location: str,
                    explicit: int | None = None) -> int | None:
    """Explicit value > ingredient override (same location) > category default for that location."""
    if explicit not in (None, ""):
        return int(explicit)
    if ing and ing.get("shelf_life_days") and (not ing.get("location") or ing["location"] == location):
        return int(ing["shelf_life_days"])
    cat = category(conn, category_key or (ing or {}).get("category"))
    days = cat.get(f"{location}_days")
    return int(days) if days else None


def expiry_from(start, days: int | None) -> str | None:
    if days is None:
        return None
    return (parse_date(start) + timedelta(days=int(days))).isoformat()


def storage_advice(conn, ing: dict | None, category_key: str | None, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    if ing and ing.get("storage_advice"):
        return ing["storage_advice"]
    return category(conn, category_key or (ing or {}).get("category")).get("advice") or ""


# --------------------------------------------------------------------------- recipes

def _norm_timers(step: dict) -> list[dict]:
    timers = []
    raw = step.get("timers") or []
    if isinstance(raw, dict):
        raw = [raw]
    for t in raw:
        if isinstance(t, (int, float)):
            t = {"seconds": t}
        if not isinstance(t, dict):
            continue
        secs = t.get("seconds")
        if secs in (None, "") and t.get("minutes") not in (None, ""):
            secs = float(t["minutes"]) * 60
        if secs in (None, ""):
            continue
        timers.append({"label": (t.get("label") or "").strip() or "Timer", "seconds": int(round(float(secs)))})
    if step.get("timer_minutes") not in (None, ""):
        timers.append({"label": "Timer", "seconds": int(round(float(step["timer_minutes"]) * 60))})
    return timers


def save_recipe(conn, data: dict, source: str = "claude") -> int:
    title = (data.get("title") or "").strip()
    rid = data.get("id")
    ts = now_iso()
    fields = {
        "title": title,
        "description": data.get("description"),
        "servings": _num(data.get("servings"), "servings"),
        "prep_minutes": data.get("prep_minutes"),
        "cook_minutes": data.get("cook_minutes"),
        "tags": _json(data.get("tags")) if data.get("tags") is not None else None,
        "equipment": _json(data.get("equipment")) if data.get("equipment") is not None else None,
        "notes": data.get("notes"),
        "storage_notes": data.get("storage_notes"),
    }
    if rid:
        existing = row(conn.execute("SELECT id FROM recipes WHERE id=?", (rid,)))
        if not existing:
            raise ServiceError(f"Recipe {rid} not found")
        upd = {k: v for k, v in fields.items() if k in data and (k != "title" or v)}
        if "archived" in data:
            upd["archived"] = 1 if data["archived"] else 0
        if upd:
            sets = ", ".join(f"{k}=?" for k in upd)
            conn.execute(f"UPDATE recipes SET {sets}, updated_at=? WHERE id=?", (*upd.values(), ts, rid))
    else:
        if not title:
            raise ServiceError("Recipe title is required")
        if fields["servings"] is None:
            fields["servings"] = get_settings(conn)["default_servings"]
        cols = [*fields.keys(), "source", "created_at", "updated_at"]
        cur = conn.execute(
            f"INSERT INTO recipes({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
            (*fields.values(), source, ts, ts),
        )
        rid = cur.lastrowid

    if data.get("ingredients") is not None:
        conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id=?", (rid,))
        for i, ing in enumerate(data["ingredients"]):
            if isinstance(ing, str):
                ing = {"name": ing}
            name = (ing.get("name") or "").strip()
            if not name:
                raise ServiceError(f"Ingredient #{i + 1} of {title or rid!r} has no name")
            cat = ing.get("category")
            if cat:
                check_category(conn, cat)
            catalog = upsert_ingredient(
                conn, name, name_nl=ing.get("name_nl"), category=cat,
                density=ing.get("density"), unit_weight=ing.get("unit_weight"))
            conn.execute(
                "INSERT INTO recipe_ingredients(recipe_id,position,ingredient_id,name,quantity,unit,prep,grp,optional)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (rid, i + 1, catalog["id"], name, _num(ing.get("quantity"), "quantity"),
                 units.norm_unit(ing.get("unit")) if ing.get("unit") not in (None, "") else
                 ("pc" if ing.get("quantity") not in (None, "") else None),
                 ing.get("prep"), ing.get("group"), 1 if ing.get("optional") else 0),
            )
    if data.get("steps") is not None:
        conn.execute("DELETE FROM recipe_steps WHERE recipe_id=?", (rid,))
        for i, st in enumerate(data["steps"]):
            if isinstance(st, str):
                st = {"text": st}
            text = (st.get("text") or "").strip()
            if not text:
                raise ServiceError(f"Step #{i + 1} of {title or rid!r} has no text")
            conn.execute("INSERT INTO recipe_steps(recipe_id,position,text,timers) VALUES(?,?,?,?)",
                         (rid, i + 1, text, _json(_norm_timers(st))))
    return rid


def recipe_stats(conn) -> dict[int, dict]:
    stats: dict[int, dict] = {}
    for r in rows(conn.execute(
            "SELECT recipe_id, AVG(stars) avg, COUNT(*) n, MAX(created_at) last FROM ratings "
            "WHERE recipe_id IS NOT NULL AND stars IS NOT NULL GROUP BY recipe_id")):
        stats[r["recipe_id"]] = {"avg_stars": _round(r["avg"], 1), "ratings": r["n"], "last_rated": r["last"]}
    for r in rows(conn.execute(
            "SELECT recipe_id, COUNT(*) n, MAX(date) last FROM meals WHERE recipe_id IS NOT NULL "
            "AND is_leftover=0 GROUP BY recipe_id")):
        stats.setdefault(r["recipe_id"], {}).update({"times_planned": r["n"], "last_planned": r["last"]})
    for r in rows(conn.execute(
            "SELECT recipe_id, COUNT(*) n FROM meals WHERE recipe_id IS NOT NULL AND status='cooked' "
            "GROUP BY recipe_id")):
        stats.setdefault(r["recipe_id"], {})["times_cooked"] = r["n"]
    return stats


def list_recipes(conn, q: str = "", include_archived: bool = False) -> list[dict]:
    sql = "SELECT id, title, description, servings, prep_minutes, cook_minutes, tags, archived, source, created_at " \
          "FROM recipes WHERE 1=1"
    args: list = []
    if not include_archived:
        sql += " AND archived=0"
    if q:
        sql += " AND (title LIKE ? OR tags LIKE ? OR description LIKE ? OR id IN " \
               "(SELECT recipe_id FROM recipe_ingredients WHERE name LIKE ?))"
        args += [f"%{q}%"] * 4
    sql += " ORDER BY title COLLATE NOCASE"
    stats = recipe_stats(conn)
    out = []
    for r in rows(conn.execute(sql, args)):
        r["tags"] = _load(r["tags"], [])
        r.update(stats.get(r["id"], {}))
        out.append(r)
    return out


def get_recipe(conn, rid: int) -> dict:
    r = row(conn.execute("SELECT * FROM recipes WHERE id=?", (rid,)))
    if not r:
        raise ServiceError(f"Recipe {rid} not found")
    r["tags"] = _load(r["tags"], [])
    r["equipment"] = _load(r["equipment"], [])
    ings = rows(conn.execute(
        "SELECT ri.*, i.name_nl, i.category, i.density AS ing_density, i.unit_weight AS ing_unit_weight "
        "FROM recipe_ingredients ri LEFT JOIN ingredients i ON i.id = ri.ingredient_id "
        "WHERE ri.recipe_id=? ORDER BY ri.position", (rid,)))
    for ing in ings:
        density, uw = conv_info({"density": ing.pop("ing_density"), "unit_weight": ing.pop("ing_unit_weight")},
                                ing["name"])
        ing["density"], ing["unit_weight"] = density, uw
        ing["group"] = ing.pop("grp")
        ing["optional"] = bool(ing["optional"])
    r["ingredients"] = ings
    steps = rows(conn.execute("SELECT position, text, timers FROM recipe_steps WHERE recipe_id=? ORDER BY position",
                              (rid,)))
    for s in steps:
        s["timers"] = _load(s["timers"], [])
    r["steps"] = steps
    r.update(recipe_stats(conn).get(rid, {}))
    r["ratings_list"] = rows(conn.execute(
        "SELECT * FROM ratings WHERE recipe_id=? ORDER BY created_at DESC", (rid,)))
    return r


def delete_recipe(conn, rid: int):
    conn.execute("DELETE FROM recipes WHERE id=?", (rid,))


def find_recipe_id(conn, ref) -> int | None:
    """Resolve a recipe reference: integer id or exact (case-insensitive) title."""
    if ref in (None, ""):
        return None
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        r = row(conn.execute("SELECT id FROM recipes WHERE id=?", (int(ref),)))
        if not r:
            raise ServiceError(f"Recipe id {ref} not found")
        return r["id"]
    r = row(conn.execute("SELECT id FROM recipes WHERE title=? COLLATE NOCASE ORDER BY archived, id DESC", (ref,)))
    if not r:
        raise ServiceError(f"No recipe titled {ref!r}. Save it first with save_recipes.")
    return r["id"]


# --------------------------------------------------------------------------- meals / plan

def _meal_rows(conn, where: str, args) -> list[dict]:
    ms = rows(conn.execute(
        "SELECT m.*, r.title AS recipe_title, r.servings AS recipe_servings, r.prep_minutes, r.cook_minutes "
        f"FROM meals m LEFT JOIN recipes r ON r.id = m.recipe_id WHERE {where} "
        "ORDER BY m.date, CASE m.slot WHEN 'breakfast' THEN 0 WHEN 'lunch' THEN 1 WHEN 'dinner' THEN 2 ELSE 3 END, "
        "m.position, m.id", args))
    if not ms:
        return ms
    ids = [m["id"] for m in ms]
    rated = {r["meal_id"]: r for r in rows(conn.execute(
        f"SELECT * FROM ratings WHERE meal_id IN ({','.join('?' * len(ids))}) ORDER BY created_at", ids))}
    reqs = {}
    for r in rows(conn.execute(
            f"SELECT * FROM change_requests WHERE status='open' AND meal_id IN ({','.join('?' * len(ids))})", ids)):
        reqs.setdefault(r["meal_id"], []).append(r)
    for m in ms:
        m["display_title"] = m["title"] or m["recipe_title"] or "Untitled meal"
        if m["is_leftover"] and not m["title"]:
            m["display_title"] = f"Leftovers: {m['recipe_title'] or 'meal'}"
        m["is_leftover"] = bool(m["is_leftover"])
        m["rating"] = rated.get(m["id"])
        m["open_requests"] = reqs.get(m["id"], [])
    return ms


def get_meal(conn, meal_id: int) -> dict:
    ms = _meal_rows(conn, "m.id=?", (meal_id,))
    if not ms:
        raise ServiceError(f"Meal {meal_id} not found")
    return ms[0]


def meal_label(m: dict) -> str:
    return f"{day_label(m['date'])} · {m['slot']} · {m.get('display_title') or m.get('title') or ''}".strip(" ·")


def get_week(conn, start=None) -> dict:
    start = monday_of(start or today())
    end = start + timedelta(days=6)
    wk = row(conn.execute("SELECT * FROM weeks WHERE start_date=?", (start.isoformat(),))) or {}
    meals = _meal_rows(conn, "m.date BETWEEN ? AND ?", (start.isoformat(), end.isoformat()))
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "summary": wk.get("summary"),
        "days": [{"date": (start + timedelta(days=i)).isoformat(),
                  "label": day_label(start + timedelta(days=i))} for i in range(7)],
        "meals": meals,
    }


def _meal_values(conn, data: dict, partial: bool) -> dict:
    vals = {}
    if "date" in data or not partial:
        vals["date"] = parse_date(data.get("date")).isoformat()
    if "slot" in data or not partial:
        slot = (data.get("slot") or "").lower()
        if slot not in SLOTS:
            raise ServiceError(f"slot must be one of {SLOTS}, got {data.get('slot')!r}")
        vals["slot"] = slot
    if "recipe_id" in data or "recipe" in data or "recipe_title" in data:
        ref = data.get("recipe_id") or data.get("recipe") or data.get("recipe_title")
        vals["recipe_id"] = find_recipe_id(conn, ref)
    for k in ("title", "notes"):
        if k in data:
            vals[k] = data[k] or None
    if "servings" in data:
        vals["servings"] = _num(data["servings"], "servings")
    if "is_leftover" in data:
        vals["is_leftover"] = 1 if data["is_leftover"] else 0
    if "status" in data and data["status"] is not None:
        if data["status"] not in MEAL_STATUSES:
            raise ServiceError(f"status must be one of {MEAL_STATUSES}")
        vals["status"] = data["status"]
    if not partial and not vals.get("recipe_id") and not vals.get("title"):
        raise ServiceError("A meal needs a recipe (recipe_id / recipe_title) or a free-text title")
    return vals


def add_meal(conn, data: dict) -> dict:
    vals = _meal_values(conn, data, partial=False)
    if vals.get("servings") is None and not vals.get("is_leftover"):
        rs = row(conn.execute("SELECT servings FROM recipes WHERE id=?", (vals.get("recipe_id"),)))
        vals["servings"] = rs["servings"] if rs else get_settings(conn)["default_servings"]
    pos = conn.execute("SELECT COALESCE(MAX(position),0)+1 FROM meals WHERE date=? AND slot=?",
                       (vals["date"], vals["slot"])).fetchone()[0]
    ts = now_iso()
    vals.update(position=pos, created_at=ts, updated_at=ts)
    cur = conn.execute(f"INSERT INTO meals({','.join(vals)}) VALUES({','.join('?' * len(vals))})",
                       tuple(vals.values()))
    return get_meal(conn, cur.lastrowid)


def update_meal(conn, meal_id: int, data: dict) -> dict:
    get_meal(conn, meal_id)
    vals = _meal_values(conn, data, partial=True)
    if vals.get("status") == "cooked":
        vals["cooked_at"] = now_iso()
    if vals:
        sets = ", ".join(f"{k}=?" for k in vals)
        conn.execute(f"UPDATE meals SET {sets}, updated_at=? WHERE id=?", (*vals.values(), now_iso(), meal_id))
    return get_meal(conn, meal_id)


def move_meal(conn, meal_id: int, to_date, to_slot: str, swap: bool = True) -> dict:
    """Move a meal to another day/slot. If exactly one meal is there, swap them."""
    m = get_meal(conn, meal_id)
    to_date = parse_date(to_date).isoformat()
    to_slot = (to_slot or "").lower()
    if to_slot not in SLOTS:
        raise ServiceError(f"slot must be one of {SLOTS}")
    if m["date"] == to_date and m["slot"] == to_slot:
        return m
    there = rows(conn.execute("SELECT id FROM meals WHERE date=? AND slot=?", (to_date, to_slot)))
    ts = now_iso()
    if swap and len(there) == 1:
        conn.execute("UPDATE meals SET date=?, slot=?, updated_at=? WHERE id=?",
                     (m["date"], m["slot"], ts, there[0]["id"]))
    pos = conn.execute("SELECT COALESCE(MAX(position),0)+1 FROM meals WHERE date=? AND slot=?",
                       (to_date, to_slot)).fetchone()[0]
    conn.execute("UPDATE meals SET date=?, slot=?, position=?, updated_at=? WHERE id=?",
                 (to_date, to_slot, pos, ts, meal_id))
    return get_meal(conn, meal_id)


def delete_meal(conn, meal_id: int):
    conn.execute("DELETE FROM meals WHERE id=?", (meal_id,))


def set_week_summary(conn, start, summary: str | None):
    start = monday_of(start).isoformat()
    ts = now_iso()
    conn.execute(
        "INSERT INTO weeks(start_date, summary, created_at, updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(start_date) DO UPDATE SET summary=excluded.summary, updated_at=excluded.updated_at",
        (start, summary, ts, ts))


def set_week_plan(conn, week_start, meals: list[dict], summary: str | None = None, replace: bool = True) -> dict:
    start = monday_of(week_start)
    end = start + timedelta(days=6)
    if replace:
        # keep meals that already happened (cooked/eaten or rated) — they are history
        conn.execute(
            "DELETE FROM meals WHERE date BETWEEN ? AND ? AND status IN ('planned','skipped') "
            "AND id NOT IN (SELECT meal_id FROM ratings WHERE meal_id IS NOT NULL)",
            (start.isoformat(), end.isoformat()))
    for i, m in enumerate(meals):
        try:
            add_meal(conn, m)
        except ServiceError as e:
            raise ServiceError(f"Meal #{i + 1} ({m.get('date')} {m.get('slot')}): {e}")
    if summary is not None:
        set_week_summary(conn, start, summary)
    return get_week(conn, start)


# --------------------------------------------------------------------------- ratings

RATING_FIELDS = ["stars", "would_repeat", "effort", "portion", "comment"]


def add_rating(conn, data: dict) -> dict:
    meal_id = data.get("meal_id")
    recipe_id = data.get("recipe_id")
    title = data.get("recipe_title")
    if meal_id:
        m = get_meal(conn, meal_id)
        recipe_id = recipe_id or m["recipe_id"]
        title = title or m["recipe_title"] or m["display_title"]
        conn.execute("DELETE FROM ratings WHERE meal_id=?", (meal_id,))  # one rating per meal
    elif recipe_id:
        r = row(conn.execute("SELECT title FROM recipes WHERE id=?", (recipe_id,)))
        title = title or (r or {}).get("title")
    vals = _clean(data, RATING_FIELDS)
    if vals.get("stars") is not None:
        vals["stars"] = max(1, min(5, int(vals["stars"])))
    cur = conn.execute(
        "INSERT INTO ratings(meal_id,recipe_id,recipe_title,stars,would_repeat,effort,portion,comment,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (meal_id, recipe_id, title, vals.get("stars"), vals.get("would_repeat"), vals.get("effort"),
         vals.get("portion"), vals.get("comment"), now_iso()))
    if meal_id:
        conn.execute("UPDATE meals SET status=CASE WHEN status='planned' THEN 'eaten' ELSE status END WHERE id=?",
                     (meal_id,))
    return row(conn.execute("SELECT * FROM ratings WHERE id=?", (cur.lastrowid,)))


def update_rating(conn, rating_id: int, data: dict) -> dict:
    vals = _clean(data, RATING_FIELDS)
    if vals:
        sets = ", ".join(f"{k}=?" for k in vals)
        conn.execute(f"UPDATE ratings SET {sets} WHERE id=?", (*vals.values(), rating_id))
    return row(conn.execute("SELECT * FROM ratings WHERE id=?", (rating_id,)))


def delete_rating(conn, rating_id: int):
    conn.execute("DELETE FROM ratings WHERE id=?", (rating_id,))


def list_ratings(conn, recipe_id: int | None = None, limit: int = 100) -> list[dict]:
    sql = "SELECT rt.*, m.date AS meal_date, m.slot AS meal_slot FROM ratings rt " \
          "LEFT JOIN meals m ON m.id = rt.meal_id"
    args: list = []
    if recipe_id:
        sql += " WHERE rt.recipe_id=?"
        args.append(recipe_id)
    sql += " ORDER BY rt.created_at DESC LIMIT ?"
    args.append(limit)
    return rows(conn.execute(sql, args))


# --------------------------------------------------------------------------- dislikes

SEVERITY = {1: "mild — fine in small or hidden amounts", 2: "avoid — leave it out", 3: "never — hates it"}


def list_dislikes(conn) -> list[dict]:
    out = rows(conn.execute("SELECT * FROM dislikes ORDER BY severity DESC, item"))
    for d in out:
        d["severity_label"] = SEVERITY.get(d["severity"], "")
    return out


def upsert_dislike(conn, item: str, severity: int = 2, note: str | None = None) -> dict:
    item = (item or "").strip()
    if not item:
        raise ServiceError("Dislike item is required")
    severity = int(severity)
    if severity not in SEVERITY:
        raise ServiceError("severity must be 1 (mild), 2 (avoid) or 3 (never)")
    ts = now_iso()
    conn.execute(
        "INSERT INTO dislikes(item, severity, note, created_at, updated_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(item) DO UPDATE SET severity=excluded.severity, "
        "note=COALESCE(excluded.note, dislikes.note), updated_at=excluded.updated_at",
        (item, severity, note, ts, ts))
    return row(conn.execute("SELECT * FROM dislikes WHERE item=? COLLATE NOCASE", (item,)))


def delete_dislike(conn, dislike_id: int):
    conn.execute("DELETE FROM dislikes WHERE id=?", (dislike_id,))


def delete_dislike_by_item(conn, item: str):
    conn.execute("DELETE FROM dislikes WHERE item=? COLLATE NOCASE", (item,))


# --------------------------------------------------------------------------- change requests

REQUEST_KINDS = ["swap_ingredients", "replace_meal", "other"]


def create_request(conn, data: dict) -> dict:
    kind = data.get("kind") or "other"
    if kind not in REQUEST_KINDS:
        raise ServiceError(f"kind must be one of {REQUEST_KINDS}")
    meal_id = data.get("meal_id")
    recipe_id = data.get("recipe_id")
    label = data.get("meal_label")
    if meal_id:
        m = get_meal(conn, meal_id)
        recipe_id = recipe_id or m["recipe_id"]
        label = label or meal_label(m)
    elif recipe_id and not label:
        r = row(conn.execute("SELECT title FROM recipes WHERE id=?", (recipe_id,)))
        label = (r or {}).get("title")
    ings = [s for s in (data.get("ingredients") or []) if s]
    cur = conn.execute(
        "INSERT INTO change_requests(meal_id,recipe_id,meal_label,kind,ingredients,reason,status,created_at)"
        " VALUES(?,?,?,?,?,?,'open',?)",
        (meal_id, recipe_id, label, kind, _json(ings), data.get("reason"), now_iso()))
    for d in data.get("dislikes") or []:
        if d and d.get("item"):
            upsert_dislike(conn, d["item"], d.get("severity", 2), d.get("note"))
    return get_request(conn, cur.lastrowid)


def get_request(conn, req_id: int) -> dict:
    r = row(conn.execute("SELECT * FROM change_requests WHERE id=?", (req_id,)))
    if not r:
        raise ServiceError(f"Change request {req_id} not found")
    r["ingredients"] = _load(r["ingredients"], [])
    return r


def list_requests(conn, status: str | None = "open") -> list[dict]:
    if status:
        rs = rows(conn.execute("SELECT * FROM change_requests WHERE status=? ORDER BY created_at DESC", (status,)))
    else:
        rs = rows(conn.execute("SELECT * FROM change_requests ORDER BY created_at DESC LIMIT 100"))
    for r in rs:
        r["ingredients"] = _load(r["ingredients"], [])
    return rs


def resolve_request(conn, req_id: int, status: str = "done", resolution: str | None = None) -> dict:
    if status not in ("open", "done", "dismissed"):
        raise ServiceError("status must be open, done or dismissed")
    get_request(conn, req_id)
    conn.execute("UPDATE change_requests SET status=?, resolution=COALESCE(?, resolution), resolved_at=? WHERE id=?",
                 (status, resolution, None if status == "open" else now_iso(), req_id))
    return get_request(conn, req_id)


# --------------------------------------------------------------------------- shopping

SHOP_FIELDS = ["name", "name_nl", "quantity", "unit", "category", "store", "offer", "price", "for_meals",
               "location", "shelf_life_days", "storage_advice", "note", "checked"]


def active_trip(conn) -> dict:
    t = row(conn.execute("SELECT * FROM trips WHERE status='open' ORDER BY id DESC LIMIT 1"))
    if t:
        return t
    cur = conn.execute("INSERT INTO trips(status, created_at) VALUES('open', ?)", (now_iso(),))
    return row(conn.execute("SELECT * FROM trips WHERE id=?", (cur.lastrowid,)))


def _shopping_rows(conn, trip_id: int) -> list[dict]:
    items = rows(conn.execute(
        "SELECT s.*, c.label AS category_label, c.label_nl AS category_label_nl, "
        "COALESCE(c.sort_order, 999) AS category_order "
        "FROM shopping_items s LEFT JOIN categories c ON c.key = s.category "
        "WHERE s.trip_id=? ORDER BY category_order, s.position, s.id", (trip_id,)))
    for it in items:
        it["checked"] = bool(it["checked"])
    return items


def get_shopping(conn) -> dict:
    trip = active_trip(conn)
    items = _shopping_rows(conn, trip["id"])
    return {"trip": trip, "items": items,
            "estimated_total": _round(sum(i["price"] or 0 for i in items), 2)}


def _shop_values(conn, data: dict, partial: bool) -> dict:
    vals = _clean(data, SHOP_FIELDS)
    if "quantity" in vals:
        vals["quantity"] = _num(vals["quantity"], "quantity")
    if "price" in vals:
        vals["price"] = _num(vals["price"], "price")
    if "unit" in vals and vals["unit"] not in (None, ""):
        vals["unit"] = units.norm_unit(vals["unit"])
    if "category" in vals:
        check_category(conn, vals["category"])
    if vals.get("location") not in (None, "", *LOCATIONS):
        raise ServiceError(f"location must be one of {LOCATIONS}")
    if "checked" in vals:
        vals["checked"] = 1 if vals["checked"] else 0
        vals["checked_at"] = now_iso() if vals["checked"] else None
    if "shelf_life_days" in vals and vals["shelf_life_days"] not in (None, ""):
        vals["shelf_life_days"] = int(float(vals["shelf_life_days"]))
    if not partial and not (vals.get("name") or "").strip():
        raise ServiceError("Shopping item name is required")
    return vals


def add_shopping_item(conn, data: dict, added_by: str = "user") -> dict:
    vals = _shop_values(conn, data, partial=False)
    vals["name"] = vals["name"].strip()
    ing = upsert_ingredient(
        conn, vals["name"], name_nl=vals.get("name_nl"), category=vals.get("category"),
        location=vals.get("location") if data.get("set_default_location") else None,
        storage_advice=vals.get("storage_advice"),
        density=data.get("density"), unit_weight=data.get("unit_weight"))
    vals.setdefault("name_nl", ing.get("name_nl"))
    vals["name_nl"] = vals.get("name_nl") or ing.get("name_nl")
    vals["category"] = vals.get("category") or ing.get("category") or "other"
    trip = active_trip(conn)
    ts = now_iso()
    pos = conn.execute("SELECT COALESCE(MAX(position),0)+1 FROM shopping_items WHERE trip_id=?",
                       (trip["id"],)).fetchone()[0]
    vals.update(trip_id=trip["id"], ingredient_id=ing["id"], position=pos, added_by=added_by,
                created_at=ts, updated_at=ts)
    cur = conn.execute(f"INSERT INTO shopping_items({','.join(vals)}) VALUES({','.join('?' * len(vals))})",
                       tuple(vals.values()))
    return get_shopping_item(conn, cur.lastrowid)


def get_shopping_item(conn, item_id: int) -> dict:
    it = row(conn.execute("SELECT * FROM shopping_items WHERE id=?", (item_id,)))
    if not it:
        raise ServiceError(f"Shopping item {item_id} not found")
    it["checked"] = bool(it["checked"])
    return it


def update_shopping_item(conn, item_id: int, data: dict) -> dict:
    get_shopping_item(conn, item_id)
    vals = _shop_values(conn, data, partial=True)
    if "name" in vals:
        ing = upsert_ingredient(conn, vals["name"])
        vals["ingredient_id"] = ing["id"]
    if vals:
        sets = ", ".join(f"{k}=?" for k in vals)
        conn.execute(f"UPDATE shopping_items SET {sets}, updated_at=? WHERE id=?",
                     (*vals.values(), now_iso(), item_id))
    return get_shopping_item(conn, item_id)


def delete_shopping_item(conn, item_id: int):
    conn.execute("DELETE FROM shopping_items WHERE id=?", (item_id,))


def clear_unchecked(conn):
    trip = active_trip(conn)
    conn.execute("DELETE FROM shopping_items WHERE trip_id=? AND checked=0", (trip["id"],))


def complete_trip(conn, keep_unchecked: bool = True, store: str | None = None,
                  total_spent=None, note: str | None = None, when=None) -> dict:
    """'Back from shopping': log the trip and move bought items into the pantry."""
    trip = active_trip(conn)
    items = _shopping_rows(conn, trip["id"])
    bought = [i for i in items if i["checked"]]
    if not bought:
        raise ServiceError("Nothing is ticked off yet — tick the items you bought first.")
    day = parse_date(when).isoformat() if when else today().isoformat()
    ts = now_iso()
    created = []
    for it in bought:
        ing = row(conn.execute("SELECT * FROM ingredients WHERE id=?", (it["ingredient_id"],))) \
            if it["ingredient_id"] else None
        loc = it["location"] or default_location(conn, ing, it["category"])
        days = shelf_life_days(conn, ing, it["category"], loc, it["shelf_life_days"])
        advice = storage_advice(conn, ing, it["category"], it["storage_advice"])
        cur = conn.execute(
            "INSERT INTO pantry_items(ingredient_id,name,quantity,unit,initial_quantity,location,purchased_at,"
            "expires_at,trip_id,storage_advice,note,status,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,'active',?,?)",
            (it["ingredient_id"], it["name"], it["quantity"], it["unit"], it["quantity"], loc, day,
             expiry_from(day, days), trip["id"], advice, it["note"], ts, ts))
        created.append(cur.lastrowid)
        # Once bought, the "running low" flag on older stock of the same thing is resolved.
        if it["ingredient_id"]:
            conn.execute("UPDATE pantry_items SET low=0 WHERE ingredient_id=? AND status='active'",
                         (it["ingredient_id"],))
    conn.execute("UPDATE trips SET status='done', completed_at=?, store=?, total_spent=?, note=? WHERE id=?",
                 (ts, store, _num(total_spent, "total_spent"), note, trip["id"]))
    leftover = [i for i in items if not i["checked"]]
    if leftover:
        if keep_unchecked:
            new_trip = active_trip(conn)
            conn.execute("UPDATE shopping_items SET trip_id=? WHERE trip_id=? AND checked=0",
                         (new_trip["id"], trip["id"]))
        else:
            conn.execute("DELETE FROM shopping_items WHERE trip_id=? AND checked=0", (trip["id"],))
    return get_trip(conn, trip["id"])


def list_trips(conn, limit: int = 50) -> list[dict]:
    return rows(conn.execute(
        "SELECT t.*, (SELECT COUNT(*) FROM shopping_items s WHERE s.trip_id=t.id) AS item_count "
        "FROM trips t WHERE t.status='done' ORDER BY t.completed_at DESC LIMIT ?", (limit,)))


def get_trip(conn, trip_id: int) -> dict:
    t = row(conn.execute("SELECT * FROM trips WHERE id=?", (trip_id,)))
    if not t:
        raise ServiceError(f"Shopping trip {trip_id} not found")
    t["items"] = _shopping_rows(conn, trip_id)
    t["pantry_items"] = rows(conn.execute(
        "SELECT * FROM pantry_items WHERE trip_id=? ORDER BY CASE location WHEN 'freezer' THEN 0 "
        "WHEN 'fridge' THEN 1 ELSE 2 END, expires_at IS NULL, expires_at, name", (trip_id,)))
    return t


# --------------------------------------------------------------------------- pantry

PANTRY_FIELDS = ["name", "quantity", "unit", "location", "purchased_at", "expires_at", "opened_at", "low",
                 "storage_advice", "note", "status"]


def list_pantry(conn, include_inactive: bool = False) -> list[dict]:
    sql = ("SELECT p.*, i.category, i.name_nl FROM pantry_items p LEFT JOIN ingredients i ON i.id=p.ingredient_id "
           + ("" if include_inactive else "WHERE p.status='active' ")
           + "ORDER BY p.expires_at IS NULL, p.expires_at, p.name COLLATE NOCASE")
    out = rows(conn.execute(sql))
    t = today()
    for p in out:
        p["low"] = bool(p["low"])
        p["days_left"] = (parse_date(p["expires_at"]) - t).days if p["expires_at"] else None
    return out


def get_pantry_item(conn, pid: int) -> dict:
    p = row(conn.execute("SELECT * FROM pantry_items WHERE id=?", (pid,)))
    if not p:
        raise ServiceError(f"Pantry item {pid} not found")
    p["low"] = bool(p["low"])
    p["days_left"] = (parse_date(p["expires_at"]) - today()).days if p["expires_at"] else None
    return p


def add_pantry_item(conn, data: dict) -> dict:
    name = (data.get("name") or "").strip()
    if not name:
        raise ServiceError("Pantry item name is required")
    ing = upsert_ingredient(conn, name, category=data.get("category"), name_nl=data.get("name_nl"))
    cat = data.get("category") or ing.get("category")
    loc = data.get("location") or default_location(conn, ing, cat)
    if loc not in LOCATIONS:
        raise ServiceError(f"location must be one of {LOCATIONS}")
    purchased = parse_date(data.get("purchased_at") or today()).isoformat()
    expires = data.get("expires_at")
    if expires:
        expires = parse_date(expires, "expires_at").isoformat()
    elif not data.get("no_expiry"):
        expires = expiry_from(purchased, shelf_life_days(conn, ing, cat, loc, data.get("shelf_life_days")))
    qty = _num(data.get("quantity"), "quantity")
    unit = units.norm_unit(data["unit"]) if data.get("unit") else (None if qty is None else "pc")
    ts = now_iso()
    cur = conn.execute(
        "INSERT INTO pantry_items(ingredient_id,name,quantity,unit,initial_quantity,location,purchased_at,expires_at,"
        "opened_at,low,storage_advice,note,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'active',?,?)",
        (ing["id"], name, qty, unit, qty, loc, purchased, expires, data.get("opened_at"),
         1 if data.get("low") else 0, storage_advice(conn, ing, cat, data.get("storage_advice")),
         data.get("note"), ts, ts))
    return get_pantry_item(conn, cur.lastrowid)


def update_pantry_item(conn, pid: int, data: dict) -> dict:
    p = get_pantry_item(conn, pid)
    vals = _clean(data, PANTRY_FIELDS)
    if "quantity" in vals:
        vals["quantity"] = _num(vals["quantity"], "quantity")
        if vals["quantity"] is not None and vals["quantity"] <= 0:
            vals["quantity"] = 0
            vals.setdefault("status", "used")
    if "unit" in vals and vals["unit"]:
        vals["unit"] = units.norm_unit(vals["unit"])
    if vals.get("location") not in (None, *LOCATIONS):
        raise ServiceError(f"location must be one of {LOCATIONS}")
    if vals.get("status") not in (None, "active", "used", "discarded"):
        raise ServiceError("status must be active, used or discarded")
    if "low" in vals:
        vals["low"] = 1 if vals["low"] else 0
    for k in ("expires_at", "purchased_at", "opened_at"):
        if vals.get(k):
            vals[k] = parse_date(vals[k], k).isoformat()
    ing = row(conn.execute("SELECT * FROM ingredients WHERE id=?", (p["ingredient_id"],))) \
        if p["ingredient_id"] else None
    loc = vals.get("location") or p["location"]
    if data.get("recompute_expiry") or (vals.get("location") and vals["location"] != p["location"]
                                        and "expires_at" not in vals):
        # moving to the freezer (or back) restarts the clock from today
        vals["expires_at"] = expiry_from(today(), shelf_life_days(conn, ing, None, loc))
    if data.get("opened") and not p["opened_at"]:
        vals["opened_at"] = today().isoformat()
        cat = category(conn, (ing or {}).get("category"))
        od = (ing or {}).get("opened_days") or cat.get("opened_days")
        if od and loc != "freezer":
            new_exp = expiry_from(today(), od)
            cur_exp = vals.get("expires_at") or p["expires_at"]
            if not cur_exp or new_exp < cur_exp:
                vals["expires_at"] = new_exp
    if vals:
        sets = ", ".join(f"{k}=?" for k in vals)
        conn.execute(f"UPDATE pantry_items SET {sets}, updated_at=? WHERE id=?", (*vals.values(), now_iso(), pid))
    return get_pantry_item(conn, pid)


def delete_pantry_item(conn, pid: int):
    conn.execute("DELETE FROM pantry_items WHERE id=?", (pid,))


def pantry_to_shopping(conn, pid: int) -> dict:
    p = get_pantry_item(conn, pid)
    ing = row(conn.execute("SELECT * FROM ingredients WHERE id=?", (p["ingredient_id"],))) \
        if p["ingredient_id"] else None
    conn.execute("UPDATE pantry_items SET low=1 WHERE id=?", (pid,))
    return add_shopping_item(conn, {
        "name": p["name"], "name_nl": (ing or {}).get("name_nl"), "category": (ing or {}).get("category"),
        "quantity": p["initial_quantity"], "unit": p["unit"], "location": p["location"],
        "note": "Restock (running low)"}, added_by="user")


# --------------------------------------------------------------------------- aggregation

def _scaled_recipe_needs(conn, meal: dict) -> list[dict]:
    if not meal.get("recipe_id") or meal.get("is_leftover"):
        return []
    rec = row(conn.execute("SELECT servings FROM recipes WHERE id=?", (meal["recipe_id"],)))
    if not rec:
        return []
    factor = (meal.get("servings") or rec["servings"] or 1) / (rec["servings"] or 1)
    ings = rows(conn.execute(
        "SELECT ri.*, i.density, i.unit_weight FROM recipe_ingredients ri "
        "LEFT JOIN ingredients i ON i.id=ri.ingredient_id WHERE ri.recipe_id=? ORDER BY position",
        (meal["recipe_id"],)))
    for ing in ings:
        ing["quantity"] = ing["quantity"] * factor if ing["quantity"] is not None else None
        ing["density"], ing["unit_weight"] = conv_info(ing, ing["name"])
    return ings


def _add_amount(bucket: dict, qty, unit, density, unit_weight):
    """Accumulate into base units; mass and volume are merged when density is known."""
    if qty is None:
        bucket.setdefault("unquantified", 0)
        bucket["unquantified"] += 1
        return
    base = units.to_base(qty, unit)
    if base is None:
        key = units.norm_unit(unit)
        bucket.setdefault("other", {}).setdefault(key, 0)
        bucket["other"][key] += qty
        return
    amount, dim = base
    if dim == "volume" and density:
        amount, dim = amount * density, "mass"
    if dim == "count" and unit_weight and bucket.get("mass") is not None:
        amount, dim = amount * unit_weight, "mass"
    bucket[dim] = bucket.get(dim, 0) + amount


def _format_bucket(bucket: dict) -> list[str]:
    out = []
    if bucket.get("mass"):
        g = bucket["mass"]
        out.append(f"{_round(g / 1000, 2)} kg" if g >= 1000 else f"{_round(g, 0)} g")
    if bucket.get("volume"):
        ml = bucket["volume"]
        out.append(f"{_round(ml / 1000, 2)} l" if ml >= 1000 else f"{_round(ml, 0)} ml")
    if bucket.get("count"):
        out.append(f"{_round(bucket['count'], 1)} pc")
    for u, q in (bucket.get("other") or {}).items():
        out.append(f"{_round(q, 1)} {u}")
    if bucket.get("unquantified"):
        out.append("some (no amount given)")
    return out


def week_ingredient_totals(conn, week_start) -> dict:
    """What the planned (not yet cooked) meals of a week need, compared with the pantry."""
    wk = get_week(conn, week_start)
    needs: dict = {}
    for m in wk["meals"]:
        if m["status"] not in ("planned",):
            continue
        for ing in _scaled_recipe_needs(conn, m):
            key = ing["ingredient_id"] or units.norm_name(ing["name"])
            e = needs.setdefault(key, {"ingredient_id": ing["ingredient_id"], "name": ing["name"], "bucket": {},
                                       "meals": [], "density": ing["density"], "unit_weight": ing["unit_weight"],
                                       "optional": True})
            _add_amount(e["bucket"], ing["quantity"], ing["unit"], ing["density"], ing["unit_weight"])
            e["optional"] = e["optional"] and bool(ing["optional"])
            lbl = f"{m['display_title']} ({DAY_NAMES[parse_date(m['date']).weekday()]} {m['slot']})"
            if lbl not in e["meals"]:
                e["meals"].append(lbl)
    pantry = list_pantry(conn)
    result = []
    for e in needs.values():
        stock = [p for p in pantry if e["ingredient_id"] and p["ingredient_id"] == e["ingredient_id"]]
        sb: dict = {}
        for p in stock:
            _add_amount(sb, p["quantity"], p["unit"], e["density"], e["unit_weight"])
        result.append({
            "ingredient_id": e["ingredient_id"], "name": e["name"], "needed": _format_bucket(e["bucket"]),
            "in_pantry": [f"{_round(p['quantity'], 1) if p['quantity'] is not None else 'some'} "
                          f"{p['unit'] or ''} ({p['location']}, expires {p['expires_at'] or 'n/a'})".replace("  ", " ")
                          for p in stock],
            "pantry_total": _format_bucket(sb) if stock else [],
            "used_in": e["meals"], "optional": e["optional"],
        })
    result.sort(key=lambda r: r["name"].lower())
    return {"week_start": wk["start"], "ingredients": result}


# --------------------------------------------------------------------------- cooking

def deduction_proposals(conn, meal_id: int) -> list[dict]:
    meal = get_meal(conn, meal_id)
    needs = _scaled_recipe_needs(conn, meal)
    pantry = [p for p in list_pantry(conn) if p["quantity"] is not None]
    used: dict[int, float] = {}
    out = []
    for ing in needs:
        if ing["quantity"] is None or not ing["ingredient_id"]:
            continue
        remaining_need = ing["quantity"]
        for p in [p for p in pantry if p["ingredient_id"] == ing["ingredient_id"]]:
            avail = p["quantity"] - used.get(p["id"], 0)
            if avail <= 0:
                continue
            need_in_p_unit = units.convert(remaining_need, ing["unit"] or "pc", p["unit"] or "pc",
                                           ing["density"], ing["unit_weight"])
            if need_in_p_unit is None:
                continue
            take = min(avail, need_in_p_unit)
            used[p["id"]] = used.get(p["id"], 0) + take
            out.append({
                "pantry_id": p["id"], "pantry_name": p["name"], "location": p["location"],
                "have": _round(p["quantity"], 2), "unit": p["unit"], "deduct": _round(take, 2),
                "left_after": _round(p["quantity"] - used[p["id"]], 2),
                "recipe_amount": f"{_round(ing['quantity'], 2)} {ing['unit'] or ''}".strip(),
                "ingredient": ing["name"],
            })
            back = units.convert(take, p["unit"] or "pc", ing["unit"] or "pc", ing["density"], ing["unit_weight"])
            remaining_need -= back if back is not None else remaining_need
            if remaining_need <= 1e-9:
                break
    return out


def mark_cooked(conn, meal_id: int, deductions: list[dict] | None = None) -> dict:
    for d in deductions or []:
        pid, amount = d.get("pantry_id"), _num(d.get("deduct"), "deduct")
        if not pid or not amount:
            continue
        p = get_pantry_item(conn, pid)
        if p["quantity"] is None:
            continue
        update_pantry_item(conn, pid, {"quantity": round(p["quantity"] - amount, 3)})
    return update_meal(conn, meal_id, {"status": "cooked"})


# --------------------------------------------------------------------------- context for Claude

def planning_context(conn, weeks_back: int = 4) -> dict:
    t = today()
    this_monday = monday_of(t)
    since = (this_monday - timedelta(weeks=weeks_back)).isoformat()
    history = _meal_rows(conn, "m.date >= ? AND m.date < ?", (since, this_monday.isoformat()))
    pantry = list_pantry(conn)
    return {
        "today": t.isoformat(),
        "weekday": DAY_NAMES[t.weekday()],
        "this_week_start": this_monday.isoformat(),
        "next_week_start": (this_monday + timedelta(days=7)).isoformat(),
        "profile": get_settings(conn)["profile"],
        "stores": get_settings(conn)["stores"],
        "dislikes": [{"item": d["item"], "severity": d["severity"], "meaning": d["severity_label"],
                      "note": d["note"]} for d in list_dislikes(conn)],
        "open_change_requests": list_requests(conn, "open"),
        "pantry": [{k: p[k] for k in ("id", "name", "quantity", "unit", "location", "expires_at", "days_left",
                                      "opened_at", "low", "category")} for p in pantry],
        "expiring_within_4_days": [p["name"] for p in pantry if p["days_left"] is not None and p["days_left"] <= 4],
        "running_low": [p["name"] for p in pantry if p["low"]],
        "recent_ratings": [{k: r[k] for k in ("recipe_id", "recipe_title", "stars", "would_repeat", "effort",
                                              "portion", "comment", "meal_date")}
                           for r in list_ratings(conn, limit=40)],
        "recipe_library": [{k: r.get(k) for k in ("id", "title", "tags", "avg_stars", "ratings", "times_planned",
                                                  "times_cooked", "last_planned")}
                           for r in list_recipes(conn)],
        "past_meals": [{"date": m["date"], "slot": m["slot"], "title": m["display_title"], "status": m["status"],
                        "stars": (m["rating"] or {}).get("stars")} for m in history],
        "this_week": _compact_week(get_week(conn, this_monday)),
        "next_week": _compact_week(get_week(conn, this_monday + timedelta(days=7))),
        "shopping_list": [{k: i[k] for k in ("id", "name", "quantity", "unit", "store", "checked", "for_meals")}
                          for i in get_shopping(conn)["items"]],
        "categories": [{k: c[k] for k in ("key", "label", "default_location", "fridge_days", "freezer_days",
                                          "pantry_days")} for c in list_categories(conn)],
        "how_to_plan": PLANNING_GUIDE,
    }


def _compact_week(wk: dict) -> dict:
    return {"start": wk["start"], "summary": wk["summary"],
            "meals": [{"id": m["id"], "date": m["date"], "slot": m["slot"], "title": m["display_title"],
                       "recipe_id": m["recipe_id"], "servings": m["servings"], "status": m["status"],
                       "is_leftover": m["is_leftover"]} for m in wk["meals"]]}


PLANNING_GUIDE = """Weekly planning workflow (do it all in one go):
1. Read this context. Handle open_change_requests first (swap ingredients or replace the meal, then resolve_change_requests).
2. Check this week's offers at Lidl (lidl.nl/aanbiedingen), Albert Heijn (ah.nl/bonus) and Dirk (dirk.nl/aanbiedingen) with web search, and build part of the menu around good deals. Add some variety: about 1–2 new dishes per week next to proven favourites (avg_stars >= 4). Prefer one store for most items.
3. Respect dislikes: severity 3 = never, 2 = leave it out, 1 = only small/hidden amounts. Read recent ratings (portion/effort/comments) and adapt.
4. Use pantry items that expire soon and anything already in stock. Fridge/freezer space is limited.
5. save_recipes for new dishes (full beginner-level detail; timers on every step that involves waiting/cooking; metric units; [[n]] in step text inserts ingredient n with its scaled amount). Reuse existing recipe ids where possible.
6. set_week_plan with lunch + dinner for each day (servings = portions cooked; add leftover meals with is_leftover=true).
7. get_week_ingredient_totals, subtract what's in the pantry, then update_shopping_list with real package sizes (e.g. 500 g pack), Dutch name (name_nl), category, store + offer, estimated price, storage location, shelf_life_days and storage_advice for each item. Use clear_unchecked=true to replace the old unticked list.
8. upsert_ingredients for any ingredient whose density (g/ml) or piece weight is useful for unit conversion.
9. Summarise the week, the offers used and the estimated cost in the chat."""
