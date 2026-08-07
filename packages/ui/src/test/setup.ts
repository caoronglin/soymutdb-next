import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Auto-cleanup between tests (vitest runs without globals here).
afterEach(() => {
  cleanup();
});
