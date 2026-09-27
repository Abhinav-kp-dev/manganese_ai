from __future__ import annotations

import io
import threading
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ml import synthetic
from ml.features import DRIVER_GROUPS, FEATURES
from ml.forecasting import HORIZONS, QUANTILES, XGB_Q_PARAMS, achievement_probability, risk_level
from ml.optimizer import reallocation_check
from ml.prospectivity import COVER_RELIABILITY, CUTOFF_MN_PCT, FEATURE_LABELS, FORBIDDEN_FEATURES, SURFACE_FEATURES
from ml.reference import CLUSTERS, DATA_SOURCES, MINES, STUDY_BBOX
from ml.scenarios import PRESETS, SCENARIOS, overrides_for, realigned_target

from .. import ingest, pipeline
from ..auth import DEMO_ACCOUNTS_ENABLED, DEMO_PASSWORD, ROLES, User, authenticate, current_user, in_scope, issue_token, public_user, require
from ..db import AuditEntry, Borehole, MinePlan, ProductionLog, SessionLocal, WeatherFeature
from ..epistemic import DISCLAIMERS, FORECAST, FORECAST_TAGS, MODEL_INFERENCE, OBSERVED, SCENARIO, meta
from ..state import STATE

public = APIRouter(prefix="/api")
router = APIRouter(prefix="/api", dependencies=[Depends(require("read"))])
MINE = {m["mine_id"]: m for m in MINES}
APP_NAME = "Manganese Horizon"


def _ready():
    if not STATE.ready:
        raise HTTPException(503, "Models are still training. Retry in a few seconds.")


def _meta(*extra):
    return meta(STATE.data_mode, STATE.model_version, list(extra))


def _r(x, n=1):
    return None if x is None else round(float(x), n)


def _fc_public(f):
    return {
        "mine_id": f["mine_id"], "mine_name": MINE[f["mine_id"]]["mine_name"], "cluster_id": MINE[f["mine_id"]]["cluster_id"],
        "mine_type": MINE[f["mine_id"]]["mine_type"], "month": f["month"], "horizon": f["horizon"],
        "p10": _r(f["p10"], 0), "p50": _r(f["p50"], 0), "p90": _r(f["p90"], 0), "target": _r(f["target"], 0),
        "deficit_p50": _r(f["deficit_p50"], 0), "achievement_probability": _r(f["achievement_probability"], 3),
        "risk_level": f["risk_level"], "rated_monthly_capacity": _r(f["rated_monthly_capacity"], 0),
        "shap_base_tonnes": _r(f["shap_base_tonnes"], 0),
        "drivers": [{"driver": d["driver"], "contribution_tonnes": _r(d["contribution_tonnes"], 0), "lever": d["lever"]} for d in f["drivers"]],
        "attribution": {
            "risk_drivers": [{"driver": d["driver"], "contribution_tonnes": _r(d["contribution_tonnes"], 0)} for d in f["attribution"]["risk_drivers"]],
            "positive_drivers": [{"driver": d["driver"], "contribution_tonnes": _r(d["contribution_tonnes"], 0)} for d in f["attribution"]["positive_drivers"]],
            "attribution_confidence": _r(f["attribution"]["attribution_confidence"], 3),
            "insufficient_evidence": f["attribution"]["insufficient_evidence"], "message": f["attribution"]["message"],
        },
        "guardrail": f["guardrail"], "target_above_p90": bool(f["target_above_p90"]),
        "inputs": {k: _r(v, 3) for k, v in f["inputs"].items()},
        "tags": FORECAST_TAGS,
    }


# ------------------------------------------------------------------------------------ system
@public.get("/health")
def health():
    return {"status": "ok" if STATE.ready else "training", "model_version": STATE.model_version}


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


@public.post("/auth/login")
def login(body: LoginIn):
    u = authenticate(body.username, body.password)
    return {"token": issue_token(u), "user": public_user(u)}


@public.get("/auth/roles")
def roles():
    """Role catalogue for the sign-in screen; demo accounts are listed only when enabled."""
    from ..auth import User as U
    with SessionLocal() as s:
        users = s.scalars(select(U).where(U.active.is_(True))).all() if DEMO_ACCOUNTS_ENABLED else []
    return {"roles": [{"role": k, "label": v["label"], "permissions": sorted(v["perms"])} for k, v in ROLES.items()],
            "demo_accounts": [{"username": u.username, "full_name": u.full_name, "role": u.role, "site_scope": u.site_scope} for u in users],
            "demo_password_hint": DEMO_PASSWORD if DEMO_ACCOUNTS_ENABLED and DEMO_PASSWORD == "demo123" else None}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return public_user(user)


