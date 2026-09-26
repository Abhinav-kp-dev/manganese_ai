"""Application state: seeds the database, trains all modules, caches artefacts, serves results."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import delete, func, select

from ml import synthetic
from ml.features import build_panel
from ml.forecasting import attribution_summary, capacity_guardrail, forecast, train_module2
from ml.optimizer import optimise
from ml.prospectivity import run_module1
from ml.reference import MINES

from .db import (DATA_DIR, Borehole, Forecast, Mine, MinePlan, Occurrence, ProductionLog, Recommendation,
                 ReserveConfidenceCell, SessionLocal, WeatherFeature, init_db)

log = logging.getLogger("manganese_horizon")
MODEL_VERSION_PREFIX = "mh-1.0"
MIN_REAL_ROWS_FOR_REAL_ONLY = 240  # ~2 years x 10 mines before synthetic rows are dropped from training
GRID_FILE = DATA_DIR / "geology_grid.pkl"


def _df(session, model):
    return pd.read_sql(select(model), session.bind)


class AppState:
    def __init__(self):
        self.lock = threading.RLock()
        self.ready = False
        self.m1 = self.m2 = None
        self.panel = None
        self.data_mode = "SYNTHETIC"
        self.model_version = None
        self.trained_at = None
        self.train_seconds = None
        self._cache: dict = {}

    # ------------------------------------------------------------------ seeding
    def seed_if_empty(self):
        init_db()
        with SessionLocal() as s:
            if s.scalar(select(func.count()).select_from(Mine)):
                return False
            log.info("Seeding database with synthetic demo data (seed %s)", synthetic.SEED)
            data = synthetic.generate_all()
            s.add_all(Mine(**{k: m[k] for k in Mine.__table__.columns.keys()}) for m in MINES)
            s.flush()
            s.bulk_insert_mappings(Borehole, data["boreholes"].assign(is_synthetic=True).to_dict("records"))
            s.bulk_insert_mappings(Occurrence, data["occurrences"].assign(is_synthetic=True).to_dict("records"))
            s.bulk_insert_mappings(ProductionLog, data["production_logs"].to_dict("records"))
            s.bulk_insert_mappings(WeatherFeature, data["weather_features"].to_dict("records"))
            s.bulk_insert_mappings(MinePlan, data["mine_plans"].to_dict("records"))
            s.commit()
            joblib.dump({"grid": data["grid"], "lineaments": data["lineaments"]}, GRID_FILE)
            return True

    # ------------------------------------------------------------------ loading
    def load_frames(self):
        with SessionLocal() as s:
            logs = _df(s, ProductionLog)
            weather = _df(s, WeatherFeature)
            plans = _df(s, MinePlan)
            boreholes = _df(s, Borehole)
            occ = _df(s, Occurrence)
        n_real = int((~logs.is_synthetic.astype(bool)).sum())
        if n_real >= MIN_REAL_ROWS_FOR_REAL_ONLY:
            self.data_mode = "REAL"
            logs = logs[~logs.is_synthetic.astype(bool)]  # training excludes synthetic rows entirely
        elif n_real > 0:
            self.data_mode = "MIXED"
        else:
            self.data_mode = "SYNTHETIC"
        geo = joblib.load(GRID_FILE)
        return {"production_logs": logs, "weather_features": weather, "mine_plans": plans,
                "boreholes": boreholes, "occurrences": occ, "grid": geo["grid"], "lineaments": geo["lineaments"]}

    @staticmethod
    def fingerprint(frames):
        h = hashlib.sha256()
        for k in ("production_logs", "weather_features", "mine_plans", "boreholes", "occurrences"):
            h.update(pd.util.hash_pandas_object(frames[k].drop(columns=[c for c in ("id",) if c in frames[k]]), index=False).values.tobytes())
        return h.hexdigest()[:10]

    # ------------------------------------------------------------------ training
    def train(self, force=False):
        with self.lock:
            t0 = time.time()
            frames = self.load_frames()
            fp = self.fingerprint(frames)
            cache = DATA_DIR / f"artefacts_{fp}.joblib"
            if cache.exists() and not force:
                art = joblib.load(cache)
            else:
                log.info("Training Module 1 and Module 2 (data fingerprint %s)", fp)
                art = {"m1": run_module1(frames), "m2": train_module2(build_panel(frames["production_logs"], frames["weather_features"], frames["mine_plans"]))}
                for old in DATA_DIR.glob("artefacts_*.joblib"):
                    old.unlink()
                joblib.dump(art, cache)
            self.frames = frames
            self.m1, self.m2 = art["m1"], art["m2"]
            self.panel = build_panel(frames["production_logs"], frames["weather_features"], frames["mine_plans"])
            self.model_version = f"{MODEL_VERSION_PREFIX}+{fp}"
            self.trained_at = pd.Timestamp.now('UTC').isoformat()
            self.train_seconds = round(time.time() - t0, 1)
            self._cache.clear()
            self._persist_outputs()
            self.ready = True

    def _persist_outputs(self):
        grid = self.m1["grid"]
        half = synthetic.GRID_STEP_DEG / 2
        with SessionLocal() as s:
            s.execute(delete(Recommendation))
            s.execute(delete(Forecast))
            s.execute(delete(ReserveConfidenceCell))
            s.bulk_insert_mappings(ReserveConfidenceCell, [
                {"cell_id": int(i), "latitude": float(r.latitude), "longitude": float(r.longitude),
                 "geometry_wkt": f"POLYGON(({r.longitude-half:.4f} {r.latitude-half:.4f},{r.longitude+half:.4f} {r.latitude-half:.4f},"
                                 f"{r.longitude+half:.4f} {r.latitude+half:.4f},{r.longitude-half:.4f} {r.latitude+half:.4f},"
                                 f"{r.longitude-half:.4f} {r.latitude-half:.4f}))",
                 "confidence_score": float(r.confidence), "uncertainty": float(r.uncertainty), "zone": r.zone,
                 "grid_resolution_m": synthetic.GRID_STEP_DEG * 111000, "model_version": self.model_version}
                for i, r in grid.iterrows()])
            for h in (1, 2, 3):
                fcs = self.forecasts(h)
                ids = {}
                for f in fcs:
                    row = Forecast(mine_id=f["mine_id"], forecast_date=pd.Timestamp(f["month"] + "-01").date(), horizon=h,
                                   p10=f["p10"], p50=f["p50"], p90=f["p90"], target_achievement_prob=f["achievement_probability"],
                                   risk_level=f["risk_level"], model_version=self.model_version)
                    s.add(row)
                    s.flush()
                    ids[f["mine_id"]] = row.forecast_id
                for mid, block in self.actions(h)["actions_by_mine"].items():
                    for a in block["actions"]:
                        s.add(Recommendation(forecast_id=ids[mid], priority=a["priority"], action_title=a["action_title"],
                                             reason=a["reason"], supporting_features=_jsonable(a["supporting_features"]),
                                             assumptions=a["assumptions"], tonnes=a["tonnes"], confidence=a["confidence"]))
            s.commit()

    # ------------------------------------------------------------------ queries
    def forecasts(self, horizon=1, overrides=None, key=None):
        ck = ("fc", horizon, key)
        if key is not None or overrides is None:
            if ck in self._cache:
                return self._cache[ck]
        all_fc = forecast(self.panel, self.m2, overrides)
        hist_max = self.panel.groupby("mine_id").production_tonnes.max().to_dict()
        out = []
        for f in all_fc:
            if f["horizon"] != horizon:
                continue
            f = dict(f)
            f["attribution"] = attribution_summary(f)
            f["guardrail"] = capacity_guardrail(f["target"], f["rated_monthly_capacity"], hist_max.get(f["mine_id"]))
            f["target_above_p90"] = f["target"] > f["p90"]
            out.append(f)
        if key is not None or overrides is None:
            self._cache[ck] = out
        return out

    def actions(self, horizon=1, overrides=None, key=None):
        ck = ("act", horizon, key)
        if (key is not None or overrides is None) and ck in self._cache:
            return self._cache[ck]
        fcs = self.forecasts(horizon, overrides, key)
        res = optimise(fcs, {f["mine_id"]: f["attribution"] for f in fcs})
        res["month"] = fcs[0]["month"] if fcs else None
        if key is not None or overrides is None:
            self._cache[ck] = res
        return res


def _jsonable(d):
    return json.loads(json.dumps(d, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o)))


STATE = AppState()
