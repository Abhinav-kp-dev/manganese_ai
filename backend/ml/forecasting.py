"""Module 2: Shortfall Forecasting.

Direct multi-horizon (1-3 months) quantile XGBoost at alpha = 0.10 / 0.50 / 0.90 on mine
utilisation (production / rated monthly capacity), so one model generalises across mines of
different size. Intervals are conformally calibrated (CQR) on a held-out window, quantiles are
forced monotone and non-negative, and every accuracy number is reported next to persistence and
seasonal-naive baselines on the same test window. Explanations come from exact TreeSHAP
(xgboost pred_contribs) on the P50 model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb
from scipy.stats import norm

from .features import DRIVER_GROUPS, DRIVER_LEVER, FEATURES, make_features

QUANTILES = (0.10, 0.50, 0.90)
HORIZONS = (1, 2, 3)
TEST_MONTHS = 12
EVIDENCE_THRESHOLD = 0.15
XGB_Q_PARAMS = dict(n_estimators=450, max_depth=4, learning_rate=0.03, subsample=0.8, colsample_bytree=0.8,
                    min_child_weight=3, reg_lambda=1.5, tree_method="hist", random_state=26009, n_jobs=2)


# Physically motivated monotone constraints keep what-if scenarios coherent
# (e.g. more forecast rain can never raise the forecast, all else equal).
MONOTONE = {
    "rainfall_forecast_mm": -1, "rainy_days_forecast": -1, "haulage_friction_index": -1,
    "planned_maintenance_hours": -1, "downtime_ratio_lag": -1,
    "fleet_health_index": 1, "availability_lag": 1, "blast_window_days": 1,
    "planned_operating_days": 1, "effective_capacity_util": 1,
}
MONOTONE_CONSTRAINTS = "(" + ",".join(str(MONOTONE.get(f, 0)) for f in FEATURES) + ")"


def _fit_quantiles(X, y):
    return {q: xgb.XGBRegressor(objective="reg:quantileerror", quantile_alpha=q, monotone_constraints=MONOTONE_CONSTRAINTS,
                                **XGB_Q_PARAMS).fit(X, y) for q in QUANTILES}


def _predict_quantiles(models, X, cqr=0.0):
    raw = np.column_stack([models[q].predict(X) for q in QUANTILES])
    raw[:, 0] -= cqr
    raw[:, 2] += cqr
    raw = np.sort(raw, axis=1)  # monotonicity: P10 <= P50 <= P90
    return np.clip(raw, 0, None)


def pinball(y, q_pred, alpha):
    d = y - q_pred
    return float(np.mean(np.maximum(alpha * d, (alpha - 1) * d)))


def achievement_probability(target, p10, p50, p90):
    """P(Y >= target) under a split-normal fitted through the three quantiles."""
    z = norm.ppf(0.9)
    sd_lo = max((p50 - p10) / z, 1e-6)
    sd_hi = max((p90 - p50) / z, 1e-6)
    cdf = norm.cdf((target - p50) / (sd_lo if target <= p50 else sd_hi))
    return float(np.clip(1 - cdf, 0, 1))


def risk_level(prob):
    return "LOW" if prob >= 0.7 else "MODERATE" if prob >= 0.4 else "HIGH" if prob >= 0.2 else "CRITICAL"


def _split(df):
    months = np.sort(df.month.unique())
    test_start = months[-TEST_MONTHS]
    cal_start = months[-2 * TEST_MONTHS]
    return df.month < cal_start, (df.month >= cal_start) & (df.month < test_start), df.month >= test_start


def train_module2(panel: pd.DataFrame) -> dict:
    hist = panel[panel.util.notna()]
    last_hist = hist.month.max()
    models, cqr, metrics = {}, {}, {}
    backtest_rows = []
    for h in HORIZONS:
        df = make_features(panel, h)
        df = df[(df.month <= last_hist) & df[FEATURES].notna().all(axis=1) & df.util.notna()]
        tr, cal, te = _split(df)
        X, y = df[FEATURES].values, df.util.values

        m_eval = _fit_quantiles(X[tr], y[tr])
        pc = _predict_quantiles(m_eval, X[cal])
        q_eval = float(np.quantile(np.maximum(pc[:, 0] - y[cal], y[cal] - pc[:, 2]), 0.8 * (1 + 1 / cal.sum())))
        pt = _predict_quantiles(m_eval, X[te], q_eval)
        cap = df.capacity_tonnes.values[te]
        y_t = y[te] * cap
        p10, p50, p90 = (pt[:, i] * cap for i in range(3))
        persist = (df.util_lag_a.values[te] * cap)
        seasonal = (df.util_same_month_ly.values[te] * cap)
        target = df.production_target.values[te]
        err = lambda p: {"mae_tonnes": float(np.mean(np.abs(p - y_t))), "mape_pct": float(np.mean(np.abs(p - y_t) / y_t) * 100)}
        hit_actual = y_t >= target
        probs = np.array([achievement_probability(t, a, b, c) for t, a, b, c in zip(target, p10, p50, p90)])
        metrics[h] = {
            "horizon_months": h,
            "test_window": f"{pd.Timestamp(df.month[te].min()):%b %Y} - {pd.Timestamp(df.month[te].max()):%b %Y}",
            "n_test": int(te.sum()), "n_train": int(tr.sum()), "n_calibration": int(cal.sum()),
            "model_p50": err(p50), "persistence_baseline": err(persist), "seasonal_naive_baseline": err(seasonal),
            "pinball_loss_tonnes": {"p10": pinball(y_t, p10, 0.1), "p50": pinball(y_t, p50, 0.5), "p90": pinball(y_t, p90, 0.9)},
            "p10_p90_coverage": float(np.mean((y_t >= p10) & (y_t <= p90))),
            "nominal_coverage": 0.8,
            "shortfall_detection": {
                "actual_shortfalls": int((~hit_actual).sum()),
                "flagged_prob_below_50pct": int((probs < 0.5).sum()),
                "hit_rate": float(np.mean(probs[~hit_actual] < 0.5)) if (~hit_actual).any() else None,
                "false_alarm_rate": float(np.mean(probs[hit_actual] < 0.5)) if hit_actual.any() else None,
                "brier_score": float(np.mean((probs - hit_actual) ** 2)),
            },
            "cqr_adjustment_util": q_eval,
        }
        if h == 1:
            for i, (mid, mo) in enumerate(zip(df.mine_id.values[te], df.month.values[te])):
                backtest_rows.append({"mine_id": mid, "month": pd.Timestamp(mo).strftime("%Y-%m"), "p10": float(p10[i]), "p50": float(p50[i]),
                                      "p90": float(p90[i]), "actual": float(y_t[i]), "target": float(target[i])})

        # Deployment model: trained on everything before the last 12 months, conformalised on them.
        fit_mask = tr | cal
        models[h] = _fit_quantiles(X[fit_mask], y[fit_mask])
        pd_ = _predict_quantiles(models[h], X[te])
        cqr[h] = float(np.quantile(np.maximum(pd_[:, 0] - y[te], y[te] - pd_[:, 2]), 0.8 * (1 + 1 / te.sum())))
    return {"models": models, "cqr": cqr, "metrics": metrics, "backtest": backtest_rows, "last_history_month": pd.Timestamp(last_hist)}


def explain_row(models_h, x_row: np.ndarray, capacity: float):
    contrib = models_h[0.5].get_booster().predict(xgb.DMatrix(x_row.reshape(1, -1), feature_names=None), pred_contribs=True)[0]
    base = float(contrib[-1]) * capacity
    per_feat = dict(zip(FEATURES, contrib[:-1] * capacity))
    drivers = []
    for name, cols in DRIVER_GROUPS.items():
        drivers.append({"driver": name, "contribution_tonnes": float(sum(per_feat[c] for c in cols)),
                        "features": {c: float(per_feat[c]) for c in cols}, "lever": DRIVER_LEVER.get(name)})
    drivers.sort(key=lambda d: d["contribution_tonnes"])
    return base, drivers


def forecast(panel: pd.DataFrame, trained: dict, overrides: dict | None = None) -> list[dict]:
    """Forecast every mine for the 1-3 plan months after the last observed month."""
    overrides = overrides or {}
    last = trained["last_history_month"]
    out = []
    for h in HORIZONS:
        p = panel.copy()
        target_month = last + pd.DateOffset(months=h)
        sel = p.month == target_month
        for mine_id, changes in overrides.items():
            ms = sel & ((p.mine_id == mine_id) | (mine_id == "*"))
            for col, fn in changes.items():
                p.loc[ms, col] = fn(p.loc[ms, col])
        df = make_features(p, h)
        df = df[df.month == target_month]
        models_h = trained["models"][h]
        q = _predict_quantiles(models_h, df[FEATURES].values, trained["cqr"][h])
        for i, (_, row) in enumerate(df.iterrows()):
            cap = row.capacity_tonnes
            p10, p50, p90 = (float(v) for v in q[i] * cap)
            target = float(row.production_target)
            prob = achievement_probability(target, p10, p50, p90)
            base, drivers = explain_row(models_h, df[FEATURES].values[i], cap)
            out.append({
                "mine_id": row.mine_id, "month": target_month.strftime("%Y-%m"), "horizon": h,
                "p10": p10, "p50": p50, "p90": p90, "target": target,
                "deficit_p50": max(0.0, target - p50),
                "achievement_probability": prob, "risk_level": risk_level(prob),
                "shap_base_tonnes": base, "drivers": drivers,
                "inputs": {c: (float(row[c]) if pd.notna(row[c]) else None) for c in FEATURES},
                "rated_monthly_capacity": float(cap),
            })
    return out


def attribution_summary(fc: dict, min_share=0.01):
    """Positive and risk drivers with the no-hallucination guardrail applied."""
    width = max(fc["p90"] - fc["p10"], 1.0)
    threshold = max(min_share * fc["p50"], 25.0)
    risk = [d for d in fc["drivers"] if d["contribution_tonnes"] <= -threshold]
    pos = [d for d in reversed(fc["drivers"]) if d["contribution_tonnes"] >= threshold]
    top = abs(risk[0]["contribution_tonnes"]) if risk else 0.0
    evidence = top / width
    insufficient = fc["deficit_p50"] > 0 and (not risk or evidence < EVIDENCE_THRESHOLD)
    return {
        "risk_drivers": risk[:5], "positive_drivers": pos[:5],
        "attribution_confidence": float(min(evidence, 1.0)),
        "insufficient_evidence": insufficient,
        "message": "Insufficient evidence to determine the cause." if insufficient else None,
    }


def capacity_guardrail(target, rated_monthly, hist_max):
    flags = []
    if hist_max and target > 1.5 * hist_max:
        flags.append(f"Target exceeds 1.5x the mine's historical maximum ({hist_max:,.0f} t).")
    if target > 1.25 * rated_monthly:
        flags.append(f"Target exceeds 1.25x rated monthly capacity ({rated_monthly:,.0f} t).")
    return {"potentially_unrealistic": bool(flags), "flags": flags}
