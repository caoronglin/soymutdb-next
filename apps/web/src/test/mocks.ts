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
 * A `t` with i18next's stable identity and its most-used semantics:
 * `defaultValue` fallback plus `{{name}}` interpolation.
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
  const template = options?.defaultValue ?? key;
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
