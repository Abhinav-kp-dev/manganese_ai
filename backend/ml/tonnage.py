"""Conceptual tonnage ranges for drill targets, and indicator kriging as a check on the
Gaussian grade model.

The ranges follow the spirit of a JORC Clause 17 "Exploration Target": a range of tonnes and
grade, stated as conceptual, from geometry assumptions plus kriged grade and thickness. They are
not a Mineral Resource and are never labelled as reserves. Every assumption is returned with
the numbers so the UI can show it.

Monte Carlo, per target:
    ore tonnes = strike length x true thickness x down-dip extent x continuity x bulk density
with grade and thickness drawn from their kriging distributions. A draw whose grade falls below
the cut-off contributes zero tonnes, so the probability that there is no ore at all is part of
the range rather than hidden.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import norm

from .geostats import OrdinaryKriging, fit_variogram

# Geometry assumptions (ranges, sampled uniformly). Chosen for Sausar-Group gondite-hosted lenses:
# MOIL's mines work lenses a few hundred metres to ~2 km along strike, a few metres thick,
# followed down dip for a few hundred metres. These are planning assumptions, not measurements.
ASSUMPTIONS = {
    "strike_length_m": (500.0, 2000.0),
    "down_dip_extent_m": (100.0, 300.0),
    "continuity_fraction": (0.3, 0.7),
    "bulk_density_t_m3": (3.5, 4.0),
    "min_thickness_m": 0.5,
}
N_DRAWS = 4000
LABEL = ("Conceptual exploration-target range: a planning estimate from assumed geometry and kriged "
         "borehole grade/thickness. It is not a Mineral Resource or Reserve (UNFC/JORC) and needs drilling to test.")


def krige_thickness(bxy, thickness, targets_xy):
    vario = fit_variogram(bxy, thickness)
    ok = OrdinaryKriging(vario).fit(bxy, thickness)
    m, v = ok.predict(targets_xy)
    return m, np.sqrt(v), vario


def target_range(grade_mean, grade_sd, thick_mean, thick_sd, cutoff, rng, n=N_DRAWS):
    a = ASSUMPTIONS
    u = lambda lo_hi: rng.uniform(*lo_hi, n)
    grade = rng.normal(grade_mean, max(grade_sd, 1e-6), n)
    thick = np.maximum(rng.normal(thick_mean, max(thick_sd, 1e-6), n), 0.0)
    is_ore = (grade >= cutoff) & (thick >= a["min_thickness_m"])
    tonnes = u(a["strike_length_m"]) * thick * u(a["down_dip_extent_m"]) * u(a["continuity_fraction"]) * u(a["bulk_density_t_m3"])
    tonnes = np.where(is_ore, tonnes, 0.0)
    mn = tonnes * np.clip(grade, 0, 60) / 100.0
    ore_grade = grade[is_ore]
    q = lambda x: [float(np.percentile(x, p)) for p in (10, 50, 90)]
    return {
        "p_ore_present": float(is_ore.mean()),
        "ore_tonnes_p10_p50_p90": q(tonnes),
        "contained_mn_tonnes_p10_p50_p90": q(mn),
        "grade_if_ore_pct_p10_p50_p90": q(ore_grade) if len(ore_grade) >= 20 else None,
        "mean_ore_tonnes": float(tonnes.mean()),
    }


def add_tonnage(targets: list[dict], grid, boreholes, km_xy, cutoff, seed=26009):
    """Attach a conceptual tonnage range to each drill target (in place) and return the thickness model."""
    if not targets:
        return {"variogram": None}
    bx, by = km_xy(boreholes.latitude.values, boreholes.longitude.values)
    bxy = np.column_stack([bx, by])
    tx, ty = km_xy(np.array([t["latitude"] for t in targets]), np.array([t["longitude"] for t in targets]))
    t_mean, t_sd, vario = krige_thickness(bxy, boreholes.thickness_m.values.astype(float), np.column_stack([tx, ty]))
    rng = np.random.default_rng(seed)
    for t, tm, ts in zip(targets, t_mean, t_sd):
        g = grid.loc[t["_cell"]]
        rng_t = target_range(float(g.kriged_grade_pct), float(g.kriging_sd_pct), float(tm), float(ts), cutoff, rng)
        t["tonnage"] = {
            **{k: (np.round(v, 0).tolist() if isinstance(v, list) else round(v, 3)) for k, v in rng_t.items()},
            "kriged_thickness_m": round(float(tm), 2), "kriged_thickness_sd_m": round(float(ts), 2),
            "assumptions": ASSUMPTIONS, "label": LABEL,
        }
    return {"variogram": vario}


# --------------------------------------------------------------------------------- indicator kriging
def indicator_kriging(bxy, grade, cutoff, xy_new):
    """P(grade >= cut-off) by ordinary kriging of the 0/1 indicator (no Gaussian assumption)."""
    ind = (np.asarray(grade) >= cutoff).astype(float)
    vario = fit_variogram(bxy, ind)
    ok = OrdinaryKriging(vario).fit(bxy, ind)
    p, _ = ok.predict(xy_new)
    return np.clip(p, 0, 1), vario


def compare_probability_models(bxy, grade, cutoff, x_km, y_km, k=5, seed=26009):
    """Cross-validated Brier score of Gaussian-kriging vs indicator-kriging P(grade >= cut-off)."""
    grade = np.asarray(grade, float)
    folds = np.random.default_rng(seed).permutation(len(grade)) % k
    p_gauss = np.zeros(len(grade))
    p_ik = np.zeros(len(grade))
    for f in range(k):
        te = folds == f
        v = fit_variogram(bxy[~te], grade[~te])
        m, var = OrdinaryKriging(v).fit(bxy[~te], grade[~te]).predict(bxy[te])
        p_gauss[te] = 1 - norm.cdf((cutoff - m) / np.maximum(np.sqrt(var), 1e-6))
        p_ik[te], _ = indicator_kriging(bxy[~te], grade[~te], cutoff, bxy[te])
    y = (grade >= cutoff).astype(float)
    base = np.mean(y)
    brier = lambda p: float(np.mean((p - y) ** 2))
    return {
        "scheme": f"random {k}-fold over boreholes",
        "brier_gaussian_kriging": brier(p_gauss), "brier_indicator_kriging": brier(p_ik),
        "brier_climatology": brier(np.full(len(y), base)),
        "n_boreholes": int(len(y)), "fraction_above_cutoff": float(base),
        "reading": "Lower is better. The map uses Gaussian kriging; indicator kriging is shown as the distribution-free check.",
    }
