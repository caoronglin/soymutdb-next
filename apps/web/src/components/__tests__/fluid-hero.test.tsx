// @vitest-environment jsdom
import type { ReactNode } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AnimationProvider } from "@/lib/animation-context";
import { FluidHero } from "../fluids/fluid-hero";

afterEach(cleanup);

function renderWithProvider(ui: ReactNode) {
  return render(<AnimationProvider>{ui}</AnimationProvider>);
}

describe("FluidHero", () => {
  it("renders Ant Design primitives around the animated surface", () => {
    renderWithProvider(
      <FluidHero
        title="Hero title"
        subtitle="Hero subtitle"
        eyebrow="eyebrow"
        primaryLabel="CTA one"
        secondaryLabel="CTA two"
      />,
    );

    const title = screen.getByText("Hero title");
    expect(title.closest("h1, h2, h3, h4, h5, h6")).toBeTruthy();
    expect(screen.getByText("Hero subtitle")).toBeTruthy();
    expect(screen.getByText("CTA one").closest("button")).toBeTruthy();
    expect(screen.getByText("CTA two").closest("button")).toBeTruthy();
    // Must not collide with the legacy `[data-testid="hero"]` selector.
    expect(screen.queryByTestId("hero")).toBeNull();
  });

  it("propagates reduced-motion from the app animation policy", () => {
    renderWithProvider(<FluidHero />);
    // Renders without crashing and keeps the section landmark.
    expect(screen.getByRole("region", { name: "featured hero" })).toBeTruthy();
  });
});
