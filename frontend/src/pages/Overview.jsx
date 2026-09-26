import { Link } from "react-router-dom";
import { CircleMarker, MapContainer, TileLayer, Tooltip as LTooltip } from "react-leaflet";
import { ArrowRight, Pickaxe, Satellite } from "lucide-react";
import { fmt, monthLabel, pct, useApi } from "../api.js";
import { useI18n } from "../i18n.jsx";
import { Card, Note, PageHeader, PriorityBadge, RISK_COLOR, RiskBadge, Stat, StaleNote, Tag, useLoaded } from "../components/ui.jsx";

export const TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
export const TILE_ATTR = '&copy; OpenStreetMap contributors';

export default function Overview() {
  const { t } = useI18n();
  const q = useApi("/api/overview");
  const mines = useApi("/api/mines");
  const gate = useLoaded(q);
  if (gate) return gate;
  const o = q.data;
  const p = o.production;
  const zoneHi = (o.reserves.zone_area_km2["Very High"] || 0) + (o.reserves.zone_area_km2.High || 0);
  const mineLoc = Object.fromEntries((mines.data?.mines || []).map((m) => [m.mine_id, m]));

  return (
    <div className="space-y-5">
      <PageHeader title={`${t("nav_overview")} — ${monthLabel(o.month)}`} subtitle={t("tagline")} />
      <StaleNote stale={q.stale} />

      <div className="grid gap-3 md:grid-cols-2">
        <div className="flex gap-3 rounded-xl border border-mn-500/30 bg-mn-500/5 p-4 text-sm">
          <Pickaxe className="mt-0.5 h-5 w-5 shrink-0 text-mn-400" />
          <div><b>Where is the ore?</b> A geology problem: borehole kriging + satellite surface proxies → confidence zones for where to drill next. <Link to="/reserves" className="text-mn-300 underline">Reserve map</Link></div>
        </div>
        <div className="flex gap-3 rounded-xl border border-teal-500/30 bg-teal-500/5 p-4 text-sm">
          <Satellite className="mt-0.5 h-5 w-5 shrink-0 text-teal-300" />
          <div><b>Will we hit production?</b> An equipment/weather/blasting problem: rainfall, soil moisture, NDVI and LST drive the forecast. {t("satellite_note")}</div>
        </div>
      </div>

      <div id="kpis" className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Stat label={`P50 · ${t("next_month")}`} value={`${fmt(p.sum_of_mine_p50 / 1000, 1)} kt`} sub={`${t("target")} ${fmt(p.sum_of_targets / 1000, 1)} kt`} tag="MODEL_INFERENCE" />
        <Stat label={t("deficit")} value={`${fmt(p.total_deficit_p50)} t`} sub="Sum over mines below target" tag="MODEL_INFERENCE" tone={p.total_deficit_p50 > 0 ? "#fb923c" : undefined} />
        <Stat label={t("mines_at_risk")} value={`${p.mines_at_risk} / 10`} sub="P(meet target) < 50%" tag="MODEL_INFERENCE" />
        <Stat label={t("mitigated")} value={`${fmt(p.mitigated_by_plan)} t`} sub={`${t("unmitigated")}: ${fmt(p.unmitigated)} t`} tag="SCENARIO" tone="#34d399" />
        <Stat label="High-confidence zones" value={`${fmt(zoneHi)} km²`} sub="Very High + High prospectivity" tag="MODEL_INFERENCE" />
        <Stat label={t("drill_targets")} value={o.reserves.drill_targets.length} sub={`Spatial-CV AUC ${o.reserves.surface_cv_auc}`} tag="MODEL_INFERENCE" />
      </div>

      <div className="grid gap-4 xl:grid-cols-5">
        <Card title="MOIL mines — next-month risk" tag="MODEL_INFERENCE" className="xl:col-span-2">
          <div className="h-[340px] overflow-hidden rounded-lg">
            <MapContainer center={[21.62, 79.7]} zoom={8} className="h-full w-full" scrollWheelZoom={false}>
              <TileLayer url={TILE_URL} attribution={TILE_ATTR} />
              {o.mines.map((f) => mineLoc[f.mine_id] && (
                <CircleMarker key={f.mine_id} center={[mineLoc[f.mine_id].latitude, mineLoc[f.mine_id].longitude]} radius={6 + Math.sqrt(f.rated_monthly_capacity) / 25}
                  pathOptions={{ color: RISK_COLOR[f.risk_level], fillColor: RISK_COLOR[f.risk_level], fillOpacity: 0.55, weight: 2 }}>
                  <LTooltip>{f.mine_name}: {pct(f.achievement_probability)} chance of target</LTooltip>
                </CircleMarker>
              ))}
            </MapContainer>
          </div>
          <p className="mt-2 text-[11px] text-ink-400">Locations approximate (±2-3 km). Marker size ∝ rated capacity.</p>
        </Card>

        <Card title={`${t("next_month")} — ${monthLabel(o.month)}`} tag="MODEL_INFERENCE" className="xl:col-span-3">
          <div className="overflow-x-auto">
            <table className="data">
              <thead><tr><th>{t("mine")}</th><th>Risk</th><th className="text-right">{t("median")}</th><th className="text-right">{t("target")}</th><th className="text-right">P(≥ target)</th><th>Main risk driver</th></tr></thead>
              <tbody>
                {o.mines.map((f) => (
                  <tr key={f.mine_id} className="hover:bg-ink-800/60">
                    <td><Link className="hover:text-mn-300" to={`/forecast?mine=${f.mine_id}`}>{f.mine_name}</Link><div className="text-[10px] text-ink-400">{f.mine_type} · {f.cluster_id}</div></td>
                    <td><RiskBadge level={f.risk_level} /></td>
                    <td className="num text-right">{fmt(f.p50)}<div className="text-[10px] text-ink-400">{fmt(f.p10)}–{fmt(f.p90)}</div></td>
                    <td className="num text-right">{fmt(f.target)}{f.guardrail.potentially_unrealistic && <span title={f.guardrail.flags.join(" ")} className="ml-1 text-amber-400">⚠</span>}</td>
                    <td className="num text-right">{pct(f.achievement_probability)}</td>
                    <td className="text-xs text-ink-300">{f.attribution.insufficient_evidence ? <i className="text-ink-400">{f.attribution.message}</i> : f.attribution.risk_drivers[0] ? `${f.attribution.risk_drivers[0].driver} (${fmt(f.attribution.risk_drivers[0].contribution_tonnes)} t)` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Top corrective actions" tag="SCENARIO" right={<Link to="/actions" className="flex items-center gap-1 text-xs text-mn-300">All actions <ArrowRight className="h-3 w-3" /></Link>}>
          <ul className="space-y-2">
            {o.top_actions.map((a, i) => (
              <li key={i} className="flex items-start justify-between gap-3 rounded-lg border border-ink-700 bg-ink-800/50 p-2.5">
                <div>
                  <div className="text-sm">{a.action_title}</div>
                  <div className="text-xs text-ink-400">{a.reason}</div>
                </div>
                <div className="shrink-0 text-right"><PriorityBadge p={a.priority} /><div className="num mt-1 text-sm text-emerald-300">+{fmt(a.tonnes)} t</div></div>
              </li>
            ))}
          </ul>
          <div className="mt-3"><Note>Scenario estimates — not guaranteed operational instructions. Each needs approval by the Mine Manager / Shift In-Charge.</Note></div>
        </Card>
        <Card title="Where to drill next" tag="MODEL_INFERENCE" right={<Link to="/reserves" className="flex items-center gap-1 text-xs text-mn-300">Reserve map <ArrowRight className="h-3 w-3" /></Link>}>
          <table className="data">
            <thead><tr><th>Target</th><th>Zone</th><th className="text-right">Confidence</th><th className="text-right">Uncertainty</th><th>Why</th></tr></thead>
            <tbody>
              {o.reserves.drill_targets.map((d) => (
                <tr key={d.target_id}><td className="font-mono">{d.target_id}</td><td>{d.zone}</td><td className="num text-right">{d.confidence.toFixed(2)}</td><td className="num text-right">{d.uncertainty.toFixed(2)}</td><td className="text-xs text-ink-300">{d.reasons[0]}</td></tr>
              ))}
            </tbody>
          </table>
          <div className="mt-3"><Note>{t("prospectivity_note")}</Note></div>
        </Card>
      </div>
      <p className="text-[11px] text-ink-400">Legend: <Tag kind="OBSERVED" /> logged data · <Tag kind="FORECAST" /> external projection · <Tag kind="MODEL_INFERENCE" /> model output · <Tag kind="SCENARIO" /> what-if.</p>
    </div>
  );
}