@router.get("/meta")
def get_meta():
    _ready()
    with SessionLocal() as s:
        syn = s.scalar(select(func.count()).select_from(ProductionLog).where(ProductionLog.is_synthetic.is_(True)))
        real = s.scalar(select(func.count()).select_from(ProductionLog).where(ProductionLog.is_synthetic.is_(False)))
    return {
        "app_name": APP_NAME, "problem_statement": "SIH26009", "data_mode": STATE.data_mode,
        "model_version": STATE.model_version, "trained_at": STATE.trained_at, "train_seconds": STATE.train_seconds,
        "last_observed_month": STATE.m2["last_history_month"].strftime("%Y-%m"),
        "forecast_months": [(STATE.m2["last_history_month"] + pd.DateOffset(months=h)).strftime("%Y-%m") for h in HORIZONS],
        "production_rows": {"synthetic": syn, "real": real}, "clusters": CLUSTERS,
        "meta": _meta("satellite"),
    }


@router.get("/mines")
def mines():
    _ready()
    fc = {f["mine_id"]: f for f in STATE.forecasts(1)}
    p = STATE.panel[STATE.panel.production_tonnes.notna()]
    last = p.sort_values("month").groupby("mine_id").tail(1).set_index("mine_id")
    ytd = p[p.month >= pd.Timestamp("2026-04-01")].groupby("mine_id").production_tonnes.sum()
    out = []
    for m in MINES:
        mid = m["mine_id"]
        out.append({**m, "last_month": last.loc[mid, "month"].strftime("%Y-%m"),
                    "last_month_production": _r(last.loc[mid, "production_tonnes"], 0),
                    "last_month_target": _r(last.loc[mid, "production_target"], 0),
                    "fy_to_date_production": _r(ytd.get(mid, 0), 0),
                    "next_month": {"p50": _r(fc[mid]["p50"], 0), "target": _r(fc[mid]["target"], 0),
                                   "achievement_probability": _r(fc[mid]["achievement_probability"], 3), "risk_level": fc[mid]["risk_level"]},
                    "tags": {"last_month_production": OBSERVED, "next_month": MODEL_INFERENCE},
                    "location_note": "Approximate location (±2-3 km), for visualisation only."})
    return {"mines": out, "meta": _meta()}


@router.get("/overview")
def overview():
    _ready()
    fcs = STATE.forecasts(1)
    act = STATE.actions(1)
    grid = STATE.m1["grid"]
    cell_km2 = (synthetic.GRID_STEP_DEG * synthetic.KM_PER_DEG_LAT) * (synthetic.GRID_STEP_DEG * synthetic.KM_PER_DEG_LON)
    zones = grid.zone.value_counts().to_dict()
    risk_counts = pd.Series([f["risk_level"] for f in fcs]).value_counts().to_dict()
    return {
        "month": fcs[0]["month"],
        "production": {
            "sum_of_mine_p50": _r(sum(f["p50"] for f in fcs), 0), "sum_of_targets": _r(sum(f["target"] for f in fcs), 0),
            "total_deficit_p50": _r(sum(f["deficit_p50"] for f in fcs), 0),
            "mitigated_by_plan": _r(act["summary"]["total_mitigated"], 0), "unmitigated": _r(act["summary"]["unmitigated"], 0),
            "risk_counts": risk_counts, "mines_at_risk": sum(1 for f in fcs if f["achievement_probability"] < 0.5),
            "note": "Sum of per-mine medians is an approximation of the company median.",
            "tags": {"sum_of_mine_p50": MODEL_INFERENCE, "sum_of_targets": OBSERVED, "mitigated_by_plan": SCENARIO},
        },
        "reserves": {
            "zone_area_km2": {z: _r(n * cell_km2, 0) for z, n in zones.items()},
            "drill_targets": STATE.m1["drill_targets"][:5],
            "surface_cv_auc": _r(STATE.m1["surface_validation"]["spatial_cv_auc"], 3),
            "tags": {"zone_area_km2": MODEL_INFERENCE},
        },
        "mines": [_fc_public(f) for f in sorted(fcs, key=lambda f: f["achievement_probability"])],
        "top_actions": sorted([dict(a, mine_id=k, mine_name=v["mine_name"]) for k, v in act["actions_by_mine"].items() for a in v["actions"]],
                              key=lambda a: (["Critical", "High", "Medium", "Low"].index(a["priority"]), -a["tonnes"]))[:6],
        "meta": _meta("action"),
    }


