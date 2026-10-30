"""SQLite storage: connection helper, schema and first-run seed data."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS categories (
  key TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  label_nl TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  default_location TEXT NOT NULL DEFAULT 'pantry',
  fridge_days INTEGER,
  freezer_days INTEGER,
  pantry_days INTEGER,
  opened_days INTEGER,
  advice TEXT
);

CREATE TABLE IF NOT EXISTS ingredients (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name_nl TEXT,
  category TEXT,
  default_unit TEXT,
  density REAL,
  unit_weight REAL,
  location TEXT,
  shelf_life_days INTEGER,
  opened_days INTEGER,
  storage_advice TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS recipes (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT,
  servings REAL NOT NULL DEFAULT 1,
  prep_minutes INTEGER,
  cook_minutes INTEGER,
  tags TEXT,
  equipment TEXT,
  notes TEXT,
  storage_notes TEXT,
  source TEXT,
  archived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS recipe_ingredients (
  id INTEGER PRIMARY KEY,
  recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  ingredient_id INTEGER REFERENCES ingredients(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  quantity REAL,
  unit TEXT,
  prep TEXT,
  grp TEXT,
  optional INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS recipe_steps (
  id INTEGER PRIMARY KEY,
  recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  text TEXT NOT NULL,
  timers TEXT
);

CREATE TABLE IF NOT EXISTS weeks (
  start_date TEXT PRIMARY KEY,
  summary TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS meals (
  id INTEGER PRIMARY KEY,
  date TEXT NOT NULL,
  slot TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  recipe_id INTEGER REFERENCES recipes(id) ON DELETE SET NULL,
  title TEXT,
  servings REAL,
  is_leftover INTEGER NOT NULL DEFAULT 0,
  notes TEXT,
  status TEXT NOT NULL DEFAULT 'planned',
  cooked_at TEXT,
  created_at TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS meals_date ON meals(date);

CREATE TABLE IF NOT EXISTS ratings (
  id INTEGER PRIMARY KEY,
  meal_id INTEGER REFERENCES meals(id) ON DELETE SET NULL,
  recipe_id INTEGER REFERENCES recipes(id) ON DELETE SET NULL,
  recipe_title TEXT,
  stars INTEGER,
  would_repeat TEXT,
  effort TEXT,
  portion TEXT,
  comment TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS dislikes (
  id INTEGER PRIMARY KEY,
  item TEXT NOT NULL UNIQUE COLLATE NOCASE,
  severity INTEGER NOT NULL DEFAULT 2,
  note TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS change_requests (
  id INTEGER PRIMARY KEY,
  meal_id INTEGER REFERENCES meals(id) ON DELETE SET NULL,
  recipe_id INTEGER REFERENCES recipes(id) ON DELETE SET NULL,
  meal_label TEXT,
  kind TEXT NOT NULL,
  ingredients TEXT,
  reason TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  resolution TEXT,
  created_at TEXT,
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS trips (
  id INTEGER PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT,
  completed_at TEXT,
  store TEXT,
  note TEXT,
  total_spent REAL
);

CREATE TABLE IF NOT EXISTS shopping_items (
  id INTEGER PRIMARY KEY,
  trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
  position INTEGER NOT NULL DEFAULT 0,
  ingredient_id INTEGER REFERENCES ingredients(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  name_nl TEXT,
  quantity REAL,
  unit TEXT,
  category TEXT,
  store TEXT,
  offer TEXT,
  price REAL,
  for_meals TEXT,
  location TEXT,
  shelf_life_days INTEGER,
  storage_advice TEXT,
  note TEXT,
  checked INTEGER NOT NULL DEFAULT 0,
  checked_at TEXT,
  added_by TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS pantry_items (
  id INTEGER PRIMARY KEY,
  ingredient_id INTEGER REFERENCES ingredients(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  quantity REAL,
  unit TEXT,
  initial_quantity REAL,
  location TEXT NOT NULL DEFAULT 'pantry',
  purchased_at TEXT,
  expires_at TEXT,
  opened_at TEXT,
  low INTEGER NOT NULL DEFAULT 0,
  trip_id INTEGER REFERENCES trips(id) ON DELETE SET NULL,
  storage_advice TEXT,
  note TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS oauth_clients (client_id TEXT PRIMARY KEY, data TEXT NOT NULL, created_at TEXT);
CREATE TABLE IF NOT EXISTS oauth_pending (id TEXT PRIMARY KEY, client_id TEXT NOT NULL, params TEXT NOT NULL, created_at REAL);
CREATE TABLE IF NOT EXISTS oauth_codes (code TEXT PRIMARY KEY, data TEXT NOT NULL, expires_at REAL);
CREATE TABLE IF NOT EXISTS oauth_tokens (
  token TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  client_id TEXT NOT NULL,
  scopes TEXT,
  resource TEXT,
  expires_at INTEGER,
  pair TEXT,
  created_at TEXT
);
"""

