import { useEffect, useMemo, useState } from "react";
import { CircleMarker, ImageOverlay, MapContainer, Marker, Polyline, TileLayer, Tooltip as LTooltip, useMapEvents } from "react-leaflet";
import L from "leaflet";
import { api, fmt, pct, useApi } from "../api.js";
import { useI18n } from "../i18n.jsx";
import { MiniBars, VariogramChart } from "../components/charts.jsx";
import { Card, Note, PageHeader, StaleNote, Tag, useLoaded } from "../components/ui.jsx";
import { TILE_ATTR, TILE_URL } from "./Overview.jsx";

const ramp = (stops) => (v) => {
  const x = Math.max(0, Math.min(1, v));
  for (let i = 1; i < stops.length; i++) {
    if (x <= stops[i][0]) {
      const [a, ca] = stops[i - 1], [b, cb] = stops[i];
      const f = (x - a) / (b - a || 1);
      return ca.map((c, k) => Math.round(c + f * (cb[k] - c)));
    }
  }
  return stops[stops.length - 1][1];
};
const PURPLE = ramp([[0, [20, 16, 40]], [0.15, [59, 36, 110]], [0.3, [109, 60, 190]], [0.5, [167, 110, 250]], [0.7, [236, 180, 255]], [1, [255, 240, 200]]]);
const HEAT = ramp([[0, [15, 60, 70]], [0.4, [40, 150, 130]], [0.7, [245, 190, 60]], [1, [240, 70, 70]]]);
const GRADE = ramp([[0, [30, 40, 80]], [0.35, [40, 110, 160]], [0.6, [60, 180, 120]], [0.8, [220, 210, 60]], [1, [250, 120, 50]]]);
const COVER = { 0: [80, 80, 90], 1: [180, 90, 50], 2: [60, 140, 200], 3: [90, 90, 140] };

const LAYERS = {
  confidence: { label: "Fused confidence", color: PURPLE, norm: (v) => v, legend: ["0", "0.15", "0.3", "0.5", "0.7", "1"], tag: "MODEL_INFERENCE" },
  uncertainty: { label: "Uncertainty", color: HEAT, norm: (v) => v, legend: ["low", "", "", "high"], tag: "MODEL_INFERENCE" },
  kriged_grade_pct: { label: "Kriged Mn grade (%)", color: GRADE, norm: (v) => (v - 10) / 35, legend: ["10%", "", "27%", "", "45%"], tag: "MODEL_INFERENCE" },
  kriging_sd_pct: { label: "Kriging std. dev. (%)", color: HEAT, norm: (v) => v / 10, legend: ["0", "", "5", "", "10+"], tag: "MODEL_INFERENCE" },
  p_grade_above_cutoff: { label: "P(grade ≥ cut-off) · Gaussian kriging", color: GRADE, norm: (v) => v, legend: ["0", "", "0.5", "", "1"], tag: "MODEL_INFERENCE" },
  p_grade_above_cutoff_ik: { label: "P(grade ≥ cut-off) · indicator kriging", color: GRADE, norm: (v) => v, legend: ["0", "", "0.5", "", "1"], tag: "MODEL_INFERENCE" },
  surface_prob: { label: "Satellite surface proxy", color: PURPLE, norm: (v) => v, legend: ["0", "", "0.5", "", "1"], tag: "MODEL_INFERENCE" },
  data_support: { label: "Borehole data support", color: GRADE, norm: (v) => v, legend: ["none", "", "strong"], tag: "MODEL_INFERENCE" },
  cover_type: { label: "Surface cover (masks satellite signal)", categorical: true, tag: "OBSERVED" },
};

