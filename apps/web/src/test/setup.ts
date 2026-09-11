/**
 * Shared test bootstrap for the public portal.
 *
 * The admin app already had a setup file; the portal did not, so any test that
 * relied on an initialised i18next silently got `defaultValue` returned
 * verbatim. Initialise the real instance here so component tests exercise the
 * same translation pipeline as the app, and the key map stays in one place
 * (packages/i18n) instead of drifting per test file.
 */
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import { initI18n } from "@soymutdb/i18n";

initI18n("en");

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
