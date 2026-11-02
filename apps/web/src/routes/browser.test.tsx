import * as React from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useTranslation as getMockTranslation } from "react-i18next";
const runtime = vi.hoisted(() => ({
  search: { assembly: "Wm82.a4.v1", locus: "chr01:100-200", release: "4", tracks: undefined as string[] | undefined },
  navigate: vi.fn(),
}));
vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: unknown) => ({ options, useSearch: () => runtime.search }),
  useNavigate: () => runtime.navigate,
}));
vi.mock("react-i18next", () => {
  // These boundary tests assert keys; keep their translator stable across renders.
  const translation = { t: (key: string) => key };
  return { useTranslation: () => translation };
});
vi.mock("../components/route-motion", () => ({ FadeUp: ({ children }: { children: React.ReactNode }) => children }));
import { Route } from "./browser";
const Page = (Route.options as { component: React.ComponentType }).component;
beforeEach(() => {
  runtime.search = { assembly: "Wm82.a4.v1", locus: "chr01:100-200", release: "4", tracks: undefined };
  runtime.navigate.mockReset();
});
afterEach(cleanup);

it("keeps the mocked translator identical across hook calls", () => {
  expect(getMockTranslation().t).toBe(getMockTranslation().t);
});

function mount() {
  const result = render(<Page />);
  const iframe = screen.getByTestId("browser-iframe") as HTMLIFrameElement;
  const post = vi.spyOn(iframe.contentWindow!, "postMessage").mockImplementation(() => {});
  const message = (type: string, payload: unknown = {}) => act(() => {
    window.dispatchEvent(new MessageEvent("message", {
      origin: new URL(iframe.src).origin, source: iframe.contentWindow,
      data: { source: "soymutdb-jbrowse", version: 1, type, payload },
    }));
  });
  return { ...result, iframe, post, message };
}
it("does not turn an absent track selection into a clear-all init", () => {
  const { post, message } = mount();
  message("ready");
  expect(post).toHaveBeenCalled();
  expect(post.mock.calls[0][0].payload.tracks).toBeUndefined();
  expect(post.mock.calls[0][0].payload.release).toBe("4");
});
it("forwards an explicit track selection unchanged", () => {
  runtime.search.tracks = ["track_42", "track_43"];
  const { post, message } = mount();
  message("ready");
  expect(post.mock.calls[0][0].payload.tracks).toEqual(["track_42", "track_43"]);
});
it("sends a new init for a release-only URL change even when locus and assembly are identical", () => {
  const { post, message, rerender } = mount();
  message("ready");
  post.mockClear();
  runtime.search = { ...runtime.search, release: "9" };
  rerender(<Page />);
  expect(post).toHaveBeenCalled();
  expect(post.mock.calls.at(-1)![0].payload.release).toBe("9");
  const link = screen.getByTestId("browser-open-new-tab");
  expect(new URL(link.getAttribute("href")!).searchParams.get("release")).toBe("9");
  // The embedded iframe stays mounted; live changes use the bridge.
  expect(new URL((screen.getByTestId("browser-iframe") as HTMLIFrameElement).src).searchParams.get("release")).toBe("4");
});
it("does not carry the previous scope's coordinates or tracks into a new release", () => {
  const { post, message, rerender } = mount();
  message("ready");
  post.mockClear();
  runtime.search = { ...runtime.search, release: "9" };
  rerender(<Page />);
  const payload = post.mock.calls.at(-1)![0].payload;
  expect(payload.locus).toBeUndefined();
  expect(payload.tracks).toBeUndefined();
  expect(payload.scopeEpoch).toBeGreaterThan(1);
});
it("keeps an explicitly chosen destination locus across a release change", () => {
  const { post, message, rerender } = mount();
  message("ready");
  post.mockClear();
  runtime.search = { ...runtime.search, release: "9", locus: "chr07:1000-2000" };
  rerender(<Page />);
  expect(post.mock.calls.at(-1)![0].payload.locus).toBe("chr07:1000-2000");
});
it("does not relabel late old-release viewport events with the new release", () => {
  const { message, rerender } = mount();
  message("ready");
  runtime.search = { ...runtime.search, release: "9" };
  rerender(<Page />);
  message("locus-change", { assembly: "Wm82.a4.v1", release: "4", locus: "chr02:500-900" });
  expect(runtime.navigate).not.toHaveBeenCalled();
});
it("rejects a stale viewport event even when the release string matches again", () => {
  const { message, rerender } = mount();
  message("ready");
  runtime.search = { ...runtime.search, release: "9" };
  rerender(<Page />);
  // The embedded browser reports the new scope, so the portal mirror follows.
  message("locus-change", { assembly: "Wm82.a4.v1", release: "9", scopeEpoch: 2, locus: "chr05:1-100" });
  runtime.navigate.mockClear();
  runtime.search = { ...runtime.search, release: "4" };
  rerender(<Page />);
  // A viewport event from the first release-4 scope must not win again.
  message("locus-change", { assembly: "Wm82.a4.v1", release: "4", scopeEpoch: 1, locus: "chr02:500-900" });
  expect(runtime.navigate).not.toHaveBeenCalled();
});
it("keeps native assembly and track-only changes in the portal URL", () => {
  const { message } = mount();
  message("ready");
  message("locus-change", { assembly: "Wm82.a5.v1", release: "4", locus: runtime.search.locus, tracks: ["track_99"] });
  expect(runtime.navigate).toHaveBeenCalledWith({ to: "/browser", replace: true, search: { ...runtime.search, assembly: "Wm82.a5.v1", tracks: ["track_99"] } });
});
