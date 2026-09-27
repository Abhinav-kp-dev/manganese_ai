"""Real satellite and terrain features for the Module 1 study grid.

Builds, from public cloud-optimised GeoTIFFs (no account or API key needed):

* Sentinel-2 L2A (ESA Copernicus, AWS Open Data ``sentinel-cogs``): cloud-masked dry-season
  median of the ferric-iron ratio (B4/B2), clay/alteration ratio (B11/B12), NDVI and NDWI,
  plus true- and false-colour composites for the map.
* Copernicus DEM GLO-30 (AWS Open Data): elevation, slope, local relief.
* ESA WorldCover 2021 v200 (AWS Open Data): land-cover fractions per cell, used to show how much
  of each cell is bare/mined ground (a known confounder, see ``realdata.py``).

Output goes to ``backend/data/real/`` and is committed, so the app never needs network access or
the geospatial stack at runtime. Re-run with::

    pip install -r requirements-geo.txt
    python -m ml.remote_sensing            # from backend/, takes a few minutes

Only rasterio, pyproj and numpy are needed; everything else is the standard library.
"""
from __future__ import annotations

import json
import os
import re
import struct
import sys
import time
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .reference import STUDY_BBOX
from .synthetic import GRID_STEP_DEG

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "real"

S2_BUCKET = "https://sentinel-cogs.s3.us-west-2.amazonaws.com"
S2_PREFIX = "sentinel-s2-l2a-cogs"
S2_TILES = ["44QKJ", "44QKK", "44QLJ", "44QLK", "44QMJ", "44QMK"]  # MGRS tiles covering STUDY_BBOX
S2_SEASONS = [(2024, (2, 3, 4)), (2025, (2, 3, 4))]  # dry season: low cloud, crops harvested
S2_MAX_CLOUD_PCT = 10.0
S2_MAX_NODATA_PCT = 40.0
S2_SCENES_PER_TILE = 3
S2_READ_RES_M = 80.0  # read COG overviews at ~80 m; cells are ~2 km
S2_ASSETS = {"blue": "B02", "green": "B03", "red": "B04", "nir": "B08", "swir16": "B11", "swir22": "B12"}
SCL_INVALID = (0, 1, 3, 8, 9, 10, 11)  # no data, saturated, cloud shadow, cloud (medium/high), cirrus, snow

DEM_URL = "https://copernicus-dem-30m.s3.amazonaws.com/{n}/{n}.tif"
DEM_READ_STEP_DEG = 1 / 1200  # 3 arc-seconds (~90 m)
WORLDCOVER_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{t}_Map.tif"
WORLDCOVER_READ_STEP_DEG = 0.001
WORLDCOVER_CLASSES = {"tree": (10,), "shrub_grass": (20, 30), "cropland": (40,), "built": (50,), "bare": (60,), "water": (80, 90)}

FINE_STEP_DEG = GRID_STEP_DEG / 10  # composite bins (~220 m); 10 x 10 bins per model cell

S2_FEATURES = ["ferric_ratio_b4_b2", "clay_ratio_b11_b12", "ndvi", "ndwi"]
DEM_FEATURES = ["elevation_m", "slope_deg", "ruggedness_m"]
COVER_FEATURES = [f"frac_{k}" for k in WORLDCOVER_CLASSES]

ATTRIBUTION = [
    "Contains modified Copernicus Sentinel data {years} (ESA), accessed via the AWS Open Data 'sentinel-cogs' archive.",
    "Copernicus DEM GLO-30: produced using Copernicus WorldDEM-30 (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH "
    "2014-2018, provided under COPERNICUS by the European Union and ESA; all rights reserved.",
    "ESA WorldCover 10 m 2021 v200 (c) ESA WorldCover project / contains modified Copernicus Sentinel data (2021) processed by "
    "the ESA WorldCover consortium; CC BY 4.0.",
]


