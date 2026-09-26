import { useEffect, useState } from "react";
import { HardHat, LogIn, Mountain, Pickaxe, ShieldCheck, Eye, ClipboardList } from "lucide-react";
import { api } from "../api.js";
import { useAuth } from "../auth.jsx";
import { LANGS, useI18n } from "../i18n.jsx";

const ICON = { ADMIN: ShieldCheck, MINE_MANAGER: HardHat, PLANNER: ClipboardList, GEOLOGIST: Mountain, VIEWER: Eye };
const CAN = {
  decide: "Approve / reject actions", defer: "Defer actions", upload_data: "Upload MOIL data",
  run_pipeline: "Run data pipeline", manage_users: "Manage users", read: "View dashboards",
};

export default function Login() {
  const { signIn } = useAuth();
  const { t, lang, setLang } = useI18n();
  const [cat, setCat] = useState(null);
  const [role, setRole] = useState("MINE_MANAGER");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api("/api/auth/roles").then(setCat).catch(() => setErr("Cannot reach the server.")); }, []);
  const accounts = (cat?.demo_accounts || []).filter((a) => a.role === role);
  useEffect(() => {
    if (accounts[0]) { setUsername(accounts[0].username); setPassword(cat?.demo_password_hint || ""); }
    else { setUsername(""); setPassword(""); }
  }, [role, cat]); // eslint-disable-line

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try { signIn(await api("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) })); }
    catch (e2) { setErr(e2.detail || "Sign-in failed"); }
    finally { setBusy(false); }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-3xl">
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src="/icon.svg" alt="" className="h-10 w-10" />
            <div><div className="text-lg font-bold">{t("appName")}</div><div className="text-xs text-ink-400">SIH26009 · MOIL · {t("tagline")}</div></div>
          </div>
          <select className="input" value={lang} onChange={(e) => setLang(e.target.value)} aria-label={t("language")}>
            {LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
          </select>
        </div>
        <form onSubmit={submit} className="card space-y-4 p-6">
          <div>
            <h1 className="text-lg font-semibold">Sign in — choose your role</h1>
            <p className="text-xs text-ink-400">What you can do depends on your role. Mine Managers can approve or reject actions only for their own cluster.</p>
          </div>
          <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-5">
            {(cat?.roles || []).map((r) => {
              const Icon = ICON[r.role] || Pickaxe;
              return (
                <button type="button" key={r.role} onClick={() => setRole(r.role)}
                  className={`rounded-lg border p-3 text-left text-xs transition ${role === r.role ? "border-mn-500 bg-mn-500/15" : "border-ink-700 bg-ink-800/50 hover:bg-ink-800"}`}>
                  <Icon className="mb-1 h-5 w-5 text-mn-300" />
                  <div className="text-sm font-medium text-ink-100">{r.label}</div>
                  <ul className="mt-1 space-y-0.5 text-ink-400">{r.permissions.filter((p) => p !== "read").map((p) => <li key={p}>· {CAN[p]}</li>)}{r.permissions.length === 1 && <li>· {CAN.read}</li>}</ul>
                </button>
              );
            })}
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            {accounts.length > 1 ? (
              <label className="text-sm">Site / account
                <select className="input mt-1 w-full" value={username} onChange={(e) => setUsername(e.target.value)}>
                  {accounts.map((a) => <option key={a.username} value={a.username}>{a.full_name}</option>)}
                </select>
              </label>
            ) : (
              <label className="text-sm">Username<input className="input mt-1 w-full" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" /></label>
            )}
            <label className="text-sm">Password<input className="input mt-1 w-full" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
            <div className="flex items-end"><button className="btn-primary w-full justify-center py-2" disabled={busy || !username || !password}><LogIn className="h-4 w-4" /> {busy ? "Signing in…" : "Sign in"}</button></div>
          </div>
          {err && <p className="text-sm text-rose-300">{err}</p>}
          {cat?.demo_password_hint && <p className="text-[11px] text-amber-300/80">Demo accounts are enabled (password “{cat.demo_password_hint}”). Disable with MH_DEMO_ACCOUNTS=0 and set MH_DEMO_PASSWORD / MH_SECRET for any real deployment.</p>}
        </form>
      </div>
    </div>
  );
}