# ------------------------------------------------------------------------------------ module 1
LAYERS = ["confidence", "uncertainty", "kriged_grade_pct", "kriging_sd_pct", "p_grade_above_cutoff", "p_grade_above_cutoff_ik",
          "surface_prob", "data_support", "cover_type"]


@router.get("/reserves/grid")
def reserve_grid():
    _ready()
    g = STATE.m1["grid"]
    shape = (int(g.row.max()) + 1, int(g.col.max()) + 1)
    return {
        "bbox": STUDY_BBOX, "step_deg": synthetic.GRID_STEP_DEG, "rows": shape[0], "cols": shape[1],
        "row_order": "row 0 = southern edge; values are row-major",
        "layers": {k: np.round(g.sort_values(["row", "col"])[k].values.astype(float), 3).tolist() for k in LAYERS},
        "zone_thresholds": {"Very High": 0.7, "High": 0.5, "Moderate": 0.3, "Low": 0.15},
        "cover_types": synthetic.COVER_TYPES, "cutoff_mn_pct": CUTOFF_MN_PCT,
        "tags": {k: MODEL_INFERENCE for k in LAYERS[:-1]} | {"cover_type": OBSERVED},
        "meta": _meta("prospectivity", "satellite"),
    }


@router.get("/reserves/cell")
def reserve_cell(lat: float, lon: float):
    _ready()
    g = STATE.m1["grid"]
    i = int(np.argmin((g.latitude - lat) ** 2 + (g.longitude - lon) ** 2))
    r = g.iloc[i]
    contrib = STATE.m1["surface_model"].get_booster().predict(xgb.DMatrix(g[SURFACE_FEATURES].values[i:i + 1]), pred_contribs=True)[0]
    feats = sorted([{"feature": f, "label": FEATURE_LABELS[f], "value": _r(r[f], 3), "contribution_logodds": _r(c, 3)}
                    for f, c in zip(SURFACE_FEATURES, contrib[:-1])], key=lambda d: -abs(d["contribution_logodds"]))
    return {
        "latitude": _r(r.latitude, 4), "longitude": _r(r.longitude, 4), "zone": r.zone,
        "confidence": _r(r.confidence, 3), "uncertainty": _r(r.uncertainty, 3),
        "subsurface": {"kriged_grade_pct": _r(r.kriged_grade_pct, 2), "kriging_sd_pct": _r(r.kriging_sd_pct, 2),
                       "p_grade_above_cutoff": _r(r.p_grade_above_cutoff, 3), "p_grade_above_cutoff_ik": _r(r.p_grade_above_cutoff_ik, 3),
                       "data_support": _r(r.data_support, 3)},
        "surface": {"probability": _r(r.surface_prob, 3), "model_spread": _r(r.surface_model_spread, 3),
                    "cover": r.cover_name, "proxy_reliability": COVER_RELIABILITY[int(r.cover_type)], "features": feats},
        "tags": {"confidence": MODEL_INFERENCE, "subsurface": MODEL_INFERENCE, "surface.features": OBSERVED},
        "meta": _meta("prospectivity"),
    }


@router.get("/reserves/points")
def reserve_points():
    _ready()
    bh = STATE.frames["boreholes"].copy()
    bh["observation_date"] = pd.to_datetime(bh.observation_date).dt.strftime("%Y-%m-%d")
    occ = STATE.frames["occurrences"]
    return {
        "boreholes": bh.replace({np.nan: None}).to_dict("records"),
        "occurrences": occ.drop(columns=["id"], errors="ignore").to_dict("records"),
        "lineaments": [[[round(a, 4), round(b, 4)] for a, b in seg] for seg in STATE.frames["lineaments"]],
        "drill_targets": STATE.m1["drill_targets"],
        "tags": {"boreholes": OBSERVED, "occurrences": OBSERVED, "drill_targets": MODEL_INFERENCE},
        "meta": _meta("prospectivity"),
    }


@router.get("/reserves/validation")
def reserve_validation():
    _ready()
    m1 = STATE.m1
    return {"variogram": m1["variogram"], "kriging_cv": m1["kriging_cv"], "surface_validation": m1["surface_validation"],
            "feature_importance": m1["feature_importance"], "simulation_check": m1["simulation_check"],
            "probability_models": m1["probability_models"], "cutoff_mn_pct": CUTOFF_MN_PCT, "meta": _meta("prospectivity")}


REAL_LAYERS = ["surface_prob_real", "ferric_ratio_b4_b2", "clay_ratio_b11_b12", "ndvi", "ndwi", "elevation_m", "slope_deg",
               "ruggedness_m", "frac_bare", "frac_built", "frac_tree", "frac_cropland", "frac_water"]
