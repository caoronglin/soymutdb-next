// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  __resetMotionForTests,
  installRouteMotion,
  parseMotionPreference,
  readMotionTokens,
  resolveMotionDecision,
  supportsViewTransitions,
  useMotion,
  type MotionPreference,
  type MotionReason,
} from "./motion";

/**
 * The motion runtime is the accessibility boundary: `prefers-reduced-motion`
 * and the persisted `off` preference must both stop every animation, and the
 * timings must come from the `--anim-*` tokens instead of a second hardcoded
 * copy. These tests own that contract without a browser.
 */

type Listener = () => void;

/** Install a fake `window.matchMedia` and expose a way to fire `change`. */
function stubMatchMedia(matches: boolean) {
  const listeners = new Set<Listener>();
  const media = {
    matches,
    media: "(prefers-reduced-motion: reduce)",
    addEventListener: (_event: string, listener: Listener) => listeners.add(listener),
    removeEventListener: (_event: string, listener: Listener) => listeners.delete(listener),
  };
  vi.stubGlobal("matchMedia", vi.fn(() => media));
  return {
    setMatches(next: boolean) {
      media.matches = next;
      listeners.forEach((listener) => listener());
    },
  };
}

/** Make the CSS token read deterministic and observable. */
function stubTokens(values: Record<string, string>): void {
  vi.spyOn(window, "getComputedStyle").mockReturnValue({
    getPropertyValue: (property: string) => values[property] ?? "",
  } as CSSStyleDeclaration);
}

beforeEach(() => {
  window.localStorage.clear();
  __resetMotionForTests();
});

