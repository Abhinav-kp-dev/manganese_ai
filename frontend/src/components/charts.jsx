import { Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmt, monthLabel } from "../api.js";
import { chartColors, useTheme } from "../theme.jsx";

// History + backtest band + 3-month forecast fan against target.
export function FanChart({ history, backtest, forecast, height = 320 }) {
  const { theme } = useTheme();
  const C = chartColors(theme);
  const AXIS = { stroke: C.axis, fontSize: 11 };
  const tooltipStyle = { contentStyle: { background: C.tooltipBg, border: `1px solid ${C.tooltipBorder}`, borderRadius: 8, fontSize: 12 }, labelStyle: { color: C.text } };
  const byMonth = {};
  history.forEach((h) => (byMonth[h.month] = { month: h.month, actual: h.actual, target: h.target }));
  backtest.forEach((b) => Object.assign((byMonth[b.month] ||= { month: b.month }), { bt: [b.p10, b.p90], btP50: b.p50 }));
  const last = history[history.length - 1];
  if (last) Object.assign(byMonth[last.month], { fc: [last.actual, last.actual], fcP50: last.actual });
  forecast.forEach((f) => Object.assign((byMonth[f.month] ||= { month: f.month }), { fc: [f.p10, f.p90], fcP50: f.p50, target: f.target }));
  const data = Object.values(byMonth).sort((a, b) => a.month.localeCompare(b.month));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 0 }}>
        <CartesianGrid stroke={C.grid} vertical={false} />
        <XAxis dataKey="month" tickFormatter={monthLabel} {...AXIS} minTickGap={24} />
        <YAxis {...AXIS} domain={[(min) => Math.max(0, Math.floor((min * 0.85) / 1000) * 1000), (max) => Math.ceil((max * 1.05) / 1000) * 1000]} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} width={40} />
        <Tooltip {...tooltipStyle} labelFormatter={monthLabel}
          formatter={(v, n) => [Array.isArray(v) ? `${fmt(v[0])} – ${fmt(v[1])} t` : `${fmt(v)} t`, { actual: "Actual (observed)", target: "Target", bt: "Backtest P10–P90", btP50: "Backtest P50", fc: "Forecast P10–P90", fcP50: "Forecast P50" }[n] || n]} />
        <Area dataKey="bt" stroke="none" fill="#8b5cf6" fillOpacity={0.12} isAnimationActive={false} />
        <Area dataKey="fc" stroke="none" fill="#8b5cf6" fillOpacity={0.35} isAnimationActive={false} />
        <Line dataKey="target" stroke="#fbbf24" strokeDasharray="5 4" dot={false} strokeWidth={1.5} isAnimationActive={false} />
        <Line dataKey="actual" stroke={C.text} dot={false} strokeWidth={2} isAnimationActive={false} />
        <Line dataKey="btP50" stroke="#a78bfa" dot={false} strokeWidth={1} strokeDasharray="2 3" isAnimationActive={false} />
        <Line dataKey="fcP50" stroke="#c4b5fd" dot={{ r: 3 }} strokeWidth={2} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