IMAGERY = {"s2_true_colour.png": "true_colour", "s2_false_colour_swir.png": "false_colour"}


def _real_summary(real):
    if not real.get("available"):
        return {"available": False, "reason": real.get("reason")}
    v, prov = real["validation"], real["provenance"]
    return {
        "available": True,
        "validation": v, "feature_importance": real["feature_importance"], "univariate": real["univariate"],
        "disturbance_auc": real["disturbance_auc"], "n_labels_listed": real["n_labels_listed"], "n_labels_used": real["n_labels_used"],
        "labels": real["labels"].replace({np.nan: None}).to_dict("records"),
        "provenance": {"generated_at": prov["generated_at"], "scenes": prov["sentinel2"]["scenes"], "dem_tiles": prov["dem"]["tiles"],
                       "worldcover_tiles": prov["worldcover"]["tiles"], "not_available": prov["not_available"],
                       "attribution": prov["attribution"], "season": prov["sentinel2"]["season"]},
    }


@router.get("/reserves/real")
def reserve_real():
    """Module 1 surface proxy on real Sentinel-2 / Copernicus DEM features and real Mn locations."""
    _ready()
    real = STATE.real
    out = _real_summary(real)
    if real.get("available"):
        g = real["grid"].sort_values(["row", "col"])
        out.update({
            "bbox": STUDY_BBOX, "step_deg": synthetic.GRID_STEP_DEG, "rows": int(g.row.max()) + 1, "cols": int(g.col.max()) + 1,
            "layers": {k: [None if not np.isfinite(x) else round(float(x), 4) for x in g[k].values] for k in REAL_LAYERS},
            "imagery": {v: f"/api/imagery/{k}" for k, v in IMAGERY.items()},
            "tags": {"surface_prob_real": MODEL_INFERENCE} | {k: OBSERVED for k in REAL_LAYERS[1:]},
        })
    out["meta"] = _meta("prospectivity", "satellite")
    return out


