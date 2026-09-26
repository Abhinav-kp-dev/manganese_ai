import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Activity, CloudOff, LogOut, FileText, Gauge, Layers, Menu, PlayCircle, ShieldCheck, SlidersHorizontal, Wrench, X } from "lucide-react";
import { flushQueue, pendingCount, useApi } from "../api.js";
import { LANGS, useI18n } from "../i18n.jsx";
import { useAuth } from "../auth.jsx";

const NAV = [
  { to: "/", key: "nav_overview", icon: Gauge },
  { to: "/reserves", key: "nav_reserves", icon: Layers },
  { to: "/forecast", key: "nav_forecast", icon: Activity },
  { to: "/actions", key: "nav_actions", icon: Wrench },
  { to: "/scenarios", key: "nav_scenarios", icon: SlidersHorizontal },
  { to: "/integrity", key: "nav_integrity", icon: ShieldCheck },
  { to: "/report", key: "nav_report", icon: FileText },
];

function useOnline() {
  const [online, setOnline] = useState(navigator.onLine);
  const [pending, setPending] = useState(0);
  useEffect(() => {
    const refresh = () => pendingCount().then(setPending);
    const up = () => { setOnline(true); flushQueue().then(refresh); };
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    window.addEventListener("mh-queue", refresh);
    refresh();
    if (navigator.onLine) flushQueue().then(refresh);
    return () => { window.removeEventListener("online", up); window.removeEventListener("offline", down); window.removeEventListener("mh-queue", refresh); };
  }, []);
  return { online, pending };
}

export default function Layout() {
  const { t, lang, setLang } = useI18n();
  const meta = useApi("/api/meta");
  const { online, pending } = useOnline();
  const { user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const [tour, setTour] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);
  const mode = meta.data?.data_mode;

  return (
    <div className="min-h-screen">
      {mode !== "REAL" && (
        <div role="status" className="no-print sticky top-0 z-[1200] border-b border-amber-500/40 bg-amber-950/95 px-4 py-1.5 text-center text-xs font-medium text-amber-200">
          {mode === "MIXED" ? t("banner_mixed") : t("banner_synthetic")}
        </div>
      )}
      <div className="flex">
        <aside className={`no-print fixed inset-y-0 left-0 z-[1100] w-64 transform border-r border-ink-700 bg-ink-900 pt-9 transition md:sticky md:top-0 md:h-screen md:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}>
          <div className="px-5 pb-4 pt-3">
            <div className="flex items-center gap-2">
              <img src="/icon.svg" alt="" className="h-8 w-8" />
              <div>
                <div className="text-sm font-bold leading-tight">{t("appName")}</div>
                <div className="text-[10px] uppercase tracking-wider text-ink-400">SIH26009 · MOIL</div>
              </div>
            </div>
          </div>
          <nav className="flex flex-col gap-0.5 px-3">
            {NAV.map(({ to, key, icon: Icon }) => (
              <NavLink key={to} to={to} end={to === "/"}
                className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${isActive ? "bg-mn-600/20 text-mn-300" : "text-ink-300 hover:bg-ink-800"}`}>
                <Icon className="h-4 w-4" /> {t(key)}
              </NavLink>
            ))}
          </nav>
          <div className="mx-3 mt-5 rounded-lg border border-ink-700 bg-ink-800/60 p-3 text-xs">
            <div className="font-medium text-ink-100">{user.full_name}</div>
            <div className="text-mn-300">{user.role_label}</div>
            <div className="text-ink-400">Site scope: {user.site_scope === "ALL" ? "All mines" : user.site_scope}</div>
            <button className="mt-2 flex items-center gap-1 text-ink-300 hover:text-rose-300" onClick={signOut}><LogOut className="h-3 w-3" /> Sign out</button>
          </div>
          <div className="mt-4 space-y-3 px-5 text-xs text-ink-400">
            <button className="btn-primary w-full justify-center" onClick={() => setTour(true)}><PlayCircle className="h-4 w-4" /> {t("guided_demo")}</button>
            <label className="block">
              <span className="mb-1 block">{t("language")}</span>
              <select className="input w-full" value={lang} onChange={(e) => setLang(e.target.value)}>
                {LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
              </select>
            </label>
            <div className="flex items-center gap-2">
              {online ? <span className="h-2 w-2 rounded-full bg-emerald-400" /> : <CloudOff className="h-3.5 w-3.5 text-amber-400" />}
              {online ? t("online") : t("offline")}
            </div>
            {pending > 0 && <div className="text-amber-300">{pending} {t("pending_sync")}</div>}
            {meta.data && (
              <div className="space-y-0.5 border-t border-ink-700 pt-3 font-mono text-[10px] leading-relaxed">
                <div>data: {meta.data.data_mode}</div>
                <div>model: {meta.data.model_version}</div>
                <div>last obs: {meta.data.last_observed_month}</div>
              </div>
            )}
          </div>
        </aside>
        <main className="min-w-0 flex-1 px-4 pb-16 pt-4 md:px-8">
          <div className="no-print mb-3 flex items-center gap-3 md:hidden">
            <button className="btn-ghost" onClick={() => setOpen(!open)} aria-label="Menu">{open ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}</button>
            <span className="font-semibold">{t("appName")}</span>
          </div>
          <Outlet context={{ meta: meta.data }} />
        </main>
      </div>
      {tour && <GuidedTour onClose={() => setTour(false)} />}
    </div>
  );
}

