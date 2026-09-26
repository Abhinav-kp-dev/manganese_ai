"""Validation and storage of real MOIL production logs (shared by upload API and inbox job)."""
from __future__ import annotations

import pandas as pd

from ml.reference import MINES

from .db import ProductionLog, SessionLocal

UPLOAD_COLUMNS = ["mine_id", "date", "production_tonnes", "production_target", "operating_days", "downtime_hours",
                  "equipment_availability_pct", "maintenance_hours", "blasting_tonnes_broken", "stockpile_tonnes", "workforce_headcount"]
RANGES = {"production_tonnes": (0, 1e6), "production_target": (0, 1e6), "operating_days": (0, 31), "downtime_hours": (0, 744),
          "equipment_availability_pct": (0, 100), "maintenance_hours": (0, 744), "blasting_tonnes_broken": (0, 2e6),
          "stockpile_tonnes": (0, 5e6), "workforce_headcount": (0, 20000)}
TEMPLATE = ",".join(UPLOAD_COLUMNS) + "\nBLG-01,2026-08-01,33000,34000,26,70,92.5,54,36000,48000,1450\n"
MINE_IDS = {m["mine_id"] for m in MINES}


def validate(df: pd.DataFrame):
    errors = []
    missing = [c for c in UPLOAD_COLUMNS if c not in df.columns]
    if missing:
        return None, [f"Missing columns: {', '.join(missing)}"]
    df = df[UPLOAD_COLUMNS].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for i, r in df.iterrows():
        if r.mine_id not in MINE_IDS:
            errors.append(f"Row {i + 2}: unknown mine_id '{r.mine_id}'")
        if pd.isna(r.date):
            errors.append(f"Row {i + 2}: date not parseable")
        elif r.date.day != 1:
            errors.append(f"Row {i + 2}: date must be the first day of the month (monthly logs)")
        for c, (lo, hi) in RANGES.items():
            v = pd.to_numeric(r[c], errors="coerce")
            if pd.isna(v) or not lo <= v <= hi:
                errors.append(f"Row {i + 2}: {c}={r[c]!r} outside [{lo:g}, {hi:g}]")
        if len(errors) >= 50:
            errors.append("... further errors truncated")
            break
    if df.duplicated(["mine_id", "date"]).any():
        errors.append("Duplicate (mine_id, date) rows")
    return df, errors


def store(df: pd.DataFrame) -> int:
    """Upsert validated rows as real data (is_synthetic = FALSE)."""
    with SessionLocal() as s:
        for r in df.to_dict("records"):
            d = r["date"].date()
            vals = {k: (float(v) if k not in ("mine_id", "date") else v) for k, v in r.items()}
            vals.update(date=d, is_synthetic=False, operating_days=int(vals["operating_days"]), workforce_headcount=int(vals["workforce_headcount"]))
            existing = s.get(ProductionLog, (r["mine_id"], d))
            if existing:
                for k, v in vals.items():
                    setattr(existing, k, v)
            else:
                s.add(ProductionLog(**vals))
        s.commit()
    return len(df)
