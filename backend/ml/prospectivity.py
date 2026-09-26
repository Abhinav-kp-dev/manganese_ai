"""Module 1: Reserve Confidence Mapping.

Two independent evidence layers are fused per grid cell:
  * sub-surface: ordinary kriging of borehole Mn grade -> P(grade >= cut-off) with kriging variance
  * surface proxy: XGBoost trained on known occurrences vs distance-constrained pseudo-absences
    using Sentinel-2 band ratios, Sentinel-1 SAR, DEM derivatives, lineaments and mapped lithology.

Guardrails: no "distance to known deposit" and no raw coordinates as features (the model must
learn geology, not proximity); spatially blocked CV; output is "prospectivity", never "reserve".
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb
from scipy.stats import norm
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold

from .geostats import OrdinaryKriging, assign_block_folds, fit_variogram, kriging_cv, spatial_blocks
from .synthetic import COVER_TYPES, _km_xy

SURFACE_FEATURES = [
    "ferric_ratio_b4_b2", "clay_ratio_b11_b12", "ndvi", "ndwi", "sar_vv_db", "sar_vh_db",
    "elevation_m", "slope_deg", "ruggedness_m", "dist_lineament_km", "lithology_favourability",
]
FEATURE_LABELS = {
    "ferric_ratio_b4_b2": "Ferric-iron ratio (S2 B4/B2)",
    "clay_ratio_b11_b12": "Clay/alteration ratio (S2 B11/B12)",
    "ndvi": "Vegetation index (NDVI)",
    "ndwi": "Water index (NDWI)",
    "sar_vv_db": "SAR backscatter VV (S1)",
    "sar_vh_db": "SAR backscatter VH (S1)",
    "elevation_m": "Elevation (DEM)",
    "slope_deg": "Slope",
    "ruggedness_m": "Terrain ruggedness",
    "dist_lineament_km": "Distance to lineament/fault",
    "lithology_favourability": "Mapped host lithology (Gondite / Sausar Gp.)",
}
FORBIDDEN_FEATURES = {"dist_known_deposit_km", "min_distance_to_known_deposit_km", "latitude", "longitude", "x_km", "y_km"}
CUTOFF_MN_PCT = 25.0
EXCLUSION_BUFFER_KM = 3.0
BLOCK_KM = 30.0
ZONES = [(0.70, "Very High"), (0.50, "High"), (0.30, "Moderate"), (0.15, "Low"), (-1, "Very Low")]
COVER_RELIABILITY = {0: 1.0, 1: 0.6, 2: 0.15, 3: 0.1}

XGB_PARAMS = dict(n_estimators=250, max_depth=3, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                  min_child_weight=2, reg_lambda=2.0, eval_metric="logloss", random_state=26009, n_jobs=2)


def _nearest_cells(grid, lat, lon):
    gx, gy = grid["x_km"].values, grid["y_km"].values
    x, y = _km_xy(np.asarray(lat), np.asarray(lon))
    return np.array([int(np.argmin((gx - a) ** 2 + (gy - b) ** 2)) for a, b in zip(x, y)])


def build_training_set(grid, occurrences, rng, ratio=5):
    pos_cells = np.unique(_nearest_cells(grid, occurrences.latitude, occurrences.longitude))
    px, py = grid.x_km.values[pos_cells], grid.y_km.values[pos_cells]
    d_min = np.sqrt((grid.x_km.values[:, None] - px[None]) ** 2 + (grid.y_km.values[:, None] - py[None]) ** 2).min(axis=1)
    eligible = np.flatnonzero(d_min >= EXCLUSION_BUFFER_KM)
    neg_cells = rng.choice(eligible, size=min(len(eligible), ratio * len(pos_cells)), replace=False)
    cells = np.concatenate([pos_cells, neg_cells])
    y = np.concatenate([np.ones(len(pos_cells)), np.zeros(len(neg_cells))]).astype(int)
    return cells, y


def train_surface_model(grid, occurrences, seed=26009):
    assert not FORBIDDEN_FEATURES & set(SURFACE_FEATURES), "leakage feature in surface model"
    rng = np.random.default_rng(seed)
    cells, y = build_training_set(grid, occurrences, rng)
    X = grid.loc[cells, SURFACE_FEATURES].values
    spw = (y == 0).sum() / max((y == 1).sum(), 1)

    folds = assign_block_folds(spatial_blocks(grid.x_km.values[cells], grid.y_km.values[cells], BLOCK_KM), 5, seed)
    oof = np.full(len(y), np.nan)
    fold_models, fold_auc = [], []
    for f in range(5):
        te = folds == f
        m = xgb.XGBClassifier(scale_pos_weight=spw, **XGB_PARAMS).fit(X[~te], y[~te])
        fold_models.append(m)
        oof[te] = m.predict_proba(X[te])[:, 1]
        if len(np.unique(y[te])) == 2:
            fold_auc.append({"fold": f, "auc": float(roc_auc_score(y[te], oof[te])), "n_pos": int(y[te].sum()), "n": int(te.sum())})
    spatial_auc = float(roc_auc_score(y, oof))
    boot = []
    for _ in range(400):
        idx = rng.integers(0, len(y), len(y))
        if len(np.unique(y[idx])) == 2:
            boot.append(roc_auc_score(y[idx], oof[idx]))

    rand_oof = np.zeros(len(y))
    for tr, te in StratifiedKFold(5, shuffle=True, random_state=seed).split(X, y):
        rand_oof[te] = xgb.XGBClassifier(scale_pos_weight=spw, **XGB_PARAMS).fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]

    final = xgb.XGBClassifier(scale_pos_weight=spw, **XGB_PARAMS).fit(X, y)
    gain = final.get_booster().get_score(importance_type="gain")
    total = sum(gain.values()) or 1.0
    importance = sorted(
        [{"feature": f, "label": FEATURE_LABELS[f], "importance": float(gain.get(f"f{i}", gain.get(f, 0.0)) / total)} for i, f in enumerate(SURFACE_FEATURES)],
        key=lambda d: -d["importance"])
    validation = {
        "method": "Spatially blocked 5-fold CV (~30 km blocks)",
        "spatial_cv_auc": spatial_auc,
        "spatial_cv_auc_ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
        "per_fold": fold_auc,
        "random_kfold_auc_for_comparison": float(roc_auc_score(y, rand_oof)),
        "n_positive": int(y.sum()), "n_pseudo_absence": int((y == 0).sum()),
        "pseudo_absence_buffer_km": EXCLUSION_BUFFER_KM,
        "excluded_features": sorted(FORBIDDEN_FEATURES),
        "note": "Positive-unlabelled setting: pseudo-absences are background, not proven barren ground. "
                "The small positive count widens the true uncertainty of this AUC; treat as indicative.",
    }
    return final, fold_models, validation, importance


def run_module1(data: dict) -> dict:
    grid = data["grid"].copy()
    bh = data["boreholes"]
    bx, by = _km_xy(bh.latitude.values, bh.longitude.values)
    bxy = np.column_stack([bx, by])
    z = bh.grade_mn_pct.values.astype(float)

    vario = fit_variogram(bxy, z)
    kcv = {
        "interpolation": kriging_cv(bxy, z, vario, bx, by),
        "extrapolation": kriging_cv(bxy, z, vario, bx, by, block_km=BLOCK_KM),
        "reading": "Kriging is reliable within ~one variogram range of boreholes and no better than a regional "
                   "mean beyond it. That gap is what the satellite surface proxy is fused in to cover.",
    }
    ok = OrdinaryKriging(vario).fit(bxy, z)
    mean, var = ok.predict(grid[["x_km", "y_km"]].values)
    sd = np.sqrt(var)
    sill = vario["nugget"] + vario["partial_sill"]
    grid["kriged_grade_pct"] = mean
    grid["kriging_sd_pct"] = sd
    grid["p_grade_above_cutoff"] = 1 - norm.cdf((CUTOFF_MN_PCT - mean) / np.maximum(sd, 1e-6))
    support = np.clip(1 - var / sill, 0, 1)
    grid["data_support"] = support

    final, fold_models, validation, importance = train_surface_model(grid, data["occurrences"])
    Xg = grid[SURFACE_FEATURES].values
    grid["surface_prob"] = final.predict_proba(Xg)[:, 1]
    ens = np.stack([m.predict_proba(Xg)[:, 1] for m in fold_models])
    grid["surface_model_spread"] = ens.std(axis=0)

    r = grid.cover_type.map(COVER_RELIABILITY).values
    prior = float(np.mean(grid["surface_prob"] > 0.5))
    surf_eff = r * grid["surface_prob"].values + (1 - r) * prior
    conf = support * grid["p_grade_above_cutoff"].values + (1 - support) * surf_eff
    u_sub = np.clip(sd / np.sqrt(sill), 0, 1)
    u_surf = r * np.clip(grid["surface_model_spread"].values * 2, 0, 1) + (1 - r)
    grid["confidence"] = np.clip(conf, 0, 1)
    grid["uncertainty"] = np.clip(support * u_sub + (1 - support) * u_surf, 0, 1)
    grid["zone"] = [next(name for th, name in ZONES if c >= th) for c in grid["confidence"]]
    grid["cover_name"] = grid.cover_type.map(COVER_TYPES)

    # Simulation-only sanity check: only possible because the synthetic world has a known truth.
    truth = (grid["_grade_true"] >= CUTOFF_MN_PCT).astype(int)
    covered = grid.cover_type >= 2
    sim_check = {
        "fused_auc_vs_synthetic_truth": float(roc_auc_score(truth, grid.confidence)),
        "surface_only_auc_vs_synthetic_truth": float(roc_auc_score(truth, grid.surface_prob)),
        "fused_auc_under_cover": float(roc_auc_score(truth[covered], grid.confidence[covered])) if truth[covered].nunique() == 2 else None,
        "surface_only_auc_under_cover": float(roc_auc_score(truth[covered], grid.surface_prob[covered])) if truth[covered].nunique() == 2 else None,
        "note": "Possible only in simulation where the true grade field is known. Never reportable for real data.",
    }

    targets = select_drill_targets(grid, final, data)
    return {
        "grid": grid.drop(columns=["_latent", "_grade_true"]),
        "variogram": vario, "kriging_cv": kcv, "surface_validation": validation,
        "feature_importance": importance, "simulation_check": sim_check, "drill_targets": targets,
        "surface_model": final, "cutoff_mn_pct": CUTOFF_MN_PCT,
    }


def select_drill_targets(grid, model, data, n=10, min_sep_km=6.0, lease_buffer_km=3.0):
    """Rank by value of information: promising (confidence) AND poorly constrained (uncertainty)."""
    mines = pd.DataFrame(data_mines())
    mx, my = _km_xy(mines.latitude.values, mines.longitude.values)
    d_mine = np.sqrt((grid.x_km.values[:, None] - mx[None]) ** 2 + (grid.y_km.values[:, None] - my[None]) ** 2).min(axis=1)
    voi = grid.confidence * grid.uncertainty
    cand = grid[(d_mine > lease_buffer_km) & (grid.confidence >= 0.35)].assign(voi=voi).sort_values("voi", ascending=False)
    contribs = model.get_booster().predict(xgb.DMatrix(grid[SURFACE_FEATURES].values), pred_contribs=True)
    chosen = []
    for idx, row in cand.iterrows():
        if any(np.hypot(row.x_km - c.x_km, row.y_km - c.y_km) < min_sep_km for c in chosen):
            continue
        chosen.append(row)
        if len(chosen) >= n:
            break
    out = []
    for rank, row in enumerate(chosen, 1):
        c = contribs[row.name][:-1]
        top = np.argsort(-c)[:3]
        reasons = [f"{FEATURE_LABELS[SURFACE_FEATURES[i]]} supports prospectivity" for i in top if c[i] > 0]
        if row.data_support > 0.5:
            reasons.insert(0, f"Kriged borehole grade {row.kriged_grade_pct:.1f}% Mn (±{row.kriging_sd_pct:.1f})")
        else:
            reasons.append("Sparse borehole control: a hole here reduces uncertainty the most")
        if row.cover_type >= 2:
            reasons.append(f"Under {row.cover_name.lower()}: satellite proxy is largely blind here")
        out.append({
            "target_id": f"DT-{rank:02d}", "rank": rank, "latitude": round(float(row.latitude), 4),
            "longitude": round(float(row.longitude), 4), "confidence": round(float(row.confidence), 3),
            "uncertainty": round(float(row.uncertainty), 3), "value_of_information": round(float(row.voi), 3),
            "zone": row.zone, "cover": row.cover_name, "reasons": reasons,
        })
    return out


def data_mines():
    from .reference import MINES
    return MINES
