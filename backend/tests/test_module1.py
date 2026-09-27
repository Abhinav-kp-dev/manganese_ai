"""Module 1 guardrails: the surface model must learn surface signals (not location), and tonnage
ranges must behave like honest, conditional estimates."""
import numpy as np
import pytest

from ml.prospectivity import SURFACE_FEATURES, train_surface_model
from ml.tonnage import LABEL, compare_probability_models, indicator_kriging, target_range


def test_surface_model_finds_nothing_when_ore_is_unrelated_to_surface_signals(data):
    """Scramble the satellite/terrain features across cells, so the known occurrences no longer sit
    on any surface signal. A model that had learned location instead of geology would still score
    well here; ours must fall to chance."""
    grid = data["grid"].copy()
    rng = np.random.default_rng(7)
    grid[SURFACE_FEATURES] = grid[SURFACE_FEATURES].values[rng.permutation(len(grid))]
    _, _, val, _ = train_surface_model(grid, data["occurrences"])
    assert val["spatial_cv_auc"] < 0.65, val["spatial_cv_auc"]


def test_surface_model_does_find_ore_when_the_signal_is_there(data):
    """Control for the test above: same pipeline, real synthetic signal, clearly above chance."""
    _, _, val, _ = train_surface_model(data["grid"], data["occurrences"])
    assert val["spatial_cv_auc"] > 0.8


def test_tonnage_is_zero_when_grade_is_far_below_cutoff():
    r = target_range(grade_mean=10, grade_sd=1, thick_mean=5, thick_sd=1, cutoff=25, rng=np.random.default_rng(0))
    assert r["p_ore_present"] == 0
    assert r["ore_tonnes_p10_p50_p90"] == [0.0, 0.0, 0.0]


def test_tonnage_range_is_ordered_and_positive_when_ore_is_likely():
    r = target_range(grade_mean=40, grade_sd=2, thick_mean=6, thick_sd=1, cutoff=25, rng=np.random.default_rng(0))
    p10, p50, p90 = r["ore_tonnes_p10_p50_p90"]
    assert r["p_ore_present"] > 0.95
    assert 0 < p10 < p50 < p90
    m10, m50, m90 = r["contained_mn_tonnes_p10_p50_p90"]
    assert m50 < p50  # contained metal is a fraction of ore tonnes


def test_uncertain_grade_widens_the_range_and_lowers_p_ore():
    rng = np.random.default_rng(0)
    sure = target_range(30, 1, 6, 1, 25, rng)
    unsure = target_range(30, 12, 6, 1, 25, rng)
    assert unsure["p_ore_present"] < sure["p_ore_present"]
    assert unsure["ore_tonnes_p10_p50_p90"][0] <= sure["ore_tonnes_p10_p50_p90"][0]


def test_indicator_kriging_gives_probabilities(data):
    bh = data["boreholes"]
    from ml.synthetic import _km_xy
    bx, by = _km_xy(bh.latitude.values, bh.longitude.values)
    bxy = np.column_stack([bx, by])
    p, _ = indicator_kriging(bxy, bh.grade_mn_pct.values, 25.0, bxy[:20])
    assert ((p >= 0) & (p <= 1)).all()
    cmp = compare_probability_models(bxy, bh.grade_mn_pct.values, 25.0, bx, by)
    assert cmp["brier_gaussian_kriging"] < cmp["brier_climatology"]
    assert cmp["brier_indicator_kriging"] < cmp["brier_climatology"]


def test_drill_targets_carry_conceptual_tonnage(client):
    targets = client.get("/api/reserves/points").json()["drill_targets"]
    assert targets
    for t in targets:
        tn = t["tonnage"]
        assert tn["label"] == LABEL and "not a Mineral Resource" in tn["label"]
        lo, mid, hi = tn["ore_tonnes_p10_p50_p90"]
        assert 0 <= lo <= mid <= hi
        assert 0 <= tn["p_ore_present"] <= 1
        assert "_cell" not in t