const STEPS = [
  { path: "/", el: "kpis", title: "Two problems, not one",
    body: "SIH26009 bundles reserve identification (a geology problem) with production shortfall (an equipment/weather problem). Satellites cannot see ore underground, so they feed the surface-proxy layer and the weather drivers — never a direct sub-surface claim." },
  { path: "/reserves", el: "reserve-map", title: "Module 1 — reserve confidence, not 'reserves'",
    body: "Ordinary kriging of borehole assays gives a sub-surface estimate with variance. A surface-proxy model (Sentinel-2 ratios, Sentinel-1 SAR, DEM, lineaments, mapped lithology) fills gaps. Switch to the Uncertainty layer: the map says where it does not know." },
  { path: "/reserves", el: "reserve-validation", title: "Honest validation",
    body: "Spatially blocked CV holds out whole 30 km blocks; random k-fold is shown for comparison because it is optimistic. Kriging is reported at two scales: skilful within the variogram range, no better than a mean beyond it." },
  { path: "/reserves", el: "drill-targets", title: "Where to drill next",
    body: "Targets are ranked by value of information: promising AND poorly constrained. Existing leases are excluded. This prioritises drilling; it never replaces it." },
  { path: "/forecast?mine=BLG-01", el: "fan-chart", title: "Module 2 — ranges, not single numbers",
    body: "Quantile XGBoost gives P10/P50/P90 for the next three months, conformally calibrated. The gauge is the chance of meeting target. Balaghat's September target is at risk." },
  { path: "/forecast?mine=BLG-01", el: "shap", title: "Why — TreeSHAP drivers",
    body: "Exact SHAP contributions, grouped into named mechanisms: the scheduled hoist overhaul and the monsoon outlook pull the forecast down. If evidence is weak, the system says 'Insufficient evidence' instead of inventing a cause." },
  { path: "/forecast?mine=BLG-01", el: "baselines", title: "Accuracy is always relative",
    body: "Every error metric is shown next to persistence and seasonal-naive baselines on the same held-out window." },
  { path: "/actions", el: "action-plan", title: "Module 3 — a real optimiser",
    body: "A linear programme (HiGHS) closes the deficit at least cost across levers tied to the SHAP drivers and to sister-mine spare capacity. Every action states its assumptions and carries a scenario disclaimer; a human approves it." },
  { path: "/scenarios", el: "scenario-panel", title: "What-if, clearly labelled",
    body: "Heavy monsoon, breakdowns, optimistic case, target realignment, sister-mine rebalance. Scenario outputs are tagged SCENARIO — never presented as forecasts." },
  { path: "/integrity", el: "checklist", title: "Scientific integrity, checked live",
    body: "The checklist is computed from the running system: leakage, spatial CV, monotone quantiles, baselines, calibration, labelling. The dashboard also works offline and in Hindi/Marathi for site supervisors." },
];

function GuidedTour({ onClose }) {
  const [i, setI] = useState(0);
  const nav = useNavigate();
  const { t } = useI18n();
  const step = STEPS[i];
  useEffect(() => {
    nav(step.path);
    let tries = 0;
    let prev;
    const timer = setInterval(() => {
      const el = document.getElementById(step.el);
      if (el || ++tries > 40) {
        clearInterval(timer);
        if (el) { el.scrollIntoView({ behavior: "smooth", block: "center" }); el.classList.add("tour-highlight"); prev = el; }
      }
    }, 150);
    return () => { clearInterval(timer); prev?.classList.remove("tour-highlight"); };
  }, [i]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="no-print fixed bottom-4 right-4 z-[1300] w-[min(420px,calc(100vw-2rem))] rounded-xl border border-amber-400/50 bg-ink-900 p-4 shadow-2xl">
      <div className="mb-1 flex items-center justify-between text-xs text-amber-300">
        <span>{t("guided_demo")} · {i + 1}/{STEPS.length}</span>
        <button onClick={onClose} aria-label={t("close")}><X className="h-4 w-4" /></button>
      </div>
      <h3 className="font-semibold">{step.title}</h3>
      <p className="mt-1 text-sm text-ink-300">{step.body}</p>
      <div className="mt-3 flex justify-between">
        <button className="btn-ghost" disabled={i === 0} onClick={() => setI(i - 1)}>{t("back")}</button>
        {i < STEPS.length - 1 ? <button className="btn-primary" onClick={() => setI(i + 1)}>{t("next")}</button> : <button className="btn-primary" onClick={onClose}>{t("close")}</button>}
      </div>
    </div>
  );
}
