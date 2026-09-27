"""Module 1 on real data: real satellite/terrain features and real manganese locations.

This runs next to (not inside) the demo's fused model. The demo fusion also needs borehole assays,
which are MOIL/GSI internal, so it stays on synthetic data. What can be tested honestly today is
the surface-proxy half: does a model on *real* Sentinel-2 and Copernicus DEM features, trained on
*real* manganese locations, rank those locations above background under spatial cross-validation?

Two caveats are computed, not just stated:
* Very few labels: the only public, point-accurate locations in the study area are MOIL's ten
  operating mines (one EarthByte/mindat locality coincides with Tirodi). The bootstrap interval is
  reported and is wide.
* Mining disturbance: every label is an active mine, so a surface model can score by detecting
  pits and waste dumps rather than ore. ``disturbance_check`` scores the cells by WorldCover
  bare + built-up fraction alone; if that rivals the model, the model has learned mining, not
  geology.

Users can add GSI Bhukosh (or other) occurrences by placing a CSV with the same columns as
``data/real/occurrences_real.csv`` at ``<MH_DATA_DIR>/real_occurrences_extra.csv``.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from .prospectivity import FEATURE_LABELS, build_training_set, train_surface_model
from .reference import STUDY_BBOX
from .remote_sensing import DEM_FEATURES, OUT_DIR as REAL_DIR, S2_FEATURES, grid_axes
from .synthetic import _km_xy

REAL_FEATURES = S2_FEATURES + DEM_FEATURES
REAL_LABELS = {**FEATURE_LABELS, "ruggedness_m": "Local relief (std. of 90 m DEM in cell)"}
LABEL_COLUMNS = ["name", "kind", "latitude", "longitude", "location_precision_km", "source", "source_ref", "use_for_training", "note"]
FILES = {"features": "grid_features_real.csv", "labels": "occurrences_real.csv", "provenance": "provenance.json",
         "true_colour": "s2_true_colour.png", "false_colour": "s2_false_colour_swir.png"}
SEED = 26009


def available(real_dir: Path = REAL_DIR) -> bool:
    return all((real_dir / f).exists() for f in FILES.values())


def load_grid(real_dir: Path = REAL_DIR) -> pd.DataFrame:
    g = pd.read_csv(real_dir / FILES["features"])
    lats, lons = grid_axes()
    if len(g) != len(lats) * len(lons):
        raise ValueError("Real feature grid does not match the study grid; rebuild with python -m ml.remote_sensing")
    g = g.sort_values(["row", "col"]).reset_index(drop=True)
    if not (np.allclose(g.latitude.values, np.repeat(lats, len(lons)), atol=1e-4)
            and np.allclose(g.longitude.values, np.tile(lons, len(lats)), atol=1e-4)):
        raise ValueError("Real feature grid cell centres do not match the study grid")
    g["x_km"], g["y_km"] = _km_xy(g.latitude.values, g.longitude.values)
    return g


def validate_labels(df: pd.DataFrame) -> list[str]:
    errors = []
    missing = [c for c in ("name", "latitude", "longitude", "source") if c not in df.columns]
    if missing:
        return [f"Missing columns: {', '.join(missing)}"]
    lat, lon = pd.to_numeric(df.latitude, errors="coerce"), pd.to_numeric(df.longitude, errors="coerce")
    if lat.isna().any() or lon.isna().any():
        errors.append("latitude/longitude must be numeric")
    if df.source.isna().any() or (df.source.astype(str).str.strip() == "").any():
        errors.append("every occurrence needs a source")
    return errors


def load_labels(real_dir: Path = REAL_DIR, extra: Path | None = None) -> pd.DataFrame:
    frames = [pd.read_csv(real_dir / FILES["labels"])]
    if extra is not None and extra.exists():
        x = pd.read_csv(extra)
        errs = validate_labels(x)
        if errs:
            raise ValueError(f"{extra.name}: " + "; ".join(errs))
        frames.append(x)
    df = pd.concat(frames, ignore_index=True)
    for c in LABEL_COLUMNS:
        if c not in df:
            df[c] = None
    df["use_for_training"] = df.use_for_training.map(lambda v: str(v).strip().lower() not in ("false", "0", "no")).astype(bool)
    inside = df.latitude.between(STUDY_BBOX["lat_min"], STUDY_BBOX["lat_max"]) & df.longitude.between(STUDY_BBOX["lon_min"], STUDY_BBOX["lon_max"])
    df["inside_study_area"] = inside
    return df[LABEL_COLUMNS + ["inside_study_area"]]


def disturbance_check(grid, occurrences, seed=SEED):
    """AUC from WorldCover bare + built-up fraction alone, on the same training cells as the model."""
    cells, y = build_training_set(grid, occurrences, np.random.default_rng(seed))
    score = (grid.loc[cells, "frac_bare"].fillna(0) + grid.loc[cells, "frac_built"].fillna(0)).values
    return float(roc_auc_score(y, score)) if len(np.unique(y)) == 2 else None


def univariate_auc(grid, occurrences, features, seed=SEED):
    cells, y = build_training_set(grid, occurrences, np.random.default_rng(seed))
    out = []
    for f in features:
        v = grid.loc[cells, f].values
        ok = np.isfinite(v)
        if len(np.unique(y[ok])) == 2:
            a = roc_auc_score(y[ok], v[ok])
            out.append({"feature": f, "label": REAL_LABELS.get(f, f), "auc": float(a), "direction": "higher at Mn sites" if a >= 0.5 else "lower at Mn sites"})
    return sorted(out, key=lambda d: -abs(d["auc"] - 0.5))


def run_real_module1(real_dir: Path = REAL_DIR, extra_labels: Path | None = None) -> dict:
    if not available(real_dir):
        return {"available": False, "reason": f"Real data files not found in {real_dir}. Build them with: python -m ml.remote_sensing"}
    grid = load_grid(real_dir)
    labels = load_labels(real_dir, extra_labels)
    train = labels[labels.use_for_training & labels.inside_study_area]
    final, _, validation, importance = train_surface_model(grid, train, seed=SEED, features=REAL_FEATURES, labels=REAL_LABELS)
    validation = dict(validation)
    validation["note"] = ("Real Sentinel-2 + Copernicus DEM features, real locations. Every positive is an operating mine, so the "
                          "model can partly learn mining disturbance; see disturbance_auc. Few positives: treat the AUC as indicative only.")
    grid["surface_prob_real"] = final.predict_proba(grid[REAL_FEATURES].values)[:, 1]
    prov = json.loads((real_dir / FILES["provenance"]).read_text())
    return {
        "available": True,
        "grid": grid,
        "features": REAL_FEATURES,
        "validation": validation,
        "feature_importance": importance,
        "univariate": univariate_auc(grid, train, REAL_FEATURES),
        "disturbance_auc": disturbance_check(grid, train),
        "labels": labels,
        "n_labels_listed": int(len(labels)),
        "n_labels_used": int(len(train)),
        "provenance": prov,
    }
