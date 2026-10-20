import * as React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
const runtime = vi.hoisted(() => ({ navigate: vi.fn(), redirect: "/genes\u007f" }));
vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: unknown) => ({ options }),
  useNavigate: () => runtime.navigate,
  useRouterState: () => ({ redirect: runtime.redirect }),
  Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));
vi.mock("@tanstack/react-query", () => ({ useQueryClient: () => ({ removeQueries: vi.fn() }) }));
vi.mock("@soymutdb/api-client", () => ({ ApiError: class extends Error {}, request: async () => ({ access_token: "token" }), setAccessToken: vi.fn() }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../components/route-motion", () => ({
  TextReveal: () => null,
  Reveal: ({ children }: { children: React.ReactNode }) => children,
  Stagger: ({ children }: { children: React.ReactNode }) => children,
}));
import { Route } from "./login";
const Page = (Route.options as { component: React.ComponentType }).component;
afterEach(cleanup);
it("uses the shared redirect guard to reject DEL in a post-login path", async () => {
  render(<Page />);
  fireEvent.submit(screen.getByTestId("login-email").closest("form")!);
  await waitFor(() => expect(runtime.navigate).toHaveBeenCalledWith({ to: "/" }));
});
