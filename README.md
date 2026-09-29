# Manganese Horizon

**AI decision support for MOIL: where to drill next, whether next month's target will be met, and what to do about it.**

Smart India Hackathon 2026 · Problem Statement **SIH26009** — *Using AI/ML and Space Technology to Identify Manganese Reserves and Overcome Production Shortfalls* · Ministry of Steel (MOIL Limited) · Theme: Space Technology · Software

> **Read this first: what is proven and what is not.**
> The forecasting and action-planning modules are validated on **synthetic** production data, because MOIL's telemetry is not public. The reserve module has been **re-tested on real Sentinel-2 imagery and real mine locations, and the result was weak** (spatial-CV AUC 0.56, 95% CI 0.31–0.77, which includes chance). We publish that result, and the reasons it is weak, alongside the strong synthetic one. See [Real-data validation](#real-data-validation-module-1) and [Limitations](#limitations).

---

## Contents

1. [The idea](#the-idea)
2. [Verify it yourself in five minutes](#verify-it-yourself-in-five-minutes)
3. [Quick start](#quick-start)
4. [Architecture](#architecture)
5. [Module 1: Reserve confidence](#module-1-reserve-confidence)
6. [Real-data validation (Module 1)](#real-data-validation-module-1)
7. [Module 2: Shortfall forecast](#module-2-shortfall-forecast)
8. [Module 3: Corrective actions](#module-3-corrective-actions)
9. [Dashboard](#dashboard)
10. [Sign-in and roles](#sign-in-and-roles)
11. [Data pipeline](#data-pipeline)
12. [API reference](#api-reference)
13. [Configuration](#configuration)
14. [Testing and CI](#testing-and-ci)
15. [Deployment](#deployment)
16. [Repository layout](#repository-layout)
17. [Honesty by design](#honesty-by-design)
18. [Limitations](#limitations)
19. [Data sources and attribution](#data-sources-and-attribution)
20. [Further documentation](#further-documentation)

---

## The idea

SIH26009 is really **two problems**.

- *Where is the ore?* is a geology problem. Satellites cannot see ore underground, so borehole data does the sub-surface work and satellite imagery only narrows where to drill next.
- *Will we hit production?* is an equipment, weather and blasting problem. This is where the four satellite variables in the statement (rainfall, soil moisture, NDVI, land-surface temperature) earn their place.

Manganese Horizon answers both, then turns a forecast shortfall into an optimised, auditable action plan. Every number it shows is tagged as **observed**, a **forecast**, a **model inference** or a **scenario**.

| Module | Question | Method |
|---|---|---|
| 1 · Reserve confidence | Where should we drill next? | Ordinary kriging of borehole Mn grade (with variance), fused with an XGBoost surface-proxy model on Sentinel-2 band ratios, Sentinel-1 SAR, DEM, lineaments and mapped lithology. Validated with spatial-block CV. Drill targets are ranked by value of information and carry a conceptual tonnage range. |
| 2 · Shortfall forecast | Will we miss target, and why? | Direct multi-horizon (1–3 months) quantile XGBoost (P10/P50/P90) with split-conformal calibration, physical monotone constraints and exact TreeSHAP drivers. Always benchmarked against persistence and seasonal-naive baselines. |
| 3 · Corrective actions | What should we do? | One linear programme (HiGHS) across all deficit mines. Levers are tied to the SHAP drivers (blasting reschedule, loader redeployment, overhaul compression, wet-weather plan, extra shifts), plus sister-mine reallocation limited by each mine's real spare capacity. |

---

## Verify it yourself in five minutes

Nothing in this project needs to be taken on trust. The API is live and computes everything on request; there are no mocked responses. Start the server (see [Quick start](#quick-start)), then:

```bash
# 1. Sign in (demo account) and keep the token
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -H 'content-type: application/json' \
  -d '{"username":"admin","password":"demo123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
H="Authorization: Bearer $TOKEN"

# 2. The live scientific-integrity checklist (every check re-evaluated on request)
curl -s -H "$H" localhost:8000/api/integrity | python3 -m json.tool | less

# 3. The weak real-data result, straight from the model
curl -s -H "$H" localhost:8000/api/reserves/real | python3 -c \
  "import sys,json;d=json.load(sys.stdin);print(d['validation']['spatial_cv_auc'], d['validation']['spatial_cv_auc_ci95'], d['disturbance_auc'])"

# 4. Forecast accuracy against baselines on the held-out year
curl -s -H "$H" localhost:8000/api/forecast/metrics | python3 -m json.tool | less

# 5. The action plan, with each lever's assumptions and disclaimer
curl -s -H "$H" localhost:8000/api/actions | python3 -m json.tool | less
```

Or run the code paths directly, without the server:

```bash
cd backend
python -c "from ml.realdata import run_real_module1 as r; v=r()['validation']; print(v['spatial_cv_auc'], v['spatial_cv_auc_ci95'], v['n_positive'])"
python -m pytest -q          # 47 tests
```

Expected on a fresh clone: `0.558 [0.305, 0.773] 10`, and `47 passed`.

---

## Quick start

Requires Python 3.11+ and Node 18+.

```bash
make install                         # pip + npm
make run                             # builds the dashboard, serves API + UI on http://localhost:8000 (API docs at /docs)
# or hot-reload:  make api  (port 8000)  +  make web  (port 5173, proxies /api)

make test                            # backend test suite (47 tests)
make reset-demo                      # delete backend/var so demo data and models are regenerated
```

On first start the server generates the deterministic demo dataset, seeds the database and trains every model (about 10–30 s, cached afterwards). `/api/health` reports `training` until it is ready.

The default database is SQLite (no setup, works on a site laptop). For PostgreSQL/PostGIS, run `db/postgis_schema.sql` on the server and set `DATABASE_URL=postgresql+psycopg2://<user>:<password>@<host>:5432/manganese_horizon`.

---

## Architecture

```
 Public data (GSI, IBM, Sentinel-1/2, Bhuvan DEM, IMD/NASA POWER/MODIS)      MOIL logs (CSV upload / future MoU feed)
                    │  simulated in demo, same schema                                │ validated → is_synthetic = FALSE
                    ▼                                                                ▼
           ┌───────────────────────── SQLite / PostgreSQL + PostGIS ─────────────────────────┐
           │ mines · boreholes · occurrences · production_logs · weather_features · mine_plans │
           │ reserve_confidence_grid · forecasts · recommendations · audit_log · pipeline_runs │
           └───────────────┬───────────────────────────────┬──────────────────────────────────┘
                           ▼                               ▼
   Module 1  Reserve confidence              Module 2  Shortfall forecast
   ├ variogram fit + ordinary kriging        ├ ex-ante features (plan, IMD outlook, lags)
   ├ XGBoost surface proxy (PU, 3 km buffer) ├ quantile XGBoost α=.1/.5/.9 × horizons 1-3
   ├ spatial-block CV (30 km)                ├ monotone constraints + conformal (CQR)
   ├ fusion → confidence + uncertainty       ├ TreeSHAP → named drivers + evidence guardrail
   ├ drill targets by value of information   └ baselines, coverage, Brier, capacity guardrail
   └ Monte Carlo conceptual tonnage                       │ deficit = target − P50 > 0
                                                          ▼
                                         Module 3  LP corrective-action engine (HiGHS)
                                         levers ← SHAP drivers; sister spare capacity
                                                          │
                           ┌──────────────────────────────┴─────────────────────────┐
                           ▼                                                        ▼
            FastAPI  /api/*  (epistemic tags + data-mode meta on every response)   what-if scenarios
                           │
                           ▼
   React PWA — Command Centre · Reserve map · Forecast · Actions · Scenarios · Integrity · Brief
   Workbox NetworkFirst cache + IndexedDB fallback · offline decision queue · EN/HI/MR

 Separate, committed real-data track (does not feed the demo fusion):
   AWS Open Data (Sentinel-2 L2A, Copernicus DEM, WorldCover) ──► ml/remote_sensing.py ──► backend/data/real/
   backend/data/real/ + real MOIL mine locations ──► ml/realdata.py ──► /api/reserves/real
```

### Key design choices

| Choice | Why |
|---|---|
| Model utilisation (production ÷ rated monthly capacity), not tonnes | One model generalises across mines from 250 to 1,600 t/day. |
| Direct multi-horizon models instead of recursive roll-forward | Errors don't compound, and each horizon gets its own calibrated interval. |
| Only ex-ante inputs (plans, IMD outlook, last observations) | No look-ahead. Realised rain and downtime of the forecast month are never features. |
| Monotone constraints (rain ↓, fleet health ↑, blast window ↑ …) | Keeps what-if scenarios physically coherent. |
| Split-conformal widening of P10–P90 | Coverage is measured, not assumed. |
| TreeSHAP via `xgboost pred_contribs` | Exact, fast, no extra dependency. Grouped into mechanisms planners recognise. |
| LP rather than an LLM for actions | Quantified, auditable and reproducible; every tonne traces to a lever and a constraint. |
| Stockpile drawdown reported separately | It protects dispatches but does not recover production. Counting it would flatter the plan. |
| Real-data track committed to the repo | The app never needs network access or the geospatial stack at runtime; results are reproducible offline. |
| SQLite default, PostGIS optional | Runs on a site laptop with no infrastructure; scales to PostGIS without code changes. |

---

## Module 1: Reserve confidence

**Scope statement: this is a drilling-prioritisation tool, not a reserve estimate.** The system says *prospectivity*, never "reserve".

- **Kriging.** A spherical variogram is fitted to borehole Mn grade and ordinary kriging gives a grade and a variance per cell. Kriging is validated at two scales (see below).
- **Surface proxy.** An XGBoost model on Sentinel-2 ratios, SAR, DEM, lineament distance and mapped lithology, framed as positive-unlabelled learning: pseudo-absences are background drawn at least 3 km from known occurrences, not "proven barren" ground.
- **Fusion.** The two are combined into a confidence and an uncertainty. Under alluvium or Deccan Trap basalt, where the surface reflects cover rather than bedrock, the surface proxy's weight is cut to 10–15% and uncertainty rises instead of the map faking confidence.
- **Drill targets** are ranked by value of information: high prospectivity combined with high uncertainty, which is where a hole teaches the most.
- **Conceptual tonnage** (`ml/tonnage.py`). Each target gets a Monte Carlo range of ore tonnes and contained Mn, from assumed lens geometry (strike 500–2,000 m, down-dip 100–300 m, continuity 0.3–0.7, density 3.5–4.0 t/m³) and kriged grade and thickness. A draw below the cut-off contributes zero tonnes, so the probability of finding no ore is part of the range. The current top target, for example, has a P10 and P50 of 0 t and only a 25% probability of ore being present. Every range ships with its assumptions and a label stating it is **not** a Mineral Resource or Reserve.
- **Indicator kriging** is reported as a distribution-free check on the Gaussian grade model (cross-validated Brier score against climatology).

### Demo-data results (synthetic)

These come from **synthetic** data, so they are optimistic relative to real MOIL records. They are reproduced live at `/api/reserves/validation`.

| Check | Result |
|---|---|
| Surface proxy, spatial-block CV (30 km) | AUC **0.91** (95% CI 0.87–0.95), 61 synthetic occurrences |
| Same model, random k-fold | AUC 0.93, which is why random CV is optimistic and not used |
| Kriging, interpolation inside drilled areas | 3.3 %Mn MAE (mean-only baseline: 7.8) |
| Kriging, extrapolation beyond ~14 km variogram range | 8.9 %Mn MAE (mean-only baseline: 8.0), i.e. **no better than the mean** |

The last row is deliberate: the map shows this as uncertainty, and it is exactly the gap the satellite proxy is meant to cover.

---

## Real-data validation (Module 1)

The demo fusion needs borehole assays, which are MOIL/GSI internal. What *can* be tested honestly today is the surface-proxy half: **does a model on real Sentinel-2 and Copernicus DEM features, trained on real manganese locations, rank those locations above background under spatial cross-validation?**

### What the real data is

| Item | Detail |
|---|---|
| Study area | lat 21.2–22.1, lon 78.8–80.6 (Balaghat–Bhandara–Nagpur belt), 0.02° grid, 45 × 90 cells |
| Sentinel-2 L2A | 20 scenes across 6 tiles, dry seasons (Feb–Apr) of 2024 and 2025, ≤ 10% cloud, SCL-masked, median composite at 80 m |
| Copernicus DEM GLO-30 | Elevation, slope, local relief |
| ESA WorldCover 2021 v200 | Land-cover fractions per cell (used for the disturbance check) |
| Features used | `ferric_ratio_b4_b2`, `clay_ratio_b11_b12`, `ndvi`, `ndwi`, `elevation_m`, `slope_deg`, `ruggedness_m` |
| Labels | MOIL's operating mines from the public mine list (12 rows listed, 11 flagged for training, 10 positives in the CV). Coordinates are approximate (± 2–3 km). |

Everything above is in `backend/data/real/` with a full `provenance.json` (scene IDs, dates, cloud cover, processing baselines, attribution). Rebuild it with `pip install -r backend/requirements-geo.txt && python -m ml.remote_sensing` from `backend/`.

### The result

| Measure | Value |
|---|---|
| Spatial-block CV AUC | **0.56** (95% CI **0.31–0.77**) |
| Random k-fold AUC (for comparison) | 0.63 |
| Per-fold AUC | 0.67, 0.10, 0.67, 0.38 (folds hold 1–6 positives each) |
| Bare + built-up ground alone (the "just detect the mine" baseline) | **0.64** |
| Synthetic-data AUC, same model family | 0.91 |

**Reading.** The interval includes 0.5, so on real data the surface proxy **has not shown skill**. Worse, a trivial score based only on how much bare or built-up ground a cell has (AUC 0.64) does at least as well as the model, which suggests the model is at best detecting pits and waste dumps around operating mines, not ore geology.

**Why it is weak, honestly.**
1. Only ten point-accurate labels exist in the public domain for this area, so the confidence interval is enormous.
2. Every label is an *active mine*, so the label itself is confounded with surface disturbance.
3. Coordinates are ± 2–3 km, coarser than the 2 km grid cell.
4. Sentinel-1 SAR, lineaments and mapped lithology, the layers most likely to help, could not be obtained (below).

This is why the project claims the *method* is sound, not that the demo AUC of 0.91 is evidence of real-world skill. The Integrity page states the same thing and marks the check as "reported as is".

### What could not be obtained (`not_available` in `provenance.json`)

The provenance file records what we tried and failed to get, instead of quietly substituting synthetic values:

| Missing | Reason |
|---|---|
| `sar_vv_db`, `sar_vh_db` (Sentinel-1) | No Sentinel-1 analysis-ready archive covering India is openly readable without an account. |
| `dist_lineament_km`, `lithology_favourability` | Need GSI Bhukosh 1:50k geology and structure layers (login required). |

### How to improve it

Drop a CSV with the same columns as `data/real/occurrences_real.csv` at `<MH_DATA_DIR>/real_occurrences_extra.csv` (for example GSI Bhukosh occurrences with proper precision and non-mine deposits). It is validated (numeric coordinates, mandatory `source`) and merged on the next run. More labels that are *not* operating mines is the single most useful thing that could change this result.

---

## Module 2: Shortfall forecast

- **Target:** utilisation (production ÷ rated monthly capacity), converted back to tonnes.
- **Models:** one quantile XGBoost per quantile (0.1 / 0.5 / 0.9) per horizon (+1, +2, +3 months), with monotone constraints and a split-conformal (CQR) adjustment fitted on a calibration window.
- **Drivers:** exact TreeSHAP contributions, grouped into named mechanisms (blasting window, fleet health, rainfall, overhaul schedule …).
- **Guardrails:** if the largest driver explains under 15% of the P10–P90 width, the output says *"Insufficient evidence to determine the cause"*. Targets above 1.5× historical maximum or 1.25× rated capacity are flagged, as are targets above P90.

### Results on held-out Sep 2025 – Aug 2026 (synthetic data, n = 120 per horizon)

| Horizon | Model P50 MAE | Persistence | Seasonal-naive | P10–P90 coverage (nominal 80%) |
|---|---|---|---|---|
| +1 month | **418 t** | 1,050 t | 867 t | 85% |
| +2 months | **470 t** | 1,157 t | 867 t | 79% |
| +3 months | **449 t** | 1,320 t | 867 t | 78% |

At +1 month the shortfall detector caught 23 of 25 actual shortfalls (flagged when P(meeting target) < 50%) with a 7% false-alarm rate and a Brier score of 0.092.

**These figures are synthetic and optimistic.** They also went *up* from an earlier 321 t after two look-ahead leaks were found and removed: fleet health is now read at issue time for +2/+3 month forecasts, and the simulated rainfall outlook has realistic skill (anomaly correlation ≈ 0.55 instead of near-perfect foresight). `tests/test_leakage.py` scrambles every later value and requires identical features, so the leaks cannot return unnoticed.

---

## Module 3: Corrective actions

A single linear programme (SciPy HiGHS) minimises indicative cost subject to closing each mine's deficit, capped by lever capacity and by sister mines' real spare capacity.

| Lever | Enabled only when this SHAP driver is present |
|---|---|
| Blasting reschedule into dry windows | Blasting-window contribution |
| Loader / fleet redeployment | Fleet-health contribution |
| Overhaul compression | Scheduled overhaul contribution |
| Wet-weather plan | Rainfall contribution |
| Extra (derated) shifts | Capacity headroom |
| Sister-mine reallocation | Spare capacity at other mines in the cluster |

Each action carries a rank, priority, confidence, cost per tonne, the supporting features that triggered it, a list of **assumptions**, and the disclaimer *"Scenario estimate — not a guaranteed operational instruction. Requires approval by the Mine Manager / Shift In-Charge."*

**How realistic are the recommendations?** The blasting lever, for instance, is only offered for mines where the model shows the blasting window as a driver, states how many planned days have no window, and attaches the assumptions *"Magazine stock and licence validity confirmed"* and *"DGMS blasting-hour restrictions respected"* (Directorate General of Mines Safety, the Indian mining safety regulator). To be precise about scope: DGMS compliance is a **stated assumption the manager must confirm**, not an automated regulatory check. Stockpile drawdown is reported separately because it protects dispatches but does not recover production.

---

## Dashboard

An **offline-first PWA** in **English / हिन्दी / मराठी** (React 18, Vite, Tailwind, Leaflet, Recharts, Workbox, IndexedDB).

| Page | What it shows |
|---|---|
| Command Centre | KPIs for the current month: mines at risk, total deficit, how much the plan mitigates |
| Reserve map | Fused confidence and uncertainty layers, borehole and occurrence points, drill targets with SHAP reasons and tonnage ranges, real Sentinel-2 true/false-colour overlays, real-data validation |
| Forecast | P10/P50/P90 fan per mine, probability of meeting target, drivers, baselines table |
| Actions | Ranked levers per mine, sister-mine reallocation, approve / reject / defer |
| Scenarios | What-if runs (e.g. heavy monsoon); the optimiser re-plans, tagged SCENARIO |
| Data & Integrity | Live checklist of the scientific-integrity rules, pipeline runs, data upload, stated limitations |
| Brief | Printable executive summary |

Decisions made offline are queued in IndexedDB and synced when connectivity returns. A guided 10-step judge demo is built in (sidebar → **Guided demo**); the script is in [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md).

---

## Sign-in and roles

Every data endpoint needs a signed-in user. Pick a role on the sign-in screen (demo password `demo123`):

| Role | Demo account(s) | Can |
|---|---|---|
| Administrator | `admin` | everything, incl. running the data pipeline |
| Mine Manager | `manager.balaghat`, `manager.bhandara`, `manager.nagpur` | approve / reject / defer actions **for mines in their own cluster only** |
| Mine Planning Engineer | `planner` | defer actions, upload MOIL data |
| Exploration Geologist | `geologist` | upload data, view everything |
| Viewer | `viewer` | read-only |

Tokens are stateless HMAC-signed bearers with PBKDF2 password hashes. Decisions are recorded in the audit log under the signed-in account and role (no free-text names). For a real deployment set `MH_SECRET`, change `MH_DEMO_PASSWORD`, or disable demo accounts with `MH_DEMO_ACCOUNTS=0`. LDAP/SSO integration is a deployment step and is not built.

---

## Data pipeline

| Job | What it does |
|---|---|
| `nasa_power` | Pulls **real** daily rainfall, soil wetness and surface temperature for each mine from NASA POWER (free, no API key; needs internet access to `power.larc.nasa.gov`) and stores monthly values in `external_weather` (`is_synthetic = FALSE`). |
| `inbox` | Validates and loads MOIL CSV exports dropped into `backend/var/inbox/`; bad files go to `rejected/` with an error report. |
| `retrain` | Retrains the models when the data changed. |

It runs inside the server every `MH_PIPELINE_INTERVAL_MIN` minutes (default 360; `0` turns it off), can be triggered by an Administrator from the **Data & Integrity** page, or from cron:

```bash
0 */6 * * *  cd /path/to/manganese_ai/backend && python -m app.pipeline all
```

Every run is logged in `pipeline_runs` and shown on the dashboard. The NASA POWER series is kept next to, not inside, the model features until real MOIL production logs arrive, because mixing real weather with simulated production would corrupt training. Once ≥ 240 real production rows exist, training drops synthetic rows.

---

## API reference

Interactive docs at `/docs`. All routes are under `/api`; everything except `/health`, `/auth/login` and `/auth/roles` requires a bearer token.

| Area | Endpoints |
|---|---|
| System | `GET /health` · `POST /auth/login` · `GET /auth/roles` · `GET /auth/me` · `GET /meta` · `GET /integrity` |
| Overview | `GET /overview` · `GET /mines` |
| Reserves (demo fusion) | `GET /reserves/grid` · `/reserves/cell` · `/reserves/points` · `/reserves/validation` |
| Reserves (real data) | `GET /reserves/real` |
| Forecast | `GET /forecast/summary` · `/forecast/metrics` · `/forecast/mine/{mine_id}` |
| Actions | `GET /actions` · `POST /actions/reallocate` |
| Scenarios | `GET /scenarios` · `POST /scenarios/run` |
| Audit | `POST /audit` · `GET /audit` |
| Data | `POST /data/upload` · `GET /pipeline` · `POST /pipeline/run/{job}` · `GET /external-weather/{mine_id}` |

Every response carries an epistemic `tags` map and `meta.data_mode` (`SYNTHETIC` or real), which the UI renders as badges.

---

## Configuration

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL; default is SQLite under `backend/var/` |
| `MH_DATA_DIR` | Data/model directory; also where `real_occurrences_extra.csv` is read from |
| `MH_SECRET` | Token-signing secret (auto-generated key file if unset; set it in production) |
| `MH_TOKEN_TTL_HOURS` | Token lifetime |
| `MH_DEMO_ACCOUNTS` | `0` disables demo accounts |
| `MH_DEMO_PASSWORD` | Password for demo accounts (default `demo123`) |
| `MH_PIPELINE_INTERVAL_MIN` | Built-in scheduler period in minutes; `0` disables |
| `MH_CORS_ORIGINS` | Allowed origins when the UI is hosted separately |
| `MH_FRONTEND_DIST` | Path of the built dashboard to serve |
| `MH_SYNC_BOOTSTRAP` | Train synchronously at start-up instead of in the background |

---

## Testing and CI

```bash
make test        # cd backend && python -m pytest -q   →  47 tests
```

| Suite | Covers |
|---|---|
| `test_science.py` | No leakage features, quantile monotonicity, baselines, epistemic tags, forbidden wording, disclaimers |
| `test_leakage.py` | Look-ahead guard: scrambles all later values and requires identical features |
| `test_module1.py` | Kriging, surface proxy, spatial CV, fusion, drill targets |
| `test_realdata.py` | Real-data track: feature grid integrity, label validation, disturbance check |
| `test_auth_pipeline.py` | Sign-in, role and cluster-scope enforcement, pipeline jobs, CSV inbox |
| `test_api.py` | Endpoint contracts and the disclaimer on every action |

`.github/workflows/ci.yml` runs three jobs on every push and pull request: backend tests (Python 3.11), frontend build (Node 22), and a Playwright end-to-end smoke test (`frontend/e2e/smoke.spec.js`) that signs in and visits every page while watching for console errors.

---

## Deployment

- **Single service (recommended):** `make run` serves the API and the built dashboard from one FastAPI process on port 8000.
- **Database:** SQLite by default; PostgreSQL/PostGIS via `db/postgis_schema.sql` and `DATABASE_URL`.
- **Static frontend on Vercel:** `vercel.json` builds and hosts the dashboard only. It has **no backend**, so the UI needs a separately hosted API (set `MH_CORS_ORIGINS` on the API and point the frontend at it). Deploying the frontend alone shows a sign-in screen with nothing behind it.
- **Production checklist:** set `MH_SECRET`, change or disable demo accounts, put the API behind HTTPS, and integrate MOIL's directory for SSO.

---

## Repository layout

```
backend/
  ml/              reference.py (MOIL mines) · synthetic.py (generator) · geostats.py (kriging)
                   prospectivity.py (Module 1) · tonnage.py (conceptual ranges, indicator kriging)
                   remote_sensing.py (builds real features) · realdata.py (real-data Module 1)
                   features.py + forecasting.py (Module 2) · optimizer.py (Module 3) · scenarios.py
  app/             FastAPI app, auth, SQLAlchemy schema, ingest, pipeline, state/training cache, epistemic tags
  data/real/       committed real Sentinel-2/DEM/WorldCover features, real labels, provenance.json, map imagery
  tests/           science guardrails, leakage, real data, auth, API
frontend/          React 18 · Vite · Tailwind · Leaflet · Recharts · Workbox PWA · IndexedDB · Playwright e2e
db/                PostGIS schema for deployment
docs/              ARCHITECTURE · SCIENTIFIC_INTEGRITY · DEMO_SCRIPT · JURY_QA · WHAT_WE_COMBINED
```

---

## Honesty by design

- The system says *prospectivity*, never "reserve". It is not usable for UNFC / JORC / CRIRSCO reporting, which needs a Competent Person. Tonnage ranges are labelled conceptual exploration targets.
- **No `distance to known deposit` or coordinates in Module 1**, so the model cannot learn proximity instead of geology. This is asserted in code and tested.
- **Spatial CV, never random CV**, for Module 1. The random figure is shown only to expose its optimism.
- **The weak real-data result is reported**, next to a disturbance baseline that beats it, on the Integrity page and in the API.
- **`not_available` provenance** records what could not be obtained instead of faking it.
- Every synthetic row carries `is_synthetic = TRUE`, and a banner that cannot be dismissed says so.
- If SHAP evidence is weak, the forecast says **"Insufficient evidence to determine the cause"** rather than inventing one.
- Every corrective action carries a scenario disclaimer and needs a human decision, recorded in the audit log.
- A live scan of `frontend/src` fails the integrity check if wording such as "confirmed reserve", "proven tonnage" or "will happen" appears.

---

## Limitations

1. **No real production or drilling data.** MOIL's telemetry is not public. Forecast, action and demo-fusion results come from synthetic data and overstate what real data will give. There are no real-data validation numbers for Modules 2 or 3.
2. **The real-data surface proxy has not shown skill** (AUC 0.56, CI 0.31–0.77, below a bare-ground baseline of 0.64). Only 10 positives, all active mines, with ± 2–3 km coordinates.
3. **Missing layers:** Sentinel-1 SAR, lineaments and mapped lithology are absent from the real-data track (accounts/logins required). The demo fusion includes them only as simulated features.
4. **Optical indices degrade under monsoon cloud.** The real composites use dry-season scenes only.
5. **Kriging is no better than a regional mean beyond ~14 km** of a borehole (shown on the map as uncertainty).
6. **Tonnage ranges rest on assumed geometry**, not measurements, and are not resources.
7. **Action costs are indicative.** Rail/road logistics are not modelled. DGMS compliance is a stated assumption, not an automated check.
8. **Sign-in is local** (username/password with signed tokens); MOIL SSO/LDAP is not integrated.
9. **NASA POWER weather is stored beside, not inside, the model features** until real production logs exist.
10. **Not production-ready.** What exists: role-based sign-in, a scheduled pipeline, CSV onboarding and a tested deployment path. What is still needed: an MoU for MOIL's production and drilling records, re-validation on those records, and SSO.

---

## Data sources and attribution

**Used for real in the real-data track**
- Sentinel-2 L2A: contains modified Copernicus Sentinel data 2024–2025 (ESA), via the AWS Open Data `sentinel-cogs` archive.
- Copernicus DEM GLO-30: produced using Copernicus WorldDEM-30 © DLR e.V. 2010–2014 and © Airbus Defence and Space GmbH 2014–2018, provided under COPERNICUS by the European Union and ESA; all rights reserved.
- ESA WorldCover 10 m 2021 v200 © ESA WorldCover project, CC BY 4.0.
- MOIL Limited public mine list (moil.nic.in) for operating-mine locations.
- NASA POWER for daily rainfall, soil wetness and surface temperature.

**Simulated in the demo with the same schema** (see `/api/integrity`): GSI Bhukosh geology, IBM National Mineral Inventory / Indian Minerals Yearbook, Sentinel-1, ISRO Bhuvan/VEDAS (CartoDEM), IMD, MODIS, and MOIL production and borehole records. Swapping in real extracts is a data-loading task, not a model change.

---

## Further documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · design choices and API summary
- [`docs/SCIENTIFIC_INTEGRITY.md`](docs/SCIENTIFIC_INTEGRITY.md) · every guardrail and where it is enforced
- [`docs/JURY_QA.md`](docs/JURY_QA.md) · prepared answers to likely questions
- [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) · the 3-minute guided demo
- [`docs/WHAT_WE_COMBINED.md`](docs/WHAT_WE_COMBINED.md) · what was kept, replaced and fixed from earlier codebases
