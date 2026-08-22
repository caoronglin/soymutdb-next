// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CountUp, FadeIn, FadeUp, Reveal, ScaleIn, Stagger, TextReveal } from "../route-motion";

const motionProps = {
  baseDelay: 500,
  delay: 120,
  once: true,
  stagger: 80,
  step: 40,
  variant: "fade-up",
};

describe("route motion wrappers", () => {
  it("does not leak motion-only props into rendered markup", () => {
    render(
      <>
        <FadeUp data-testid="fade-up" {...motionProps}>Fade up</FadeUp>
        <FadeIn data-testid="fade-in" {...motionProps}>Fade in</FadeIn>
        <ScaleIn data-testid="scale-in" {...motionProps}>Scale in</ScaleIn>
        <Reveal data-testid="reveal" {...motionProps}>Reveal</Reveal>
        <Stagger data-testid="stagger" {...motionProps}>Stagger</Stagger>
        <TextReveal data-testid="text-reveal" {...motionProps} text="Text reveal" />
        <CountUp data-testid="count-up" {...motionProps} end={1} />
      </>,
    );

    for (const testId of [
      "fade-up",
      "fade-in",
      "scale-in",
      "reveal",
      "stagger",
      "text-reveal",
      "count-up",
    ]) {
      const element = screen.getByTestId(testId);
      for (const attribute of ["basedelay", "delay", "once", "stagger", "step", "variant"]) {
        expect(element.hasAttribute(attribute)).toBe(false);
      }
    }
  });
});
