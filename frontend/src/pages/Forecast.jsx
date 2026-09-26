import { useSearchParams } from "react-router-dom";
import { fmt, monthLabel, pct, useApi } from "../api.js";
import { useI18n } from "../i18n.jsx";
import { FanChart, Gauge, ShapWaterfall } from "../components/charts.jsx";
import { Card, Note, PageHeader, RiskBadge, StaleNote, Tag, useLoaded } from "../components/ui.jsx";

const INPUTS = [
  ["rainfall_forecast_mm", "Rainfall outlook (mm)", "FORECAST"],
  ["rainy_days_forecast", "Rainy days outlook", "FORECAST"],
  ["lst_forecast_c", "Land surface temp. (°C)", "FORECAST"],
  ["soil_moisture_lag", "Soil moisture (last obs.)", "OBSERVED"],
  ["ndvi_lag", "NDVI (last obs.)", "OBSERVED"],
  ["fleet_health_index", "Fleet health index", "OBSERVED"],
  ["availability_lag", "Equipment availability % (last)", "OBSERVED"],
  ["planned_maintenance_hours", "Planned maintenance (h)", "OBSERVED"],
  ["blast_window_days", "Blasting window (days)", "OBSERVED"],
  ["planned_operating_days", "Planned operating days", "OBSERVED"],
  ["stockpile_days_lag", "Opening stockpile (days)", "OBSERVED"],
];

