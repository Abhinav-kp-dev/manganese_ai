"""Real-data path: committed Sentinel-2 / DEM / WorldCover features and real Mn locations."""
import pandas as pd
import pytest

from ml.realdata import REAL_DIR, REAL_FEATURES, available, load_grid, load_labels, run_real_module1, validate_labels
from ml.reference import MINES
from ml.remote_sensing import check_physical, grid_axes


def test_real_files_are_committed():
    assert available(), f"missing real data in {REAL_DIR}"


def test_real_grid_matches_study_grid_and_is_physical():
    g = load_grid()
    lats, lons = grid_axes()
    assert len(g) == len(lats) * len(lons)
    assert check_physical(g) == []
    assert g[REAL_FEATURES].notna().mean().min() > 0.95


def test_real_grid_is_consistent_across_sources():
    """Independent geolocation check: Sentinel-2 water index agrees with ESA WorldCover water."""
    g = load_grid()
    assert g[["ndwi", "frac_water"]].corr().iloc[0, 1] > 0.4


def test_moil_labels_match_the_mine_registry():
    lab = load_labels()
    for m in MINES:
        row = lab[lab.source_ref == m["mine_id"]]
        assert len(row) == 1
        assert abs(row.latitude.iloc[0] - m["latitude"]) < 1e-9 and abs(row.longitude.iloc[0] - m["longitude"]) < 1e-9
    assert lab.source.notna().all()


def test_extra_labels_are_validated(tmp_path):
    bad = tmp_path / "extra.csv"
    pd.DataFrame({"name": ["x"], "latitude": [21.5], "longitude": [79.5]}).to_csv(bad, index=False)
    with pytest.raises(ValueError, match="source"):
        load_labels(extra=bad)
    good = tmp_path / "good.csv"
    pd.DataFrame({"name": ["GSI occurrence"], "latitude": [21.6], "longitude": [79.9], "source": ["GSI Bhukosh"]}).to_csv(good, index=False)
    lab = load_labels(extra=good)
    assert "GSI occurrence" in set(lab.name) and lab[lab.name == "GSI occurrence"].use_for_training.iloc[0]
    assert validate_labels(pd.DataFrame({"name": ["a"], "latitude": ["x"], "longitude": [1], "source": ["s"]}))


def test_real_evaluation_reports_honest_uncertainty():
    r = run_real_module1()
    v = r["validation"]
    assert r["available"] and v["method"].startswith("Spatially blocked")
    assert v["n_positive"] >= 9
    lo, hi = v["spatial_cv_auc_ci95"]
    assert 0 <= lo <= v["spatial_cv_auc"] <= hi <= 1
    assert r["disturbance_auc"] is not None
    assert not ({"latitude", "longitude", "x_km", "y_km"} & set(r["features"]))


def test_real_endpoint_and_imagery(client):
    j = client.get("/api/reserves/real").json()
    assert j["available"]
    assert len(j["layers"]["surface_prob_real"]) == j["rows"] * j["cols"]
    assert j["provenance"]["attribution"] and j["provenance"]["scenes"]
    for url in j["imagery"].values():
        r = client.get(url, headers={"Authorization": ""})  # public: open ESA data
        assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get("/api/imagery/secret.key").status_code == 404
    r = client.get("/api/imagery/..%2Fprovenance.json")  # traversal must never reach the data directory
    assert r.status_code == 404 or b"sentinel2" not in r.content


def test_integrity_reports_real_next_to_synthetic(client):
    j = client.get("/api/integrity").json()
    rows = {r["metric"]: r for r in j["real_vs_synthetic"]}
    auc = rows["Module 1 surface proxy, spatial-CV AUC"]
    assert auc["synthetic"] is not None and auc["real"] is not None
    assert any(c["id"] == "real_data" and c["pass"] for c in j["checks"])
