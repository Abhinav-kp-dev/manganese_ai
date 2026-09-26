"""Epistemic labelling: every number the dashboard shows says what kind of knowledge it is."""

OBSERVED = "OBSERVED"            # logged historical data
FORECAST = "FORECAST"            # external weather/satellite projection
MODEL_INFERENCE = "MODEL_INFERENCE"  # derived by an ML / geostatistical model
SCENARIO = "SCENARIO"            # hypothetical what-if, not a prediction

DISCLAIMERS = {
    "synthetic": "Demo mode: production, borehole and satellite values are simulated (is_synthetic = TRUE). "
                 "Outputs demonstrate the method and are not scientifically validated for MOIL operations.",
    "mixed": "Mixed mode: uploaded real records are combined with simulated records. Outputs are not validated.",
    "prospectivity": "Prospectivity is a drilling-prioritisation aid, not a reserve or resource estimate under UNFC / JORC / CRIRSCO. "
                     "Statutory reporting requires drilling, assay and sign-off by a Competent Person.",
    "action": "Scenario estimate — not a guaranteed operational instruction.",
    "satellite": "Satellites see the surface only. They cannot detect sub-surface ore; they supply surface proxies and weather drivers.",
}

FORECAST_TAGS = {
    "p10": MODEL_INFERENCE, "p50": MODEL_INFERENCE, "p90": MODEL_INFERENCE,
    "achievement_probability": MODEL_INFERENCE, "deficit_p50": MODEL_INFERENCE, "drivers": MODEL_INFERENCE,
    "target": OBSERVED, "rated_monthly_capacity": OBSERVED,
    "inputs.rainfall_forecast_mm": FORECAST, "inputs.rainy_days_forecast": FORECAST, "inputs.lst_forecast_c": FORECAST,
    "inputs.soil_moisture_lag": OBSERVED, "inputs.ndvi_lag": OBSERVED, "inputs.availability_lag": OBSERVED,
}


def meta(data_mode: str, model_version: str | None = None, extra: list[str] | None = None) -> dict:
    notes = [DISCLAIMERS["synthetic"] if data_mode == "SYNTHETIC" else DISCLAIMERS["mixed"] if data_mode == "MIXED" else None]
    notes += [DISCLAIMERS[e] for e in (extra or [])]
    return {"data_mode": data_mode, "is_synthetic": data_mode != "REAL", "model_version": model_version,
            "disclaimers": [n for n in notes if n]}
