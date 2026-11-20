import * as React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const animation = vi.hoisted(() => ({
  reduced: false,
  duration: 300,
  durationSlow: 500,
  stagger: 60,
}));

vi.mock("../lib/animation-context", () => ({
  useAnimationOptional: () => animation,
}));

import { FadeUp, Stagger, TextReveal, useReveal } from "./route-motion";

afterEach(cleanup);

beforeEach(() => {
  animation.reduced = false;
});

describe("route-motion", () => {
  it("renders children inside a plain element when motion is off", () => {
    animation.reduced = true;
    render(
      <FadeUp data-testid="fade" className="section">
        <span>static content</span>
      </FadeUp>,
    );
    const element = screen.getByTestId("fade");
    expect(element.tagName).toBe("DIV");
    expect(element.className).toBe("section");
    expect(element.style.opacity).toBe("");
    expect(element.textContent).toBe("static content");
  });

  it("keeps the public element and children when animation is enabled", () => {
    render(
      <FadeUp data-testid="fade" className="section" delay={120}>
        <span>animated content</span>
      </FadeUp>,
    );
    const element = screen.getByTestId("fade");
    expect(element.className).toBe("section");
    expect(element.textContent).toBe("animated content");
  });

  it("staggers children without dropping any content", () => {
    render(
      <Stagger data-testid="stagger" baseDelay={50} step={25}>
        <p>first</p>
        <p>second</p>
        <p>third</p>
      </Stagger>,
    );
    const element = screen.getByTestId("stagger");
    expect(element.textContent).toBe("firstsecondthird");
    expect(element.querySelectorAll("p")).toHaveLength(3);
  });

  it("renders staggered children directly when motion is off", () => {
    animation.reduced = true;
    render(
      <Stagger data-testid="stagger">
        <p>first</p>
        <p>second</p>
      </Stagger>,
    );
    const element = screen.getByTestId("stagger");
    expect(element.children).toHaveLength(2);
    expect(element.textContent).toBe("firstsecond");
  });

  it("splits text into words while preserving the original string", () => {
    render(<TextReveal data-testid="text" text="Soy mutant database" />);
    const element = screen.getByTestId("text");
    expect(element.tagName).toBe("SPAN");
    expect(element.textContent).toBe("Soy mutant database");
  });

  it("returns the caller-owned ref from useReveal", () => {
    let seen: React.RefObject<HTMLDivElement | null> | undefined;
    function Probe() {
      const ref = React.useRef<HTMLDivElement>(null);
      seen = useReveal(ref, { threshold: 0.05 });
      return <div ref={ref} />;
    }
    render(<Probe />);
    expect(seen).toBeDefined();
    expect(seen?.current).toBeInstanceOf(HTMLDivElement);
  });
});