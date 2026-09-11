/**
 * Shared test doubles for i18n in component tests.
 *
 * Two problems this file exists to prevent, both observed on a real CNB build:
 *
 * 1. **Unstable identity.** A mock written inline as
 *
 *        useTranslation: () => ({ t: (key) => key })
 *
 *    returns a NEW `t` on every render. Any component with `t` in a
 *    `useCallback`/`useEffect` dependency array then gets a new callback every
 *    render and re-runs its effect every render. When that effect fetches and
 *    sets state, it loops:
 *
 *        expected "vi.fn()" to be called 2 times, but got 224 times
 *        Error: Unable to perform pointer interaction as the element has
 *               `pointer-events: none`
 *
 *    i18next memoises `t`; this double does too.
 *
 * 2. **Missing interpolation.** i18next substitutes `{{name}}` placeholders from
 *    the options object. A double that returns `defaultValue` verbatim renders
 *    the literal template:
 *
 *        t("admin.ops.validationErrors", {
 *          errors: String(count),
 *          defaultValue: "{{errors}} validation errors",
 *        })                        // -> "{{errors}} validation errors"
 *
 *    which looks like a product bug. Substitution is implemented below.
 *
 * Tests that do not mock `react-i18next` get the real, initialised instance from
 * `src/test/setup.ts`. Import `mockTranslation` when a test needs a stubbed
 * translation surface.
 */

/**
 * A `t` with i18next's stable identity and its most-used semantics:
 * `defaultValue` fallback plus `{{name}}` interpolation.
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

/**
 * Value for `vi.mock("react-i18next", ...)`.
 *
 *     import { mockTranslation } from "<relative>/test/mocks";
 *     vi.mock("react-i18next", async () => (await import("<relative>/test/mocks")).mockTranslation);
 *
 * The async factory is required because `vi.mock` is hoisted above imports; a
 * static import of this module inside the factory would be hoisted too.
 * `useTranslation` returns module-level constants, so identity is stable for the
 * whole test file.
 */
export const mockTranslation = {
  useTranslation: () => ({
    t: stableT,
    i18n: { language: "en", changeLanguage: async () => undefined },
    ready: true,
  }),
  Trans: ({ children }: { children?: unknown }) => children,
  initReactI18next: { type: "3rdParty", init: () => undefined },
};