function useRaster(grid, layer) {
  return useMemo(() => {
    if (!grid) return null;
    const { rows, cols } = grid;
    const vals = grid.layers[layer];
    const cfg = LAYERS[layer];
    const c = document.createElement("canvas");
    c.width = cols; c.height = rows;
    const ctx = c.getContext("2d");
    const img = ctx.createImageData(cols, rows);
    for (let r = 0; r < rows; r++) for (let q = 0; q < cols; q++) {
      const v = vals[r * cols + q];
      const rgb = cfg.categorical ? COVER[v] : cfg.color(cfg.norm(v));
      const o = ((rows - 1 - r) * cols + q) * 4;
      img.data[o] = rgb[0]; img.data[o + 1] = rgb[1]; img.data[o + 2] = rgb[2];
      img.data[o + 3] = layer === "confidence" ? Math.round(60 + 195 * Math.min(1, v * 1.6)) : 230;
    }
    ctx.putImageData(img, 0, 0);
    return c.toDataURL();
  }, [grid, layer]);
}

function ClickProbe({ onPick }) {
  useMapEvents({ click: (e) => onPick(e.latlng) });
  return null;
}

const targetIcon = (label) => L.divIcon({ className: "", html: `<div style="background:#fbbf24;color:#111;font:700 10px Inter;padding:1px 4px;border-radius:4px;border:1px solid #111;white-space:nowrap">${label}</div>`, iconAnchor: [14, 8] });

