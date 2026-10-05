// @vitest-environment jsdom
/**
 * `getMotionPrefs` is the browser-capability probe. It has no injected seam —
 * it reads `window.matchMedia` and `navigator` directly — so each case pins a
 * `navigator` and a `matchMedia` and asserts the resulting triple.
 *
 * The three signals are independent inputs to `resolveMotionDecision`, so the
 * cases below cover them one at a time and then pin the two that share an
 * OR branch in the `lowPower` expression.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { getMotionPrefs } from "./motion-prefs";

interface NavigatorShape {
  userAgent?: string;
  hardwareConcurrency?: number;
  deviceMemory?: number;
  connection?: { saveData?: boolean };
}

/**
 * Install a `navigator` and a `matchMedia`. Unspecified keys are omitted
 * entirely rather than set to `undefined`, because the implementation reads
 * them with `?? default` and the two are not distinguishable.
 */
function stubEnvironment(
  nav: NavigatorShape = {},
  options: { reduced?: boolean; noMatchMedia?: boolean } = {},
): void {
  vi.stubGlobal("navigator", { userAgent: "desktop", ...nav });
  if (options.noMatchMedia) {
    vi.stubGlobal("matchMedia", undefined);
    return;
  }
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
    matches: options.reduced === true,
    media: query,
  })));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getMotionPrefs", () => {
  it("reads reduced-motion from the media query", () => {
    stubEnvironment({}, { reduced: true });
    expect(getMotionPrefs().reduced).toBe(true);

    stubEnvironment({}, { reduced: false });
    expect(getMotionPrefs().reduced).toBe(false);
  });

  it("queries the prefers-reduced-motion media query specifically", () => {
    const matchMedia = vi.fn(() => ({ matches: false, media: "" }));
    vi.stubGlobal("navigator", { userAgent: "desktop" });
    vi.stubGlobal("matchMedia", matchMedia);

    getMotionPrefs();

    expect(matchMedia).toHaveBeenCalledWith("(prefers-reduced-motion: reduce)");
  });

  it("treats a missing matchMedia as not reduced", () => {
    // Optional-call guard: an engine without matchMedia must not throw.
    stubEnvironment({ hardwareConcurrency: 8, deviceMemory: 8 }, { noMatchMedia: true });
    expect(getMotionPrefs().reduced).toBe(false);
  });

  it("reads save-data from the network connection when present", () => {
    stubEnvironment({ connection: { saveData: true } });
    expect(getMotionPrefs().saveData).toBe(true);

    stubEnvironment({ connection: { saveData: false } });
    expect(getMotionPrefs().saveData).toBe(false);
  });

  it("treats an absent connection as not save-data", () => {
    stubEnvironment();
    expect(getMotionPrefs().saveData).toBe(false);
  });

  it("flags low power on few cores or little memory", () => {
    stubEnvironment({ hardwareConcurrency: 2, deviceMemory: 8 });
    expect(getMotionPrefs().lowPower).toBe(true);

    stubEnvironment({ hardwareConcurrency: 8, deviceMemory: 2 });
    expect(getMotionPrefs().lowPower).toBe(true);
  });

  it("flags low power on a mobile user agent regardless of specs", () => {
    for (const userAgent of [
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
      "Mozilla/5.0 (Linux; Android 14; Pixel 8)",
      "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)",
    ]) {
      stubEnvironment({ userAgent, hardwareConcurrency: 12, deviceMemory: 8 });
      expect(getMotionPrefs().lowPower).toBe(true);
    }
  });

  it("does not flag a capable desktop", () => {
    stubEnvironment({ userAgent: "Mozilla/5.0 (X11; Linux x86_64)", hardwareConcurrency: 8, deviceMemory: 8 });
    expect(getMotionPrefs()).toEqual({ reduced: false, saveData: false, lowPower: false });
  });

  it("uses mid-range defaults when the device reports nothing", () => {
    // `?? 4` for both cores and memory: 4 > 2, so the fallback reads as a
    // capable desktop rather than a constrained one.
    stubEnvironment();
    expect(getMotionPrefs()).toEqual({ reduced: false, saveData: false, lowPower: false });
  });

  it("reports the three signals independently", () => {
    stubEnvironment(
      { userAgent: "Mozilla/5.0 (iPhone)", hardwareConcurrency: 1, connection: { saveData: true } },
      { reduced: true },
    );
    expect(getMotionPrefs()).toEqual({ reduced: true, saveData: true, lowPower: true });
  });
});