# key, label, label_nl, aisle order, default location, fridge, freezer, pantry, opened days, advice
DEFAULT_CATEGORIES = [
    ("vegetables", "Vegetables", "Groente", 10, "fridge", 7, 240, 7, 3,
     "Most vegetables go in the fridge's vegetable drawer, unwashed. Potatoes, onions and garlic stay out of "
     "the fridge in a cool, dark, dry place (not in a closed plastic bag), and potatoes away from onions."),
    ("fruit", "Fruit", "Fruit", 20, "pantry", 10, 240, 5, 2,
     "Bananas, apples and citrus are fine in a fruit bowl; berries and grapes go in the fridge unwashed. "
     "Keep bananas away from other fruit (they speed up ripening)."),
    ("herbs", "Fresh herbs", "Verse kruiden", 30, "fridge", 5, 180, 2, None,
     "Wrap in a slightly damp paper towel inside a bag in the fridge. Basil prefers a glass of water on the counter."),
    ("bakery", "Bread & bakery", "Brood & bakkerij", 40, "pantry", None, 90, 4, None,
     "Keep bread in its bag at room temperature, not in the fridge (it goes stale faster). "
     "Freeze what you won't eat in 3–4 days in slices so you can toast them straight from frozen."),
    ("meat", "Meat", "Vlees", 50, "fridge", 2, 120, None, 1,
     "Bottom shelf of the fridge, on a plate so juices can't drip. Cook within 1–2 days or freeze straight away "
     "in flat, portion-sized bags labelled with the date. Thaw overnight in the fridge, never on the counter."),
    ("fish", "Fish", "Vis", 55, "fridge", 1, 90, None, 1,
     "Coldest part of the fridge (bottom shelf). Cook the same or next day, or freeze immediately."),
    ("deli", "Cold cuts & deli", "Vleeswaren", 60, "fridge", 7, 60, None, 3,
     "Fridge. Once opened, close the pack well and use within about 3 days."),
    ("dairy", "Milk, yogurt & cream", "Zuivel", 70, "fridge", 7, 90, None, 4,
     "Fridge, not in the door if it's warm there. Once opened, use within about 4 days (check the label)."),
    ("cheese", "Cheese", "Kaas", 75, "fridge", 21, 90, None, 14,
     "Fridge, wrapped or in a closed box so it doesn't dry out. Grated cheese freezes well."),
    ("eggs", "Eggs", "Eieren", 80, "fridge", 28, None, 21, None,
     "Keep in their box in the fridge (not in the door)."),
    ("chilled", "Chilled ready food", "Gekoeld", 85, "fridge", 5, 60, None, 2,
     "Fridge. Fresh pasta, tofu, hummus and similar: once opened use within 2 days."),
    ("frozen", "Frozen", "Diepvries", 90, "freezer", 2, 180, None, None,
     "Straight into the freezer when you get home. Don't refreeze once thawed."),
    ("grains", "Pasta, rice & grains", "Pasta, rijst & granen", 100, "pantry", None, None, 365, 180,
     "Cupboard. After opening, close the bag with a clip or move to a jar to keep bugs and moisture out."),
    ("canned", "Tins & jars", "Conserven", 110, "pantry", None, None, 540, 4,
     "Cupboard. Once opened, move leftovers to a closed container in the fridge (not the open tin) and use within ~4 days."),
    ("baking", "Baking & flour", "Bakken", 120, "pantry", None, None, 180, 120,
     "Cupboard, closed tightly."),
    ("spices", "Dried herbs & spices", "Kruiden & specerijen", 130, "pantry", None, None, 365, 365,
     "Cupboard, away from the stove's heat."),
    ("sauces", "Sauces & condiments", "Sauzen", 140, "pantry", None, None, 270, 60,
     "Cupboard until opened; most sauces (mayo, pesto, curry paste) go in the fridge after opening — check the label."),
    ("oils", "Oil & vinegar", "Olie & azijn", 150, "pantry", None, None, 365, 180,
     "Cupboard, away from light and the hob."),
    ("breakfast", "Breakfast & spreads", "Ontbijt & beleg", 160, "pantry", None, None, 180, 60,
     "Cupboard. Jam goes in the fridge after opening."),
    ("snacks", "Snacks & sweets", "Snacks & snoep", 170, "pantry", None, None, 120, 30,
     "Cupboard, closed."),
    ("drinks", "Drinks", "Dranken", 180, "pantry", 5, None, 180, 3,
     "Cupboard; juice and milk drinks in the fridge once opened."),
    ("household", "Household & non-food", "Huishouden", 190, "pantry", None, None, None, None, ""),
    ("other", "Other", "Overig", 200, "pantry", None, None, None, None, ""),
]