# ----------------------------------------------------------------------------------- grid
def grid_axes():
    """Cell-centre latitudes and longitudes, identical to ``synthetic.generate_geology``."""
    lats = np.arange(STUDY_BBOX["lat_min"] + GRID_STEP_DEG / 2, STUDY_BBOX["lat_max"], GRID_STEP_DEG)
    lons = np.arange(STUDY_BBOX["lon_min"] + GRID_STEP_DEG / 2, STUDY_BBOX["lon_max"], GRID_STEP_DEG)
    return lats, lons


def fine_shape():
    lats, lons = grid_axes()
    return len(lats) * 10, len(lons) * 10


def fine_index(lat, lon):
    """Flat index into the fine composite grid, or -1 outside the study area."""
    nr, nc = fine_shape()
    i = np.floor((np.asarray(lat) - STUDY_BBOX["lat_min"]) / FINE_STEP_DEG + 1e-9).astype(np.int64)
    j = np.floor((np.asarray(lon) - STUDY_BBOX["lon_min"]) / FINE_STEP_DEG + 1e-9).astype(np.int64)
    ok = (i >= 0) & (i < nr) & (j >= 0) & (j < nc)
    return np.where(ok, i * nc + j, -1)


def bin_mean(idx, values, n_bins, min_count=1):
    ok = (idx >= 0) & np.isfinite(values)
    cnt = np.bincount(idx[ok], minlength=n_bins)
    tot = np.bincount(idx[ok], weights=values[ok], minlength=n_bins)
    out = np.full(n_bins, np.nan)
    good = cnt >= min_count
    out[good] = tot[good] / cnt[good]
    return out, cnt