export default function Reserves() {
  const { t } = useI18n();
  const grid = useApi("/api/reserves/grid");
  const pts = useApi("/api/reserves/points");
  const val = useApi("/api/reserves/validation");
  const mines = useApi("/api/mines");
  const [layer, setLayer] = useState("confidence");
  const [opacity, setOpacity] = useState(0.8);
  const [show, setShow] = useState({ boreholes: true, occurrences: false, lineaments: true, targets: true, mines: true });
  const [cell, setCell] = useState(null);
  const url = useRaster(grid.data, layer);
  const pick = async ({ lat, lng }) => setCell(await api(`/api/reserves/cell?lat=${lat}&lon=${lng}`).catch(() => null));
  useEffect(() => { if (pts.data && !cell) pick({ lat: pts.data.drill_targets[0].latitude, lng: pts.data.drill_targets[0].longitude }); }, [pts.data]); // eslint-disable-line

  const gate = useLoaded(grid);
  if (gate) return gate;
  const g = grid.data;
  const bounds = [[g.bbox.lat_min, g.bbox.lon_min], [g.bbox.lat_max, g.bbox.lon_max]];

  return (
    <div className="space-y-5">
      <PageHeader title={t("nav_reserves")} subtitle="Module 1 · Ordinary kriging of borehole Mn assays fused with a Sentinel-2/Sentinel-1/DEM surface-proxy model. Output is prospectivity with explicit uncertainty, for prioritising drilling." />
      <StaleNote stale={grid.stale} />
      <div className="grid gap-3 md:grid-cols-2">
        <Note tone="warn">{t("prospectivity_note")} Statutory use needs drilling, assay and sign-off by a Competent Person.</Note>
        <Note>{t("satellite_note")} Under alluvium or Deccan Trap basalt the surface proxy is nearly blind; the fusion falls back to boreholes and widens uncertainty.</Note>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <Card id="reserve-map" title="Study area — Nagpur · Bhandara · Balaghat belt" tag={LAYERS[layer].tag}
          right={<select className="input" value={layer} onChange={(e) => setLayer(e.target.value)}>{Object.entries(LAYERS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>}>
          <div className="h-[520px] overflow-hidden rounded-lg">
            <MapContainer bounds={bounds} className="h-full w-full">
              <TileLayer url={TILE_URL} attribution={TILE_ATTR} />
              {url && <ImageOverlay key={layer} url={url} bounds={bounds} opacity={opacity} className="pixelated" />}
              <ClickProbe onPick={pick} />
              {show.lineaments && pts.data?.lineaments.map((s, i) => <Polyline key={i} positions={s} pathOptions={{ color: "#94a3b8", weight: 1, opacity: 0.6, dashArray: "3 3" }} />)}
              {show.boreholes && pts.data?.boreholes.map((b) => (
                <CircleMarker key={b.borehole_id} center={[b.latitude, b.longitude]} radius={2.5} pathOptions={{ color: "#e8ecf4", weight: 1, fillColor: b.grade_mn_pct >= 25 ? "#fbbf24" : "#475569", fillOpacity: 1 }}>
                  <LTooltip>{b.borehole_id}: {b.grade_mn_pct}% Mn, {b.thickness_m} m @ {b.depth_m} m depth<br />{b.source}</LTooltip>
                </CircleMarker>
              ))}
              {show.occurrences && pts.data?.occurrences.map((o, i) => (
                <CircleMarker key={i} center={[o.latitude, o.longitude]} radius={4} pathOptions={{ color: "#34d399", weight: 1.5, fillOpacity: 0 }}><LTooltip>{o.name} — {o.kind}</LTooltip></CircleMarker>
              ))}
              {show.mines && mines.data?.mines.map((m) => (
                <CircleMarker key={m.mine_id} center={[m.latitude, m.longitude]} radius={7} pathOptions={{ color: "#fff", weight: 2, fillColor: "#8b5cf6", fillOpacity: 0.9 }}><LTooltip>{m.mine_name} ({m.mine_type})</LTooltip></CircleMarker>
              ))}
              {show.targets && pts.data?.drill_targets.map((d) => (
                <Marker key={d.target_id} position={[d.latitude, d.longitude]} icon={targetIcon(d.target_id)} eventHandlers={{ click: () => pick({ lat: d.latitude, lng: d.longitude }) }} />
              ))}
            </MapContainer>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-ink-300">
            <Legend layer={layer} cover={g.cover_types} />
            <label className="flex items-center gap-2">Opacity <input type="range" min="0.2" max="1" step="0.05" value={opacity} onChange={(e) => setOpacity(+e.target.value)} /></label>
            {Object.keys(show).map((k) => (
              <label key={k} className="flex items-center gap-1 capitalize"><input type="checkbox" checked={show[k]} onChange={() => setShow({ ...show, [k]: !show[k] })} /> {k}</label>
            ))}
          </div>
          <p className="mt-1 text-[11px] text-ink-400">Click anywhere to inspect a 2.2 km cell. Boreholes: yellow ≥ {g.cutoff_mn_pct}% Mn cut-off. Dashed: lineaments/faults.</p>
        </Card>

        <CellPanel cell={cell} />
      </div>

      {val.data && <Validation v={val.data} />}
      {pts.data && <DrillTargets targets={pts.data.drill_targets} onPick={pick} />}
    </div>
  );
}

function Legend({ layer, cover }) {
  const cfg = LAYERS[layer];
  if (cfg.categorical) return (
    <div className="flex flex-wrap gap-2">{Object.entries(cover).map(([k, v]) => <span key={k} className="flex items-center gap-1"><span className="h-3 w-3 rounded-sm" style={{ background: `rgb(${COVER[k].join(",")})` }} />{v}</span>)}</div>
  );
  const stops = Array.from({ length: 24 }, (_, i) => `rgb(${cfg.color(i / 23).join(",")})`).join(",");
  return (
    <div className="w-56">
      <div className="h-2.5 rounded" style={{ background: `linear-gradient(90deg, ${stops})` }} />
      <div className="mt-0.5 flex justify-between text-[10px] text-ink-400">{cfg.legend.map((l, i) => <span key={i}>{l}</span>)}</div>
    </div>
  );
}

function CellPanel({ cell }) {
  if (!cell) return <Card title="Cell inspector"><p className="text-sm text-ink-400">Click the map.</p></Card>;
  const s = cell.subsurface, f = cell.surface;
  return (
    <Card title="Cell inspector" tag="MODEL_INFERENCE">
      <div className="mb-3 flex items-baseline justify-between">
        <div className="font-mono text-xs text-ink-400">{cell.latitude}°N {cell.longitude}°E</div>
        <div className="text-sm font-semibold text-mn-300">{cell.zone}</div>
      </div>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <Metric label="Confidence" v={cell.confidence.toFixed(2)} />
        <Metric label="Uncertainty" v={cell.uncertainty.toFixed(2)} />
      </div>
      <h3 className="card-title mb-1 mt-4">Sub-surface (kriging)</h3>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <Metric label="Kriged grade" v={`${s.kriged_grade_pct}% ±${s.kriging_sd_pct}`} />
        <Metric label="P(grade ≥ cut-off)" v={pct(s.p_grade_above_cutoff)} />
        {s.p_grade_above_cutoff_ik !== undefined && <Metric label="Same, indicator kriging" v={pct(s.p_grade_above_cutoff_ik)} />}
        <Metric label="Borehole support" v={pct(s.data_support)} />
      </div>
      <h3 className="card-title mb-1 mt-4 flex items-center gap-2">Surface proxy <Tag kind="OBSERVED" /></h3>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <Metric label="Proxy probability" v={f.probability.toFixed(2)} />
        <Metric label="Cover" v={f.cover} />
        <Metric label="Proxy reliability" v={pct(f.proxy_reliability)} />
        <Metric label="Model spread" v={`±${f.model_spread.toFixed(2)}`} />
      </div>
      <ul className="mt-3 space-y-1 text-xs">
        {f.features.slice(0, 6).map((x) => (
          <li key={x.feature} className="flex justify-between gap-2">
            <span className="text-ink-300">{x.label} <span className="font-mono text-ink-400">({x.value})</span></span>
            <span className={`num ${x.contribution_logodds >= 0 ? "text-emerald-300" : "text-rose-300"}`}>{x.contribution_logodds >= 0 ? "+" : ""}{x.contribution_logodds.toFixed(2)}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[10px] text-ink-400">Contributions are TreeSHAP log-odds of the surface-proxy model.</p>
    </Card>
  );
}

const Metric = ({ label, v }) => <div className="rounded-lg bg-ink-800 px-2 py-1.5"><div className="text-[10px] uppercase text-ink-400">{label}</div><div className="num">{v}</div></div>;

function Validation({ v }) {
  const sv = v.surface_validation;
  const k = v.kriging_cv;
  return (
    <div id="reserve-validation" className="grid gap-4 xl:grid-cols-3">
      <Card title="Surface-proxy model validation" tag="MODEL_INFERENCE">
        <div className="grid grid-cols-2 gap-2 text-sm">
          <Metric label="Spatial-block CV AUC" v={`${sv.spatial_cv_auc.toFixed(3)}`} />
          <Metric label="95% bootstrap CI" v={`${sv.spatial_cv_auc_ci95[0].toFixed(2)}–${sv.spatial_cv_auc_ci95[1].toFixed(2)}`} />
          <Metric label="Random k-fold AUC" v={`${sv.random_kfold_auc_for_comparison.toFixed(3)} (optimistic)`} />
          <Metric label="Positives / background" v={`${sv.n_positive} / ${sv.n_pseudo_absence}`} />
        </div>
        <table className="data mt-3">
          <thead><tr><th>Fold</th><th className="text-right">AUC</th><th className="text-right">Positives</th></tr></thead>
          <tbody>{sv.per_fold.map((f) => <tr key={f.fold}><td>{f.fold + 1}</td><td className="num text-right">{f.auc.toFixed(3)}</td><td className="num text-right">{f.n_pos}</td></tr>)}</tbody>
        </table>
        <p className="mt-2 text-xs text-ink-400">{sv.note} Excluded to prevent leakage: {sv.excluded_features.join(", ")}.</p>
      </Card>
      <Card title="Kriging validation (two scales)" tag="MODEL_INFERENCE">
        <table className="data">
          <thead><tr><th>Scheme</th><th className="text-right">MAE %Mn</th><th className="text-right">Mean-only</th><th className="text-right">90% cov.</th></tr></thead>
          <tbody>
            {[["Interpolation", k.interpolation], ["Extrapolation", k.extrapolation]].map(([n, r]) => (
              <tr key={n}><td>{n}<div className="text-[10px] text-ink-400">{r.scheme}</div></td><td className="num text-right">{r.mae_pct_mn.toFixed(2)}</td><td className="num text-right">{r.baseline_mean_mae_pct_mn.toFixed(2)}</td><td className="num text-right">{pct(r.coverage_90pct_interval)}</td></tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-ink-400">{k.reading}</p>
        {v.probability_models && (
          <div className="mt-2 text-xs text-ink-300">
            <b>P(grade ≥ cut-off), cross-validated Brier score</b> (lower is better): Gaussian kriging <span className="num">{v.probability_models.brier_gaussian_kriging.toFixed(3)}</span> · indicator kriging <span className="num">{v.probability_models.brier_indicator_kriging.toFixed(3)}</span> · base rate only <span className="num">{v.probability_models.brier_climatology.toFixed(3)}</span>
          </div>
        )}
        <h3 className="card-title mb-1 mt-3">Variogram (spherical fit, range {v.variogram.range_km.toFixed(1)} km)</h3>
        <VariogramChart variogram={v.variogram} />
      </Card>
      <Card title="What the surface model relies on" tag="MODEL_INFERENCE">
        <MiniBars data={v.feature_importance.slice(0, 8)} dataKey="importance" nameKey="label" height={230} format={(x) => pct(x, 1)} />
        <div className="mt-3 rounded-lg border border-dashed border-ink-600 p-2 text-xs text-ink-300">
          <b>Simulation-only sanity check</b> <span className="text-ink-400">(possible only because the synthetic world has a known truth)</span>
          <div className="mt-1 grid grid-cols-2 gap-1 font-mono">
            <span>fused vs truth: {v.simulation_check.fused_auc_vs_synthetic_truth.toFixed(3)}</span>
            <span>proxy only: {v.simulation_check.surface_only_auc_vs_synthetic_truth.toFixed(3)}</span>
            <span>fused, under cover: {v.simulation_check.fused_auc_under_cover?.toFixed(3)}</span>
            <span>proxy, under cover: {v.simulation_check.surface_only_auc_under_cover?.toFixed(3)}</span>
          </div>
        </div>
      </Card>
    </div>
  );
}

function DrillTargets({ targets, onPick }) {
  return (
    <Card id="drill-targets" title="Drill-target shortlist — ranked by value of information" tag="MODEL_INFERENCE">
      <div className="overflow-x-auto">
        <table className="data">
          <thead><tr><th>#</th><th>Location</th><th>Zone</th><th className="text-right">Confidence</th><th className="text-right">Uncertainty</th><th className="text-right">VOI</th><th>Cover</th><th className="text-right">P(ore)</th><th className="text-right">Ore, Mt (P10 · P50 · P90)</th><th>Rationale</th></tr></thead>
          <tbody>
            {targets.map((d) => (
              <tr key={d.target_id} className="cursor-pointer hover:bg-ink-800/60" onClick={() => onPick({ lat: d.latitude, lng: d.longitude })}>
                <td className="font-mono">{d.target_id}</td><td className="font-mono text-xs">{d.latitude}, {d.longitude}</td><td>{d.zone}</td>
                <td className="num text-right">{d.confidence.toFixed(2)}</td><td className="num text-right">{d.uncertainty.toFixed(2)}</td><td className="num text-right">{d.value_of_information.toFixed(2)}</td>
                <td className="text-xs">{d.cover}</td>
                <td className="num text-right">{d.tonnage ? pct(d.tonnage.p_ore_present) : "—"}</td>
                <td className="num whitespace-nowrap text-right">{d.tonnage ? d.tonnage.ore_tonnes_p10_p50_p90.map((x) => fmt(x / 1e6, 2)).join(" · ") : "—"}</td>
                <td className="text-xs text-ink-300">{d.reasons.join(" · ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-ink-400">VOI = confidence × uncertainty: holes where the ground looks promising <i>and</i> is least constrained teach the most. Cells within 3 km of operating leases are excluded. {fmt(targets.length)} targets, ≥ 6 km apart.</p>
      {targets[0]?.tonnage && (
        <p className="mt-1 text-xs text-amber-200/90">
          Tonnage columns: {targets[0].tonnage.label} Assumed strike {targets[0].tonnage.assumptions.strike_length_m.join("–")} m, down-dip {targets[0].tonnage.assumptions.down_dip_extent_m.join("–")} m,
          continuity {targets[0].tonnage.assumptions.continuity_fraction.join("–")}, density {targets[0].tonnage.assumptions.bulk_density_t_m3.join("–")} t/m³; grade and thickness from kriging. P(ore) is the chance the block clears the cut-off at all; a P10 or P50 of 0 means it may not.
        </p>
      )}
    </Card>
  );
}
