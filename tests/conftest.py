import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp(prefix="mealplanner-test-")
os.environ["DATA_DIR"] = _tmp
os.environ["APP_PASSWORD"] = "test-pass"
os.environ["BASE_URL"] = "http://localhost"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, base_url="http://localhost", follow_redirects=False) as c:
        r = c.post("/login", data={"password": "test-pass", "next": "/"})
        assert r.status_code == 303
        yield c


@pytest.fixture(scope="session")
def token(client):
    from oauth_flow import oauth_token

    return oauth_token("http://localhost", "test-pass", "client_secret_post", client)["access_token"]
