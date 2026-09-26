"""Ordinary kriging with a fitted spherical variogram (no external geostatistics dependency).

Kriging is an interpolator of borehole assays: it estimates grade between holes and, just as
importantly, reports the kriging variance, which grows with distance from data. That variance
is what lets the dashboard say "we don't know here" instead of inventing a number.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import curve_fit
from scipy.spatial.distance import cdist


def spherical(h, nugget, psill, rng):
    h = np.asarray(h, dtype=float)
    r = np.clip(h / rng, 0, 1)
    return np.where(h == 0, 0.0, nugget + psill * (1.5 * r - 0.5 * r ** 3))


def empirical_variogram(xy, z, n_bins=14, max_lag=None):
    d = cdist(xy, xy)
    iu = np.triu_indices(len(z), k=1)
    h, g = d[iu], 0.5 * (z[:, None] - z[None, :])[iu] ** 2
    max_lag = max_lag or np.percentile(h, 45)
    edges = np.linspace(0, max_lag, n_bins + 1)
    lags, gam, counts = [], [], []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (h >= a) & (h < b)
        if m.sum() >= 12:
            lags.append(h[m].mean()); gam.append(g[m].mean()); counts.append(int(m.sum()))
    return np.array(lags), np.array(gam), np.array(counts)


def fit_variogram(xy, z):
    lags, gam, counts = empirical_variogram(xy, z)
    var = float(np.var(z))
    p0 = [0.1 * var, 0.9 * var, lags.max() / 2]
    bounds = ([0, 1e-6, 0.5], [var * 1.5, var * 3, lags.max() * 3])
    params, _ = curve_fit(spherical, lags, gam, p0=p0, bounds=bounds, sigma=1 / np.sqrt(counts), maxfev=20000)
    nugget, psill, rng = (float(p) for p in params)
    return {"model": "spherical", "nugget": nugget, "partial_sill": psill, "range_km": rng,
            "empirical": {"lag_km": lags.round(3).tolist(), "semivariance": gam.round(3).tolist(), "pairs": counts.tolist()}}


class OrdinaryKriging:
    def __init__(self, variogram: dict):
        self.v = variogram

    def _gamma(self, h):
        return spherical(h, self.v["nugget"], self.v["partial_sill"], self.v["range_km"])

    def fit(self, xy, z):
        self.xy, self.z = np.asarray(xy, float), np.asarray(z, float)
        n = len(self.z)
        A = np.ones((n + 1, n + 1))
        A[:n, :n] = self._gamma(cdist(self.xy, self.xy))
        A[n, n] = 0.0
        self.A_inv = np.linalg.pinv(A)
        return self

    def predict(self, xy_new, chunk=2000):
        xy_new = np.asarray(xy_new, float)
        n = len(self.z)
        means, variances = [], []
        for s in range(0, len(xy_new), chunk):
            b = np.ones((n + 1, min(chunk, len(xy_new) - s)))
            b[:n] = self._gamma(cdist(self.xy, xy_new[s:s + chunk]))
            w = self.A_inv @ b
            means.append(w[:n].T @ self.z)
            variances.append(np.einsum("ij,ij->j", w, b))
        return np.concatenate(means), np.clip(np.concatenate(variances), 0, None)


def spatial_blocks(x_km, y_km, block_km):
    bx = np.floor(np.asarray(x_km) / block_km).astype(int)
    by = np.floor(np.asarray(y_km) / block_km).astype(int)
    return bx * 1000 + by


def assign_block_folds(blocks, k, seed=26009):
    uniq = np.unique(blocks)
    rng = np.random.default_rng(seed)
    order = rng.permutation(uniq)
    fold_of = {b: i % k for i, b in enumerate(order)}
    return np.array([fold_of[b] for b in blocks])


def kriging_cv(xy, z, variogram, x_km, y_km, k=5, block_km=None):
    """k-fold CV of the kriging interpolator.

    block_km=None -> random folds (interpolation skill inside drilled areas);
    block_km=30   -> whole blocks held out (extrapolation skill far from boreholes).
    """
    if block_km:
        folds = assign_block_folds(spatial_blocks(x_km, y_km, block_km), k)
    else:
        folds = np.random.default_rng(26009).permutation(len(z)) % k
    pred, sd, base = np.zeros_like(z), np.zeros_like(z), np.zeros_like(z)
    for f in range(k):
        te = folds == f
        if te.sum() == 0 or (~te).sum() < 10:
            continue
        ok = OrdinaryKriging(variogram).fit(xy[~te], z[~te])
        m, v = ok.predict(xy[te])
        pred[te], sd[te] = m, np.sqrt(v)
        base[te] = z[~te].mean()
    err = pred - z
    zscore = err / np.maximum(sd, 1e-6)
    return {
        "folds": k, "scheme": f"spatial blocks ({block_km:.0f} km)" if block_km else "random",
        "mae_pct_mn": float(np.mean(np.abs(err))),
        "rmse_pct_mn": float(np.sqrt(np.mean(err ** 2))),
        "baseline_mean_mae_pct_mn": float(np.mean(np.abs(z - base))),
        "coverage_90pct_interval": float(np.mean(np.abs(zscore) <= 1.645)),
        "n_boreholes": int(len(z)),
    }
