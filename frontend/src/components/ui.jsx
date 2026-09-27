import { AlertTriangle, Info, Loader2 } from "lucide-react";
import { useI18n } from "../i18n.jsx";

const TAG_STYLE = {
  OBSERVED: "border-sky-500/40 bg-sky-500/10 text-sky-300",
  FORECAST: "border-teal-500/40 bg-teal-500/10 text-teal-300",
  MODEL_INFERENCE: "border-mn-500/50 bg-mn-500/10 text-mn-300",
  SCENARIO: "border-amber-500/40 bg-amber-500/10 text-amber-300",
};
const TAG_HELP = {
  OBSERVED: "From logged historical data",
  FORECAST: "From an external weather/satellite projection",
  MODEL_INFERENCE: "Derived by an ML or geostatistical model",
  SCENARIO: "A hypothetical what-if, not a prediction",
};

export function Tag({ kind }) {
  const { t } = useI18n();
  return (
    <span title={TAG_HELP[kind]} className={`inline-flex items-center rounded border px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide ${TAG_STYLE[kind]}`}>
      {t(`tag_${kind}`)}
    </span>
  );
}

export const RISK_COLOR = { LOW: "#34d399", MODERATE: "#fbbf24", HIGH: "#fb923c", CRITICAL: "#f43f5e" };
const PRIORITY_STYLE = {
  Critical: "bg-rose-500/15 text-rose-300 border-rose-500/40",
  High: "bg-orange-500/15 text-orange-300 border-orange-500/40",
  Medium: "bg-amber-500/15 text-amber-300 border-amber-500/40",
  Low: "bg-ink-700 text-ink-300 border-ink-600",
};

export function RiskBadge({ level }) {
  const { t } = useI18n();
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-ink-600 px-2 py-0.5 text-xs font-semibold" style={{ color: RISK_COLOR[level] }}>
      <span className="h-2 w-2 rounded-full" style={{ background: RISK_COLOR[level] }} />
      {t(`risk_${level}`)}
    </span>
  );
}

export function PriorityBadge({ p }) {
  return <span className={`rounded border px-1.5 py-0.5 text-[11px] font-semibold ${PRIORITY_STYLE[p]}`}>{p}</span>;
}

export function Card({ title, tag, right, children, className = "", id }) {
  return (
    <section id={id} className={`card ${className}`}>
      {(title || right) && (
        <header className="mb-3 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            {title && <h2 className="card-title">{title}</h2>}
            {tag && <Tag kind={tag} />}
          </div>
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, sub, tag, tone }) {
  return (
    <div className="card flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <span className="card-title">{label}</span>
        {tag && <Tag kind={tag} />}
      </div>
      <div className="num text-2xl font-semibold" style={tone ? { color: tone } : undefined}>{value}</div>
      {sub && <div className="text-xs text-ink-400">{sub}</div>}
    </div>
  );
}

export function PageHeader({ title, subtitle, right }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-ink-100">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-ink-400">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

export function Loading({ state }) {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-3 p-10 text-ink-400">
      <Loader2 className="h-5 w-5 animate-spin" /> {state?.training ? `${t("training")}${state.waitedSeconds ? ` (${state.waitedSeconds} s)` : ""}` : t("loading")}
    </div>
  );
}

export function ErrorBox({ error }) {
  return (
    <div className="card flex items-center gap-2 border-rose-500/40 text-rose-300">
      <AlertTriangle className="h-4 w-4" /> Could not load data ({error?.status || "network"}). {error?.detail || "Check that the API server is running."}
    </div>
  );
}

export function Note({ children, tone = "info" }) {
  const cls = tone === "warn" ? "border-amber-500/40 bg-amber-500/5 text-amber-800 dark:text-amber-200" : "border-ink-600 bg-ink-800/60 text-ink-300";
  return (
    <div className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-xs ${cls}`}>
      {tone === "warn" ? <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" /> : <Info className="mt-px h-3.5 w-3.5 shrink-0" />}
      <div>{children}</div>
    </div>
  );
}

export function StaleNote({ stale }) {
  return stale ? <Note tone="warn">Showing the last cached copy — you are offline or the server is unreachable.</Note> : null;
}

export function useLoaded(q) {
  if (q.loading && !q.data) return <Loading state={q} />;
  if (q.error) return <ErrorBox error={q.error} />;
  return null;
}