// SHAP waterfall: model baseline -> grouped driver contributions -> P50.
export function ShapWaterfall({ base, drivers, p50, target, height = 360 }) {
  const { theme } = useTheme();
  const C = chartColors(theme);
  const AXIS = { stroke: C.axis, fontSize: 11 };
  const tooltipStyle = { contentStyle: { background: C.tooltipBg, border: `1px solid ${C.tooltipBorder}`, borderRadius: 8, fontSize: 12 }, labelStyle: { color: C.text } };
  const shown = drivers.filter((d) => Math.abs(d.contribution_tonnes) >= 25).sort((a, b) => a.contribution_tonnes - b.contribution_tonnes);
  let run = base;
  const steps = shown.map((d) => {
    const from = run;
    run += d.contribution_tonnes;
    return { name: d.driver, from, to: run, kind: d.contribution_tonnes < 0 ? "neg" : "pos", v: d.contribution_tonnes };
  });
  const lows = [base, p50, target || Infinity, ...steps.map((s) => Math.min(s.from, s.to))];
  const lo = Math.max(0, Math.floor((Math.min(...lows) * 0.97) / 500) * 500);
  const rows = [
    { name: "Model baseline", range: [lo, base], kind: "base", v: base },
    ...steps.map((s) => ({ ...s, range: [Math.min(s.from, s.to), Math.max(s.from, s.to)] })),
    { name: "Forecast P50", range: [lo, p50], kind: "total", v: p50 },
  ];
  const color = { base: C.base, neg: "#f43f5e", pos: "#34d399", total: "#8b5cf6" };
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
        <CartesianGrid stroke={C.grid} horizontal={false} />
        <XAxis type="number" domain={[lo, "auto"]} allowDataOverflow {...AXIS} tickFormatter={(v) => `${(v / 1000).toFixed(1)}k`} />
        <YAxis type="category" dataKey="name" width={210} {...AXIS} tick={{ fill: C.subtext, fontSize: 11 }} />
        <Tooltip {...tooltipStyle} formatter={(_, __, p) => [`${p.payload.kind === "neg" || p.payload.kind === "pos" ? (p.payload.v > 0 ? "+" : "") : ""}${fmt(p.payload.v)} t`, "Contribution"]} />
        {target ? <ReferenceLine x={target} stroke="#fbbf24" strokeDasharray="5 4" label={{ value: "Target", fill: "#fbbf24", fontSize: 11, position: "top" }} /> : null}
        <Bar dataKey="range" isAnimationActive={false} radius={2}>
          {rows.map((r, i) => <Cell key={i} fill={color[r.kind]} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function Gauge({ value, size = 150 }) {
  const { theme } = useTheme();
  const C = chartColors(theme);
  const v = Math.max(0, Math.min(1, value ?? 0));
  const color = v >= 0.7 ? "#34d399" : v >= 0.4 ? "#fbbf24" : v >= 0.2 ? "#fb923c" : "#f43f5e";
  const r = 60, cx = 75, cy = 72;
  const arc = (a) => [cx + r * Math.cos(Math.PI * (1 - a)), cy - r * Math.sin(Math.PI * (1 - a))];
  const [x0, y0] = arc(0), [x1, y1] = arc(v), [xe, ye] = arc(1);
  return (
    <svg width={size} height={size * 0.62} viewBox="0 0 150 92" role="img" aria-label={`Probability ${Math.round(v * 100)}%`}>
      <path d={`M${x0},${y0} A${r},${r} 0 0 1 ${xe},${ye}`} stroke={C.grid} strokeWidth="12" fill="none" strokeLinecap="round" />
      {v > 0.005 && <path d={`M${x0},${y0} A${r},${r} 0 0 1 ${x1},${y1}`} stroke={color} strokeWidth="12" fill="none" strokeLinecap="round" />}
      <text x={cx} y={cy - 6} textAnchor="middle" fontSize="24" fontWeight="700" fill={color} fontFamily="JetBrains Mono, monospace">{Math.round(v * 100)}%</text>
      <text x={cx} y={cy + 14} textAnchor="middle" fontSize="9" fill={C.axis}>P(production ≥ target)</text>
    </svg>
  );
}

export function MiniBars({ data, dataKey, nameKey, height = 200, color = "#8b5cf6", format = (v) => v }) {
  const { theme } = useTheme();
  const C = chartColors(theme);
  const AXIS = { stroke: C.axis, fontSize: 11 };
  const tooltipStyle = { contentStyle: { background: C.tooltipBg, border: `1px solid ${C.tooltipBorder}`, borderRadius: 8, fontSize: 12 }, labelStyle: { color: C.text } };
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 12, left: 0, bottom: 0 }}>
        <XAxis type="number" hide />
        <YAxis type="category" dataKey={nameKey} width={230} {...AXIS} tick={{ fill: C.subtext, fontSize: 11 }} />
        <Tooltip {...tooltipStyle} formatter={(v) => format(v)} />
        <Bar dataKey={dataKey} fill={color} radius={3} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function VariogramChart({ variogram }) {
  const { theme } = useTheme();
  const C = chartColors(theme);
  const AXIS = { stroke: C.axis, fontSize: 11 };
  const tooltipStyle = { contentStyle: { background: C.tooltipBg, border: `1px solid ${C.tooltipBorder}`, borderRadius: 8, fontSize: 12 }, labelStyle: { color: C.text } };
  const { nugget, partial_sill: ps, range_km: rg, empirical } = variogram;
  const model = (h) => (h === 0 ? 0 : h >= rg ? nugget + ps : nugget + ps * (1.5 * (h / rg) - 0.5 * (h / rg) ** 3));
  const maxH = Math.max(...empirical.lag_km) * 1.05;
  const data = Array.from({ length: 40 }, (_, i) => {
    const h = (i / 39) * maxH;
    return { h: +h.toFixed(2), model: model(h) };
  });
  empirical.lag_km.forEach((h, i) => data.push({ h, emp: empirical.semivariance[i] }));
  data.sort((a, b) => a.h - b.h);
  return (
    <ResponsiveContainer width="100%" height={200}>
      <ComposedChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={C.grid} vertical={false} />
        <XAxis dataKey="h" type="number" {...AXIS} unit=" km" />
        <YAxis {...AXIS} width={36} />
        <Tooltip {...tooltipStyle} formatter={(v) => (v ?? 0).toFixed(1)} labelFormatter={(h) => `lag ${h} km`} />
        <Line dataKey="model" stroke="#8b5cf6" dot={false} strokeWidth={2} connectNulls isAnimationActive={false} />
        <Line dataKey="emp" stroke="none" dot={{ r: 3, fill: C.text }} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
