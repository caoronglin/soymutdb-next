import { expect, afterEach } from "vitest";
import * as matchers from "@testing-library/jest-dom/matchers";
import { cleanup } from "@testing-library/react";

// Explicit registration — the "@testing-library/jest-dom/vitest" entry
// doesn't extend expect reliably under vitest 4.1.10 + forks pool.
expect.extend(matchers);

afterEach(() => {
  cleanup();
});
