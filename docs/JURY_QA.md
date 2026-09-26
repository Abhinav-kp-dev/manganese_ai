# Jury Q&A

**"How can satellites detect ore underground?"**
They can't. Sentinel-2/1 feed a surface-proxy layer (ferric-iron and clay ratios, SAR roughness) that ranks where to drill, and the IMD/MODIS variables drive the production forecast. Sub-surface estimates come from kriged boreholes.

**"What's your accuracy?"**
On the held-out year of demo data, next-month P50 MAE is 321 t, against 1,050 t for persistence and 867 t for seasonal-naive, with P10–P90 coverage of 83%. It is synthetic data, so it is optimistic, and it is reproducible live on the Integrity page. The reserve surface model has spatial-CV AUC 0.91 (CI 0.87–0.95) from 61 occurrences, and we show the random-CV figure (0.93) to explain why we don't use it.

**"Is this usable for reserve reporting?"**
No. It is a drilling-prioritisation tool. UNFC / JORC / CRIRSCO reporting needs drilling, assay and a Competent Person's sign-off.

**"Who uses it day to day?"**
The mine planning engineer at Balaghat or Gumgaon who today reconciles drilling logs, production records and weather reports by hand, and the Mine Manager who approves actions (every decision is logged).

**"Why hasn't this been solved?"**
Geology (GSI), production (MOIL) and weather (IMD) sit with three agencies with no shared schema, and underground sites have poor connectivity. It is a data-fragmentation and infrastructure problem, not a lack of AI. Hence the canonical schema, CSV onboarding and offline PWA.

**"Aren't the recommendations just AI text?"**
No. They come from a linear programme: minimise cost subject to closing each deficit, capped by lever capacity and sister-mine spare capacity. Each lever exists only if the matching SHAP driver is present, and each carries assumptions and a disclaimer.

**"Why quantiles instead of one number?"**
A planner needs the chance of meeting target, not a point. P(production ≥ target) comes from the calibrated quantiles, and a realigned target at 60% achievability is offered as a scenario.

**"What if the model can't explain a shortfall?"**
It says "Insufficient evidence to determine the cause" rather than inventing a breakdown.

**"Is this production-ready?"**
The deployment path is built and tested, but the system has not been validated on real data. What exists: role-based sign-in (Mine Managers approve only for their own cluster), a scheduled pipeline (built-in scheduler or cron) that pulls real NASA POWER weather per mine and loads MOIL CSV exports from a drop folder, and a logged record of every pipeline run. What is still needed is an MoU for MOIL's production and drilling records, re-validation on those records, and SSO integration.
