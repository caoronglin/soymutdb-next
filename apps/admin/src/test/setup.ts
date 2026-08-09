import { expect, afterEach, vi } from "vitest";
import * as matchers from "@testing-library/jest-dom/matchers";
import { cleanup } from "@testing-library/react";

// Explicit registration — the "@testing-library/jest-dom/vitest" entry
// doesn't extend expect reliably under vitest 4.1.10 + forks pool.
expect.extend(matchers);

// AntD responsive components (ProTable/Grid) call window.matchMedia; jsdom
// does not implement it. Provide a minimal always-false mock.
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

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
