# What was combined, kept, and fixed

Inputs: the team's implementation plan and pitch notes, **manish8957/AI-Powered-Manganese-Intelligence-Exploration-Platform** (MERN + FastAPI ML) and **kartike687/Vyom-Dhatu** (FastAPI + single-page command centre).

| Idea | Source | What we did |
|---|---|---|
| Three-module split, epistemic tags, quantile forecasting, LP actions, offline PWA, Hindi/Marathi | Implementation plan | Implemented as specified. |
| React + Vite + Tailwind + Leaflet + Recharts multi-page UI, mine registry, reports page, CSV upload, data-sources page | Manganese Intelligence Platform | Kept the stack and pages; upload now validates against the canonical schema and feeds retraining as real data. |
| Judge / guided demo mode, what-if simulation, audit trail of approvals, drill targets, 3-D block-model framing | Vyom-Dhatu | Kept the guided demo, what-if and audit trail; approvals now work offline. |
| Vyom's root-cause percentages and recovery plan were hard-coded constants | — | Replaced by exact TreeSHAP and a real LP. |
| Vyom trained prospectivity on "proximity to known deposits" with a random split | — | Removed (leakage) and switched to spatial-block CV. |
| MIP classified "potential" from a synthetic formula on assay chemistry with random-forest point outputs | — | Replaced by kriging + surface proxy with uncertainty. |
| Two separate backends (Node + Python) in MIP | — | One FastAPI service serving API and UI; SQLite by default, PostGIS optional. |
