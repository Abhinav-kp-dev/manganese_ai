# Scientific integrity

Every item below is enforced in code and most are re-checked live on the **Data & Integrity** page (`GET /api/integrity`) and in `backend/tests/`.

| Plan §9 requirement | Where it is enforced |
|---|---|
| Spatially-blocked CV for Module 1 | `ml/prospectivity.py::train_surface_model` (30 km blocks); random k-fold is reported beside it only to show the optimism. |
| No target leakage | `FORBIDDEN_FEATURES` (distance-to-deposit, coordinates) asserted absent; `tests/test_science.py::test_no_leakage_features`. |
| Quantile monotonicity | `_predict_quantiles` sorts and clips at 0; live check on all 30 forecasts; unit test. |
| Baseline benchmarking | `train_module2` computes persistence and seasonal-naive on the same window; UI never shows model error alone. |
| Epistemic tagging | `app/epistemic.py` tags; `tags` map on API responses; `<Tag>` badge in UI. |
| Synthetic data labelled | `is_synthetic` on every row; `meta.data_mode` on responses; banner that can't be dismissed; training policy drops synthetic rows once ≥ 240 real rows exist. |
| No "confirmed reserve" / "proven tonnage" / "will happen" | Live scan of `frontend/src` in `/api/integrity`. |
| Scenario disclaimer on every action | `ml/optimizer.py::DISCLAIMER`; API test. |
| No look-ahead in Module 2 | Fleet health read at month t-h+1 (`ml/features.py`); rainfall outlook is climatology-anchored with realistic skill (`ml/synthetic.py::outlook`). `tests/test_leakage.py` scrambles every later value and requires identical features, and fails on the earlier code. |
| Surface model learns signal, not location | `tests/test_module1.py`: scrambling surface features across cells must drop spatial-CV AUC below 0.65; the unscrambled control must exceed 0.8. |
| Real-data check reported as is | `ml/realdata.py` + `/api/reserves/real`; `real_data` item and real-vs-synthetic table in `/api/integrity`; wording follows the confidence interval. |
| Tonnage never presented as a resource | `ml/tonnage.py::LABEL` on every range; API test checks it. |

## Additional safeguards

- **Kriging honesty.** Kriging is validated at two scales. Interpolation shows skill; extrapolation beyond the variogram range shows none. The fused map carries that as uncertainty.
- **Cover masking.** Under alluvium or Deccan Trap basalt the surface proxy's weight is cut to 10–15%, and uncertainty rises instead of the map faking confidence.
- **Positive-unlabelled framing.** Pseudo-absences are background drawn ≥ 3 km from known occurrences, not "proven barren" ground.
- **No hallucinated causes.** If the largest risk driver is under 15% of the P10–P90 width, the forecast says "Insufficient evidence to determine the cause."
- **Capacity guardrail.** Targets above 1.5× historical max or 1.25× rated capacity are flagged; targets above P90 are flagged too.
- **Simulation-only truth check.** Only because the synthetic world has a known grade field can we compare the fused map to truth. The UI labels this as impossible with real data.
- **Mining-disturbance check.** Every public, point-accurate Mn location in the study area is an operating mine. The real-data check scores cells by ESA WorldCover bare + built-up fraction alone; if that rivals the model, the model is detecting mines rather than ore. Today it does (0.64 vs 0.56).
- **Physical plausibility of real features.** `ml/remote_sensing.py::check_physical` refuses to write indices outside physical ranges or with < 95% coverage, and a test checks Sentinel-2 water against ESA WorldCover water as an independent geolocation check.

## Known limitations

1. MOIL's internal telemetry is not public; demo production and borehole data are synthetic. Real data paths are built and tested: CSV upload, the inbox drop-folder job, and the NASA POWER weather connector (which needs internet access to power.larc.nasa.gov).
2. Few positive occurrences → wide AUC confidence interval. On real data (10 operating-mine locations) the surface proxy has not yet shown skill (spatial-CV AUC 0.56, 95% CI 0.31–0.77).
3. Optical indices degrade under monsoon cloud; SAR mitigates but does not eliminate this.
4. Action costs are indicative; rail/road logistics are not yet modelled.
5. Accuracy on synthetic data overstates what real data will give. The only real-data number so far is the Module 1 surface-proxy check above; Module 2 needs MOIL production logs.
7. Sentinel-1 SAR, lineaments and mapped lithology are simulated only (no openly readable source for this area).
6. Sign-in is local (username/password with signed tokens); MOIL directory (LDAP/SSO) integration is a deployment step.
