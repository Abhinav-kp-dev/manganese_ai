# Architecture

```
 Public data (GSI, IBM, Sentinel-1/2, Bhuvan DEM, IMD/NASA POWER/MODIS)   MOIL logs (CSV upload / future MoU feed)
                    │  (simulated in demo, same schema)                         │ validated → is_synthetic = FALSE
                    ▼                                                           ▼
           ┌───────────────────────── SQLite / PostgreSQL + PostGIS ─────────────────────────┐
           │ mines · boreholes · occurrences · production_logs · weather_features · mine_plans │
           │ reserve_confidence_grid · forecasts · recommendations · audit_log                 │
           └───────────────┬───────────────────────────────┬──────────────────────────────────┘
                           ▼                               ▼
   Module 1  Reserve confidence              Module 2  Shortfall forecast
   ├ variogram fit + ordinary kriging        ├ ex-ante features (plan, IMD outlook, lags)
   ├ XGBoost surface proxy (PU, 3 km buffer) ├ quantile XGBoost α=.1/.5/.9 × horizons 1-3
   ├ spatial-block CV (30 km)                ├ monotone constraints + conformal (CQR)
   └ fusion → confidence + uncertainty       ├ TreeSHAP → named drivers + evidence guardrail
       └ drill targets by value of info      └ baselines, coverage, Brier, capacity guardrail
         + conceptual tonnage (Monte Carlo)
   Real-data check (ml/realdata.py): same surface model on real Sentinel-2 / Copernicus DEM /
   WorldCover features (backend/data/real) and real Mn locations; spatial CV + disturbance baseline
                                                        │ deficit = target − P50 > 0
                                                        ▼
                                       Module 3  LP corrective-action engine (HiGHS)
                                       levers ← SHAP drivers; sister spare capacity
                                                        │
                           ┌────────────────────────────┴───────────────────────────┐
                           ▼                                                        ▼
            FastAPI  /api/*  (epistemic tags + data-mode meta on every response)   what-if scenarios
                           │
                           ▼
   React PWA — Command Centre · Reserve map · Forecast · Actions · Scenarios · Integrity · Brief
   Workbox NetworkFirst cache + IndexedDB fallback · offline decision queue · EN/HI/MR
```

## Key design choices

| Choice | Why |
|---|---|
| Model utilisation (production ÷ rated monthly capacity), not tonnes | One model generalises across mines from 250 to 1,600 t/day. |
| Direct multi-horizon models instead of recursive roll-forward | Errors don't compound, and each horizon gets its own calibrated interval. |
| Only ex-ante inputs (plans, IMD outlook, last observations) | No look-ahead. Realised rain and downtime of the forecast month are never features, and fleet health is read at issue time (month t-h+1). Enforced by `tests/test_leakage.py`. |
| Real features built offline and committed | The app needs no network or geospatial stack at runtime; `provenance.json` records every scene and tile. |
| Monotone constraints (rain ↓, fleet health ↑, blast window ↑ …) | Keeps what-if scenarios physically coherent. |
| Split-conformal widening of P10–P90 | Coverage is measured, not assumed. |
| TreeSHAP via `xgboost pred_contribs` | Exact, fast, no extra dependency. Grouped into mechanisms planners recognise. |
| LP rather than an LLM for actions | Quantified, auditable and reproducible; every tonne traces to a lever and a constraint. |
| Stockpile drawdown reported separately | It protects dispatches but does not recover production. Counting it would flatter the plan. |
| SQLite default, PostGIS optional | Runs on a site laptop with no infrastructure; scales to PostGIS without code changes. |

## API (selected)

`GET /api/overview` · `/api/mines` · `/api/reserves/{grid,cell,points,validation}` · `/api/forecast/{summary,metrics,mine/{id}}` · `/api/actions` · `POST /api/actions/reallocate` · `GET/POST /api/scenarios[/run]` · `GET/POST /api/audit` · `POST /api/data/upload` · `GET /api/integrity`. Interactive docs at `/docs`.
