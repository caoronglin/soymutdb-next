import { beforeEach, afterEach, describe, expect, it } from "vitest";
import {
  DEFAULT_LANGUAGE,
  SUPPORTED_LANGUAGES,
  buildBaseI18nOptions,
  catalogs,
  detectLanguage,
} from "./index";

// detectLanguage reads the browser globals (window/localStorage/navigator), the
// same bare globals the real app sees. Stub them directly on globalThis.
const globalRef = globalThis as unknown as {
  window?: unknown;
  localStorage?: { getItem: (key: string) => string | null };
  navigator?: { language: string };
};

function resetGlobals() {
  delete globalRef.window;
  delete globalRef.localStorage;
  delete globalRef.navigator;
}

function stubBrowser(opts: { stored?: string | null; nav?: string }) {
  globalRef.window = {};
  globalRef.localStorage = { getItem: () => opts.stored ?? null };
  globalRef.navigator = { language: opts.nav ?? "en-US" };
}

beforeEach(resetGlobals);
afterEach(resetGlobals);

describe("i18n core", () => {
  it("declares en/zh with an English default", () => {
    expect(SUPPORTED_LANGUAGES).toEqual(["en", "zh"]);
    expect(DEFAULT_LANGUAGE).toBe("en");
    expect(Object.keys(catalogs)).toEqual(["en", "zh"]);
  });

  it("returns the default language when there is no window (SSR-safe)", () => {
    expect(typeof globalRef.window).toBe("undefined");
    expect(detectLanguage()).toBe(DEFAULT_LANGUAGE);
  });

  it("prefers a stored supported language over the browser hint", () => {
    stubBrowser({ stored: "zh", nav: "en-US" });
    expect(detectLanguage()).toBe("zh");
  });

  it("ignores an unsupported stored value and falls back to the browser hint", () => {
    stubBrowser({ stored: "fr", nav: "zh-CN" });
    expect(detectLanguage()).toBe("zh");
  });

  it("falls back to the default language when nothing indicates a preference", () => {
    stubBrowser({ stored: null, nav: "de-DE" });
    expect(detectLanguage()).toBe("en");
  });

  it("builds base i18next options wiring both catalogs under common + translation", () => {
    const options = buildBaseI18nOptions("zh");
    expect(options.lng).toBe("zh");
    expect(options.fallbackLng).toBe("en");
    expect(options.defaultNS).toBe("common");
    // The same catalog backs both the default namespace and the explicit one.
    expect(options.resources.zh.translation).toBe(options.resources.zh.common);
    expect(options.resources.en).toBeTruthy();
    expect(options.interpolation.escapeValue).toBe(false);
  });
});
