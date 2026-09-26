import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, fmt, monthLabel, pct, useApi } from "../api.js";
import { useI18n } from "../i18n.jsx";
import { Card, Note, PageHeader, PriorityBadge, RiskBadge, Stat, Tag } from "../components/ui.jsx";

const SLIDERS = [
  ["rainfall_multiplier", "Rainfall vs IMD outlook", 0.3, 2.5, 0.05, (v) => `×${(+v).toFixed(2)}`],
  ["rainy_days_delta", "Extra rainy days", -8, 10, 1, (v) => `${v > 0 ? "+" : ""}${v}`],
  ["fleet_health_delta", "Fleet health change", -0.4, 0.2, 0.01, (v) => `${v > 0 ? "+" : ""}${(+v).toFixed(2)}`],
  ["maintenance_hours_delta", "Extra maintenance / repair hours", -100, 300, 4, (v) => `${v > 0 ? "+" : ""}${v} h`],
  ["blast_window_delta", "Blasting window change (opencast)", -12, 6, 1, (v) => `${v > 0 ? "+" : ""}${v} d`],
  ["operating_days_delta", "Operating days change", -6, 3, 1, (v) => `${v > 0 ? "+" : ""}${v} d`],
];
const DEFAULTS = { rainfall_multiplier: 1, rainy_days_delta: 0, fleet_health_delta: 0, maintenance_hours_delta: 0, blast_window_delta: 0, operating_days_delta: 0 };

