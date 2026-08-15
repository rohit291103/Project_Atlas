/* Theme as an explicit choice, not only an OS reading.
 *
 * The old build only had `@media (prefers-color-scheme)`, which assumes the
 * reviewer's OS preference is the right answer for this app. It usually isn't:
 * the target user spends the day in Jira and Confluence, both light, and lands
 * here from them. So there are three states — system, light, dark — and the
 * choice persists.
 *
 * `data-theme` on <html> is what the stylesheet keys on, and it wins over the
 * media query in both directions.
 */

import { useCallback, useEffect, useState } from "react";

export type Theme = "system" | "light" | "dark";

const KEY = "atlas.theme";
const ORDER: Theme[] = ["system", "light", "dark"];

const read = (): Theme => {
  const stored = window.localStorage.getItem(KEY);
  return stored === "light" || stored === "dark" || stored === "system" ? stored : "system";
};

export const THEME_LABELS: Record<Theme, string> = {
  system: "System theme",
  light: "Light theme",
  dark: "Dark theme",
};

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(read);

  useEffect(() => {
    const root = document.documentElement;
    // "system" removes the attribute entirely rather than stamping a guess, so
    // the media query is what answers — which is what "system" means.
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    window.localStorage.setItem(KEY, theme);
  }, [theme]);

  const cycle = useCallback(
    () => setTheme((current) => ORDER[(ORDER.indexOf(current) + 1) % ORDER.length] ?? "system"),
    [],
  );

  return [theme, cycle];
}
