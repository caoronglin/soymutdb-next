// @vitest-environment jsdom
import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import RevealOnMount from "./RevealOnMount.vue";
import { __resetMotionForTests } from "../../lib/motion";

/**
 * The reveal is the SSG-sensitive part of the motion system: the prerendered /
 * first paint must stay visible, so the component may not ship an
 * `opacity: 0` initial state — it arms the animation in `onMounted` instead.
 * These tests own that contract plus the reduced-motion opt-out.
 */

const ACTIVE_CLASS = "motion-reveal--active";

function stubMatchMedia(matches: boolean): void {
  vi.stubGlobal("matchMedia", () =>
    ({
      matches,
      media: "(prefers-reduced-motion: reduce)",
      addEventListener: () => {},
      removeEventListener: () => {},
    }) as unknown as MediaQueryList,
  );
}

function mountReveal(props: Record<string, unknown> = {}) {
  return mount(RevealOnMount, {
    props,
    slots: { default: "<p>block content</p>" },
  });
}

beforeEach(() => {
  __resetMotionForTests();
  stubMatchMedia(false);
});

afterEach(() => {
  __resetMotionForTests();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("RevealOnMount", () => {
  it("plays the entrance when motion is allowed", () => {
    const wrapper = mountReveal();
    const root = wrapper.element as HTMLElement;

    expect(wrapper.text()).toContain("block content");
    expect(root.classList.contains(ACTIVE_CLASS)).toBe(true);
  });

  it("does not play under reduced motion but keeps the content", () => {
    stubMatchMedia(true);
    const wrapper = mountReveal();

    expect(wrapper.text()).toContain("block content");
    expect((wrapper.element as HTMLElement).classList.contains(ACTIVE_CLASS)).toBe(false);
  });

  it("stays visible in both modes: no inline hidden state is emitted", () => {
    for (const reduced of [false, true]) {
      stubMatchMedia(reduced);
      __resetMotionForTests();
      const wrapper = mountReveal();

      const style = (wrapper.element as HTMLElement).getAttribute("style") ?? "";
      expect(style).not.toContain("opacity");
      // The wrapper is a real element with the copy in the DOM either way.
      expect(wrapper.element as HTMLElement).toBeInstanceOf(HTMLElement);
    }
  });

  it("renders the requested tag", () => {
    const wrapper = mountReveal({ as: "section" });
    expect(wrapper.element.tagName).toBe("SECTION");
  });

  it("derives the animation delay from `delay` and `index` × stagger token", () => {
    const wrapper = mountReveal({ delay: 40, index: 2 });
    // jsdom has no style engine, so the token falls back to 60ms.
    expect((wrapper.element as HTMLElement).style.animationDelay).toBe("160ms");
  });

  it("honours `disabled` even when motion is allowed", () => {
    const wrapper = mountReveal({ disabled: true });
    expect((wrapper.element as HTMLElement).classList.contains(ACTIVE_CLASS)).toBe(false);
  });
});
