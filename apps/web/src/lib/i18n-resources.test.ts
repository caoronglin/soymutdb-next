import { describe, expect, it } from "vitest";

import { EXTRA_RESOURCES, HOME_RESOURCES, TOOLS_RESOURCES } from "./i18n-resources";

/**
 * The portal-only bundles are merged over `@soymutdb/i18n-core` at runtime, so
 * they are outside the shared catalog and outside
 * `packages/i18n-core/check-locale-keys.mjs`. A key added here in one language
 * only renders as the English fallback on the Chinese site — silently, since
 * i18next keeps the key/`defaultValue` instead of failing.
 */
function keyPaths(value: unknown, prefix = ""): string[] {
  if (value === null || typeof value !== "object") return [prefix];
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
    keyPaths(child, prefix ? `${prefix}.${key}` : key),
  );
}

const BUNDLES = {
  EXTRA_RESOURCES,
  TOOLS_RESOURCES,
  HOME_RESOURCES,
} as const;

describe("portal i18n resource parity", () => {
  for (const [name, bundle] of Object.entries(BUNDLES)) {
    it(`${name} defines the same keys in en and zh`, () => {
      const en = keyPaths(bundle.en).sort();
      const zh = keyPaths(bundle.zh).sort();
      expect(zh.filter((key) => !en.includes(key))).toEqual([]);
      expect(en.filter((key) => !zh.includes(key))).toEqual([]);
    });
  }

  it("translates the gene detail loading copy in both languages", () => {
    // The skeleton announces the wait; an untranslated announcement is the
    // first thing a Chinese reader hears from the page.
    expect(EXTRA_RESOURCES.en.genes).toMatchObject({ loading: expect.any(String) });
    expect(EXTRA_RESOURCES.zh.genes).toMatchObject({ loading: expect.any(String) });
    const en = EXTRA_RESOURCES.en.genes as Record<string, string>;
    const zh = EXTRA_RESOURCES.zh.genes as Record<string, string>;
    expect(zh.loading).not.toBe(en.loading);
  });
});