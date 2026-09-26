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

## Additional safeguards

- **Kriging honesty.** Kriging is validated at two scales. Interpolation shows skill; extrapolation beyond the variogram range shows none. The fused map carries that as uncertainty.
- **Cover masking.** Under alluvium or Deccan Trap basalt the surface proxy's weight is cut to 10–15%, and uncertainty rises instead of the map faking confidence.
- **Positive-unlabelled framing.** Pseudo-absences are background drawn ≥ 3 km from known occurrences, not "proven barren" ground.
- **No hallucinated causes.** If the largest risk driver is under 15% of the P10–P90 width, the forecast says "Insufficient evidence to determine the cause."
- **Capacity guardrail.** Targets above 1.5× historical max or 1.25× rated capacity are flagged; targets above P90 are flagged too.
- **Simulation-only truth check.** Only because the synthetic world has a known grade field can we compare the fused map to truth. The UI labels this as impossible with real data.

## Known limitations

1. MOIL's internal telemetry is not public; demo data is synthetic (the upload path to real data is built and tested).
2. Few positive occurrences → wide AUC confidence interval.
3. Optical indices degrade under monsoon cloud; SAR mitigates but does not eliminate this.
4. Action costs are indicative; rail/road logistics are not yet modelled.
5. Accuracy on synthetic data overstates what real data will give.
