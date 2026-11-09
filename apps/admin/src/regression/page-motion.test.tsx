// ABLATION — page entrance choreography runs through TweenOne and honours the
// console motion policy.
//
// Invariants:
// 1. `off` produces no timeline at all, so a reduced-motion user gets the page
//    without a wrapper, transform or animation frame.
// 2. `minimal` only fades; `standard` fades and lifts. A minimal mode that
//    still moves would make "less motion" a label rather than a behaviour.
// 3. The layout actually uses the transition, so the policy is connected to
//    the routed page and not just to a unit-tested helper.
//
// Ablation proof: the assertions below pin the exact keyframe durations and the
// presence/absence of `y`, so changing the policy in either direction fails.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AdminPageTransition } from "../components/page-transition";
import { pageRevealAnimation } from "../lib/page-motion";

const here = dirname(fileURLToPath(import.meta.url));
const rootSource = readFileSync(join(here, "../routes/__root.tsx"), "utf8");

function stubReducedMotion(reduced: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: reduced && query.includes("prefers-reduced-motion"),
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

describe("admin page motion", () => {
  it("has no timeline when motion is off", () => {
    expect(pageRevealAnimation("off")).toBeNull();
  });

  it("fades without moving in minimal mode", () => {
    const animation = pageRevealAnimation("minimal");
    expect(animation).not.toBeNull();
    expect(animation).toHaveLength(2);
    expect(animation?.every((frame) => frame.y === undefined)).toBe(true);
    expect(animation?.map((frame) => frame.duration)).toEqual([0, 120]);
    expect(animation?.at(-1)?.opacity).toBe(1);
  });

  it("fades and lifts in standard mode", () => {
    const animation = pageRevealAnimation("standard");
    expect(animation).toHaveLength(2);
    expect(animation?.map((frame) => frame.duration)).toEqual([0, 260]);
    expect(animation?.[0]).toMatchObject({ opacity: 0, y: 6, duration: 0 });
    expect(animation?.[1]).toMatchObject({ opacity: 1, y: 0, duration: 260 });
  });

  it("renders the routed page inside the transition", () => {
    stubReducedMotion(false);
    render(
      <AdminPageTransition motionKey="/" className="page-body">
        <span>dashboard body</span>
      </AdminPageTransition>,
    );
    expect(screen.getByText("dashboard body")).toBeInTheDocument();
    expect(screen.getByText("dashboard body").parentElement?.className).toContain("page-body");
  });

  it("renders without the timeline when the OS asks for reduced motion", () => {
    stubReducedMotion(true);
    const { container } = render(
      <AdminPageTransition motionKey="/" className="page-body">
        <span>reduced body</span>
      </AdminPageTransition>,
    );
    expect(screen.getByText("reduced body")).toBeInTheDocument();
    const wrapper = container.querySelector(".page-body") as HTMLElement;
    expect(wrapper.style.opacity).toBe("");
    expect(wrapper.style.transform).toBe("");
  });

  it("keeps the layout connected to the transition", () => {
    expect(rootSource).toMatch(/import \{ AdminPageTransition \} from "\.\.\/components\/page-transition"/);
    expect(rootSource).toMatch(/<AdminPageTransition\s+motionKey=\{pathname\}/);
  });
});