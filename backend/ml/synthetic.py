"""Literature-grounded synthetic data for the demo.

Everything produced here is tagged ``is_synthetic=True``. It exists only because MOIL's
internal drilling and production telemetry is not public. The generators encode the
physical mechanisms named in the problem statement (monsoon haulage/dewatering, equipment
wear and breakdown, blasting restrictions, muck-pile starvation) so that the models have
something mechanistically meaningful to learn; they are not calibrated to real mine logs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter

from .reference import MINES, STUDY_BBOX

SEED = 26009
GRID_STEP_DEG = 0.02
KM_PER_DEG_LAT = 111.0
KM_PER_DEG_LON = 111.0 * np.cos(np.radians(21.6))

# Approximate trace of the Sausar Group / Gondite belt through the MOIL mines (lat, lon).
BELT_AXIS = [
    (21.43, 78.88), (21.40, 79.10), (21.41, 79.28), (21.46, 79.52), (21.50, 79.68),
    (21.62, 79.74), (21.72, 79.86), (21.80, 80.08), (21.87, 80.25), (21.95, 80.42), (22.00, 80.56),
]
# Wainganga river trace (alluvial cover).
RIVER = [(22.10, 80.05), (21.90, 79.98), (21.70, 79.93), (21.50, 79.82), (21.30, 79.70), (21.20, 79.66)]

COVER_TYPES = {0: "Exposed bedrock", 1: "Laterite cap", 2: "Alluvium", 3: "Deccan Trap basalt"}


def _km_xy(lat, lon):
    return (np.asarray(lon) - STUDY_BBOX["lon_min"]) * KM_PER_DEG_LON, (np.asarray(lat) - STUDY_BBOX["lat_min"]) * KM_PER_DEG_LAT


def _dist_to_polyline_km(lat, lon, poly):
    x, y = _km_xy(lat, lon)
    best = np.full(np.shape(x), np.inf)
    pts = [_km_xy(a, b) for a, b in poly]
    for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
        dx, dy = x2 - x1, y2 - y1
        t = np.clip(((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy), 0, 1)
        best = np.minimum(best, np.hypot(x - (x1 + t * dx), y - (y1 + t * dy)))
    return best


def _smooth_field(rng, shape, sigma):
    f = gaussian_filter(rng.standard_normal(shape), sigma=sigma, mode="reflect")
    return (f - f.mean()) / (f.std() + 1e-9)


def generate_geology(rng: np.random.Generator):
    """Return (grid DataFrame with latent truth + observable features, lineament segments)."""
    lats = np.arange(STUDY_BBOX["lat_min"] + GRID_STEP_DEG / 2, STUDY_BBOX["lat_max"], GRID_STEP_DEG)
    lons = np.arange(STUDY_BBOX["lon_min"] + GRID_STEP_DEG / 2, STUDY_BBOX["lon_max"], GRID_STEP_DEG)
    LON, LAT = np.meshgrid(lons, lats)
    shape = LAT.shape

    d_belt = _dist_to_polyline_km(LAT, LON, BELT_AXIS)
    fold = 0.5 + 0.5 * np.sin(_km_xy(LAT, LON)[0] / 9.0 + _smooth_field(rng, shape, 6) * 0.8)
    gondite = np.exp(-((d_belt / (5.5 + 1.5 * fold)) ** 2))

    # Lineaments: belt-parallel shear zones plus NE-SW / NW-SE regional fractures.
    segments = []
    for off in (-0.035, 0.03):
        segments.append([(a + off, b) for a, b in BELT_AXIS])
    for _ in range(26):
        la = rng.uniform(STUDY_BBOX["lat_min"], STUDY_BBOX["lat_max"])
        lo = rng.uniform(STUDY_BBOX["lon_min"], STUDY_BBOX["lon_max"])
        ang = np.radians(rng.choice([45, 135]) + rng.normal(0, 12))
        half = rng.uniform(0.06, 0.2)
        segments.append([(la - half * np.sin(ang), lo - half * np.cos(ang)), (la + half * np.sin(ang), lo + half * np.cos(ang))])
    d_lin = np.min(np.stack([_dist_to_polyline_km(LAT, LON, s) for s in segments]), axis=0)

    latent = 0.62 * gondite + 0.22 * np.exp(-d_lin / 2.5) * gondite ** 0.5 + 0.10 * fold * gondite + 0.07 * _smooth_field(rng, shape, 2.5)
    latent = np.clip(latent, 0, None)
    grade_true = np.clip(10 + 34 * latent + 1.5 * _smooth_field(rng, shape, 1.5), 4, 52)

    # Cover masking surface signals.
    cover = np.zeros(shape, dtype=int)
    laterite = _smooth_field(rng, shape, 3) > 1.0
    cover[laterite] = 1
    cover[_dist_to_polyline_km(LAT, LON, RIVER) < 3.2] = 2
    basalt_edge = (LON - 78.80) * 1.0 + (LAT - 21.20) * 1.6 + 0.05 * _smooth_field(rng, shape, 4)
    cover[basalt_edge < 0.34] = 3

    x_km, y_km = _km_xy(LAT, LON)
    elevation = 300 + 60 * np.exp(-((d_belt / 4) ** 2)) + 80 * _smooth_field(rng, shape, 8) + 0.9 * y_km
    elevation[cover == 3] += 70
    elevation[cover == 2] -= 40
    gy, gx = np.gradient(elevation, GRID_STEP_DEG * KM_PER_DEG_LAT * 1000, GRID_STEP_DEG * KM_PER_DEG_LON * 1000)
    slope = np.degrees(np.arctan(np.hypot(gx, gy))) * 6.0
    rugged = np.abs(elevation - gaussian_filter(elevation, 1.5))

    forest = np.clip(0.5 + 0.35 * _smooth_field(rng, shape, 5), 0, 1)
    ndvi = np.clip(0.22 + 0.45 * forest - 0.08 * latent + 0.03 * rng.standard_normal(shape), 0.02, 0.9)
    exposure = np.where(cover == 0, 1.0, np.where(cover == 1, 0.45, 0.0)) * (1 - 0.7 * ndvi)
    ferric = 1.12 + 0.55 * latent * exposure + 0.07 * rng.standard_normal(shape) + 0.05 * (cover == 1)
    clay = 1.06 + 0.32 * latent * exposure + 0.06 * rng.standard_normal(shape)
    ndwi = np.clip(-0.1 + 0.25 * (cover == 2) - 0.2 * ndvi + 0.04 * rng.standard_normal(shape), -0.6, 0.6)
    sar_vv = -12.5 + 0.08 * rugged + 1.2 * latent * (cover < 2) + 0.8 * rng.standard_normal(shape)
    sar_vh = -19.5 + 4.0 * forest + 0.6 * rng.standard_normal(shape)

    # GSI map shows the mapped surface unit: favourable host rock is only mapped where exposed.
    lith_mapped = np.where(cover == 0, gondite, np.where(cover == 1, 0.5 * gondite, 0.05))
    lith_mapped = np.clip(lith_mapped + 0.05 * rng.standard_normal(shape), 0, 1)

    grid = pd.DataFrame({
        "row": np.repeat(np.arange(shape[0]), shape[1]),
        "col": np.tile(np.arange(shape[1]), shape[0]),
        "latitude": LAT.ravel(), "longitude": LON.ravel(),
        "x_km": x_km.ravel(), "y_km": y_km.ravel(),
        "ferric_ratio_b4_b2": ferric.ravel(), "clay_ratio_b11_b12": clay.ravel(),
        "ndvi": ndvi.ravel(), "ndwi": ndwi.ravel(), "sar_vv_db": sar_vv.ravel(), "sar_vh_db": sar_vh.ravel(),
        "elevation_m": elevation.ravel(), "slope_deg": slope.ravel(), "ruggedness_m": rugged.ravel(),
        "dist_lineament_km": d_lin.ravel(), "lithology_favourability": lith_mapped.ravel(),
        "cover_type": cover.ravel(),
        "_latent": latent.ravel(), "_grade_true": grade_true.ravel(),
    })
    grid.attrs["shape"] = shape
    return grid, segments


def generate_occurrences(rng, grid: pd.DataFrame, n_surface=46, n_drilled=8):
    """Known manganese occurrences (positives): the 10 MOIL mines + GSI-style occurrences."""
    rows = [{"latitude": m["latitude"], "longitude": m["longitude"], "kind": "MOIL mine", "name": m["mine_name"]} for m in MINES]
    exposed = grid[grid.cover_type <= 1]
    w = exposed["_latent"].clip(lower=0) ** 5
    idx = rng.choice(exposed.index, size=n_surface, replace=False, p=(w / w.sum()).values)
    for i in idx:
        r = grid.loc[i]
        rows.append({"latitude": r.latitude + rng.uniform(-0.008, 0.008), "longitude": r.longitude + rng.uniform(-0.008, 0.008),
                     "kind": "Surface occurrence (GSI-style)", "name": f"OCC-{len(rows):03d}"})
    covered = grid[grid.cover_type >= 2]
    w = covered["_latent"].clip(lower=0) ** 6
    for i in rng.choice(covered.index, size=n_drilled, replace=False, p=(w / w.sum()).values):
        r = grid.loc[i]
        rows.append({"latitude": r.latitude, "longitude": r.longitude, "kind": "Drill-confirmed under cover", "name": f"OCC-{len(rows):03d}"})
    return pd.DataFrame(rows)


def generate_boreholes(rng, grid: pd.DataFrame):
    lat_idx = lambda la: np.clip(np.round((la - STUDY_BBOX["lat_min"] - GRID_STEP_DEG / 2) / GRID_STEP_DEG).astype(int), 0, grid["row"].max())
    lon_idx = lambda lo: np.clip(np.round((lo - STUDY_BBOX["lon_min"] - GRID_STEP_DEG / 2) / GRID_STEP_DEG).astype(int), 0, grid["col"].max())
    ncol = grid["col"].max() + 1
    pts = []
    for m in MINES:  # dense drilling around operating mines
        for _ in range(16):
            pts.append((m["latitude"] + rng.normal(0, 0.018), m["longitude"] + rng.normal(0, 0.022), m["mine_id"], "MOIL mine development (simulated)"))
    for k in range(7):  # exploration traverses across the belt
        a, b = BELT_AXIS[rng.integers(1, len(BELT_AXIS) - 1)]
        for j in range(8):
            pts.append((a - 0.06 + j * 0.017 + rng.normal(0, 0.003), b + rng.normal(0, 0.01), None, "GSI exploration traverse (simulated)"))
    for _ in range(34):  # sparse regional holes, some under cover
        pts.append((rng.uniform(STUDY_BBOX["lat_min"], STUDY_BBOX["lat_max"]), rng.uniform(STUDY_BBOX["lon_min"], STUDY_BBOX["lon_max"]), None, "Regional reconnaissance (simulated)"))
    df = pd.DataFrame(pts, columns=["latitude", "longitude", "mine_id", "source"])
    df = df[df.latitude.between(STUDY_BBOX["lat_min"], STUDY_BBOX["lat_max"]) & df.longitude.between(STUDY_BBOX["lon_min"], STUDY_BBOX["lon_max"])].reset_index(drop=True)
    cell = lat_idx(df.latitude.values) * ncol + lon_idx(df.longitude.values)
    latent = grid["_latent"].values[cell]
    df["grade_mn_pct"] = np.clip(grid["_grade_true"].values[cell] + rng.normal(0, 2.2, len(df)), 3, 54).round(2)
    df["thickness_m"] = np.clip(1.0 + 11 * latent + rng.normal(0, 1.2, len(df)), 0.3, 25).round(2)
    df["depth_m"] = np.clip(rng.normal(180, 90, len(df)) + 120 * (grid["cover_type"].values[cell] >= 2), 40, 520).round(0)
    df["observation_date"] = pd.to_datetime("1988-01-01") + pd.to_timedelta(rng.integers(0, 36 * 365, len(df)), unit="D")
    df.insert(0, "borehole_id", [f"BH-{i:04d}" for i in range(len(df))])
    return df


# --------------------------------------------------------------------------- production
MONSOON_MONTHS = {6, 7, 8, 9}
CLUSTER_RAIN_SCALE = {"NGP": 1.0, "BHD": 1.12, "BLG": 1.3}
HISTORY_START, HISTORY_END = "2018-04-01", "2026-08-31"
PLAN_MONTHS = ["2026-09-01", "2026-10-01", "2026-11-01"]


def _daily_weather(rng, dates: pd.DatetimeIndex, scale: float, year_strength: dict):
    m = dates.month.values
    p_rain = np.select([np.isin(m, [7, 8]), np.isin(m, [6, 9]), np.isin(m, [10])], [0.66, 0.45, 0.16], default=0.05)
    strength = np.array([year_strength.get(y, 1.0) for y in dates.year])
    wet = rng.random(len(dates)) < np.clip(p_rain * strength, 0, 0.95)
    amount = rng.gamma(0.9, 18.0 * scale * np.sqrt(strength), len(dates)) * wet
    soil = np.zeros(len(dates))
    s = 0.18
    for i, r in enumerate(amount):
        s = s * 0.95 + r / 260.0
        s = min(max(s, 0.08), 0.55)
        soil[i] = s
    doy = dates.dayofyear.values
    lst = 31 + 9 * np.sin(2 * np.pi * (doy - 60) / 365) - 7 * (soil - 0.18) + rng.normal(0, 1.2, len(dates))
    ndvi_target = 0.24 + 0.9 * pd.Series(soil).rolling(30, min_periods=1).mean().values
    ndvi = np.clip(pd.Series(ndvi_target).ewm(span=25).mean().values + rng.normal(0, 0.015, len(dates)), 0.12, 0.82)
    return pd.DataFrame({"date": dates, "rain": amount, "soil": soil, "lst": lst, "ndvi": ndvi})


def generate_production(rng: np.random.Generator):
    """Daily physics-inspired simulation per mine, aggregated to monthly logs and ex-ante plans."""
    dates = pd.date_range(HISTORY_START, pd.Timestamp(PLAN_MONTHS[-1]) + pd.offsets.MonthEnd(0), freq="D")
    years = sorted(set(dates.year))
    year_strength = {y: float(np.clip(rng.normal(1.0, 0.2), 0.6, 1.5)) for y in years}
    year_strength[2026] = 1.15  # an above-normal 2026 monsoon drives the demo's September risk

    weather = {c: _daily_weather(rng, dates, s, year_strength) for c, s in CLUSTER_RAIN_SCALE.items()}
    logs, plans, wx_rows = [], [], []

    for mine in MINES:
        wx = weather[mine["cluster_id"]]
        ug = mine["mine_type"] == "Underground"
        rated = mine["rated_capacity_tpd"]
        n = len(dates)
        month_key = dates.to_period("M")

        # Planned maintenance: routine + periodic major overhauls (hoist/winder for UG, shovel for OC).
        planned_maint = np.full(n, 1.2)
        periods = month_key.unique()
        overhaul_months = set(periods[rng.choice(len(periods), size=len(periods) // 9, replace=False)])
        if mine["mine_id"] == "BLG-01":
            overhaul_months.add(pd.Period("2026-09", "M"))
        for p in sorted(overhaul_months):
            planned_maint[month_key == p] += rng.uniform(4, 7)

        # Explosive licence / magazine renewal gaps (known a month in advance) for opencast mines.
        licence_gap = np.zeros(n, dtype=bool)
        for p in periods:
            if rng.random() < 0.035 or (mine["mine_id"] == "BHD-01" and str(p) == "2026-09"):
                start = int(np.flatnonzero(month_key == p)[0]) + int(rng.integers(0, 15))
                licence_gap[start:start + int(rng.integers(4, 10))] = True

        health = np.zeros(n)
        h = 0.85
        muck = rated * 2.0
        stock = rated * 6.0
        stock_arr = np.zeros(n); prod = np.zeros(n); blast_t = np.zeros(n); down_h = np.zeros(n); avail = np.zeros(n); operating = np.zeros(n, dtype=bool)
        strike_days = set(rng.choice(n, size=max(1, n // 400), replace=False))
        cum7 = pd.Series(wx.rain.values).rolling(7, min_periods=1).sum().values
        for i in range(n):
            if dates[i].day == 1:
                h = min(0.95, h + (0.28 if planned_maint[i] > 3 else 0.02))  # overhaul vs routine PM
            h = max(0.35, h - rng.uniform(0.0004, 0.0016) - 0.0015 * (wx.rain.values[i] > 30))
            health[i] = h
            day_off = dates[i].dayofweek == 6 or i in strike_days
            fail_p = 0.045 * (1.7 - h)
            breakdown = rng.lognormal(np.log(9), 0.6) if rng.random() < fail_p else 0.0
            down_h[i] = breakdown + planned_maint[i]
            avail[i] = np.clip(1 - down_h[i] / 24.0 * 0.8, 0.3, 1.0)
            rain = wx.rain.values[i]
            if ug:
                weather_f = 1.0 - (0.35 if cum7[i] > 160 else 0.15 if cum7[i] > 100 else 0.0)  # dewatering
                can_blast = not day_off
            else:
                weather_f = 1.0 - 0.012 * min(rain, 45) - 0.35 * max(0.0, wx.soil.values[i] - 0.25)
                can_blast = (not day_off) and rain < 20 and not licence_gap[i]
            if can_blast and rng.random() < 0.6:
                blasted = rated * rng.uniform(1.5, 2.1)
                muck += blasted
                blast_t[i] = blasted
            if day_off:
                stock_arr[i] = stock
                continue
            operating[i] = True
            capacity = rated * avail[i] * max(weather_f, 0.25) * rng.lognormal(0, 0.05)
            p = min(capacity, muck)
            muck -= p
            prod[i] = p
            stock = max(0.0, stock + p - rated * 0.82 * rng.uniform(0.9, 1.1))
            stock_arr[i] = stock

        daily = pd.DataFrame({
            "month": month_key, "prod": prod, "blast": blast_t, "down_h": down_h, "avail": avail,
            "operating": operating, "rain": wx.rain.values, "soil": wx.soil.values, "lst": wx.lst.values,
            "ndvi": wx.ndvi.values, "health": health, "stock": stock_arr, "planned_maint": planned_maint, "licence_gap": licence_gap,
        })
        grp = daily.groupby("month")
        growth_start = pd.Period(HISTORY_START, "M")
        for p, g in grp:
            dim = p.days_in_month
            first = g.index[0]
            wet_days = int((g.rain > 2.5).sum())
            rain_total = float(g.rain.sum())
            fc_noise = rng.lognormal(0, 0.28)
            rain_fc = rain_total * fc_noise
            rainy_fc = int(np.clip(round(wet_days * fc_noise ** 0.5 + rng.normal(0, 1.5)), 0, dim))
            planned_days = int(dim - sum(1 for d in pd.date_range(p.start_time, p.end_time, freq="D") if d.dayofweek == 6))
            blast_window = planned_days - int(g.licence_gap.sum()) - (0 if ug else int(round(rainy_fc * 0.55)))
            yrs = (p - growth_start).n / 12.0
            seasonal_plan = 0.86 if p.month in MONSOON_MONTHS else 1.0
            target = rated * planned_days * 0.875 * seasonal_plan * (1 + 0.004 * yrs) * rng.uniform(0.96, 1.04)
            if mine["mine_id"] == "BLG-01" and str(p) == "2026-09":
                target *= 1.08  # ambitious corporate push in a monsoon overhaul month
            plan = {
                "mine_id": mine["mine_id"], "month": p.start_time.date(),
                "planned_operating_days": planned_days,
                "planned_maintenance_hours": round(float(g.planned_maint.sum()), 1),
                "fleet_health_index": round(float(health[first]), 4),
                "blast_window_days": max(int(blast_window), 0),
                "rainfall_forecast_mm": round(rain_fc, 1), "rainy_days_forecast": rainy_fc,
                "lst_forecast_c": round(float(g.lst.mean() + rng.normal(0, 0.8)), 2),
                "production_target": round(target, 0), "is_synthetic": True,
            }
            plans.append(plan)
            if str(p) >= PLAN_MONTHS[0][:7]:
                continue
            opd = int(g.operating.sum())
            logs.append({
                "mine_id": mine["mine_id"], "date": p.start_time.date(),
                "production_tonnes": round(float(g["prod"].sum()), 0),
                "production_target": plan["production_target"],
                "operating_days": opd,
                "downtime_hours": round(float(g.down_h.sum()), 1),
                "equipment_availability_pct": round(float(g.avail.mean() * 100), 2),
                "maintenance_hours": plan["planned_maintenance_hours"],
                "blasting_tonnes_broken": round(float(g.blast.sum()), 0),
                "stockpile_tonnes": round(float(g.stock.iloc[-1]), 0),
                "workforce_headcount": int(mine["workforce"] * rng.uniform(0.95, 1.03)),
                "is_synthetic": True,
            })
            wx_rows.append({
                "mine_id": mine["mine_id"], "date": p.start_time.date(),
                "rainfall_mm": round(rain_total, 1), "rainy_days": wet_days,
                "soil_moisture": round(float(g.soil.mean()), 4), "ndvi": round(float(g.ndvi.mean()), 4),
                "land_surface_temp_c": round(float(g.lst.mean()), 2), "is_monsoon": p.month in MONSOON_MONTHS,
                "is_synthetic": True,
            })
    return pd.DataFrame(logs), pd.DataFrame(wx_rows), pd.DataFrame(plans)



def generate_all(seed: int = SEED):
    rng = np.random.default_rng(seed)
    grid, lineaments = generate_geology(rng)
    occurrences = generate_occurrences(rng, grid)
    boreholes = generate_boreholes(rng, grid)
    logs, weather, plans = generate_production(rng)
    return {"grid": grid, "lineaments": lineaments, "occurrences": occurrences, "boreholes": boreholes,
            "production_logs": logs, "weather_features": weather, "mine_plans": plans}
