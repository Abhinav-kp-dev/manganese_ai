"""Module 3: Corrective Action Engine.

A single linear programme over all mines forecast to miss target in a month:

    minimise   sum_k c_k x_k  +  M * sum_i u_i
    subject to sum_{k in levers(i)} x_k + u_i = deficit_i         for each deficit mine i
               sum_i y_{i,j} <= spare_j                           for each sister mine j
               0 <= x_k <= cap_k

Levers are tied to the SHAP drivers of Module 2: a blasting lever only exists when the blasting
window is a quantified risk driver, and so on. Costs are indicative Rs/t planning figures and
must be replaced by MOIL's own cost sheets. Outputs are scenario estimates, not instructions.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import linprog

from .reference import MINES

DISCLAIMER = "Scenario estimate — not a guaranteed operational instruction. Requires approval by the Mine Manager / Shift In-Charge."
UNMET_PENALTY = 1e6
MINE = {m["mine_id"]: m for m in MINES}


def _road_km(a, b):
    ma, mb = MINE[a], MINE[b]
    dlat = math.radians(mb["latitude"] - ma["latitude"])
    dlon = math.radians(mb["longitude"] - ma["longitude"])
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(ma["latitude"])) * math.cos(math.radians(mb["latitude"])) * math.sin(dlon / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h)) * 1.3


def _driver(fc, name):
    return next((d["contribution_tonnes"] for d in fc["drivers"] if d["driver"] == name), 0.0)


def spare_capacity(fc):
    """Tonnes a mine could add this month after meeting its own target."""
    avail = (fc["inputs"].get("availability_lag") or 90.0) / 100
    ceiling = 0.95 * fc["rated_monthly_capacity"] * avail
    return max(0.0, ceiling - max(fc["p50"], fc["target"]))


def local_levers(fc):
    mid = fc["mine_id"]
    m = MINE[mid]
    inp = fc["inputs"]
    rated = m["rated_capacity_tpd"]
    dim = round(fc["rated_monthly_capacity"] / rated)
    avail = (inp.get("availability_lag") or 90.0) / 100
    levers = []

    blast = _driver(fc, "Blasting window (licence & weather limits)")
    lost_blast_days = max(0, inp["planned_operating_days"] - inp["blast_window_days"])
    if blast < 0 or lost_blast_days > 0:
        cap = min(abs(min(blast, 0)) * 0.7 + lost_blast_days * rated * 0.08, rated * 3)
        if cap > 1:
            levers.append(dict(lever="blasting", driver="Blasting window (licence & weather limits)", cost=60, cap=cap,
                               title=f"Reschedule blasting at {m['mine_name']} into forecast dry windows",
                               detail=f"{lost_blast_days} planned days have no blasting window. Pre-drill and charge holes on dry days; "
                                      "use water-resistant emulsion for wet holes so broken-ore stock does not run out.",
                               assumptions=["Magazine stock and licence validity confirmed", "DGMS blasting-hour restrictions respected"]))

    equip = _driver(fc, "Equipment health & availability")
    maint = _driver(fc, "Planned maintenance / overhaul")
    if equip < 0:
        levers.append(dict(lever="equipment", driver="Equipment health & availability", cost=180,
                           cap=min(abs(equip) * 0.5, rated * dim * 0.06),
                           title=f"Redeploy a standby loader/LHD to {m['mine_name']} from a sister mine",
                           detail=f"Fleet health index {inp['fleet_health_index']:.2f}; lagged availability {inp['availability_lag']:.1f}%.",
                           assumptions=["A compatible machine is idle at a sister mine", "Transfer and commissioning within 3 days"]))
    if maint < 0:
        levers.append(dict(lever="maintenance", driver="Planned maintenance / overhaul", cost=250,
                           cap=abs(maint) * 0.4,
                           title=f"Compress the scheduled overhaul at {m['mine_name']} with a contractor crew",
                           detail=f"{inp['planned_maintenance_hours']:.0f} planned maintenance hours this month. Split into two crews "
                                  "and pre-stage spares to release the equipment earlier.",
                           assumptions=["Critical spares in stock", "Statutory inspection sign-off not shortened"]))

    rain = _driver(fc, "Monsoon rainfall (IMD forecast)") + _driver(fc, "Ground wetness (satellite soil moisture)")
    if rain < 0:
        if m["mine_type"] == "Underground":
            title, detail, cost, share = (f"Stage standby dewatering pumps at {m['mine_name']}",
                                          f"Forecast rainfall {inp['rainfall_forecast_mm']:.0f} mm; avoid level flooding stoppages.", 150, 0.4)
        else:
            title, detail, cost, share = (f"Wet-weather haulage plan at {m['mine_name']}",
                                          f"Forecast rainfall {inp['rainfall_forecast_mm']:.0f} mm over {inp['rainy_days_forecast']:.0f} days. "
                                          "Dress haul roads with murrum, open drainage cuts, prioritise benches close to the crusher.", 140, 0.35)
        levers.append(dict(lever="weather", driver="Monsoon rainfall (IMD forecast)", cost=cost, cap=abs(rain) * share,
                           title=title, detail=detail, assumptions=["Pumps / grader available within cluster"]))

    extra_days = max(0, dim - int(inp["planned_operating_days"]))
    if extra_days:
        # Extra days are of little use while the hoist/fleet is down for overhaul or pits are waterlogged.
        maint_frac = min(inp["planned_maintenance_hours"] / (24 * dim), 0.45)
        wet_frac = inp["rainy_days_forecast"] / dim if m["mine_type"] == "Opencast" else 0.0
        derate = max(0.0, 1 - 2 * maint_frac - wet_frac)
        levers.append(dict(lever="shifts", driver="Scheduled operating days", cost=420,
                           cap=min(extra_days, 3) * rated * avail * 0.8 * derate,
                           title=f"Schedule up to {min(extra_days, 3)} additional working days at {m['mine_name']}",
                           detail=f"Weekly-off working with overtime crews (derated to {derate:.0%} for maintenance load and wet days).",
                           assumptions=["Workforce consent and overtime budget", "Statutory weekly-rest rules complied with"]))

    return levers


def supply_buffer(fc):
    """Stockpile cover protects customer dispatches; it is reported, not counted as production recovery."""
    rated = MINE[fc["mine_id"]]["rated_capacity_tpd"]
    stock = (fc["inputs"].get("stockpile_days_lag") or 0) * rated
    usable = max(0.0, stock - 5 * rated)
    return {"opening_stockpile_tonnes": stock, "usable_above_safety_tonnes": usable,
            "covers_deficit": usable >= fc["deficit_p50"],
            "note": "ROM stockpile can protect dispatches for this month, but does not recover production."}


def optimise(forecasts: list[dict], attribution: dict) -> dict:
    """Joint LP for one month. `forecasts` are Module 2 outputs for that month."""
    deficit = {f["mine_id"]: f for f in forecasts if f["deficit_p50"] > 0}
    spare = {f["mine_id"]: spare_capacity(f) for f in forecasts if f["mine_id"] not in deficit}
    if not deficit:
        return {"actions_by_mine": {}, "summary": {"total_deficit": 0.0, "total_mitigated": 0.0, "unmitigated": 0.0},
                "sister_spare_capacity": spare, "disclaimer": DISCLAIMER, "solver": "HiGHS (scipy.optimize.linprog)"}

    vars_, costs, ub = [], [], []
    for mid, fc in deficit.items():
        for lv in local_levers(fc):
            vars_.append(("local", mid, lv)); costs.append(lv["cost"]); ub.append(lv["cap"])
        for sj, cap in spare.items():
            if cap <= 1:
                continue
            km = _road_km(mid, sj)
            grade_gap = max(0.0, MINE[mid]["mn_grade_pct"] - MINE[sj]["mn_grade_pct"])
            same = MINE[mid]["cluster_id"] == MINE[sj]["cluster_id"]
            c = 220 + 6 * km + 40 * grade_gap + (0 if same else 150)
            vars_.append(("realloc", mid, {"from": sj, "km": km, "grade_gap": grade_gap, "same_cluster": same}))
            costs.append(c); ub.append(cap)
        vars_.append(("unmet", mid, None)); costs.append(UNMET_PENALTY); ub.append(None)

    n = len(vars_)
    mids = list(deficit)
    A_eq = np.zeros((len(mids), n)); b_eq = np.array([deficit[m]["deficit_p50"] for m in mids])
    for k, (_, mid, _) in enumerate(vars_):
        A_eq[mids.index(mid), k] = 1
    sisters = [s for s, c in spare.items() if c > 1]
    A_ub = np.zeros((max(len(sisters), 1), n)); b_ub = np.zeros(max(len(sisters), 1))
    for r, sj in enumerate(sisters):
        b_ub[r] = spare[sj]
        for k, (kind, _, info) in enumerate(vars_):
            if kind == "realloc" and info["from"] == sj:
                A_ub[r, k] = 1
    res = linprog(costs, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=[(0, u) for u in ub], method="highs")
    if not res.success:
        raise RuntimeError(f"LP failed: {res.message}")

    actions_by_mine = {}
    for mid, fc in deficit.items():
        attr = attribution[mid]
        acts, unmet = [], 0.0
        for k, (kind, m_, info) in enumerate(vars_):
            if m_ != mid or res.x[k] < 1:
                continue
            t = float(res.x[k])
            if kind == "unmet":
                unmet = t
                continue
            if kind == "local":
                drv = _driver(fc, info["driver"])
                acts.append({
                    "lever": info["lever"], "action_title": info["title"], "tonnes": t, "cost_inr": t * info["cost"],
                    "cost_per_tonne_inr": info["cost"], "additional_operating_days": None,
                    "reason": f"Addresses '{info['driver']}' ({drv:+,.0f} t SHAP contribution)." if drv else f"Addresses '{info['driver']}'.",
                    "detail": info["detail"], "supporting_features": _supporting(fc, info["lever"]),
                    "assumptions": info["assumptions"],
                })
            else:
                sj = info["from"]
                rated = MINE[sj]["rated_capacity_tpd"]
                days = math.ceil(t / rated)
                acts.append({
                    "lever": "reallocation", "sister_mine_id": sj, "action_title": f"Reallocate {t:,.0f} t of production from {MINE[mid]['mine_name']} to {MINE[sj]['mine_name']}",
                    "tonnes": t, "cost_inr": t * costs[k], "cost_per_tonne_inr": costs[k], "additional_operating_days": days,
                    "reason": f"{MINE[sj]['mine_name']} has ~{spare[sj]:,.0f} t spare capacity this month after meeting its own target.",
                    "detail": f"~{days} extra operating day(s) at rated {rated} t/d; {info['km']:.0f} km road haul"
                              f"{'' if info['same_cluster'] else ' (cross-cluster)'}; grade gap {info['grade_gap']:.1f}% Mn.",
                    "supporting_features": {"sister_spare_tonnes": spare[sj], "road_km": info["km"], "grade_gap_pct_mn": info["grade_gap"]},
                    "assumptions": [f"Surface stockpile and loading capacity available at {MINE[sj]['mine_name']}",
                                    "Customer accepts blended grade", "Rail/road logistics not constrained (not yet modelled)"],
                })
        acts.sort(key=lambda a: -a["tonnes"])
        tier = priority_tier(fc, unmet, attr)
        for i, a in enumerate(acts, 1):
            a["rank"] = i
            a["priority"] = tier if a["tonnes"] >= 0.05 * fc["deficit_p50"] else "Low"
            a["confidence"] = round(0.4 + 0.5 * attr["attribution_confidence"], 2) if a["lever"] != "reallocation" else 0.8
            a["disclaimer"] = DISCLAIMER
        actions_by_mine[mid] = {
            "mine_id": mid, "mine_name": MINE[mid]["mine_name"], "deficit_p50": fc["deficit_p50"],
            "mitigated": fc["deficit_p50"] - unmet, "unmitigated": unmet, "priority": tier,
            "achievement_probability": fc["achievement_probability"], "actions": acts,
            "cost_inr": sum(a["cost_inr"] for a in acts),
            "supply_buffer": supply_buffer(fc),
        }
    total = sum(f["deficit_p50"] for f in deficit.values())
    unmet_total = sum(v["unmitigated"] for v in actions_by_mine.values())
    return {
        "actions_by_mine": actions_by_mine,
        "summary": {"total_deficit": total, "total_mitigated": total - unmet_total, "unmitigated": unmet_total,
                    "objective_cost_inr": float(sum(a["cost_inr"] for v in actions_by_mine.values() for a in v["actions"]))},
        "sister_spare_capacity": spare, "disclaimer": DISCLAIMER, "solver": "HiGHS (scipy.optimize.linprog)",
        "formulation": "min Σ c·x + M·u  s.t.  Σ levers + u = deficit (per mine),  Σ reallocations ≤ spare (per sister),  0 ≤ x ≤ cap",
    }


def priority_tier(fc, unmet, attr):
    infeasible = fc["target"] > 0.95 * fc["rated_monthly_capacity"]
    if infeasible or unmet > 5000:
        return "Critical"
    if fc["achievement_probability"] < 0.4:
        return "High"
    if _driver(fc, "Planned maintenance / overhaul") < 0:
        return "Medium"
    return "Low"


def _supporting(fc, lever):
    i = fc["inputs"]
    keys = {
        "blasting": ["blast_window_days", "planned_operating_days", "rainy_days_forecast"],
        "equipment": ["fleet_health_index", "availability_lag", "downtime_ratio_lag"],
        "maintenance": ["planned_maintenance_hours", "fleet_health_index"],
        "weather": ["rainfall_forecast_mm", "rainy_days_forecast", "soil_moisture_lag", "haulage_friction_index"],
        "shifts": ["planned_operating_days"],
    }[lever]
    return {k: i.get(k) for k in keys}


def reallocation_check(forecasts: list[dict], from_mine: str, to_mine: str, tonnes: float) -> dict:
    """Manual calculator: move `tonnes` of a deficit at `from_mine` to sister `to_mine`."""
    fc = {f["mine_id"]: f for f in forecasts}
    spare = spare_capacity(fc[to_mine])
    feasible = tonnes <= spare
    km = _road_km(from_mine, to_mine)
    rated = MINE[to_mine]["rated_capacity_tpd"]
    return {
        "from_mine": from_mine, "to_mine": to_mine, "requested_tonnes": tonnes, "spare_capacity_tonnes": spare,
        "feasible": feasible, "allocatable_tonnes": min(tonnes, spare),
        "additional_operating_days": math.ceil(min(tonnes, spare) / rated) if spare > 0 else 0,
        "road_km": km, "same_cluster": MINE[from_mine]["cluster_id"] == MINE[to_mine]["cluster_id"],
        "remaining_deficit_at_source": max(0.0, fc[from_mine]["deficit_p50"] - min(tonnes, spare)),
        "disclaimer": DISCLAIMER,
    }
