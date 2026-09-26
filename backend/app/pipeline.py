"""Scheduled data pipeline.

Jobs
  nasa_power  real daily rainfall / soil wetness / surface temperature per mine from NASA POWER
              (free, no key), aggregated to months -> external_weather (is_synthetic = FALSE)
  inbox       CSV exports dropped into <data dir>/inbox are validated and stored as real
              production logs; files move to processed/ or rejected/ (with an error report)
  retrain     retrain models if the data fingerprint changed (cached otherwise)

Runs on a background schedule inside the API (MH_PIPELINE_INTERVAL_MIN, default 360, 0 = off)
or from cron:  cd backend && python -m app.pipeline all
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import func, select

from ml.reference import MINES

from . import ingest
from .db import DATA_DIR, ExternalWeather, PipelineRun, SessionLocal, init_db, utcnow

log = logging.getLogger("manganese_horizon.pipeline")
INBOX = DATA_DIR / "inbox"
POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
POWER_START = date(2018, 1, 1)
INTERVAL_MIN = int(os.getenv("MH_PIPELINE_INTERVAL_MIN", "360"))
_lock = threading.Lock()
_next_run: dict = {"at": None}


# ------------------------------------------------------------------------------ NASA POWER
def fetch_power_daily(lat: float, lon: float, start: date, end: date, timeout=60) -> dict:
    q = urllib.parse.urlencode({"parameters": "PRECTOTCORR,GWETTOP,TS", "community": "AG", "latitude": lat, "longitude": lon,
                                "start": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"), "format": "JSON"})
    with urllib.request.urlopen(f"{POWER_URL}?{q}", timeout=timeout) as r:  # noqa: S310 (fixed https host)
        return json.load(r)


def power_to_monthly(payload: dict) -> pd.DataFrame:
    p = payload["properties"]["parameter"]
    df = pd.DataFrame({k: pd.Series(v) for k, v in p.items()})
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.mask(df <= -998)  # POWER fill value is -999
    g = df.groupby(df.index.to_period("M"))
    out = pd.DataFrame({
        "rainfall_mm": g["PRECTOTCORR"].sum(min_count=20),
        "rainy_days": g["PRECTOTCORR"].apply(lambda s: int((s > 2.5).sum()) if s.notna().sum() >= 20 else None),
        "soil_moisture": g["GWETTOP"].mean(),
        "land_surface_temp_c": g["TS"].mean(),
        "n_days": g["PRECTOTCORR"].count(),
    })
    out = out[out.n_days >= 20]  # only complete-enough months
    out.index = out.index.to_timestamp()
    return out.drop(columns="n_days")


def job_nasa_power() -> str:
    with SessionLocal() as s:
        last = s.scalar(select(func.max(ExternalWeather.month)).where(ExternalWeather.source == "NASA_POWER"))
    start = (pd.Timestamp(last) + pd.offsets.MonthBegin(1)).date() if last else POWER_START
    end = date.today() - timedelta(days=5)  # POWER lags a few days
    if start > end:
        return "up to date"
    n = 0
    for m in MINES:
        monthly = power_to_monthly(fetch_power_daily(m["latitude"], m["longitude"], start, end))
        with SessionLocal() as s:
            for month, r in monthly.iterrows():
                row = s.get(ExternalWeather, ("NASA_POWER", m["mine_id"], month.date())) or ExternalWeather(source="NASA_POWER", mine_id=m["mine_id"], month=month.date())
                row.rainfall_mm = None if pd.isna(r.rainfall_mm) else round(float(r.rainfall_mm), 1)
                row.rainy_days = None if pd.isna(r.rainy_days) else int(r.rainy_days)
                row.soil_moisture = None if pd.isna(r.soil_moisture) else round(float(r.soil_moisture), 4)
                row.land_surface_temp_c = None if pd.isna(r.land_surface_temp_c) else round(float(r.land_surface_temp_c), 2)
                row.fetched_at = utcnow()
                s.merge(row)
                n += 1
            s.commit()
    return f"stored {n} mine-months ({start:%Y-%m} → {end:%Y-%m})"


# ------------------------------------------------------------------------------ inbox
def job_inbox() -> str:
    for d in ("", "processed", "rejected"):
        (INBOX / d).mkdir(parents=True, exist_ok=True)
    files = sorted(INBOX.glob("*.csv"))
    if not files:
        return "no files"
    stored, rejected = 0, 0
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for f in files:
        try:
            df, errors = ingest.validate(pd.read_csv(f))
        except Exception as e:  # unreadable file
            df, errors = None, [f"Could not parse CSV: {e}"]
        if errors:
            rejected += 1
            shutil.move(str(f), INBOX / "rejected" / f"{stamp}_{f.name}")
            (INBOX / "rejected" / f"{stamp}_{f.name}.errors.txt").write_text("\n".join(errors))
        else:
            stored += ingest.store(df)
            shutil.move(str(f), INBOX / "processed" / f"{stamp}_{f.name}")
    return f"{stored} rows stored from {len(files) - rejected} file(s); {rejected} file(s) rejected"


def job_retrain() -> str:
    from .state import STATE
    before = STATE.model_version
    STATE.train()
    return "no data change" if STATE.model_version == before else f"retrained → {STATE.model_version}"


JOBS = {"nasa_power": job_nasa_power, "inbox": job_inbox, "retrain": job_retrain}
JOB_INFO = {
    "nasa_power": "Real rainfall, soil wetness and surface temperature per mine from NASA POWER (daily → monthly).",
    "inbox": f"Validate and load MOIL CSV exports dropped into {INBOX}.",
    "retrain": "Retrain models when the data changed.",
}


def run_job(name: str, trigger: str = "manual") -> dict:
    with SessionLocal() as s:
        run = PipelineRun(job=name, trigger=trigger, status="running")
        s.add(run)
        s.commit()
        rid = run.id
    try:
        msg, status = JOBS[name](), "ok"
    except Exception as e:  # recorded, never raised into the scheduler
        msg, status = f"{type(e).__name__}: {e}"[:500], "failed"
        log.warning("pipeline job %s failed: %s", name, msg)
    with SessionLocal() as s:
        run = s.get(PipelineRun, rid)
        run.status, run.message, run.finished_at = status, msg, utcnow()
        s.commit()
    return {"job": name, "status": status, "message": msg}


def run_all(trigger: str = "manual") -> list[dict]:
    if not _lock.acquire(blocking=False):
        return [{"job": "all", "status": "skipped", "message": "a pipeline run is already in progress"}]
    try:
        return [run_job(j, trigger) for j in JOBS]
    finally:
        _lock.release()


def start_scheduler():
    if INTERVAL_MIN <= 0:
        return
    def loop():
        while True:
            _next_run["at"] = pd.Timestamp.now("UTC") + pd.Timedelta(minutes=INTERVAL_MIN)
            time.sleep(INTERVAL_MIN * 60)
            run_all("schedule")
    threading.Thread(target=loop, daemon=True, name="mh-scheduler").start()


def status() -> dict:
    with SessionLocal() as s:
        runs = s.scalars(select(PipelineRun).order_by(PipelineRun.id.desc()).limit(30)).all()
        ext = s.execute(select(ExternalWeather.source, func.count(), func.min(ExternalWeather.month), func.max(ExternalWeather.month))
                        .group_by(ExternalWeather.source)).all()
    last = {}
    for r in runs:
        last.setdefault(r.job, r)
    iso = lambda d: d.isoformat() if d else None
    return {
        "schedule": {"interval_minutes": INTERVAL_MIN, "enabled": INTERVAL_MIN > 0, "next_run": iso(_next_run["at"]),
                     "cron_example": "0 */6 * * *  cd /path/to/backend && python -m app.pipeline all"},
        "jobs": [{"job": j, "description": JOB_INFO[j], "last_status": last[j].status if j in last else None,
                  "last_message": last[j].message if j in last else None, "last_run": iso(last[j].started_at) if j in last else None} for j in JOBS],
        "recent_runs": [{"id": r.id, "job": r.job, "trigger": r.trigger, "status": r.status, "message": r.message,
                         "started_at": iso(r.started_at), "finished_at": iso(r.finished_at)} for r in runs],
        "external_data": [{"source": a, "mine_months": b, "from": iso(c), "to": iso(d)} for a, b, c, d in ext],
        "inbox_path": str(INBOX),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    from .state import STATE
    STATE.seed_if_empty()
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    results = run_all("cli") if which == "all" else [run_job(which, "cli")]
    for r in results:
        print(f"{r['job']:<11} {r['status']:<8} {r['message']}")
    sys.exit(1 if any(r["status"] == "failed" for r in results) else 0)