def fine_to_cells(fine: np.ndarray, reducer=np.nanmedian, min_valid=10):
    """Aggregate a (nr*10, nc*10) fine grid to model cells, row-major like the synthetic grid."""
    nr, nc = fine_shape()
    blocks = fine.reshape(nr // 10, 10, nc // 10, 10).transpose(0, 2, 1, 3).reshape(nr // 10, nc // 10, 100)
    valid = np.isfinite(blocks).sum(axis=2)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            out = reducer(blocks, axis=2)
    out[valid < min_valid] = np.nan
    return out.ravel(), valid.ravel()


# ----------------------------------------------------------------------------------- http
def _get(url, timeout=60, tries=4):
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read()
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(2 ** (k + 1))


def _gdal_env():
    import rasterio
    ca = os.environ.get("CURL_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    extra = {"CURL_CA_BUNDLE": ca} if ca else {}
    return rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                        GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="2", VSI_CACHE="TRUE", **extra)


# ----------------------------------------------------------------------------------- Sentinel-2
def list_s2_scenes(tile: str) -> list[dict]:
    zone, band, sq = tile[:2], tile[2], tile[3:]
    scenes = []
    for year, months in S2_SEASONS:
        for m in months:
            prefix = f"{S2_PREFIX}/{int(zone)}/{band}/{sq}/{year}/{m}/"
            xml = _get(f"{S2_BUCKET}/?list-type=2&delimiter=/&prefix={prefix}").decode()
            for p in re.findall(r"<Prefix>([^<]+/)</Prefix>", xml):
                if p == prefix:
                    continue
                name = p.rstrip("/").split("/")[-1]
                item = json.loads(_get(f"{S2_BUCKET}/{p}{name}.json"))
                pr = item["properties"]
                scenes.append({"tile": tile, "id": name, "datetime": pr["datetime"],
                               "cloud_pct": float(pr.get("eo:cloud_cover", 100)),
                               "nodata_pct": float(pr.get("s2:nodata_pixel_percentage", 100)),
                               "baseline": pr.get("s2:processing_baseline"), "item": item})
    return scenes


def choose_scenes(scenes: list[dict]) -> list[dict]:
    ok = [s for s in scenes if s["cloud_pct"] <= S2_MAX_CLOUD_PCT and s["nodata_pct"] <= S2_MAX_NODATA_PCT]
    ok.sort(key=lambda s: (s["cloud_pct"] + 0.2 * s["nodata_pct"], s["datetime"]))
    # Prefer one scene per season-year so the composite is not one date repeated.
    picked, years = [], set()
    for s in ok:
        y = s["datetime"][:4]
        if y not in years:
            picked.append(s)
            years.add(y)
    for s in ok:
        if len(picked) >= S2_SCENES_PER_TILE:
            break
        if s not in picked:
            picked.append(s)
    return picked[:S2_SCENES_PER_TILE]


def _read_band(url, out_n, resampling):
    import rasterio
    from rasterio.enums import Resampling
    with rasterio.open(url) as r:
        return r.read(1, out_shape=(out_n, out_n), resampling=getattr(Resampling, resampling)), r.bounds, r.crs


def read_s2_scene(scene: dict, fine_n: int, pixel_cache: dict) -> dict:
    """Cloud-masked reflectances and indices for one scene, averaged into the fine bins."""
    from pyproj import Transformer
    item = scene["item"]
    assets = item["assets"]
    href = lambda key: "/vsicurl/" + assets[key]["href"]
    import rasterio
    with rasterio.open(href("scl")) as r:  # every band shares the tile footprint
        bounds, crs = r.bounds, r.crs
    n = int(round((bounds.right - bounds.left) / S2_READ_RES_M))
    scl, _, _ = _read_band(href("scl"), n, "nearest")
    bad = np.isin(scl, SCL_INVALID)
    dns, scales, offsets = {}, {}, {}
    for key in S2_ASSETS:
        rb = assets[key].get("raster:bands", [{}])[0]
        scales[key], offsets[key] = float(rb.get("scale", 1e-4)), float(rb.get("offset", 0.0))
        dns[key], _, _ = _read_band(href(key), n, "average")
    # Processing baseline >= 04.00 adds +1000 to the DN and the item declares offset -0.1, but some
    # archived COGs already have the offset removed. Applying it twice drives blue/red reflectance
    # negative over bright ground, so test it on the data: keep the declared offset only if clear
    # pixels stay physically positive with it.
    blue = dns["blue"][(dns["blue"] > 0) & ~bad]
    apply_offset = bool(len(blue) and np.percentile(blue * scales["blue"] + offsets["blue"], 1) > 0)
    refl = {}
    for key, dn in dns.items():
        v = dn.astype(np.float64) * scales[key] + (offsets[key] if apply_offset else 0.0)
        v[(dn == 0) | bad] = np.nan
        refl[key] = v
    ck = (scene["tile"], n, str(crs))
    if ck not in pixel_cache:
        step = (bounds.right - bounds.left) / n
        xs = bounds.left + (np.arange(n) + 0.5) * step
        ys = bounds.top - (np.arange(n) + 0.5) * step
        X, Y = np.meshgrid(xs, ys)
        lon, lat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(X.ravel(), Y.ravel())
        pixel_cache[ck] = fine_index(lat, lon)
    idx = pixel_cache[ck]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = {k: v.ravel() for k, v in refl.items()}
        pos = lambda a: np.where(a > 0.005, a, np.nan)
        q = {
            "ferric_ratio_b4_b2": r["red"] / pos(r["blue"]),
            "clay_ratio_b11_b12": r["swir16"] / pos(r["swir22"]),
            "ndvi": (r["nir"] - r["red"]) / pos(r["nir"] + r["red"]),
            "ndwi": (r["green"] - r["nir"]) / pos(r["green"] + r["nir"]),
            **r,
        }
    out = {}
    for k, v in q.items():
        out[k], _ = bin_mean(idx, v, fine_n, min_count=3)
    out["_valid_px"] = int(np.isfinite(r["red"]).sum())
    out["_offset_applied"] = apply_offset
    return out


# ----------------------------------------------------------------------------------- DEM / land cover
def _dem_tiles():
    tiles = []
    for la in range(int(np.floor(STUDY_BBOX["lat_min"])), int(np.floor(STUDY_BBOX["lat_max"])) + 1):
        for lo in range(int(np.floor(STUDY_BBOX["lon_min"])), int(np.floor(STUDY_BBOX["lon_max"])) + 1):
            tiles.append(f"Copernicus_DSM_COG_10_N{la:02d}_00_E{lo:03d}_00_DEM")
    return tiles


def read_dem(fine_n):
    import rasterio
    from rasterio.enums import Resampling
    elev_sum = np.zeros(fine_n)
    slope_sum = np.zeros(fine_n)
    cnt = np.zeros(fine_n)
    cell_elev = []  # (fine_idx, elevation) for local relief
    used = []
    for name in _dem_tiles():
        url = "/vsicurl/" + DEM_URL.format(n=name)
        with rasterio.open(url) as r:
            b = r.bounds
            out_h = int(round((b.top - b.bottom) / DEM_READ_STEP_DEG))
            out_w = int(round((b.right - b.left) / DEM_READ_STEP_DEG))
            z = r.read(1, out_shape=(out_h, out_w), resampling=Resampling.average).astype(np.float64)
            nod = r.nodata
        if nod is not None:
            z[z == nod] = np.nan
        dy = (b.top - b.bottom) / out_h
        dx = (b.right - b.left) / out_w
        lats = b.top - (np.arange(out_h) + 0.5) * dy
        lons = b.left + (np.arange(out_w) + 0.5) * dx
        LON, LAT = np.meshgrid(lons, lats)
        gy, gx = np.gradient(z, dy * 111_320.0, dx * 111_320.0)
        gx = gx / np.cos(np.radians(LAT))
        slope = np.degrees(np.arctan(np.hypot(gx, gy)))
        idx = fine_index(LAT.ravel(), LON.ravel())
        ok = (idx >= 0) & np.isfinite(z.ravel()) & np.isfinite(slope.ravel())
        if not ok.any():
            continue
        used.append(name)
        elev_sum += np.bincount(idx[ok], weights=z.ravel()[ok], minlength=fine_n)
        slope_sum += np.bincount(idx[ok], weights=slope.ravel()[ok], minlength=fine_n)
        cnt += np.bincount(idx[ok], minlength=fine_n)
        cell_elev.append((idx[ok], z.ravel()[ok]))
    with np.errstate(invalid="ignore"):
        elev = np.where(cnt > 0, elev_sum / np.maximum(cnt, 1), np.nan)
        slope = np.where(cnt > 0, slope_sum / np.maximum(cnt, 1), np.nan)
    # Local relief: standard deviation of the ~90 m elevations inside each model cell.
    nr, nc = fine_shape()
    fi = np.concatenate([c[0] for c in cell_elev])
    zz = np.concatenate([c[1] for c in cell_elev])
    cell = (fi // nc) // 10 * (nc // 10) + (fi % nc) // 10
    n_cells = (nr // 10) * (nc // 10)
    c_n = np.bincount(cell, minlength=n_cells)
    c_s = np.bincount(cell, weights=zz, minlength=n_cells)
    c_ss = np.bincount(cell, weights=zz * zz, minlength=n_cells)
    with np.errstate(invalid="ignore"):
        relief = np.sqrt(np.maximum(c_ss / c_n - (c_s / c_n) ** 2, 0))
    relief[c_n < 20] = np.nan
    return elev, slope, relief, used


def read_worldcover():
    import rasterio
    from rasterio.enums import Resampling
    tiles = sorted({f"N{int(la // 3 * 3):02d}E{int(lo // 3 * 3):03d}"
                    for la in (STUDY_BBOX["lat_min"], STUDY_BBOX["lat_max"]) for lo in (STUDY_BBOX["lon_min"], STUDY_BBOX["lon_max"])})
    lats, lons = grid_axes()
    n_cells = len(lats) * len(lons)
    counts = {k: np.zeros(n_cells) for k in WORLDCOVER_CLASSES}
    total = np.zeros(n_cells)
    for t in tiles:
        url = "/vsicurl/" + WORLDCOVER_URL.format(t=t)
        with rasterio.open(url) as r:
            b = r.bounds
            win = rasterio.windows.from_bounds(STUDY_BBOX["lon_min"], STUDY_BBOX["lat_min"], STUDY_BBOX["lon_max"], STUDY_BBOX["lat_max"], r.transform)
            win = win.intersection(rasterio.windows.Window(0, 0, r.width, r.height))
            wb = rasterio.windows.bounds(win, r.transform)
            out_h = int(round((wb[3] - wb[1]) / WORLDCOVER_READ_STEP_DEG))
            out_w = int(round((wb[2] - wb[0]) / WORLDCOVER_READ_STEP_DEG))
            lc = r.read(1, window=win, out_shape=(out_h, out_w), resampling=Resampling.nearest)
        la = wb[3] - (np.arange(out_h) + 0.5) * (wb[3] - wb[1]) / out_h
        lo = wb[0] + (np.arange(out_w) + 0.5) * (wb[2] - wb[0]) / out_w
        LON, LAT = np.meshgrid(lo, la)
        i = np.floor((LAT.ravel() - STUDY_BBOX["lat_min"]) / GRID_STEP_DEG).astype(int)
        j = np.floor((LON.ravel() - STUDY_BBOX["lon_min"]) / GRID_STEP_DEG).astype(int)
        ok = (i >= 0) & (i < len(lats)) & (j >= 0) & (j < len(lons)) & (lc.ravel() > 0)
        cell = i[ok] * len(lons) + j[ok]
        v = lc.ravel()[ok]
        total += np.bincount(cell, minlength=n_cells)
        for k, codes in WORLDCOVER_CLASSES.items():
            counts[k] += np.bincount(cell[np.isin(v, codes)], minlength=n_cells)
    with np.errstate(invalid="ignore"):
        return {f"frac_{k}": np.where(total > 0, c / np.maximum(total, 1), np.nan) for k, c in counts.items()}, tiles


# ----------------------------------------------------------------------------------- imagery
def _png(path: Path, rgb: np.ndarray):
    """Minimal RGBA PNG writer (stdlib only). ``rgb`` is (h, w, 3) uint8; NaN areas are transparent."""
    h, w, _ = rgb.shape
    alpha = np.where(np.all(rgb == 0, axis=2), 0, 255).astype(np.uint8)
    raw = b"".join(b"\x00" + np.dstack([rgb, alpha])[y].tobytes() for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def composite_png(path: Path, r, g, b):
    nr, nc = fine_shape()
    bands = []
    for a in (r, g, b):
        a = a.reshape(nr, nc)[::-1]  # north up
        lo, hi = np.nanpercentile(a, 2), np.nanpercentile(a, 98)
        s = np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1) ** (1 / 1.2)
        bands.append(np.where(np.isfinite(s), 1 + np.round(s * 254), 0).astype(np.uint8))
    _png(path, np.dstack(bands))


# ----------------------------------------------------------------------------------- checks
PHYSICAL_RANGES = {"ndvi": (-1, 1), "ndwi": (-1, 1), "ferric_ratio_b4_b2": (0.2, 10), "clay_ratio_b11_b12": (0.2, 10),
                   "elevation_m": (100, 1500), "slope_deg": (0, 60), "ruggedness_m": (0, 500)}
MIN_COVERAGE = 0.95


def check_physical(cells: pd.DataFrame) -> list[str]:
    """Plausibility checks for the study area; any failure blocks the write."""
    problems = []
    for k, (lo, hi) in PHYSICAL_RANGES.items():
        v = cells[k].dropna()
        if len(v) < MIN_COVERAGE * len(cells):
            problems.append(f"{k} covers only {len(v) / len(cells):.0%} of cells")
        elif v.min() < lo or v.max() > hi:
            problems.append(f"{k} outside [{lo}, {hi}] (min {v.min():.3g}, max {v.max():.3g})")
    return problems


# ----------------------------------------------------------------------------------- main
def build(out_dir: Path = OUT_DIR, log=print):
    out_dir.mkdir(parents=True, exist_ok=True)
    nr, nc = fine_shape()
    fine_n = nr * nc
    lats, lons = grid_axes()

    stacks: dict[str, list] = {}
    used_scenes = []
    cache: dict = {}
    for tile in S2_TILES:
        scenes = choose_scenes(list_s2_scenes(tile))
        log(f"S2 {tile}: using {[s['id'] for s in scenes]}")
        for s in scenes:
            q = read_s2_scene(s, fine_n, cache)
            used_scenes.append({k: s[k] for k in ("tile", "id", "datetime", "cloud_pct", "nodata_pct", "baseline")}
                               | {"valid_pixels_80m": q.pop("_valid_px"), "declared_offset_applied": q.pop("_offset_applied")})
            for k, v in q.items():
                stacks.setdefault(k, []).append(v)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        med = {k: np.nanmedian(np.vstack(v), axis=0) for k, v in stacks.items()}

    cells = pd.DataFrame({
        "row": np.repeat(np.arange(len(lats)), len(lons)), "col": np.tile(np.arange(len(lons)), len(lats)),
        "latitude": np.repeat(lats, len(lons)), "longitude": np.tile(lons, len(lats)),
    })
    for k in S2_FEATURES:
        cells[k], valid = fine_to_cells(med[k])
    cells["s2_valid_bins"] = valid

    log("Copernicus DEM ...")
    elev, slope, relief, dem_used = read_dem(fine_n)
    cells["elevation_m"], _ = fine_to_cells(elev, np.nanmean)
    cells["slope_deg"], _ = fine_to_cells(slope, np.nanmean)
    cells["ruggedness_m"] = relief

    log("ESA WorldCover ...")
    fracs, wc_used = read_worldcover()
    for k, v in fracs.items():
        cells[k] = v

    cells = cells.round(5)
    problems = check_physical(cells)
    if problems:
        raise ValueError("Refusing to write implausible features: " + "; ".join(problems))
    cells.to_csv(out_dir / "grid_features_real.csv", index=False)
    composite_png(out_dir / "s2_true_colour.png", med["red"], med["green"], med["blue"])
    composite_png(out_dir / "s2_false_colour_swir.png", med["swir22"], med["nir"], med["red"])

    years = sorted({s["datetime"][:4] for s in used_scenes})
    prov = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "backend/ml/remote_sensing.py",
        "grid": {"bbox": STUDY_BBOX, "cell_deg": GRID_STEP_DEG, "rows": len(lats), "cols": len(lons),
                 "composite_bin_deg": FINE_STEP_DEG, "s2_read_resolution_m": S2_READ_RES_M},
        "sentinel2": {"collection": "Sentinel-2 L2A (sentinel-s2-l2a-cogs)", "tiles": S2_TILES,
                      "season": [{"year": y, "months": list(m)} for y, m in S2_SEASONS],
                      "max_cloud_pct": S2_MAX_CLOUD_PCT, "scl_masked_classes": list(SCL_INVALID), "scenes": used_scenes},
        "dem": {"collection": "Copernicus DEM GLO-30", "tiles": dem_used, "read_step_deg": DEM_READ_STEP_DEG},
        "worldcover": {"collection": "ESA WorldCover 10 m 2021 v200", "tiles": wc_used, "read_step_deg": WORLDCOVER_READ_STEP_DEG},
        "imagery": {"s2_true_colour.png": "B4/B3/B2 median", "s2_false_colour_swir.png": "B12/B8/B4 median (geology false colour)",
                    "bounds": [[STUDY_BBOX["lat_min"], STUDY_BBOX["lon_min"]], [STUDY_BBOX["lat_max"], STUDY_BBOX["lon_max"]]]},
        "features": {"sentinel2": S2_FEATURES, "dem": DEM_FEATURES, "land_cover": COVER_FEATURES},
        "not_available": {
            "sar_vv_db, sar_vh_db": "No Sentinel-1 analysis-ready archive covering India is openly readable without an account.",
            "dist_lineament_km, lithology_favourability": "Need GSI Bhukosh 1:50k geology and structure layers (login required).",
        },
        "attribution": [a.format(years="-".join(years) if len(years) > 1 else years[0]) for a in ATTRIBUTION],
    }
    (out_dir / "provenance.json").write_text(json.dumps(prov, indent=2))
    log(f"Wrote {len(cells)} cells to {out_dir}")
    return cells, prov


if __name__ == "__main__":
    with _gdal_env():
        build(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_DIR)
