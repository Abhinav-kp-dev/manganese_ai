import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MH_DATA_DIR", tempfile.mkdtemp(prefix="mh-test-"))
os.environ["MH_SYNC_BOOTSTRAP"] = "1"


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def data():
    from ml.synthetic import generate_all
    return generate_all()
