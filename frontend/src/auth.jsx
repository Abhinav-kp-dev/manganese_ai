import { createContext, useContext, useEffect, useState } from "react";

const KEY = "mh-session";
const Ctx = createContext(null);

export function getToken() {
  try { return JSON.parse(localStorage.getItem(KEY) || "null")?.token || null; } catch { return null; }
}

export function AuthProvider({ children }) {
  const [session, setSession] = useState(() => { try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch { return null; } });
  const save = (s) => { setSession(s); try { s ? localStorage.setItem(KEY, JSON.stringify(s)) : localStorage.removeItem(KEY); } catch { /* storage unavailable */ } };
  useEffect(() => {
    const out = () => save(null);
    window.addEventListener("mh-logout", out);
    return () => window.removeEventListener("mh-logout", out);
  }, []);
  const user = session?.user || null;
  const can = (perm) => !!user?.permissions.includes(perm);
  const inScope = (mine) => !!user && (user.site_scope === "ALL" || mine?.mine_id === user.site_scope || mine?.cluster_id === user.site_scope);
  return <Ctx.Provider value={{ user, signIn: save, signOut: () => save(null), can, inScope }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
