import { catalogs } from "@soymutdb/i18n-core";

import { EXTRA_RESOURCES, HOME_RESOURCES, TOOLS_RESOURCES } from "../lib/i18n-resources";

/**
 * Shared test doubles for the public portal.
 *
 * Inline `useTranslation` mocks of the form
 *
 *     useTranslation: () => ({ t: (key) => key })
 *
 * return a NEW `t` function on every render. Any component that lists `t` in a
 * `useCallback`/`useEffect` dependency array then gets a new callback every
 * render and re-runs its effect every render; if that effect fetches and sets
 * state, it loops. On a real CNB build the admin suite showed the symptom
 * directly:
 *
 *     expected "vi.fn()" to be called 2 times, but got 224 times
 *
 * i18next memoises `t`, so a per-render `t` is not a faithful stand-in. Import
 * `mockTranslation` instead of hand-rolling the mock.
 */

/**
 * Deep-merge portal resource bundles the way `addResourceBundle(..., true)`
 * does in `lib/i18n.ts`, so the double resolves the same English copy the app
 * actually renders (including the runtime-only portal/tools/home bundles).
 */
function deepMerge(
  target: Record<string, unknown>,
  source: Record<string, unknown>,
): Record<string, unknown> {
  const merged: Record<string, unknown> = { ...target };
  for (const [key, value] of Object.entries(source)) {
    const existing = merged[key];
    merged[key] =
      typeof existing === "object" &&
      existing !== null &&
      typeof value === "object" &&
      value !== null
        ? deepMerge(existing as Record<string, unknown>, value as Record<string, unknown>)
        : value;
  }
  return merged;
}

const EN_RESOURCES = [EXTRA_RESOURCES.en, TOOLS_RESOURCES.en, HOME_RESOURCES.en].reduce(
  (acc, bundle) => deepMerge(acc, bundle as Record<string, unknown>),
  catalogs.en as unknown as Record<string, unknown>,
);

/**
 * The English catalog value for a dotted key, if the key exists.
 *
 * A double that only returns `defaultValue ?? key` hides a real class of bug:
 * the component translated its copy, but no test can tell the rendered English
 * text apart from a missing key. Resolving the shared catalog makes the mock
 * behave like i18next for the strings the bundles actually define, while keys
 * that no bundle defines still fall through to `defaultValue`/key exactly as
 * before.
 */
function catalogValue(key: string): string | undefined {
  let node: unknown = EN_RESOURCES;
  for (const part of key.split(".")) {
    if (typeof node !== "object" || node === null) return undefined;
    node = (node as Record<string, unknown>)[part];
  }
  return typeof node === "string" ? node : undefined;
}

/**
 * A `t` with i18next's stable identity and its most-used semantics:
 * catalog lookup, `defaultValue` fallback and `{{name}}` interpolation.
 *
 * Interpolation matters. Components legitimately write
 *
 *     t("admin.ops.validationErrors", {
 *       errors: String(count),
 *       defaultValue: "{{errors}} validation errors",
 *     })
 *
 * and assert the interpolated output. A double that returns `defaultValue`
 * verbatim renders the literal `{{errors}} validation errors`, which reads as a
 * product bug — it cost a real CNB build, because the test did not initialise
 * i18next either and nothing substituted the placeholder.
 */
export const stableT = (
  key: string,
  options?: { defaultValue?: string; [name: string]: unknown } | string,
): string => {
  // `t(key, "literal")` is the shorthand for a plain default.
  if (typeof options === "string") return options;
  const template = catalogValue(key) ?? options?.defaultValue ?? key;
  return template.replace(/\{\{\s*([\w.]+)\s*\}\}/g, (match, name: string) => {
    const value = options?.[name];
    return value === undefined || value === null ? match : String(value);
  });
};

/** Value for `vi.mock("react-i18next", ...)`; hooks have stable identity. */
export const mockTranslation = {
  useTranslation: () => ({
    t: stableT,
    i18n: { language: "en", changeLanguage: async () => undefined },
    ready: true,
  }),
  Trans: ({ children }: { children?: unknown }) => children,
  initReactI18next: { type: "3rdParty", init: () => undefined },
};
