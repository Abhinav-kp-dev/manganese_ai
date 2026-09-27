import { createContext, useContext, useEffect, useState } from "react";

const Ctx = createContext({ theme: "dark", setTheme: () => {}, toggleTheme: () => {} });

function initialTheme() {
  try {
    const saved = localStorage.getItem("mh-theme");
    if (saved === "light" || saved === "dark") return saved;
  } catch { /* storage unavailable */ }
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(initialTheme);
  useEffect(() => {
    document.documentElement.classList.toggle("light", theme === "light");
    document.documentElement.classList.toggle("dark", theme === "dark");
    try { localStorage.setItem("mh-theme", theme); } catch { /* storage unavailable */ }
  }, [theme]);
  const toggleTheme = () => setTheme((t) => (t === "dark" ? "light" : "dark"));
  return <Ctx.Provider value={{ theme, setTheme, toggleTheme }}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);

// Shared hex palette for chart libraries (Recharts, Leaflet, raw SVG) that
// can't consume Tailwind's CSS-variable-backed utility classes directly.
export function chartColors(theme) {
  const dark = theme !== "light";
  return {
    axis: dark ? "#8b96ad" : "#5b6478",
    grid: dark ? "#222c3f" : "#dbe0ea",
    tooltipBg: dark ? "#18202f" : "#ffffff",
    tooltipBorder: dark ? "#34405a" : "#c7cede",
    text: dark ? "#e8ecf4" : "#0f1420",
    subtext: dark ? "#b4bdd0" : "#475266",
    base: dark ? "#34405a" : "#c7cede",
  };
}
