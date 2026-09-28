/**
 * Portal colour theme.
 *
 * The theme is document state, not header state: `style.css` defines the dark
 * token set on `[data-theme="dark"]`, and the Ant Design `ConfigProvider` in
 * `PortalLayout` needs the same boolean to switch its algorithm. Module state
 * keeps one source of truth without a store — the header owns the only toggle,
 * and a second mounted toggle would otherwise fight the first.
 */
import { readonly, ref } from "vue";

export type PortalTheme = "light" | "dark";

const STORAGE_KEY = "soymutdb_theme";

function readStoredTheme(): PortalTheme {
  if (typeof window === "undefined") return "light";
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "dark" ? "dark" : "light";
  } catch {
    // Storage can be blocked (private mode, hardened browsers); default to light.
    return "light";
  }
}

const theme = ref<PortalTheme>(readStoredTheme());

/** Mirror the theme onto `<html>` so the CSS token set and Tailwind's `dark:` variant follow. */
function applyTheme(next: PortalTheme): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.classList.toggle("dark", next === "dark");
  root.dataset.theme = next;
}

export function usePortalTheme() {
  function setTheme(next: PortalTheme): void {
    theme.value = next;
    applyTheme(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // The in-memory selection still applies for this session.
    }
  }

  function toggleTheme(): void {
    setTheme(theme.value === "dark" ? "light" : "dark");
  }

  return { theme: readonly(theme), setTheme, toggleTheme, applyTheme };
}
