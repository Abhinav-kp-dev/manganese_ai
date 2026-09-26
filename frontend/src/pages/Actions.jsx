import { useEffect, useState } from "react";
import { Check, Clock, X } from "lucide-react";
import { api, fmt, monthLabel, pct, submitDecision, useApi } from "../api.js";
import { useI18n } from "../i18n.jsx";
import { Card, Note, PageHeader, PriorityBadge, Stat, StaleNote, Tag, useLoaded } from "../components/ui.jsx";

export default function Actions() {
  const { t } = useI18n();
  const [h, setH] = useState(1);
  const q = useApi(`/api/actions?horizon=${h}`);
  const mines = useApi("/api/mines");
  const audit = useApi("/api/audit");
  const [who, setWho] = useState(() => { try { return localStorage.getItem("mh-who") || ""; } catch { return ""; } });
  const gate = useLoaded(q);
  if (gate) return gate;
  const r = q.data;
  const blocks = Object.values(r.actions_by_mine).sort((a, b) => ["Critical", "High", "Medium", "Low"].indexOf(a.priority) - ["Critical", "High", "Medium", "Low"].indexOf(b.priority) || b.deficit_p50 - a.deficit_p50);
  const names = Object.fromEntries((mines.data?.mines || []).map((m) => [m.mine_id, m.mine_name]));

  return (
    <div className="space-y-5">
      <PageHeader title={t("nav_actions")} subtitle="Module 3 · A linear programme closes each forecast deficit at least cost, using levers tied to the SHAP drivers and to sister-mine spare capacity. Every output is a scenario estimate that a person approves."
        right={<select className="input" value={h} onChange={(e) => setH(+e.target.value)}>{[1, 2, 3].map((x) => <option key={x} value={x}>+{x} month</option>)}</select>} />
      <StaleNote stale={q.stale} />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label={t("deficit")} value={`${fmt(r.summary.total_deficit)} t`} sub={monthLabel(r.month)} tag="MODEL_INFERENCE" />
        <Stat label={t("mitigated")} value={`${fmt(r.summary.total_mitigated)} t`} tag="SCENARIO" tone="#34d399" />
        <Stat label={t("unmitigated")} value={`${fmt(r.summary.unmitigated)} t`} tag="SCENARIO" tone={r.summary.unmitigated > 0 ? "#f43f5e" : undefined} />
        <Stat label="Indicative plan cost" value={`₹${fmt((r.summary.objective_cost_inr || 0) / 1e5, 1)} lakh`} sub="Indicative Rs/t planning costs" tag="SCENARIO" />
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-ink-300">{t("decided_by")}:</span>
        <input className="input w-64" value={who} placeholder="e.g. Mine Manager, Balaghat" onChange={(e) => { setWho(e.target.value); try { localStorage.setItem("mh-who", e.target.value); } catch { /* ignore */ } }} />
        <span className="text-xs text-ink-400">Recorded with every approve / defer / reject decision.</span>
      </div>
      {r.formulation && <div className="rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 font-mono text-[11px] text-ink-300">LP ({r.solver}): {r.formulation}</div>}

      <div id="action-plan" className="space-y-4">
        {blocks.length === 0 && <Card><p className="text-sm text-ink-300">No mine is forecast below target for this month. No corrective action needed.</p></Card>}
        {blocks.map((b) => (
          <Card key={b.mine_id} title={`${b.mine_name} — deficit ${fmt(b.deficit_p50)} t`} tag="SCENARIO"
            right={<div className="flex items-center gap-2 text-xs text-ink-400">P(target) {pct(b.achievement_probability)} <PriorityBadge p={b.priority} /></div>}>
            <div className="space-y-2">
              {b.actions.map((a) => <ActionRow key={a.rank} a={a} mine={b.mine_id} month={r.month} who={who} onDone={audit.reload} />)}
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              <div className="text-xs text-ink-400">Covered {fmt(b.mitigated)} t · uncovered <span className={b.unmitigated > 0 ? "text-rose-300" : ""}>{fmt(b.unmitigated)} t</span> · cost ₹{fmt(b.cost_inr / 1e5, 2)} lakh</div>
              <div className="text-xs text-ink-400">Supply buffer: {fmt(b.supply_buffer.usable_above_safety_tonnes)} t stockpile above safety stock — {b.supply_buffer.note}</div>
            </div>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Sister-mine spare capacity this month" tag="MODEL_INFERENCE">
          <table className="data"><thead><tr><th>{t("mine")}</th><th className="text-right">Spare after own target</th></tr></thead>
            <tbody>{Object.entries(r.sister_spare_capacity).sort((a, b) => b[1] - a[1]).map(([k, v]) => <tr key={k}><td>{names[k] || k}</td><td className="num text-right">{fmt(v)} t</td></tr>)}</tbody>
          </table>
        </Card>
        <Reallocator mines={mines.data?.mines || []} horizon={h} deficits={blocks} />
      </div>
      <AuditLog q={audit} />
    </div>
  );
}

function ActionRow({ a, mine, month, who, onDone }) {
  const { t } = useI18n();
  const [status, setStatus] = useState(null);
  const decide = async (decision) => {
    if (!who.trim()) return setStatus("name");
    const res = await submitDecision({ recommendation_key: `${month}:${mine}:${a.lever}:${a.rank}`, action_title: a.action_title, decision, decided_by: who.trim(), note: a.reason });
    setStatus(res.synced ? decision : `${decision} (queued offline)`);
    onDone?.();
  };
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-800/40 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2"><PriorityBadge p={a.priority} /><span className="font-medium">{a.action_title}</span></div>
          <div className="mt-1 text-xs text-ink-300">{a.reason}</div>
          <div className="mt-1 text-xs text-ink-400">{a.detail}</div>
        </div>
        <div className="text-right">
          <div className="num text-lg text-emerald-300">+{fmt(a.tonnes)} t</div>
          <div className="text-[11px] text-ink-400">₹{fmt(a.cost_per_tonne_inr)}/t · confidence {pct(a.confidence)}{a.additional_operating_days ? ` · +${a.additional_operating_days} day(s)` : ""}</div>
        </div>
      </div>
      <details className="mt-2 text-xs text-ink-400">
        <summary className="cursor-pointer text-ink-300">Assumptions & supporting features</summary>
        <ul className="ml-4 mt-1 list-disc">{a.assumptions.map((x) => <li key={x}>{x}</li>)}</ul>
        <div className="mt-1 font-mono">{Object.entries(a.supporting_features).map(([k, v]) => `${k}=${typeof v === "number" ? +v.toFixed(2) : v}`).join(" · ")}</div>
      </details>
      <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-ink-700 pt-2">
        <span className="text-[11px] italic text-amber-200/80">{a.disclaimer}</span>
        <div className="ml-auto flex items-center gap-2">
          <button className="btn-ghost py-1 text-xs" onClick={() => decide("APPROVED")}><Check className="h-3 w-3" />{t("approve")}</button>
          <button className="btn-ghost py-1 text-xs" onClick={() => decide("DEFERRED")}><Clock className="h-3 w-3" />{t("defer")}</button>
          <button className="btn-ghost py-1 text-xs" onClick={() => decide("REJECTED")}><X className="h-3 w-3" />{t("reject")}</button>
        </div>
      </div>
      {status && <div className="mt-1 text-right text-xs text-mn-300">{status === "name" ? "Enter your name / role at the top of the page first." : `Recorded: ${status}`}</div>}
    </div>
  );
}

function Reallocator({ mines, horizon, deficits }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [tonnes, setTonnes] = useState(1000);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { if (!from && deficits[0]) setFrom(deficits[0].mine_id); }, [deficits]); // eslint-disable-line
  const run = async () => {
    setErr(null);
    try { setRes(await api("/api/actions/reallocate", { method: "POST", body: JSON.stringify({ from_mine: from, to_mine: to, tonnes: +tonnes, horizon }) })); }
    catch (e) { setErr(e.detail || "Could not compute"); setRes(null); }
  };
  return (
    <Card title="Cross-mine reallocation calculator" tag="SCENARIO">
      <div className="grid grid-cols-3 gap-2 text-sm">
        <label>From (deficit)<select className="input mt-1 w-full" value={from} onChange={(e) => setFrom(e.target.value)}><option value="">—</option>{mines.map((m) => <option key={m.mine_id} value={m.mine_id}>{m.mine_name}</option>)}</select></label>
        <label>To (sister)<select className="input mt-1 w-full" value={to} onChange={(e) => setTo(e.target.value)}><option value="">—</option>{mines.map((m) => <option key={m.mine_id} value={m.mine_id}>{m.mine_name}</option>)}</select></label>
        <label>Tonnes<input className="input mt-1 w-full" type="number" min="1" value={tonnes} onChange={(e) => setTonnes(e.target.value)} /></label>
      </div>
      <button className="btn-primary mt-3" disabled={!from || !to || from === to} onClick={run}>Check feasibility</button>
      {err && <p className="mt-2 text-sm text-rose-300">{err}</p>}
      {res && (
        <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
          <div className={`col-span-2 rounded-lg px-2 py-1.5 ${res.feasible ? "bg-emerald-500/10 text-emerald-300" : "bg-amber-500/10 text-amber-300"}`}>{res.feasible ? "Feasible within spare capacity" : `Only ${fmt(res.allocatable_tonnes)} t can be absorbed`}</div>
          <div>Spare capacity: <span className="num">{fmt(res.spare_capacity_tonnes)} t</span></div>
          <div>Extra operating days: <span className="num">{res.additional_operating_days}</span></div>
          <div>Road distance: <span className="num">{fmt(res.road_km)} km</span>{res.same_cluster ? "" : " (cross-cluster)"}</div>
          <div>Remaining deficit at source: <span className="num">{fmt(res.remaining_deficit_at_source)} t</span></div>
          <p className="col-span-2 text-[11px] italic text-amber-200/80">{res.disclaimer}</p>
        </div>
      )}
    </Card>
  );
}

function AuditLog({ q }) {
  const rows = q.data?.entries || [];
  return (
    <Card title="Decision audit trail" tag="OBSERVED">
      {rows.length === 0 ? <p className="text-sm text-ink-400">No decisions recorded yet. Decisions made offline are queued on this device and synced automatically.</p> : (
        <div className="max-h-72 overflow-auto">
          <table className="data text-xs">
            <thead><tr><th>When (server)</th><th>Decision</th><th>By</th><th>Action</th><th>Offline?</th></tr></thead>
            <tbody>{rows.map((e) => <tr key={e.id}><td className="font-mono">{e.created_at.slice(0, 19).replace("T", " ")}</td><td>{e.decision}</td><td>{e.decided_by}</td><td>{e.action_title}</td><td>{e.synced_offline ? "queued" : ""}</td></tr>)}</tbody>
          </table>
        </div>
      )}
      <div className="mt-2 flex items-center gap-2 text-[11px] text-ink-400"><Tag kind="OBSERVED" /> Human decisions are logged; the system never dispatches equipment on its own.</div>
      <div className="mt-2"><Note>Rail/road logistics constraints are not yet modelled in the optimiser (stated future work).</Note></div>
    </Card>
  );
}