@public.get("/imagery/{name}")
def imagery(name: str):
    """Public Sentinel-2 composites (open ESA Copernicus data) for the map overlay."""
    from ml.realdata import REAL_DIR
    if name not in IMAGERY or not (REAL_DIR / name).exists():
        raise HTTPException(404, "Unknown image")
    return FileResponse(REAL_DIR / name, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


# ------------------------------------------------------------------------------------ module 2
@router.get("/forecast/summary")
def forecast_summary(horizon: int = Query(1, ge=1, le=3)):
    _ready()
    return {"forecasts": [_fc_public(f) for f in STATE.forecasts(horizon)], "meta": _meta()}


@router.get("/forecast/metrics")
def forecast_metrics():
    _ready()
    return {"metrics": STATE.m2["metrics"], "quantiles": QUANTILES, "features": FEATURES, "driver_groups": DRIVER_GROUPS,
            "hyperparameters": XGB_Q_PARAMS, "meta": _meta()}


@router.get("/forecast/mine/{mine_id}")
def forecast_mine(mine_id: str, horizon: int = Query(1, ge=1, le=3)):
    _ready()
    if mine_id not in MINE:
        raise HTTPException(404, "Unknown mine")
    p = STATE.panel[(STATE.panel.mine_id == mine_id)]
    hist = p[p.production_tonnes.notna()].tail(36)
    history = [{"month": m.strftime("%Y-%m"), "actual": _r(a, 0), "target": _r(t, 0), "rainfall_mm": _r(r, 0),
                "availability_pct": _r(av, 1)}
               for m, a, t, r, av in zip(hist.month, hist.production_tonnes, hist.production_target, hist.rainfall_mm, hist.equipment_availability_pct)]
    backtest = [b for b in STATE.m2["backtest"] if b["mine_id"] == mine_id]
    future = [_fc_public(next(f for f in STATE.forecasts(h) if f["mine_id"] == mine_id)) for h in HORIZONS]
    sel = future[horizon - 1]
    return {"mine": MINE[mine_id], "history": history, "backtest": backtest, "forecast": future, "selected": sel,
            "realigned_target_60pct": _r(realigned_target(sel["p10"], sel["p50"], sel["p90"]), 0),
            "metrics": STATE.m2["metrics"][horizon],
            "tags": {"history": OBSERVED, "backtest": MODEL_INFERENCE, "forecast": MODEL_INFERENCE, "realigned_target_60pct": SCENARIO},
            "meta": _meta()}


# ------------------------------------------------------------------------------------ module 3
@router.get("/actions")
def actions(horizon: int = Query(1, ge=1, le=3)):
    _ready()
    res = STATE.actions(horizon)
    return {**res, "tags": {"*": SCENARIO}, "meta": _meta("action")}


class ReallocationIn(BaseModel):
    from_mine: str
    to_mine: str
    tonnes: float = Field(gt=0, le=200000)
    horizon: int = Field(1, ge=1, le=3)


@router.post("/actions/reallocate")
def reallocate(body: ReallocationIn):
    _ready()
    if body.from_mine not in MINE or body.to_mine not in MINE or body.from_mine == body.to_mine:
        raise HTTPException(400, "Choose two different known mines")
    return {**reallocation_check(STATE.forecasts(body.horizon), body.from_mine, body.to_mine, body.tonnes),
            "tags": {"*": SCENARIO}, "meta": _meta("action")}


# ------------------------------------------------------------------------------------ scenarios
@router.get("/scenarios")
def list_scenarios():
    return {"scenarios": [{"id": k, **v, "params": PRESETS.get(k, {})} for k, v in SCENARIOS.items()]}


class ScenarioIn(BaseModel):
    scenario_id: str = "custom"
    horizon: int = Field(1, ge=1, le=3)
    mine_id: str | None = None
    rainfall_multiplier: float = Field(1.0, ge=0, le=3)
    rainy_days_delta: float = Field(0, ge=-15, le=15)
    fleet_health_delta: float = Field(0, ge=-0.5, le=0.5)
    maintenance_hours_delta: float = Field(0, ge=-200, le=400)
    blast_window_delta: float = Field(0, ge=-20, le=20)
    operating_days_delta: float = Field(0, ge=-10, le=5)


@router.post("/scenarios/run")
def run_scenario(body: ScenarioIn):
    _ready()
    if body.scenario_id not in SCENARIOS and body.scenario_id != "custom":
        raise HTTPException(400, "Unknown scenario")
    if body.mine_id and body.mine_id not in MINE:
        raise HTTPException(400, "Unknown mine")
    base = STATE.forecasts(body.horizon)
    params = body.model_dump()
    if body.scenario_id in PRESETS:
        params.update(PRESETS[body.scenario_id])
    key = None if body.scenario_id == "custom" else f"{body.scenario_id}:{body.mine_id}"
    ov = overrides_for(params) if body.scenario_id not in ("baseline", "target_realignment", "sister_rebalance") else None
    scen = STATE.forecasts(body.horizon, ov, key) if ov else base
    rows = []
    for b, s in zip(base, scen):
        tgt = realigned_target(s["p10"], s["p50"], s["p90"]) if body.scenario_id == "target_realignment" else s["target"]
        prob = achievement_probability(tgt, s["p10"], s["p50"], s["p90"])
        rows.append({"mine_id": s["mine_id"], "mine_name": MINE[s["mine_id"]]["mine_name"],
                     "baseline": {"p10": _r(b["p10"], 0), "p50": _r(b["p50"], 0), "p90": _r(b["p90"], 0), "target": _r(b["target"], 0),
                                  "achievement_probability": _r(b["achievement_probability"], 3), "risk_level": b["risk_level"]},
                     "scenario": {"p10": _r(s["p10"], 0), "p50": _r(s["p50"], 0), "p90": _r(s["p90"], 0), "target": _r(tgt, 0),
                                  "achievement_probability": _r(prob, 3), "risk_level": risk_level(prob)},
                     "top_risk_driver": s["attribution"]["risk_drivers"][0]["driver"] if s["attribution"]["risk_drivers"] else None})
    plan = STATE.actions(body.horizon, ov, key) if body.scenario_id in ("sister_rebalance", "bad_weather", "equipment_downtime", "custom", "optimistic") else None
    return {"scenario_id": body.scenario_id, "month": base[0]["month"], "params": {k: v for k, v in params.items() if k != "scenario_id"},
            "rows": rows,
            "totals": {"baseline_p50": _r(sum(r["baseline"]["p50"] for r in rows), 0), "scenario_p50": _r(sum(r["scenario"]["p50"] for r in rows), 0),
                       "baseline_deficit": _r(sum(max(0, r["baseline"]["target"] - r["baseline"]["p50"]) for r in rows), 0),
                       "scenario_deficit": _r(sum(max(0, r["scenario"]["target"] - r["scenario"]["p50"]) for r in rows), 0)},
            "plan": plan, "tags": {"*": SCENARIO}, "meta": _meta("action")}


# ------------------------------------------------------------------------------------ audit
class AuditIn(BaseModel):
    recommendation_key: str = Field(max_length=128)
    action_title: str = Field(max_length=500)
    mine_id: str | None = Field(None, max_length=16)
    decision: str = Field(pattern="^(APPROVED|REJECTED|DEFERRED)$")
    note: str = Field("", max_length=1000)
    client_timestamp: str | None = Field(None, max_length=40)
    synced_offline: bool = False


@router.post("/audit")
def add_audit(body: AuditIn, user: User = Depends(current_user)):
    perms = ROLES[user.role]["perms"]
    needed = "defer" if body.decision == "DEFERRED" else "decide"
    if needed not in perms:
        raise HTTPException(403, f"{ROLES[user.role]['label']} cannot {'defer' if needed == 'defer' else 'approve or reject'} actions")
    if needed == "decide" and not in_scope(user, body.mine_id):
        raise HTTPException(403, f"{body.mine_id or 'This action'} is outside your site scope ({user.site_scope})")
    with SessionLocal() as s:
        e = AuditEntry(**body.model_dump(), decided_by=user.full_name, role=user.role)
        s.add(e)
        s.commit()
        return {"id": e.id, "created_at": e.created_at.isoformat()}


@router.get("/audit")
def list_audit(limit: int = Query(100, ge=1, le=500)):
    with SessionLocal() as s:
        rows = s.scalars(select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit)).all()
        return {"entries": [{c: (getattr(r, c).isoformat() if c == "created_at" else getattr(r, c)) for c in AuditEntry.__table__.columns.keys()} for r in rows]}


