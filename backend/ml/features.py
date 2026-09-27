"""Feature engineering for Module 2 (monthly, per mine, direct multi-horizon).

For a forecast of month t issued at the end of month t-h, only information available at
issue time is used: production history up to t-h, satellite observations up to t-h, and the
ex-ante plan for month t (planned days, maintenance, blasting window, IMD extended-range
rainfall forecast) and the latest fleet-health reading (month t-h+1). Realised downtime/rainfall
of month t are never features.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .reference import MINES

PLAN_COLS = ["planned_operating_days", "planned_maintenance_hours", "fleet_health_index", "blast_window_days",
             "rainfall_forecast_mm", "rainy_days_forecast", "lst_forecast_c"]
STATIC_COLS = ["rated_capacity_tpd", "is_underground", "haul_distance_km", "depth_m"]

FEATURES = (
    ["month_sin", "month_cos", "is_monsoon"] + PLAN_COLS + STATIC_COLS +
    ["util_lag_a", "util_lag_b", "util_lag_c", "util_same_month_ly", "util_roll3", "util_roll12", "util_std3",
     "availability_lag", "downtime_ratio_lag", "stockpile_days_lag", "soil_moisture_lag", "ndvi_lag",
     "effective_capacity_util", "haulage_friction_index"]
)

DRIVER_GROUPS = {
    "Monsoon rainfall (IMD forecast)": ["rainfall_forecast_mm", "rainy_days_forecast", "haulage_friction_index"],
    "Ground wetness (satellite soil moisture)": ["soil_moisture_lag"],
    "Surface/vegetation condition (NDVI)": ["ndvi_lag"],
    "Land surface temperature": ["lst_forecast_c"],
    "Seasonal pattern": ["month_sin", "month_cos", "is_monsoon"],
    "Equipment health & availability": ["fleet_health_index", "availability_lag", "downtime_ratio_lag"],
    "Planned maintenance / overhaul": ["planned_maintenance_hours"],
    "Blasting window (licence & weather limits)": ["blast_window_days"],
    "Scheduled operating days": ["planned_operating_days", "effective_capacity_util"],
    "Recent production momentum": ["util_lag_a", "util_lag_b", "util_lag_c", "util_same_month_ly", "util_roll3", "util_roll12", "util_std3"],
    "Opening stockpile": ["stockpile_days_lag"],
    "Mine characteristics": STATIC_COLS,
}
assert sorted(sum(DRIVER_GROUPS.values(), [])) == sorted(FEATURES)

# Which lever in Module 3 addresses which driver.
DRIVER_LEVER = {
    "Monsoon rainfall (IMD forecast)": "weather",
    "Ground wetness (satellite soil moisture)": "weather",
    "Equipment health & availability": "equipment",
    "Planned maintenance / overhaul": "maintenance",
    "Blasting window (licence & weather limits)": "blasting",
    "Scheduled operating days": "shifts",
    "Opening stockpile": "stockpile",
}


def build_panel(logs: pd.DataFrame, weather: pd.DataFrame, plans: pd.DataFrame) -> pd.DataFrame:
    mines = pd.DataFrame(MINES)
    mines["is_underground"] = (mines.mine_type == "Underground").astype(int)
    p = plans.copy()
    p["month"] = pd.to_datetime(p["month"])
    lg = logs.copy()
    lg["month"] = pd.to_datetime(lg["date"])
    wx = weather.copy()
    wx["month"] = pd.to_datetime(wx["date"])
    panel = p.drop(columns=["is_synthetic"], errors="ignore").merge(
        lg.drop(columns=["date", "production_target", "is_synthetic"], errors="ignore"), on=["mine_id", "month"], how="left")
    panel = panel.merge(wx.drop(columns=["date", "is_synthetic"], errors="ignore"), on=["mine_id", "month"], how="left")
    panel = panel.merge(mines[["mine_id"] + STATIC_COLS], on="mine_id", how="left")
    panel = panel.sort_values(["mine_id", "month"]).reset_index(drop=True)
    panel["days_in_month"] = panel.month.dt.days_in_month
    panel["capacity_tonnes"] = panel.rated_capacity_tpd * panel.days_in_month
    panel["util"] = panel.production_tonnes / panel.capacity_tonnes
    panel["downtime_ratio"] = panel.downtime_hours / (panel.operating_days * 24)
    panel["stockpile_days"] = panel.stockpile_tonnes / panel.rated_capacity_tpd
    m = panel.month.dt.month
    panel["month_sin"] = np.sin(2 * np.pi * m / 12)
    panel["month_cos"] = np.cos(2 * np.pi * m / 12)
    panel["is_monsoon"] = m.isin([6, 7, 8, 9]).astype(int)
    return panel


def make_features(panel: pd.DataFrame, h: int) -> pd.DataFrame:
    """Features for target month t using information up to t-h (h>=1)."""
    df = panel.copy()
    g = df.groupby("mine_id", group_keys=False)
    s = lambda col, k: g[col].shift(k)
    df["util_lag_a"] = s("util", h)
    df["util_lag_b"] = s("util", h + 1)
    df["util_lag_c"] = s("util", h + 2)
    df["util_same_month_ly"] = s("util", 12)
    df["util_roll3"] = g["util"].transform(lambda x: x.shift(h).rolling(3, min_periods=2).mean())
    df["util_roll12"] = g["util"].transform(lambda x: x.shift(h).rolling(12, min_periods=6).mean())
    df["util_std3"] = g["util"].transform(lambda x: x.shift(h).rolling(3, min_periods=2).std())
    # Fleet health is logged on the first day of each month, so at the end of month t-h the latest
    # known value is the one for month t-h+1. For h = 1 that is the target month itself; for h > 1
    # using the target month's value would be look-ahead.
    df["fleet_health_index"] = s("fleet_health_index", h - 1)
    df["availability_lag"] = s("equipment_availability_pct", h)
    df["downtime_ratio_lag"] = s("downtime_ratio", h)
    df["stockpile_days_lag"] = s("stockpile_days", h)
    df["soil_moisture_lag"] = s("soil_moisture", h)
    df["ndvi_lag"] = s("ndvi", h)
    df["effective_capacity_util"] = df.planned_operating_days / df.days_in_month * df.availability_lag / 100
    df["haulage_friction_index"] = df.haul_distance_km * (1 + df.rainfall_forecast_mm / 200)
    df["horizon"] = h
    return df
