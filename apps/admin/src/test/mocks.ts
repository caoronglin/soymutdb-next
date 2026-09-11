/**
 * Shared test doubles for the admin app.
 *
 * `useTranslation` mocks used to be written inline per test file as
 *
 *     useTranslation: () => ({ t: (key) => key })
 *
 * which returns a NEW `t` function on every render. Any component that puts `t`
 * (or `message`) in a `useCallback`/`useEffect` dependency array therefore gets
 * a new callback every render, re-runs its effect every render, and, when that
 * effect fetches and sets state, loops forever. On a real CNB build that showed
 * up as:
 *
 *     AssertionError: expected "vi.fn()" to be called 2 times, but got 224 times
 *     Error: Unable to perform pointer interaction as the element has
 *            `pointer-events: none`
 *
 * i.e. the page was still re-rendering 224 fetches deep while user-event tried
 * to click. The product code is fine; a test double that changes identity every
 * render is not a faithful stand-in for i18next, which memoises `t`.
 *
 * Import `mockTranslation` (or `stableT`) instead of hand-rolling the mock.
 */

/** A `t` with i18next's stable identity and its common signatures. */
export const stableT = (
  key: string,
  options?: { defaultValue?: string } | string,
): string => {
  if (typeof options === "string") return options;
  return options?.defaultValue ?? key;
};

/**
 * Value for `vi.mock("react-i18next", ...)`.
 *
 *     import { mockTranslation } from "../../test/mocks";
 *     vi.mock("react-i18next", () => mockTranslation);
 *
 * The returned hooks are module-level constants, so their identity is stable for
 * the whole test file — which is what components rely on.
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
