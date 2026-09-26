import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MH_DATA_DIR", tempfile.mkdtemp(prefix="mh-test-"))
os.environ["MH_SYNC_BOOTSTRAP"] = "1"
os.environ["MH_PIPELINE_INTERVAL_MIN"] = "0"


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        tok = c.post("/api/auth/login", json={"username": "admin", "password": "demo123"}).json()["token"]
        c.headers["Authorization"] = f"Bearer {tok}"
        yield c


@pytest.fixture(scope="session")
def as_user(client):
    """Headers for a given demo account."""
    def _h(username):
        tok = client.post("/api/auth/login", json={"username": username, "password": "demo123"}).json()["token"]
        return {"Authorization": f"Bearer {tok}"}
    return _h


@pytest.fixture(scope="session")
def data():
    from ml.synthetic import generate_all
    return generate_all()
