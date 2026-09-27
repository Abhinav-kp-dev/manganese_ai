# Manganese Horizon

**AI decision support for MOIL: where to drill next, whether next month's target will be met, and what to do about it.**

Smart India Hackathon 2026 · Problem Statement **SIH26009** — *Using AI/ML and Space Technology to Identify Manganese Reserves and Overcome Production Shortfalls* · Ministry of Steel (MOIL Limited) · Theme: Space Technology · Software

---

## The idea in one paragraph

SIH26009 is really **two problems**. *Where is the ore?* is a geology problem: satellites cannot see ore underground, so borehole data does the sub-surface work and satellite imagery only narrows where to drill next. *Will we hit production?* is an equipment, weather and blasting problem, and this is where the four satellite variables in the statement (rainfall, soil moisture, NDVI, land-surface temperature) earn their place. Manganese Horizon answers both, then turns a forecast shortfall into an optimised, auditable action plan. Every number it shows says whether it is **observed**, a **forecast**, a **model inference** or a **scenario**.

| Module | Question | Method |
|---|---|---|
| 1 · Reserve confidence | Where should we drill next? | Ordinary kriging of borehole Mn grade (with variance), fused with an XGBoost surface-proxy model on Sentinel-2 band ratios, Sentinel-1 SAR, DEM, lineaments and mapped lithology. Validated with spatial-block CV. Drill targets are ranked by value of information. |
| 2 · Shortfall forecast | Will we miss target, and why? | Direct multi-horizon (1–3 months) quantile XGBoost (P10/P50/P90) with split-conformal calibration, physical monotone constraints and exact TreeSHAP drivers. Always benchmarked against persistence and seasonal-naive baselines. |
| 3 · Corrective actions | What should we do? | One linear programme (HiGHS) across all deficit mines. Levers are tied to the SHAP drivers (blasting reschedule, loader redeployment, overhaul compression, wet-weather plan, extra shifts), plus sister-mine reallocation limited by each mine's real spare capacity. |

The dashboard is an **offline-first PWA** in **English / हिन्दी / मराठी**. It has a live scientific-integrity checklist, a human-approval audit trail (decisions made offline queue and sync later), what-if scenarios, CSV onboarding of real MOIL logs, a printable executive brief and a guided 10-step judge demo.

## Quick start

Requires Python 3.11+ and Node 18+.

```bash
make install                         # pip + npm
make run                             # builds the dashboard, serves API + UI on http://localhost:8000 (API docs at /docs)
# or hot-reload:  make api  (port 8000)  +  make web  (port 5173, proxies /api)

make test                            # 25 backend tests incl. scientific guardrails and role checks
```

On first start the server generates the (deterministic) demo dataset, seeds the database and trains every model. This takes about 30 s and is cached after that. `/api/health` reports `training` until it is ready.

The default database is SQLite (no setup, works on a site laptop). For PostgreSQL/PostGIS, run `db/postgis_schema.sql` on the server and set `DATABASE_URL=postgresql+psycopg2://<user>:<password>@<host>:5432/manganese_horizon`.

## Sign-in and roles

Every data endpoint needs a signed-in user. Pick a role on the sign-in screen (demo password `demo123`):

| Role | Demo account(s) | Can |
|---|---|---|
| Administrator | `admin` | everything, incl. running the data pipeline |
| Mine Manager | `manager.balaghat`, `manager.bhandara`, `manager.nagpur` | approve / reject / defer actions **for mines in their own cluster only** |
| Mine Planning Engineer | `planner` | defer actions, upload MOIL data |
| Exploration Geologist | `geologist` | upload data, view everything |
| Viewer | `viewer` | read-only |

Decisions are recorded under the signed-in account and role (no free-text names). For a real deployment set `MH_SECRET`, change `MH_DEMO_PASSWORD` or disable demo accounts with `MH_DEMO_ACCOUNTS=0`.

## Data pipeline (real data)

