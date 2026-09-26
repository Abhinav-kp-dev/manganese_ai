import io
import json

import pandas as pd
from fastapi.testclient import TestClient

from app import pipeline
from app.auth import decode_token, hash_password, verify_password
from app.ingest import TEMPLATE


def _audit(mine, decision="APPROVED"):
    return {"recommendation_key": "k", "action_title": "t", "mine_id": mine, "decision": decision}


def test_password_hashing():
    h = hash_password("s3cret")
    assert verify_password("s3cret", h) and not verify_password("wrong", h)


def test_reads_require_sign_in(client):
    from app.main import app
    anon = TestClient(app)
    assert anon.get("/api/health").status_code == 200
    assert anon.get("/api/overview").status_code == 401
    assert anon.get("/api/overview", headers={"Authorization": "Bearer forged.token"}).status_code == 401
    assert anon.post("/api/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401
    roles = anon.get("/api/auth/roles").json()
    assert {r["role"] for r in roles["roles"]} == {"ADMIN", "MINE_MANAGER", "PLANNER", "GEOLOGIST", "VIEWER"}


def test_token_carries_role(client):
    tok = client.post("/api/auth/login", json={"username": "manager.balaghat", "password": "demo123"}).json()["token"]
    d = decode_token(tok)
    assert d["role"] == "MINE_MANAGER" and d["site"] == "BLG"


def test_mine_manager_is_site_scoped(client, as_user):
    h = as_user("manager.balaghat")
    assert client.post("/api/audit", json=_audit("BLG-01"), headers=h).status_code == 200
    r = client.post("/api/audit", json=_audit("BHD-01"), headers=h)
    assert r.status_code == 403 and "site scope" in r.json()["detail"]


def test_role_permissions(client, as_user):
    assert client.post("/api/audit", json=_audit("BLG-01"), headers=as_user("planner")).status_code == 403
    assert client.post("/api/audit", json=_audit("BLG-01", "DEFERRED"), headers=as_user("planner")).status_code == 200
    assert client.post("/api/audit", json=_audit("BLG-01", "DEFERRED"), headers=as_user("viewer")).status_code == 403
    csv = io.BytesIO(TEMPLATE.encode())
    assert client.post("/api/data/upload", files={"file": ("t.csv", csv, "text/csv")}, headers=as_user("viewer")).status_code == 403
    assert client.post("/api/pipeline/run/inbox", headers=as_user("planner")).status_code == 403
    assert client.get("/api/overview", headers=as_user("viewer")).status_code == 200


def test_inbox_job_loads_valid_and_rejects_invalid(client):
    pipeline.INBOX.mkdir(parents=True, exist_ok=True)
    (pipeline.INBOX / "good.csv").write_text(TEMPLATE)
    (pipeline.INBOX / "bad.csv").write_text("mine_id,date\nXXX,2026-01-01\n")
    res = client.post("/api/pipeline/run/inbox").json()["results"][0]
    assert res["status"] == "ok" and "1 rows stored" in res["message"] and "1 file(s) rejected" in res["message"]
    assert list((pipeline.INBOX / "rejected").glob("*bad.csv.errors.txt"))
    st = client.get("/api/pipeline").json()
    assert st["recent_runs"][0]["job"] == "inbox"
    from app.db import ProductionLog, SessionLocal
    with SessionLocal() as s:
        assert s.get(ProductionLog, ("BLG-01", pd.Timestamp("2026-08-01").date())).is_synthetic is False


def test_power_parser_and_failed_fetch_is_logged(client, monkeypatch):
    days = pd.date_range("2024-07-01", "2024-08-31")
    payload = {"properties": {"parameter": {
        "PRECTOTCORR": {d.strftime("%Y%m%d"): (10.0 if d.day % 2 else 0.0) for d in days},
        "GWETTOP": {d.strftime("%Y%m%d"): 0.6 for d in days},
        "TS": {d.strftime("%Y%m%d"): (-999.0 if d.day == 1 else 28.0) for d in days}}}}
    m = pipeline.power_to_monthly(payload)
    assert m.loc["2024-07-01", "rainfall_mm"] == 160.0 and m.loc["2024-07-01", "rainy_days"] == 16
    assert m.loc["2024-07-01", "land_surface_temp_c"] == 28.0  # fill value ignored

    monkeypatch.setattr(pipeline, "fetch_power_daily", lambda *a, **k: payload)
    ok = client.post("/api/pipeline/run/nasa_power").json()["results"][0]
    assert ok["status"] == "ok"
    rows = client.get("/api/external-weather/BLG-01").json()["rows"]
    assert rows and rows[0]["source"] == "NASA_POWER"

    def boom(*a, **k):
        raise OSError("network unreachable")
    monkeypatch.setattr(pipeline, "fetch_power_daily", boom)
    from app.db import ExternalWeather, SessionLocal
    with SessionLocal() as s:
        s.query(ExternalWeather).delete()
        s.commit()
    bad = client.post("/api/pipeline/run/nasa_power").json()["results"][0]
    assert bad["status"] == "failed" and "network unreachable" in bad["message"]
