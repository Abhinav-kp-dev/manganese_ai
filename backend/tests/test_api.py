import io


def test_health_and_meta(client):
    assert client.get("/api/health").json()["status"] == "ok"
    m = client.get("/api/meta").json()
    assert m["data_mode"] == "SYNTHETIC"
    assert m["meta"]["is_synthetic"] and m["meta"]["disclaimers"]


def test_forecasts_are_tagged_and_monotone(client):
    fcs = client.get("/api/forecast/summary").json()["forecasts"]
    assert len(fcs) == 10
    for f in fcs:
        assert 0 <= f["p10"] <= f["p50"] <= f["p90"]
        assert 0 <= f["achievement_probability"] <= 1
        assert f["tags"]["p50"] == "MODEL_INFERENCE"


def test_metrics_always_include_baselines(client):
    for h, m in client.get("/api/forecast/metrics").json()["metrics"].items():
        assert {"model_p50", "persistence_baseline", "seasonal_naive_baseline"} <= set(m)


def test_driver_guardrail_never_invents_causes(client):
    for f in client.get("/api/forecast/summary?horizon=2").json()["forecasts"]:
        a = f["attribution"]
        if a["insufficient_evidence"]:
            assert a["message"] == "Insufficient evidence to determine the cause."
        for d in a["risk_drivers"]:
            assert d["contribution_tonnes"] < 0


def test_reserve_outputs_are_prospectivity_not_reserves(client):
    g = client.get("/api/reserves/grid").json()
    assert g["rows"] * g["cols"] == len(g["layers"]["confidence"])
    assert any("not a reserve" in d for d in g["meta"]["disclaimers"])
    v = client.get("/api/reserves/validation").json()
    assert v["surface_validation"]["method"].startswith("Spatially blocked")


def test_actions_carry_disclaimer(client):
    res = client.get("/api/actions").json()
    for blk in res["actions_by_mine"].values():
        for a in blk["actions"]:
            assert "Scenario estimate" in a["disclaimer"]


def test_scenarios_move_in_physical_direction(client):
    base = client.post("/api/scenarios/run", json={"scenario_id": "baseline"}).json()["totals"]["baseline_p50"]
    bad = client.post("/api/scenarios/run", json={"scenario_id": "bad_weather"}).json()["totals"]["scenario_p50"]
    good = client.post("/api/scenarios/run", json={"scenario_id": "optimistic"}).json()["totals"]["scenario_p50"]
    assert bad < base < good


def test_equipment_scenario_moves_every_horizon(client):
    for h in (1, 2, 3):
        base = client.post("/api/scenarios/run", json={"scenario_id": "baseline", "horizon": h}).json()["totals"]["baseline_p50"]
        down = client.post("/api/scenarios/run", json={"scenario_id": "equipment_downtime", "horizon": h}).json()["totals"]["scenario_p50"]
        assert down < base, f"horizon {h}: equipment breakdown should lower the forecast"


def test_integrity_checks_pass(client):
    j = client.get("/api/integrity").json()
    failing = [c for c in j["checks"] if c["pass"] is False]
    assert not failing, failing


def test_upload_validation_rejects_bad_rows(client):
    csv = "mine_id,date,production_tonnes\nXXX,2026-01-15,5\n"
    r = client.post("/api/data/upload", files={"file": ("x.csv", io.BytesIO(csv.encode()), "text/csv")}).json()
    assert not r["valid"] and "Missing columns" in r["errors"][0]
    tpl = client.get("/api/data/template").text
    r = client.post("/api/data/upload", files={"file": ("t.csv", io.BytesIO(tpl.encode()), "text/csv")}).json()
    assert r["valid"] and not r["committed"]


def test_audit_roundtrip(client):
    r = client.post("/api/audit", json={"recommendation_key": "k", "action_title": "t", "mine_id": "BLG-01", "decision": "APPROVED"})
    assert r.status_code == 200
    e = client.get("/api/audit").json()["entries"][0]
    assert e["decision"] == "APPROVED" and e["role"] == "ADMIN" and e["decided_by"] == "Control Room Administrator"
    assert client.post("/api/audit", json={"recommendation_key": "k", "action_title": "t", "decision": "MAYBE"}).status_code == 422