| Job | What it does |
|---|---|
| `nasa_power` | Pulls **real** daily rainfall, soil wetness and surface temperature for each mine from NASA POWER (free, no API key) and stores monthly values in `external_weather` (`is_synthetic = FALSE`). |
| `inbox` | Validates and loads MOIL CSV exports dropped into `backend/var/inbox/`; bad files go to `rejected/` with an error report. |
| `retrain` | Retrains the models when the data changed. |

It runs inside the server every `MH_PIPELINE_INTERVAL_MIN` minutes (default 360; `0` turns it off), can be triggered by an Administrator from the **Data & Integrity** page, or from cron:

```bash
0 */6 * * *  cd /path/to/manganese_ai/backend && python -m app.pipeline all
```

Every run is logged in `pipeline_runs` and shown on the dashboard. The NASA POWER series is kept next to, not inside, the model features until real MOIL production logs arrive, because mixing real weather with simulated production would corrupt training.

## Repository layout

```
backend/
  ml/              reference.py (MOIL mines), synthetic.py (generator), geostats.py (kriging),
                   prospectivity.py (Module 1), features.py + forecasting.py (Module 2),
                   optimizer.py (Module 3), scenarios.py
  app/             FastAPI app, SQLAlchemy schema (plan §8), state/training cache, epistemic tags
  tests/           science guardrails + API tests
frontend/          React 18 · Vite · Tailwind · Leaflet · Recharts · Workbox PWA · IndexedDB
db/                PostGIS schema for deployment
docs/              architecture, scientific integrity, demo script, jury Q&A, what we combined
```

## What the numbers look like (demo data)

All values below are reproduced live by the running system (`/integrity`, `/forecast`, `/reserves`). They come from **synthetic** data, so they are optimistic relative to real MOIL records and must be re-measured after onboarding real data.

- **Forecast, held-out Sep 2025–Aug 2026 (n = 120 per horizon):** P50 MAE 418 t (+1 month), 470 t (+2) and 449 t (+3), against 1,050 / 1,157 / 1,320 t for persistence and 867 t for seasonal-naive. P10–P90 coverage is 85% / 79% / 78% against 80% nominal.
  These figures went *up* from 321 t after two look-ahead leaks were removed: fleet health is now read at issue time for +2/+3 month forecasts, and the simulated rainfall outlook has realistic skill (anomaly correlation ≈ 0.55 instead of near-perfect foresight). `tests/test_leakage.py` keeps both fixed.
- **Surface-proxy model:** spatial-block CV AUC 0.91 (95% CI 0.87–0.95) from 61 known occurrences. Random k-fold gives 0.93, which shows why random CV is optimistic.
- **Kriging:** 3.3 %Mn MAE when interpolating inside drilled areas (a mean-only baseline gives 7.8). Beyond the ~14 km variogram range it is no better than the mean. The map shows this as uncertainty, and it is exactly the gap the satellite proxy covers.

## Honesty by design

- The system says *prospectivity*, never "reserve". It is not usable for UNFC / JORC / CRIRSCO reporting, which needs a Competent Person.
- No `distance to known deposit` or coordinates in Module 1, so the model cannot learn proximity instead of geology.
- Every synthetic row carries `is_synthetic = TRUE`, and a banner that cannot be dismissed says so. Once ≥ 240 real production rows exist, training drops synthetic rows.
- If SHAP evidence is weak, the forecast says **"Insufficient evidence to determine the cause"** rather than inventing one.
- Every corrective action carries *"Scenario estimate — not a guaranteed operational instruction"* and needs a human decision.

See [`docs/SCIENTIFIC_INTEGRITY.md`](docs/SCIENTIFIC_INTEGRITY.md) and [`docs/JURY_QA.md`](docs/JURY_QA.md).

## Data sources

GSI Bhukosh · IBM National Mineral Inventory / Indian Minerals Yearbook · ESA Copernicus Sentinel-1/2 · ISRO Bhuvan/VEDAS (CartoDEM) · IMD / NASA POWER / MODIS · MOIL public filings. The demo simulates each of these with the same schema (see `/integrity`). Swapping in real extracts is a data-loading task, not a model change.
