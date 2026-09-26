"""Scientific-integrity guardrails from the implementation plan (§9), enforced as tests."""
import numpy as np

from ml.geostats import OrdinaryKriging, assign_block_folds, fit_variogram, spatial_blocks
from ml.forecasting import achievement_probability, _predict_quantiles
from ml.prospectivity import FORBIDDEN_FEATURES, SURFACE_FEATURES
from ml.optimizer import optimise
from ml.scenarios import realigned_target


def test_generator_is_deterministic():
    from ml.synthetic import generate_all
    a, b = generate_all(), generate_all()
    assert a["production_logs"].production_tonnes.sum() == b["production_logs"].production_tonnes.sum()


def test_everything_generated_is_tagged_synthetic(data):
    for k in ("production_logs", "weather_features", "mine_plans"):
        assert data[k]["is_synthetic"].all()


def test_kriging_is_exact_at_data_and_variance_grows_with_distance():
    rng = np.random.default_rng(0)
    xy = rng.uniform(0, 50, (60, 2))
    z = np.sin(xy[:, 0] / 8) * 10 + 30
    v = fit_variogram(xy, z)
    v["nugget"] = 0.0
    ok = OrdinaryKriging(v).fit(xy, z)
    m, var = ok.predict(xy)
    assert np.allclose(m, z, atol=1e-5)
    _, far = ok.predict(np.array([[500.0, 500.0]]))
    assert far[0] > var.max()


def test_spatial_folds_hold_out_whole_blocks():
    rng = np.random.default_rng(1)
    x, y = rng.uniform(0, 200, 500), rng.uniform(0, 100, 500)
    blocks = spatial_blocks(x, y, 30)
    folds = assign_block_folds(blocks, 5)
    for b in np.unique(blocks):
        assert len(np.unique(folds[blocks == b])) == 1


def test_no_leakage_features():
    assert not FORBIDDEN_FEATURES & set(SURFACE_FEATURES)
    assert "dist_known_deposit_km" in FORBIDDEN_FEATURES


def test_quantiles_are_monotone_and_non_negative():
    class Fake:
        def __init__(self, v): self.v = v
        def predict(self, X): return np.full(len(X), self.v)
    q = _predict_quantiles({0.1: Fake(0.9), 0.5: Fake(-0.1), 0.9: Fake(0.4)}, np.zeros((3, 2)))
    assert (q[:, 0] <= q[:, 1]).all() and (q[:, 1] <= q[:, 2]).all() and (q >= 0).all()


def test_achievement_probability_properties():
    assert abs(achievement_probability(100, 80, 100, 120) - 0.5) < 1e-9
    assert achievement_probability(80, 80, 100, 120) > 0.85
    assert achievement_probability(130, 80, 100, 120) < 0.1
    t = realigned_target(80, 100, 120, 0.6)
    assert abs(achievement_probability(t, 80, 100, 120) - 0.6) < 1e-6


def _fc(mid, p50, target, cap=30000):
    drivers = [{"driver": "Blasting window (licence & weather limits)", "contribution_tonnes": -800.0, "lever": "blasting"}]
    return {"mine_id": mid, "p10": p50 * 0.9, "p50": p50, "p90": p50 * 1.1, "target": target, "deficit_p50": max(0, target - p50),
            "achievement_probability": 0.2, "rated_monthly_capacity": cap, "drivers": drivers,
            "inputs": {"availability_lag": 90.0, "planned_operating_days": 26, "blast_window_days": 20, "fleet_health_index": 0.8,
                       "planned_maintenance_hours": 36, "rainfall_forecast_mm": 50, "rainy_days_forecast": 3, "stockpile_days_lag": 3}}


def test_lp_respects_balance_and_sister_capacity():
    fcs = [_fc("BLG-01", 20000, 26000, 48000), _fc("BLG-02", 10000, 10000, 15600), _fc("NGP-04", 9000, 9000, 13500)]
    att = {f["mine_id"]: {"attribution_confidence": 0.5} for f in fcs}
    res = optimise(fcs, att)
    blk = res["actions_by_mine"]["BLG-01"]
    assert abs(sum(a["tonnes"] for a in blk["actions"]) + blk["unmitigated"] - 6000) < 1
    for sj, spare in res["sister_spare_capacity"].items():
        used = sum(a["tonnes"] for v in res["actions_by_mine"].values() for a in v["actions"] if a.get("sister_mine_id") == sj)
        assert used <= spare + 1
    assert any(a["lever"] == "reallocation" for a in blk["actions"]), "large deficit should draw on sister capacity"
    assert all("Scenario estimate" in a["disclaimer"] for a in blk["actions"])