export default function Forecast() {
  const { t } = useI18n();
  const [sp, setSp] = useSearchParams();
  const mine = sp.get("mine") || "BLG-01";
  const horizon = +(sp.get("h") || 1);
  const mines = useApi("/api/mines");
  const q = useApi(`/api/forecast/mine/${mine}?horizon=${horizon}`);
  const metrics = useApi("/api/forecast/metrics");
  const gate = useLoaded(q);
  const set = (k, v) => { const n = new URLSearchParams(sp); n.set(k, v); setSp(n); };

  const header = (
    <PageHeader title={t("nav_forecast")} subtitle="Module 2 · Direct multi-horizon quantile XGBoost (P10/P50/P90), conformally calibrated, explained with exact TreeSHAP and always benchmarked against naive baselines."
      right={
        <div className="flex gap-2">
          <select className="input" value={mine} onChange={(e) => set("mine", e.target.value)}>
            {(mines.data?.mines || [{ mine_id: mine, mine_name: mine }]).map((m) => <option key={m.mine_id} value={m.mine_id}>{m.mine_name}</option>)}
          </select>
          <select className="input" value={horizon} onChange={(e) => set("h", e.target.value)}>
            {(q.data?.forecast || []).map((f) => <option key={f.horizon} value={f.horizon}>{monthLabel(f.month)} (+{f.horizon})</option>)}
          </select>
        </div>
      } />
  );
  if (gate) return <div>{header}{gate}</div>;
  const d = q.data;
  const s = d.selected;
  const a = s.attribution;

  return (
    <div className="space-y-5">
      {header}
      <StaleNote stale={q.stale} />
      <div className="grid gap-4 xl:grid-cols-[320px_1fr]">
        <Card title={`${d.mine.mine_name} · ${monthLabel(s.month)}`} tag="MODEL_INFERENCE">
          <div className="flex flex-col items-center">
            <Gauge value={s.achievement_probability} size={220} />
            <div className="mt-1"><RiskBadge level={s.risk_level} /></div>
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
            <Row k="P10" v={`${fmt(s.p10)} t`} /><Row k="P50" v={`${fmt(s.p50)} t`} /><Row k="P90" v={`${fmt(s.p90)} t`} />
            <Row k={t("target")} v={`${fmt(s.target)} t`} tag="OBSERVED" />
            <Row k={t("deficit")} v={`${fmt(s.deficit_p50)} t`} />
            <Row k="Rated capacity" v={`${fmt(s.rated_monthly_capacity)} t`} />
          </dl>
          {s.guardrail.potentially_unrealistic && <div className="mt-3"><Note tone="warn"><b>Target potentially unrealistic.</b> {s.guardrail.flags.join(" ")}</Note></div>}
          {s.target_above_p90 && <div className="mt-3"><Note tone="warn">Target is above even the optimistic P90 case.</Note></div>}
          <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-200">
            <div className="flex items-center gap-2"><Tag kind="SCENARIO" /> Realigned target</div>
            <div className="num mt-1 text-base">{fmt(d.realigned_target_60pct)} t</div>
            <div className="text-amber-200/70">The level with a 60% chance of being met under this forecast.</div>
          </div>
        </Card>
        <Card id="fan-chart" title="Production — observed history, backtest and 3-month forecast" tag="MODEL_INFERENCE">
          <FanChart history={d.history} backtest={d.backtest} forecast={d.forecast} />
          <div className="mt-2 flex flex-wrap gap-4 text-[11px] text-ink-400">
            <span><span className="mr-1 inline-block h-0.5 w-4 bg-ink-100 align-middle" />Actual <Tag kind="OBSERVED" /></span>
            <span><span className="mr-1 inline-block h-0.5 w-4 border-t border-dashed border-amber-400 align-middle" />Target</span>
            <span><span className="mr-1 inline-block h-2 w-4 bg-mn-500/20 align-middle" />Backtest P10–P90 (held-out, h=1)</span>
            <span><span className="mr-1 inline-block h-2 w-4 bg-mn-500/50 align-middle" />Forecast P10–P90</span>
          </div>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <Card id="shap" title={`Why — TreeSHAP drivers of the P50 (${monthLabel(s.month)})`} tag="MODEL_INFERENCE">
          <ShapWaterfall base={s.shap_base_tonnes} drivers={s.drivers} p50={s.p50} target={s.target} />
          <p className="mt-1 text-[11px] text-ink-400">Contributions in tonnes relative to the model's average month. Drivers are grouped features. Driver signal vs. forecast uncertainty: <b>{a.attribution_confidence >= 0.5 ? "strong" : a.attribution_confidence >= 0.15 ? "moderate" : "weak"}</b>.</p>
        </Card>
        <div className="space-y-4">
          <Card title={t("risk_drivers")} tag="MODEL_INFERENCE">
            {a.insufficient_evidence && <Note tone="warn">{a.message} The deficit is within the model's uncertainty band; no single driver explains it.</Note>}
            {a.risk_drivers.length === 0 && !a.insufficient_evidence && <p className="text-sm text-ink-400">No material risk drivers.</p>}
            <ul className="space-y-1.5 text-sm">{a.risk_drivers.map((r) => <li key={r.driver} className="flex justify-between"><span>{r.driver}</span><span className="num text-rose-300">{fmt(r.contribution_tonnes)} t</span></li>)}</ul>
          </Card>
          <Card title={t("positive_drivers")} tag="MODEL_INFERENCE">
            {a.positive_drivers.length === 0 && <p className="text-sm text-ink-400">No material positive drivers this month.</p>}
            <ul className="space-y-1.5 text-sm">{a.positive_drivers.map((r) => <li key={r.driver} className="flex justify-between"><span>{r.driver}</span><span className="num text-emerald-300">+{fmt(r.contribution_tonnes)} t</span></li>)}</ul>
          </Card>
          <Card title="Inputs known before the month starts">
            <table className="data text-xs"><tbody>
              {INPUTS.map(([k, l, tag]) => <tr key={k}><td>{l}</td><td><Tag kind={tag} /></td><td className="num text-right">{fmt(s.inputs[k], k.includes("index") || k.includes("ndvi") || k.includes("soil") ? 2 : 0)}</td></tr>)}
            </tbody></table>
            <p className="mt-2 text-[10px] text-ink-400">Realised downtime and rainfall of the forecast month are never used as inputs (no look-ahead).</p>
          </Card>
        </div>
      </div>

      {metrics.data && <Baselines metrics={metrics.data.metrics} />}
    </div>
  );
}

const Row = ({ k, v, tag }) => <div className="rounded-lg bg-ink-800 px-2 py-1.5"><dt className="flex items-center gap-1 text-[10px] uppercase text-ink-400">{k} {tag && <Tag kind={tag} />}</dt><dd className="num">{v}</dd></div>;

function Baselines({ metrics }) {
  const hs = Object.values(metrics);
  return (
    <Card id="baselines" title="Accuracy on the held-out window — always against baselines" tag="MODEL_INFERENCE">
      <div className="overflow-x-auto">
        <table className="data">
          <thead><tr><th>Horizon</th><th>Test window</th><th className="text-right">Model P50 MAE</th><th className="text-right">Persistence MAE</th><th className="text-right">Seasonal-naive MAE</th><th className="text-right">Model MAPE</th><th className="text-right">P10–P90 coverage</th><th className="text-right">Shortfall hit rate</th><th className="text-right">False alarms</th><th className="text-right">Brier</th></tr></thead>
          <tbody>
            {hs.map((m) => (
              <tr key={m.horizon_months}>
                <td>+{m.horizon_months} month</td><td className="text-xs">{m.test_window} · n={m.n_test}</td>
                <td className="num text-right text-mn-300">{fmt(m.model_p50.mae_tonnes)} t</td>
                <td className="num text-right">{fmt(m.persistence_baseline.mae_tonnes)} t</td>
                <td className="num text-right">{fmt(m.seasonal_naive_baseline.mae_tonnes)} t</td>
                <td className="num text-right">{m.model_p50.mape_pct.toFixed(1)}%</td>
                <td className="num text-right">{pct(m.p10_p90_coverage)} <span className="text-ink-400">/ 80%</span></td>
                <td className="num text-right">{m.shortfall_detection.hit_rate == null ? "—" : pct(m.shortfall_detection.hit_rate)}</td>
                <td className="num text-right">{m.shortfall_detection.false_alarm_rate == null ? "—" : pct(m.shortfall_detection.false_alarm_rate)}</td>
                <td className="num text-right">{m.shortfall_detection.brier_score.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3"><Note tone="warn">These numbers are measured on <b>synthetic</b> logs and will be optimistic relative to real MOIL data. They are reproducible live from this system and must be re-measured after onboarding real records.</Note></div>
    </Card>
  );
}