afterEach(() => {
  __resetMotionForTests();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("resolveMotionDecision", () => {
  const cases: Array<{
    reduced: boolean;
    preference: MotionPreference;
    animate: boolean;
    effective: string;
    reason: MotionReason;
  }> = [
    { reduced: false, preference: "auto", animate: true, effective: "standard", reason: "auto" },
    {
      reduced: false,
      preference: "off",
      animate: false,
      effective: "off",
      reason: "preference",
    },
    {
      reduced: true,
      preference: "auto",
      animate: false,
      effective: "off",
      reason: "reduced-motion",
    },
    {
      reduced: true,
      preference: "off",
      animate: false,
      effective: "off",
      reason: "reduced-motion",
    },
  ];

  it.each(cases)(
    "reduced=$reduced preference=$preference resolves to $effective",
    ({ reduced, preference, animate, effective, reason }) => {
      expect(resolveMotionDecision({ reduced, preference })).toEqual({
        requested: preference,
        effective,
        animate,
        reason,
      });
    },
  );

  it("lets the OS setting win over an explicit non-off preference", () => {
    for (const preference of ["standard", "minimal"] as const) {
      expect(
        resolveMotionDecision({ reduced: true, preference }),
      ).toMatchObject({ animate: false, effective: "off", reason: "reduced-motion" });
    }
  });

  it("keeps minimal animating with the minimal token set", () => {
    expect(resolveMotionDecision({ reduced: false, preference: "minimal" })).toMatchObject({
      animate: true,
      effective: "minimal",
      reason: "preference",
    });
  });
});

describe("parseMotionPreference", () => {
  it("accepts the persisted vocabulary", () => {
    expect(parseMotionPreference(JSON.stringify({ intensity: "off" }))).toBe("off");
    expect(parseMotionPreference(JSON.stringify({ intensity: "minimal" }))).toBe("minimal");
    expect(parseMotionPreference(JSON.stringify({ intensity: "standard" }))).toBe("standard");
  });

  it("falls back to auto for absent, unknown or malformed storage", () => {
    expect(parseMotionPreference(null)).toBe("auto");
    expect(parseMotionPreference("")).toBe("auto");
    expect(parseMotionPreference("{not json")).toBe("auto");
    expect(parseMotionPreference(JSON.stringify({ intensity: "loud" }))).toBe("auto");
  });
});

describe("readMotionTokens", () => {
  it("parses ms and s values and keeps the CSS easing", () => {
    const reader = {
      getPropertyValue: (property: string) =>
        ({
          "--anim-duration": " 420ms ",
          "--anim-duration-fast": "0.12s",
          "--anim-duration-slow": "700ms",
          "--anim-stagger": "35ms",
          "--anim-easing": "cubic-bezier(0.1, 0.2, 0.3, 0.4)",
          "--anim-easing-spring": "linear",
        })[property] ?? "",
    };

    expect(readMotionTokens(reader)).toEqual({
      durationMs: 420,
      durationFastMs: 120,
      durationSlowMs: 700,
      staggerMs: 35,
      easing: "cubic-bezier(0.1, 0.2, 0.3, 0.4)",
      easingSpring: "linear",
    });
  });

  it("falls back per-token when a value is missing or unparseable", () => {
    const tokens = readMotionTokens({
      getPropertyValue: (property: string) =>
        property === "--anim-duration" ? "quick" : "",
    });
    expect(tokens.durationMs).toBe(300);
    expect(tokens.durationFastMs).toBe(200);
    expect(tokens.durationSlowMs).toBe(500);
    expect(tokens.staggerMs).toBe(60);
    expect(tokens.easing).toContain("cubic-bezier");
  });
});

describe("useMotion", () => {
  it("follows the media query at init and on change", () => {
    const media = stubMatchMedia(false);
    const motion = useMotion();

    expect(motion.reduced.value).toBe(false);
    expect(motion.preference.value).toBe("auto");
    expect(document.documentElement.dataset.anim).toBe("standard");

    media.setMatches(true);
    expect(motion.reduced.value).toBe(true);
    expect(document.documentElement.dataset.anim).toBe("off");

    media.setMatches(false);
    expect(motion.reduced.value).toBe(false);
    expect(document.documentElement.dataset.anim).toBe("standard");
  });

  it("treats a persisted off preference as reduced and persists changes", () => {
    stubMatchMedia(false);
    window.localStorage.setItem("soymutdb-animation-prefs", JSON.stringify({ intensity: "off" }));
    __resetMotionForTests();

    const motion = useMotion();
    expect(motion.reduced.value).toBe(true);
    expect(document.documentElement.dataset.anim).toBe("off");

    motion.setPreference("standard");
    expect(motion.reduced.value).toBe(false);
    expect(JSON.parse(window.localStorage.getItem("soymutdb-animation-prefs") ?? "{}")).toEqual({
      intensity: "standard",
    });
  });

  it("resolves duration, stagger and easing from the CSS tokens", () => {
    stubMatchMedia(false);
    stubTokens({ "--anim-duration": "420ms", "--anim-stagger": "35ms", "--anim-easing": "linear" });

    const motion = useMotion();
    expect(motion.durationMs.value).toBe(420);
    expect(motion.staggerMs.value).toBe(35);
    expect(motion.easing.value).toBe("linear");
  });
});

describe("installRouteMotion", () => {
  function fakeRouter() {
    const handlers: Array<(to: { fullPath: string }, from: { fullPath: string }) => void> = [];
    return {
      handlers,
      afterEach(handler: (to: { fullPath: string }, from: { fullPath: string }) => void) {
        handlers.push(handler);
        return () => {};
      },
      /** Run the registered hook the way Vue Router would. */
      navigate(to: string, from: string) {
        handlers.forEach((handler) => handler({ fullPath: to }, { fullPath: from }));
      },
    };
  }

  it("wraps a real navigation in a view transition", async () => {
    stubMatchMedia(false);
    const router = fakeRouter();
    const host = {
      startViewTransition: vi.fn((update: () => void | Promise<void>) => {
        void update();
        return { finished: Promise.resolve() };
      }),
    };

    installRouteMotion(router, host);
    router.navigate("/about", "/");

    expect(host.startViewTransition).toHaveBeenCalledTimes(1);
    // Let nextTick settle so the queued flush cannot leak into another test.
    await Promise.resolve();
  });

  it("degrades to a plain navigation when startViewTransition is missing", () => {
    stubMatchMedia(false);
    const router = fakeRouter();

    installRouteMotion(router, {});

    expect(() => router.navigate("/about", "/")).not.toThrow();
    expect(router.handlers).toHaveLength(1);
  });

  it("neither wraps the same route twice nor animates under reduced motion", () => {
    const host = { startViewTransition: vi.fn(() => ({ finished: Promise.resolve() })) };
    const router = fakeRouter();

    stubMatchMedia(false);
    installRouteMotion(router, host);
    router.navigate("/", "/");
    expect(host.startViewTransition).not.toHaveBeenCalled();

    stubMatchMedia(true);
    __resetMotionForTests();
    const reducedRouter = fakeRouter();
    installRouteMotion(reducedRouter, host);
    reducedRouter.navigate("/about", "/");
    expect(host.startViewTransition).not.toHaveBeenCalled();
  });

  it("survives a throwing host and still hands back an unregister", () => {
    stubMatchMedia(false);
    const router = fakeRouter();
    const host = {
      startViewTransition: vi.fn(() => {
        throw new Error("unsupported polyfill");
      }),
    };

    const dispose = installRouteMotion(router, host);
    expect(typeof dispose).toBe("function");
    expect(() => router.navigate("/about", "/")).not.toThrow();
  });

  it("detects runtime support without throwing when there is no host", () => {
    expect(supportsViewTransitions({})).toBe(false);
    expect(supportsViewTransitions({ startViewTransition: () => undefined })).toBe(true);
    expect(supportsViewTransitions(null)).toBe(false);
  });
});

describe("SSR safety", () => {
  it("resolves to reduced and touches no DOM when window is absent", async () => {
    vi.resetModules();
    vi.stubGlobal("window", undefined);
    vi.stubGlobal("document", undefined);

    const ssr = await import("./motion");
    const motion = ssr.useMotion();

    expect(motion.reduced.value).toBe(true);
    expect(motion.durationMs.value).toBe(300);
    expect(motion.easing.value).toContain("cubic-bezier");

    const router = {
      afterEach: () => () => {},
    };
    expect(() => ssr.installRouteMotion(router)).not.toThrow();
  });
});
