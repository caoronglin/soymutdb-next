// @vitest-environment jsdom
/**
 * Instance-context badge contract.
 *
 * The badge sits in the shared admin header, so it renders on every console
 * page. It used to fall back to a *status word* ("Active" / "生效中") when the
 * build carried no release id, which made a console with no active release
 * pointer announce "Release Active" — a statement about a release that did
 * not exist, on every page of the console.
 *
 * These tests pin the two states that matter:
 *
 *   - a pinned release id is shown as the id itself;
 *   - with no pinned id, the badge says that no active release is set instead
 *     of borrowing a status word.
 */
import { cleanup, render, screen } from "@testing-library/react";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);
// The real Ant Design facade needs a ConfigProvider and a layout engine the
// unit environment does not have; the double renders the same props as plain
// DOM, which is what this test asserts on.
vi.mock("@/lib/antd", async () => (await import("../test/antd-double")));

const instance = vi.hoisted(() => ({
  current: {
    name: "Preview",
    code: "PREVIEW",
    api_base_url: "http://127.0.0.1:18010",
  },
  isRemote: false,
  isLoading: false,
}));

vi.mock("../lib/instance-context-react", () => ({
  useInstanceContext: () => instance,
}));

import { InstanceContextBadge } from "./instance-context-badge";

async function renderBadge(): Promise<void> {
  // The badge links to /instances, so it needs a router.
  // The root route has to render the outlet, or the child route never mounts.
  const root = createRootRoute({ component: () => <Outlet /> });
  // The router renders the route tree, so the badge has to live in a route
  // component rather than as a React child of the provider.
  const index = createRoute({
    getParentRoute: () => root,
    path: "/",
    component: () => <InstanceContextBadge />,
  });
  const router = createRouter({
    routeTree: root.addChildren([index]),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  render(<RouterProvider router={router} />);
}

function releaseText(): string {
  return screen.getByTestId("instance-context-release").textContent ?? "";
}

describe("instance context badge", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
  });

  it("shows the pinned release id when the build carries one", async () => {
    vi.stubEnv("VITE_SOYMUTDB_RELEASE_ID", "release-42");
    await renderBadge();

    expect(releaseText()).toContain("release-42");
  });

  it("says no active release is set instead of borrowing a status word", async () => {
    vi.stubEnv("VITE_SOYMUTDB_RELEASE_ID", "");
    await renderBadge();

    const text = releaseText();
    // The status word is what used to stand in for the missing id.
    expect(text).not.toContain("生效中");
    expect(text).not.toMatch(/\bActive\b/);
    // It must still say something true about the release. The unit mock
    // resolves `defaultValue`, so that is the string under test here; the
    // Chinese catalogue entry is checked by the locale-key gate.
    expect(text).toContain("No active release");
  });

  it("does not treat a blank release id as a release", async () => {
    vi.stubEnv("VITE_SOYMUTDB_RELEASE_ID", "   ");
    await renderBadge();

    expect(releaseText()).toContain("No active release");
  });
});
