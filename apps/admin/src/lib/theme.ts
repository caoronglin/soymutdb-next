/**
 * Console colour theme.
 *
 * The React console toggled `data-theme` on `<html>` and read it back on mount;
 * `style.css` already defines the dark token set for `[data-theme="dark"]`.
 * Module state keeps one source of truth without a store: the shell is the only
 * consumer, and a second mounted toggle would otherwise fight the first.
 */
import { readonly, ref } from "vue";

export type AdminTheme = "light" | "dark";

function readInitialTheme(): AdminTheme {
  if (typeof document === "undefined") return "light";
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

const theme = ref<AdminTheme>(readInitialTheme());

export function useAdminTheme() {
  function setTheme(next: AdminTheme): void {
    theme.value = next;
    document.documentElement.setAttribute("data-theme", next);
  }

  function toggleTheme(): void {
    setTheme(theme.value === "dark" ? "light" : "dark");
  }

  return { theme: readonly(theme), setTheme, toggleTheme };
}
