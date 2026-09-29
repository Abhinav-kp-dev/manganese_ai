import { Printer } from "lucide-react";
import { fmt, monthLabel, pct, useApi } from "../api.js";
import { useI18n } from "../i18n.jsx";
import { useLoaded } from "../components/ui.jsx";

export default function Report() {
  const { t } = useI18n();
  const o = useApi("/api/overview");
  const a = useApi("/api/actions");
  const m = useApi("/api/forecast/metrics");
  const v = useApi("/api/reserves/validation");
  const meta = useApi("/api/meta");
  const gate = useLoaded(o) || useLoaded(a);
  if (gate) return gate;
  const ov = o.data, p = ov.production, act = a.data;
  const m1 = m.data?.metrics?.["1"];
  const sv = v.data?.surface_validation;

  return (
    <div>
      <div className="no-print mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">{t("nav_report")}</h1>
        <button className="btn-primary" onClick={() => window.print()}><Printer className="h-4 w-4" /> Print / save PDF</button>
      </div>
      <article className="print-page mx-auto max-w-4xl space-y-5 rounded-xl border border-ink-700 bg-ink-900 p-8 text-sm leading-relaxed">
        <header className="border-b border-ink-700 pb-3">
          <div className="text-xs uppercase tracking-wider text-ink-400">MnPulse · SIH26009 · MOIL Limited</div>
          <h2 className="text-2xl font-bold">Production continuity brief — {monthLabel(ov.month)}</h2>
          <div className="text-xs text-ink-400">Generated {new Date().toLocaleString("en-IN")} · model {meta.data?.model_version} · data mode {meta.data?.data_mode}</div>
          {meta.data?.data_mode !== "REAL" && <div className="mt-2 rounded border border-amber-500/50 px-2 py-1 text-xs text-amber-300">DEMO DATA — values are simulated and not validated for MOIL operations.</div>}
        </header>

        <section>
          <h3 className="font-semibold">1. Headline</h3>
          <p>Across MOIL's ten mines the summed median forecast for {monthLabel(ov.month)} is <b>{fmt(p.sum_of_mine_p50)} t</b> against targets of <b>{fmt(p.sum_of_targets)} t</b> [model inference]. {p.mines_at_risk} mine(s) have less than a 50% chance of meeting target. The expected deficit at mines below target is <b>{fmt(p.total_deficit_p50)} t</b>; the optimised action plan covers <b>{fmt(p.mitigated_by_plan)} t</b> [scenario], leaving {fmt(p.unmitigated)} t uncovered.</p>
        </section>

        <section>
          <h3 className="font-semibold">2. Mines at risk</h3>
          <table className="data mt-1"><thead><tr><th>Mine</th><th className="text-right">P10–P90 (t)</th><th className="text-right">Target (t)</th><th className="text-right">P(≥ target)</th><th>Main driver</th></tr></thead>
            <tbody>{ov.mines.filter((f) => f.achievement_probability < 0.7).map((f) => (
              <tr key={f.mine_id}><td>{f.mine_name}</td><td className="num text-right">{fmt(f.p10)}–{fmt(f.p90)}</td><td className="num text-right">{fmt(f.target)}</td><td className="num text-right">{pct(f.achievement_probability)}</td>
                <td>{f.attribution.insufficient_evidence ? f.attribution.message : f.attribution.risk_drivers[0]?.driver || "—"}</td></tr>
            ))}</tbody>
          </table>
        </section>

        <section>
          <h3 className="font-semibold">3. Recommended actions (for approval)</h3>
          <ol className="ml-5 list-decimal space-y-1">
            {Object.values(act.actions_by_mine).flatMap((b) => b.actions.map((x) => ({ ...x, mine: b.mine_name }))).sort((x, y) => y.tonnes - x.tonnes).map((x, i) => (
              <li key={i}><b>{x.action_title}</b> — +{fmt(x.tonnes)} t, ~₹{fmt(x.cost_per_tonne_inr)}/t, priority {x.priority}. <span className="text-ink-400">{x.reason}</span></li>
            ))}
          </ol>
          <p className="mt-2 text-xs italic">{act.disclaimer}</p>
        </section>

        <section>
          <h3 className="font-semibold">4. Exploration — where to drill next</h3>
          <p>{ov.reserves.drill_targets.map((d) => `${d.target_id} (${d.latitude}, ${d.longitude}; ${d.zone})`).join("; ")}. Ranked by value of information (confidence × uncertainty). These are prospectivity targets for drilling, not reserves.</p>
        </section>

        <section>
          <h3 className="font-semibold">5. How far to trust this</h3>
          <ul className="ml-5 list-disc">
            {m1 && <li>Next-month forecast error on a held-out year ({m1.test_window}): P50 MAE {fmt(m1.model_p50.mae_tonnes)} t vs persistence {fmt(m1.persistence_baseline.mae_tonnes)} t and seasonal-naive {fmt(m1.seasonal_naive_baseline.mae_tonnes)} t; P10–P90 coverage {pct(m1.p10_p90_coverage)} (nominal 80%). Measured on synthetic data.</li>}
            {sv && <li>Surface-proxy model spatial-block CV AUC {sv.spatial_cv_auc.toFixed(2)} (95% CI {sv.spatial_cv_auc_ci95[0].toFixed(2)}–{sv.spatial_cv_auc_ci95[1].toFixed(2)}) from {sv.n_positive} known occurrences.</li>}
            <li>Satellites observe the surface only; they inform weather drivers and surface proxies, never sub-surface ore directly.</li>
            <li>Not for statutory reserve reporting (UNFC / JORC / CRIRSCO require Competent Person sign-off).</li>
          </ul>
        </section>
        <footer className="border-t border-ink-700 pt-2 text-[11px] text-ink-400">Tags: [observed] logged data · [forecast] external projection · [model inference] model output · [scenario] what-if.</footer>
      </article>
    </div>
  );
}
