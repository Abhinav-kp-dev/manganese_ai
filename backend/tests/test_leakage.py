"""Look-ahead guardrails for Module 2: a forecast issued at the end of month t-h may only use
information that existed then."""
import numpy as np
import pandas as pd
import pytest

from ml.features import FEATURES, PLAN_COLS, build_panel, make_features


@pytest.fixture(scope="module")
def panel(data):
    return build_panel(data["production_logs"], data["weather_features"], data["mine_plans"])


@pytest.mark.parametrize("h", [1, 2, 3])
def test_features_ignore_everything_realised_after_issue_time(panel, h):
    """Scramble every observed value (production, downtime, weather) from the issue month onwards
    and every plan value between issue time and the target month: target-month features must not move."""
    months = np.sort(panel.month.unique())
    target = pd.Timestamp(months[-40])
    issue = target - pd.DateOffset(months=h)
    observed = ["production_tonnes", "util", "downtime_ratio", "equipment_availability_pct", "stockpile_days",
                "soil_moisture", "ndvi", "rainfall_mm", "land_surface_temp_c"]
    later_plan = ["fleet_health_index"]  # plan columns read at a lag
    p = panel.copy()
    rng = np.random.default_rng(0)
    after_issue = p.month > issue
    for c in observed:
        p.loc[after_issue, c] = rng.permutation(p.loc[after_issue, c].values)
    between = (p.month > issue + pd.DateOffset(months=1)) & (p.month <= target)
    for c in later_plan:
        p.loc[between, c] = rng.uniform(0.2, 0.98, between.sum())
    a = make_features(panel, h)
    b = make_features(p, h)
    sel = a.month == target
    pd.testing.assert_frame_equal(a.loc[sel, FEATURES].reset_index(drop=True), b.loc[sel, FEATURES].reset_index(drop=True))


def test_fleet_health_is_read_at_issue_time(panel):
    months = np.sort(panel.month.unique())
    t = pd.Timestamp(months[-20])
    for h in (1, 2, 3):
        f = make_features(panel, h)
        got = f[(f.month == t) & (f.mine_id == "BLG-01")].fleet_health_index.iloc[0]
        known_month = t - pd.DateOffset(months=h - 1)
        want = panel[(panel.month == known_month) & (panel.mine_id == "BLG-01")].fleet_health_index.iloc[0]
        assert got == want


def test_rainfall_outlook_has_realistic_not_perfect_skill(data):
    m = data["mine_plans"].merge(data["weather_features"], left_on=["mine_id", "month"], right_on=["mine_id", "date"])
    mo = pd.to_datetime(m.month).dt.month
    clim = np.log1p(m.groupby(mo).rainfall_mm.transform("mean"))
    r = np.corrcoef(np.log1p(m.rainfall_forecast_mm) - clim, np.log1p(m.rainfall_mm) - clim)[0, 1]
    assert 0.2 < r < 0.75, f"outlook anomaly correlation {r:.2f} is outside the plausible range for a monthly outlook"


def test_plan_columns_are_all_ex_ante():
    assert "rainfall_mm" not in FEATURES and "downtime_hours" not in FEATURES
    assert set(PLAN_COLS) <= set(FEATURES)
