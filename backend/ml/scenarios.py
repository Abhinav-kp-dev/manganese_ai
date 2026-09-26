"""What-if scenarios. Every output of this module is tagged SCENARIO, never FORECAST."""
from __future__ import annotations

import numpy as np
from scipy.stats import norm

SCENARIOS = {
    "baseline": {"title": "Current plan", "description": "Forecast under the current mine plans and IMD outlook."},
    "bad_weather": {"title": "Heavy monsoon", "description": "Rainfall 60% above forecast, 5 extra rainy days, blasting window cut by 4 days at opencast mines."},
    "equipment_downtime": {"title": "Equipment breakdown", "description": "Fleet health drops by 0.20 and 96 h of unplanned repair at the selected mine(s)."},
    "optimistic": {"title": "Optimistic case", "description": "Rainfall 40% below forecast, 3 fewer rainy days, fleet health +0.05."},
    "target_realignment": {"title": "Target realignment", "description": "Targets reset to the level with a 60% chance of being met."},
    "sister_rebalance": {"title": "Sister-mine rebalance", "description": "Run the network LP so spare capacity in each cluster covers deficits."},
}


def overrides_for(params: dict) -> dict:
    """Translate slider-style parameters into per-mine, per-column transforms of the plan table.

    The blasting-window change only applies to opencast mines (underground blasting is not
    rain-restricted in the same way).
    """
    from .reference import MINES
    target = params.get("mine_id") or "*"
    rain_mult = float(params.get("rainfall_multiplier", 1.0))
    rainy_delta = float(params.get("rainy_days_delta", 0))
    health_delta = float(params.get("fleet_health_delta", 0))
    maint_delta = float(params.get("maintenance_hours_delta", 0))
    blast_delta = float(params.get("blast_window_delta", 0))
    days_delta = float(params.get("operating_days_delta", 0))
    ch = {}
    if rain_mult != 1.0:
        ch["rainfall_forecast_mm"] = lambda s, k=rain_mult: s * k
    if rainy_delta:
        ch["rainy_days_forecast"] = lambda s, d=rainy_delta: (s + d).clip(0, 30)
    if health_delta:
        ch["fleet_health_index"] = lambda s, d=health_delta: (s + d).clip(0.2, 0.98)
    if maint_delta:
        ch["planned_maintenance_hours"] = lambda s, d=maint_delta: (s + d).clip(0, None)
    if days_delta:
        ch["planned_operating_days"] = lambda s, d=days_delta: (s + d).clip(15, 31)
    out = {}
    for m in MINES:
        if target not in ("*", m["mine_id"]):
            continue
        mc = dict(ch)
        if blast_delta and m["mine_type"] == "Opencast":
            mc["blast_window_days"] = lambda s, d=blast_delta: (s + d).clip(0, 31)
        if mc:
            out[m["mine_id"]] = mc
    return out


PRESETS = {
    "bad_weather": {"rainfall_multiplier": 1.6, "rainy_days_delta": 5, "blast_window_delta": -4},
    "equipment_downtime": {"fleet_health_delta": -0.20, "maintenance_hours_delta": 96},
    "optimistic": {"rainfall_multiplier": 0.6, "rainy_days_delta": -3, "fleet_health_delta": 0.05, "blast_window_delta": 2},
}


def realigned_target(p10, p50, p90, prob=0.6):
    """Target T such that P(Y >= T) = prob under the split-normal used for achievement probability."""
    z = norm.ppf(1 - prob)
    sd = (p50 - p10) / norm.ppf(0.9) if z < 0 else (p90 - p50) / norm.ppf(0.9)
    return float(max(0.0, p50 + z * sd))