DEFAULT_PROFILE = """Cooking for one (Miguel). Very new to cooking: explain every step fully — portion sizes, pan size, heat level on an induction hob (1–9), how to tell when something is done, timings, and basics like how to cut an onion.
Kitchen: induction hob, oven with an air-fryer function, microwave, fridge. Shared house, so fridge and freezer space is limited.
Likes: beef, cheese, dairy, olives, battered eggplant, zucchini cream, potato cream. Not a big fan of vegetables — wants healthy meals that aren't too "green", but open to trying new things.
Prefers regular fried fries over sweet-potato fries; oven/air-fried fries are OK but less liked. Plain chicken on its own is boring (fine with good sides or sauce).
Portion reference: 300 g potato + 400 g chicken for one dinner was too much.
Breakfast is fixed (a glass of whole milk with toast and fruit spread, or cereal/cookies): only put breakfast staples on the shopping list when they run low.
Plan lunch and dinner for every day; leftovers for lunch are fine.
Shops 1–2 times a week, ideally at one cheap supermarket (Lidl or similar). Price-conscious, not extreme. Use current offers at Lidl, Albert Heijn and Dirk to steer the menu, and add some variety to discover new dishes."""

DEFAULT_DISLIKES = [
    ("cucumber", 2, "Added from earlier chats — adjust the severity if needed"),
    ("ketchup", 2, "Added from earlier chats — adjust the severity if needed"),
]


def now_iso() -> str:
    return datetime.now(config.TIMEZONE).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@contextmanager
def session():
    """Open a connection, commit on success, roll back on error."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def row(cur) -> dict | None:
    r = cur.fetchone()
    return dict(r) if r else None


def init_db() -> None:
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if version is None:
            _seed(conn)
            conn.execute("INSERT INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
        conn.commit()
    finally:
        conn.close()


def _seed(conn: sqlite3.Connection) -> None:
    for c in DEFAULT_CATEGORIES:
        conn.execute(
            "INSERT OR IGNORE INTO categories(key,label,label_nl,sort_order,default_location,fridge_days,"
            "freezer_days,pantry_days,opened_days,advice) VALUES(?,?,?,?,?,?,?,?,?,?)",
            c,
        )
    ts = now_iso()
    for item, sev, note in DEFAULT_DISLIKES:
        conn.execute(
            "INSERT OR IGNORE INTO dislikes(item,severity,note,created_at,updated_at) VALUES(?,?,?,?,?)",
            (item, sev, note, ts, ts),
        )
    defaults = {
        "profile": DEFAULT_PROFILE,
        "stores": json.dumps(["Lidl", "Albert Heijn", "Dirk"]),
        "default_servings": "1",
    }
    for k, v in defaults.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (k, v))
