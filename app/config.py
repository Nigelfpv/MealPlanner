"""Runtime configuration, read from environment variables."""

import os
import secrets
from pathlib import Path
from zoneinfo import ZoneInfo

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "mealplanner.db"

# Public URL of the app, e.g. https://comida.mmrdrive.duckdns.org (no trailing slash).
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")

# Password for the web UI and for authorising Claude.
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

TIMEZONE = ZoneInfo(os.environ.get("TZ", "Europe/Amsterdam"))

SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "180"))
ACCESS_TOKEN_DAYS = int(os.environ.get("ACCESS_TOKEN_DAYS", "30"))
REFRESH_TOKEN_DAYS = int(os.environ.get("REFRESH_TOKEN_DAYS", "365"))


def secret_key() -> str:
    """SECRET_KEY env var, or a random key persisted in the data dir."""
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "secret_key"
    if path.exists():
        return path.read_text().strip()
    key = secrets.token_urlsafe(48)
    path.write_text(key)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key