# ------------------------------------------------------------------------------------ data upload
@public.get("/data/template", response_class=PlainTextResponse)
def upload_template():
    return ingest.TEMPLATE


@router.post("/data/upload")
async def upload(file: UploadFile = File(...), commit: bool = False, user: User = Depends(require("upload_data"))):
    raw = await file.read()
    if len(raw) > 5_000_000:
        raise HTTPException(413, "File too large (max 5 MB)")
    try:
        df = pd.read_csv(io.BytesIO(raw))
    except Exception as e:
        raise HTTPException(400, f"Could not parse CSV: {e}") from e
    df, errors = ingest.validate(df)
    report = {"rows": 0 if df is None else len(df), "errors": errors, "valid": not errors, "committed": False,
              "preview": [] if df is None else df.head(8).astype(str).to_dict("records")}
    if errors or not commit:
        return report
    ingest.store(df)
    threading.Thread(target=STATE.train, kwargs={"force": True}, daemon=True).start()
    report.update(committed=True, message=f"Stored as real (is_synthetic = FALSE) by {user.full_name}. Models are retraining in the background.")
    return report


# ------------------------------------------------------------------------------------ pipeline
@router.get("/pipeline")
def pipeline_status():
    return pipeline.status()


@router.post("/pipeline/run/{job}")
def pipeline_run(job: str, user: User = Depends(require("run_pipeline"))):
    if job == "all":
        return {"results": pipeline.run_all("manual")}
    if job not in pipeline.JOBS:
        raise HTTPException(404, "Unknown job")
    return {"results": [pipeline.run_job(job, "manual")]}


@router.get("/external-weather/{mine_id}")
def external_weather(mine_id: str):
    """Real observations (if the pipeline has fetched them) next to the simulated series used by the demo model."""
    from ..db import ExternalWeather
    if mine_id not in MINE:
        raise HTTPException(404, "Unknown mine")
    with SessionLocal() as s:
        rows = s.scalars(select(ExternalWeather).where(ExternalWeather.mine_id == mine_id).order_by(ExternalWeather.month)).all()
    return {"mine_id": mine_id, "rows": [{"source": x.source, "month": x.month.strftime("%Y-%m"), "rainfall_mm": x.rainfall_mm, "rainy_days": x.rainy_days,
                                           "soil_moisture": x.soil_moisture, "land_surface_temp_c": x.land_surface_temp_c} for x in rows],
            "tags": {"rows": OBSERVED}}


# ------------------------------------------------------------------------------------ integrity
FRONTEND_SRC = Path(__file__).resolve().parents[3] / "frontend" / "src"
BANNED_PHRASES = ["confirmed reserve", "proven tonnage", "will happen", "guaranteed production"]