export default function Scenarios() {
  const { t } = useI18n();
  const list = useApi("/api/scenarios");
  const mines = useApi("/api/mines");
  const [sid, setSid] = useState("bad_weather");
  const [params, setParams] = useState(DEFAULTS);
  const [mine, setMine] = useState("");
  const [h, setH] = useState(1);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = async (id = sid) => {
    setBusy(true);
    try {
      setRes(await api("/api/scenarios/run", { method: "POST", body: JSON.stringify({ scenario_id: id, horizon: h, mine_id: mine || null, ...(id === "custom" ? params : {}) }) }));
    } finally { setBusy(false); }
  };
  useEffect(() => { if (sid !== "custom") run(sid); }, [sid, h, mine]); // eslint-disable-line

  const chart = res?.rows.map((r) => ({ name: r.mine_name, baseline: r.baseline.p50, scenario: r.scenario.p50, target: r.scenario.target })) || [];

  return (
    <div className="space-y-5">
      <PageHeader title={t("nav_scenarios")} subtitle="Stress-test the plan. Scenario outputs are hypothetical and tagged SCENARIO — they are never presented as forecasts."
        right={<div className="flex gap-2">
          <select className="input" value={mine} onChange={(e) => setMine(e.target.value)}><option value="">All mines</option>{(mines.data?.mines || []).map((m) => <option key={m.mine_id} value={m.mine_id}>{m.mine_name}</option>)}</select>
          <select className="input" value={h} onChange={(e) => setH(+e.target.value)}>{[1, 2, 3].map((x) => <option key={x} value={x}>+{x} month</option>)}</select>
        </div>} />

      <div id="scenario-panel" className="space-y-4">
        <div className="flex flex-wrap gap-2">
          {(list.data?.scenarios || []).filter((s) => s.id !== "baseline").map((s) => (
            <button key={s.id} onClick={() => setSid(s.id)} className={`rounded-lg border px-3 py-2 text-left text-sm ${sid === s.id ? "border-mn-500 bg-mn-500/15" : "border-ink-700 bg-ink-900 hover:bg-ink-800"}`}>
              <div className="font-medium">{s.title}</div><div className="max-w-[240px] text-[11px] text-ink-400">{s.description}</div>
            </button>
          ))}
          <button onClick={() => setSid("custom")} className={`rounded-lg border px-3 py-2 text-left text-sm ${sid === "custom" ? "border-mn-500 bg-mn-500/15" : "border-ink-700 bg-ink-900 hover:bg-ink-800"}`}>
            <div className="font-medium">Custom what-if</div><div className="text-[11px] text-ink-400">Set the drivers yourself</div>
          </button>
        </div>

        {sid === "custom" && (
          <Card title="Custom drivers" tag="SCENARIO" right={<button className="btn-primary" disabled={busy} onClick={() => run("custom")}>{busy ? "Running…" : "Run scenario"}</button>}>
            <div className="grid gap-x-6 gap-y-3 md:grid-cols-3">
              {SLIDERS.map(([k, label, min, max, step, show]) => (
                <label key={k} className="text-sm">
                  <div className="flex justify-between"><span className="text-ink-300">{label}</span><span className="num text-mn-300">{show(params[k])}</span></div>
                  <input type="range" className="w-full" min={min} max={max} step={step} value={params[k]} onChange={(e) => setParams({ ...params, [k]: +e.target.value })} />
                </label>
              ))}
            </div>
            <button className="btn-ghost mt-3 text-xs" onClick={() => setParams(DEFAULTS)}>Reset</button>
          </Card>
        )}

        {res && (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat label="Sum of P50 — current plan" value={`${fmt(res.totals.baseline_p50)} t`} sub={monthLabel(res.month)} tag="MODEL_INFERENCE" />
              <Stat label="Sum of P50 — scenario" value={`${fmt(res.totals.scenario_p50)} t`} sub={`${res.totals.scenario_p50 >= res.totals.baseline_p50 ? "+" : ""}${fmt(res.totals.scenario_p50 - res.totals.baseline_p50)} t`} tag="SCENARIO" />
              <Stat label="Deficit — scenario" value={`${fmt(res.totals.scenario_deficit)} t`} sub={`current plan ${fmt(res.totals.baseline_deficit)} t`} tag="SCENARIO" tone={res.totals.scenario_deficit > res.totals.baseline_deficit ? "#fb923c" : "#34d399"} />
              <Stat label="Covered by LP plan" value={res.plan ? `${fmt(res.plan.summary.total_mitigated)} t` : "—"} sub={res.plan ? `uncovered ${fmt(res.plan.summary.unmitigated)} t` : "Targets realigned instead"} tag="SCENARIO" />
            </div>
            <div className="grid gap-4 xl:grid-cols-2">
              <Card title="Median production by mine: current plan vs scenario" tag="SCENARIO">
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={chart} margin={{ top: 4, right: 8, left: 0, bottom: 40 }}>
                    <CartesianGrid stroke="#222c3f" vertical={false} />
                    <XAxis dataKey="name" angle={-35} textAnchor="end" interval={0} stroke="#8b96ad" fontSize={11} />
                    <YAxis stroke="#8b96ad" fontSize={11} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} width={36} />
                    <Tooltip contentStyle={{ background: "#18202f", border: "1px solid #34405a" }} formatter={(v) => `${fmt(v)} t`} />
                    <Legend verticalAlign="top" height={24} wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="baseline" name="Current plan P50" fill="#475569" isAnimationActive={false} />
                    <Bar dataKey="scenario" name="Scenario P50" fill="#f59e0b" isAnimationActive={false} />
                    <Bar dataKey="target" name={sid === "target_realignment" ? "Realigned target" : "Target"} fill="#8b5cf6" fillOpacity={0.5} isAnimationActive={false} />
                    <ReferenceLine y={0} stroke="#34405a" />
                  </BarChart>
                </ResponsiveContainer>
              </Card>
              <Card title="Per-mine outcome" tag="SCENARIO">
                <div className="max-h-[300px] overflow-auto">
                  <table className="data text-xs">
                    <thead><tr><th>{t("mine")}</th><th>Now</th><th>Scenario</th><th className="text-right">P(target)</th><th>Top risk driver</th></tr></thead>
                    <tbody>{res.rows.map((r) => (
                      <tr key={r.mine_id}><td>{r.mine_name}</td><td><RiskBadge level={r.baseline.risk_level} /></td><td><RiskBadge level={r.scenario.risk_level} /></td>
                        <td className="num text-right">{pct(r.baseline.achievement_probability)} → {pct(r.scenario.achievement_probability)}</td><td>{r.top_risk_driver || "—"}</td></tr>
                    ))}</tbody>
                  </table>
                </div>
              </Card>
            </div>
            {res.plan && Object.keys(res.plan.actions_by_mine).length > 0 && (
              <Card title="Optimised response under this scenario" tag="SCENARIO">
                <div className="grid gap-3 md:grid-cols-2">
                  {Object.values(res.plan.actions_by_mine).map((b) => (
                    <div key={b.mine_id} className="rounded-lg border border-ink-700 p-3">
                      <div className="mb-1 flex items-center justify-between"><b>{b.mine_name}</b><PriorityBadge p={b.priority} /></div>
                      <ul className="space-y-1 text-xs">{b.actions.map((a) => <li key={a.rank} className="flex justify-between gap-2"><span className="text-ink-300">{a.action_title}</span><span className="num shrink-0 text-emerald-300">+{fmt(a.tonnes)} t</span></li>)}</ul>
                      {b.unmitigated > 0 && <div className="mt-1 text-xs text-rose-300">Uncovered: {fmt(b.unmitigated)} t</div>}
                    </div>
                  ))}
                </div>
                <div className="mt-3"><Note>{res.plan.disclaimer}</Note></div>
              </Card>
            )}
            <p className="flex items-center gap-2 text-[11px] text-ink-400"><Tag kind="SCENARIO" /> Hypothetical: changes the plan inputs, re-runs the calibrated models and the LP. Not a prediction of what will occur.</p>
          </>
        )}
      </div>
    </div>
  );
}
