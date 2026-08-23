// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FluidGradient } from "../fluids/fluid-gradient";

describe("FluidGradient", () => {
  it("renders a decorative full-bleed canvas with overlay content", () => {
    const { container } = render(
      <FluidGradient reduced>
        <span>Overlay copy</span>
      </FluidGradient>,
    );

    expect(screen.getByText("Overlay copy")).toBeTruthy();
    expect(container.querySelector("canvas")).toBeTruthy();
    // Decorative background must be hidden from assistive tech.
    expect(container.firstElementChild?.getAttribute("aria-hidden")).toBe("true");
  });

  it("falls back to a CSS gradient when WebGL2 is unavailable", () => {
    // jsdom has no WebGL2; the component must still render, not throw.
    const { container } = render(<FluidGradient reduced />);
    const wrapper = container.firstElementChild as HTMLElement;
    expect(wrapper.style.background).toContain("linear-gradient");
  });
});