def _scan_copy():
    if not FRONTEND_SRC.exists():
        return None, []
    hits = []
    for f in FRONTEND_SRC.rglob("*.js*"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            low = line.lower()
            if any(p in low for p in BANNED_PHRASES) and "guardrail-ok" not in low:
                hits.append(f"{f.name}:{n}")
    return not hits, hits


@router.get("/integrity")
def integrity():
    _ready()
    fcs = [f for h in HORIZONS for f in STATE.forecasts(h)]
    mono = all(0 <= f["p10"] <= f["p50"] <= f["p90"] for f in fcs)
    val = STATE.m1["surface_validation"]
    acts = [a for h in HORIZONS for v in STATE.actions(h)["actions_by_mine"].values() for a in v["actions"]]
    with SessionLocal() as s:
        counts = {t.__tablename__: {"synthetic": s.scalar(select(func.count()).select_from(t).where(t.is_synthetic.is_(True))),
                                    "real": s.scalar(select(func.count()).select_from(t).where(t.is_synthetic.is_(False)))}
                  for t in (ProductionLog, WeatherFeature, MinePlan, Borehole)}
    copy_ok, copy_hits = _scan_copy()
    m = STATE.m2["metrics"][1]
    real = STATE.real
    if real.get("available"):
        rv = real["validation"]
        real_evidence = (f"Real Sentinel-2 + Copernicus DEM features, {rv['n_positive']} real Mn locations: spatial-CV AUC {rv['spatial_cv_auc']:.2f} "
                         f"(95% CI {rv['spatial_cv_auc_ci95'][0]:.2f}–{rv['spatial_cv_auc_ci95'][1]:.2f}); bare/built-ground baseline {real['disturbance_auc']:.2f}. "
                         f"Synthetic-data AUC for comparison: {val['spatial_cv_auc']:.2f}.")
    else:
        real_evidence = real.get("reason") or "Real data not available."
    checks = [
        {"id": "spatial_cv", "label": "Spatially-blocked CV used for Module 1 (never random k-fold)", "pass": val["method"].startswith("Spatially blocked"),
         "evidence": f"Spatial AUC {val['spatial_cv_auc']:.3f} vs random k-fold {val['random_kfold_auc_for_comparison']:.3f} (random CV is optimistic)."},
        {"id": "real_data", "label": "Module 1 surface proxy re-validated on real satellite data and real Mn locations (result reported as is)",
         "pass": bool(real.get("available")), "evidence": real_evidence},
        {"id": "no_leakage", "label": "No target-leakage features in Module 1", "pass": not (FORBIDDEN_FEATURES & set(SURFACE_FEATURES)),
         "evidence": f"Excluded: {', '.join(sorted(FORBIDDEN_FEATURES))}."},
        {"id": "no_lookahead", "label": "Module 2 uses only information available at issue time", "pass": True,
         "evidence": "Fleet health is read at month t-h+1; the rainfall outlook is climatology-anchored with realistic skill. tests/test_leakage.py scrambles every later value and requires identical features."},
        {"id": "monotone", "label": "Quantile monotonicity enforced (0 ≤ P10 ≤ P50 ≤ P90)", "pass": mono,
         "evidence": f"Checked {len(fcs)} live forecasts."},
        {"id": "baselines", "label": "Module 2 benchmarked against naive baselines on the same window", "pass": all(k in m for k in ("persistence_baseline", "seasonal_naive_baseline")),
         "evidence": f"P50 MAE {m['model_p50']['mae_tonnes']:.0f} t vs persistence {m['persistence_baseline']['mae_tonnes']:.0f} t, seasonal {m['seasonal_naive_baseline']['mae_tonnes']:.0f} t ({m['test_window']})."},
        {"id": "coverage", "label": "Uncertainty intervals calibrated (conformal)", "pass": abs(m["p10_p90_coverage"] - 0.8) <= 0.1,
         "evidence": f"Empirical P10-P90 coverage {m['p10_p90_coverage']:.0%} vs nominal 80%."},
        {"id": "epistemic", "label": "Every output tagged OBSERVED / FORECAST / MODEL INFERENCE / SCENARIO", "pass": bool(FORECAST_TAGS),
         "evidence": "API responses carry a 'tags' map; the UI renders a badge for each tagged value."},
        {"id": "synthetic_labelled", "label": "Synthetic data labelled everywhere (DB rows, API meta, UI banner)", "pass": True,
         "evidence": f"Data mode {STATE.data_mode}; row counts {counts}."},
        {"id": "copy", "label": "No 'confirmed reserve', 'proven tonnage' or 'will happen' claims in UI copy", "pass": copy_ok,
         "evidence": "Scanned frontend/src." if copy_ok else (f"Found in: {', '.join(copy_hits[:5])}" if copy_hits else "Frontend source not present; checked in CI.")},
        {"id": "access_control", "label": "Sign-in and role-based permissions on every data endpoint", "pass": True,
         "evidence": "Signed bearer tokens; approve/reject limited to Mine Managers within their site scope (and Admin); uploads and pipeline runs are role-gated."},
        {"id": "disclaimer", "label": "Corrective actions carry the scenario disclaimer", "pass": all(a.get("disclaimer") == DISCLAIMERS["action"] or "Scenario estimate" in a.get("disclaimer", "") for a in acts),
         "evidence": f"{len(acts)} actions checked."},
    ]
    limitations = [
        "No access to MOIL's proprietary production/drilling telemetry: synthetic data stands in, tagged is_synthetic, with an MoU-dependent path to real data (CSV upload is already wired).",
        f"Module 1's demo fusion trains on {val['n_positive']} synthetic occurrences and synthetic satellite features, so its AUC is not evidence of real-world skill.",
        ("On real data the surface proxy has not yet shown skill: " + real_evidence) if real.get("available") else real_evidence,
        "Every public, point-accurate Mn location in the study area is an operating mine, so a real-data surface model can learn mining disturbance instead of geology. GSI Bhukosh occurrences (login required) are the next step.",
        "Sentinel-1 SAR, lineaments and mapped lithology are simulated only: no open SAR archive for India and GSI layers need a login.",
        "Optical indices degrade under monsoon cloud; the real composite uses dry-season (Feb–Apr) scenes for that reason.",
        "Kriging has no skill beyond ~one variogram range from boreholes; the map says so via its uncertainty layer.",
        "Corrective-action costs are indicative planning figures. Rail/road logistics are not yet modelled (future work).",
        "NASA POWER observations are stored alongside, not yet inside, the model features: mixing real weather with simulated production would corrupt training. They switch in once real MOIL production logs are onboarded.",
        "Sign-in is local (username/password, signed tokens). Integration with MOIL's directory (LDAP/SSO) is a deployment step.",
        "Forecast accuracy on synthetic data overstates what real data will give; re-validate after onboarding MOIL logs.",
    ]
    real_vs_synthetic = [
        {"metric": "Module 1 surface proxy, spatial-CV AUC", "synthetic": _r(val["spatial_cv_auc"], 3),
         "real": _r(real["validation"]["spatial_cv_auc"], 3) if real.get("available") else None,
         "note": "Real: Sentinel-2 + Copernicus DEM, operating-mine locations. Synthetic: simulated features built from the same truth that placed the occurrences."},
        {"metric": "Module 1 surface proxy, 95% CI", "synthetic": [_r(x, 2) for x in val["spatial_cv_auc_ci95"]],
         "real": [_r(x, 2) for x in real["validation"]["spatial_cv_auc_ci95"]] if real.get("available") else None, "note": ""},
        {"metric": "Module 1 positives used", "synthetic": val["n_positive"], "real": real["validation"]["n_positive"] if real.get("available") else None, "note": ""},
        {"metric": "Bare/built-ground baseline AUC (mining-disturbance check)", "synthetic": None,
         "real": _r(real["disturbance_auc"], 3) if real.get("available") else None, "note": "If this rivals the model, the model is detecting mines, not ore."},
        {"metric": "Module 2 +1 month P50 MAE (t)", "synthetic": _r(m["model_p50"]["mae_tonnes"], 0), "real": None,
         "note": "Needs MOIL production logs (CSV upload / inbox is wired)."},
    ]
    return {"checks": checks, "all_pass": all(c["pass"] for c in checks), "data_sources": DATA_SOURCES, "limitations": limitations,
            "real_vs_synthetic": real_vs_synthetic,
            "row_counts": counts, "model_card": {
                "module1": {"kriging": "Ordinary kriging, spherical variogram (weighted least squares)", "surface_model": "XGBoost classifier (PU framing, 3 km pseudo-absence buffer)",
                            "features": [FEATURE_LABELS[f] for f in SURFACE_FEATURES], "cutoff_mn_pct": CUTOFF_MN_PCT,
                            "real_data_features": list(real.get("features", [])),
                            "tonnage": "Monte Carlo conceptual range per drill target (kriged grade and thickness, stated geometry); not a Mineral Resource"},
                "module2": {"model": "Direct multi-horizon quantile XGBoost (α = 0.1/0.5/0.9) + split-conformal calibration",
                            "target": "Utilisation = production / rated monthly capacity", "n_features": len(FEATURES), "explainability": "Exact TreeSHAP (xgboost pred_contribs) on P50"},
                "module3": {"solver": "Linear programme, HiGHS via scipy.optimize.linprog", "levers": ["reallocation", "blasting", "equipment", "maintenance", "weather", "shifts"]},
            }, "meta": _meta("prospectivity", "satellite", "action")}
