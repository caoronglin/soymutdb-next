import { expect, afterEach, vi } from "vitest";
import * as matchers from "@testing-library/jest-dom/matchers";
import { cleanup } from "@testing-library/react";

// Explicit registration — the "@testing-library/jest-dom/vitest" entry
// doesn't extend expect reliably under vitest 4.1.10 + forks pool.
expect.extend(matchers);

// AntD responsive components (ProTable/Grid) call window.matchMedia; jsdom
// does not implement it. Provide a minimal always-false mock.
if (!globalThis.ResizeObserver) {
  class ResizeObserverMock {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverMock as typeof ResizeObserver;
}

if (!window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

// Initialise the REAL i18next before any component renders.
//
// Components legitimately call
//
//     t("admin.ops.validationErrors", {
//       errors: String(count),
//       defaultValue: "{{errors}} validation errors",
//     })
//
// and assert the interpolated output. Without an initialised instance, i18next
// returns `defaultValue` verbatim, so the DOM contained the literal
// `{{errors}} validation errors` and the assertion failed — a real CNB failure
// that reads like a product bug but is a missing test bootstrap. Initialising
// here means tests exercise the same translation pipeline as the app, and the
// key map stays in one place (packages/i18n) instead of drifting per test file.
import { initI18n } from "@soymutdb/i18n";

initI18n("en");

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
