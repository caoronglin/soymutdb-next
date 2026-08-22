// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { startViewTransition } from "../view-transitions";

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("view transition motion policy", () => {
  it("does not start a transition when the saved motion preference is off", () => {
    localStorage.setItem("soymutdb-animation-prefs", JSON.stringify({ intensity: "off" }));
    const transition = vi.fn(() => ({ ready: Promise.resolve(), finished: Promise.resolve() }));
    Object.defineProperty(document, "startViewTransition", {
      configurable: true,
      value: transition,
    });
    const update = vi.fn();

    expect(startViewTransition(update)).toBeNull();
    expect(transition).not.toHaveBeenCalled();
  });
});
