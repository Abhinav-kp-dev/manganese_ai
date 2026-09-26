import { useCallback, useEffect, useState } from "react";
import { del, get, keys, set } from "idb-keyval";
import { getToken } from "./auth.jsx";

const BASE = import.meta.env.VITE_API_BASE || "";

export async function api(path, opts = {}) {
  const token = getToken();
  const headers = { ...(opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(opts.headers || {}) };
  const res = await fetch(BASE + path, { ...opts, headers });
  if (res.status === 401 && token && !path.startsWith("/api/auth/login")) window.dispatchEvent(new Event("mh-logout"));
  if (!res.ok) {
    const err = new Error(`${res.status}`);
    err.status = res.status;
    try { err.detail = (await res.json()).detail; } catch { /* non-JSON */ }
    throw err;
  }
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  if (!opts.method || opts.method === "GET") set(`cache:${path}`, data).catch(() => {});
  return data;
}

// GET with IndexedDB fallback so pages still render at connectivity-poor sites.
export function useApi(path, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true, stale: false });
  const load = useCallback(async () => {
    if (!path) return;
    setState((s) => ({ ...s, loading: true }));
    for (let attempt = 0; attempt < 20; attempt++) {
      try {
        const data = await api(path);
        setState({ data, error: null, loading: false, stale: false });
        return;
      } catch (e) {
        if (e.status === 503) { setState((s) => ({ ...s, training: true })); await new Promise((r) => setTimeout(r, 3000)); continue; }
        const cached = await get(`cache:${path}`).catch(() => null);
        setState(cached ? { data: cached, error: null, loading: false, stale: true } : { data: null, error: e, loading: false, stale: false });
        return;
      }
    }
  }, [path]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load, ...deps]); // eslint-disable-line react-hooks/exhaustive-deps
  return { ...state, reload: load };
}

// Offline-first decision log: queued in IndexedDB, flushed when connectivity returns.
export async function submitDecision(entry) {
  const payload = { ...entry, client_timestamp: new Date().toISOString() };
  if (navigator.onLine) {
    try { return { synced: true, ...(await api("/api/audit", { method: "POST", body: JSON.stringify(payload) })) }; }
    catch (e) { if (e.status && e.status !== 503) return { synced: false, error: e.detail || `Error ${e.status}` }; }
  }
  await set(`queue:${Date.now()}:${Math.random().toString(36).slice(2)}`, { ...payload, synced_offline: true });
  window.dispatchEvent(new Event("mh-queue"));
  return { synced: false };
}

export async function pendingCount() {
  return (await keys()).filter((k) => String(k).startsWith("queue:")).length;
}

export async function flushQueue() {
  let sent = 0;
  for (const k of (await keys()).filter((k) => String(k).startsWith("queue:"))) {
    try {
      await api("/api/audit", { method: "POST", body: JSON.stringify(await get(k)) });
      await del(k);
      sent++;
    } catch (e) {
      if (e.status === 403 || e.status === 422) { await del(k); continue; } // permanently refused: drop
      break;
    }
  }
  window.dispatchEvent(new Event("mh-queue"));
  return sent;
}

export const fmt = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v) ? "—" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d }));
export const pct = (v, d = 0) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(d)}%`);
export const monthLabel = (m) => (m ? new Date(`${m}-01T00:00:00`).toLocaleString("en-IN", { month: "short", year: "numeric" }) : "");
