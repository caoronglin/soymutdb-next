// @vitest-environment jsdom
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const state = vi.hoisted(() => {
  class ApiError extends Error {
    constructor(
      message: string,
      readonly status: number,
    ) {
      super(message);
    }
  }

  return {
    ApiError,
    locationSearch: { redirect: "/analyses" } as unknown,
    navigate: vi.fn(),
    removeQueries: vi.fn(),
    request: vi.fn(),
    setAccessToken: vi.fn(),
  };
});

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: unknown) => options,
  Link: ({ to: _to, children, ...props }: { to: unknown; children?: React.ReactNode }) => (
    <a {...props}>{children}</a>
  ),
  useNavigate: () => state.navigate,
  useRouterState: ({ select }: { select: (routerState: unknown) => unknown }) =>
    select({ location: { search: state.locationSearch } }),
}));

vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ removeQueries: state.removeQueries }),
}));

vi.mock("@soymutdb/api-client", () => ({
  ApiError: state.ApiError,
  request: state.request,
  setAccessToken: state.setAccessToken,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      ({
        "auth.email": "Email",
        "auth.password": "Password",
        "auth.loginButton": "Sign in",
        "common.loading": "Loading",
        "loginPage.invalidCredentials": "Invalid email or password.",
        "loginPage.loginUnavailable": "Unable to sign in. Please try again.",
      })[key] ?? key,
  }),
}));

vi.mock("../../components/route-motion", () => ({
  Reveal: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  Stagger: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  TextReveal: ({ text }: { text: string }) => <span>{text}</span>,
}));

import { Route } from "../login";

const LoginComponent = (Route as unknown as { component: React.ComponentType }).component;

function submitLogin(email = "researcher@example.org", password = "correct-horse-battery-staple") {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: email } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
  const form = screen.getByRole("button", { name: "Sign in" }).closest("form");
  if (!form) throw new Error("login form was not rendered");
  fireEvent.submit(form);
}

describe("login route", () => {
  beforeEach(() => {
    state.locationSearch = { redirect: "/analyses" };
    state.navigate.mockReset().mockResolvedValue(undefined);
    state.removeQueries.mockReset();
    state.request.mockReset().mockResolvedValue({ access_token: "access-token", expires_in: 900 });
    state.setAccessToken.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("authenticates anonymously, retains the refresh cookie, and redirects after updating session state", async () => {
    render(<LoginComponent />);

    submitLogin();

    await waitFor(() => expect(state.request).toHaveBeenCalledTimes(1));
    expect(state.request).toHaveBeenCalledWith("/auth/login", {
      method: "POST",
      json: { email: "researcher@example.org", password: "correct-horse-battery-staple" },
      auth: false,
      withCredentials: true,
    });
    expect(state.setAccessToken).toHaveBeenCalledWith("access-token");
    expect(state.removeQueries).toHaveBeenCalledWith({ queryKey: ["current-user"], exact: true });
    expect(state.navigate).toHaveBeenCalledWith({ to: "/analyses" });
    expect(screen.queryByRole("checkbox", { name: /remember/i })).toBeNull();
  });

  it("keeps the user on the form and exposes a generic credential error", async () => {
    state.request.mockRejectedValueOnce(new state.ApiError("Unauthorized", 401));
    render(<LoginComponent />);

    submitLogin();

    expect((await screen.findByRole("alert")).textContent).toContain("Invalid email or password.");
    expect(state.navigate).not.toHaveBeenCalled();
  });

  it("rejects protocol-relative redirect targets after a successful login", async () => {
    state.locationSearch = { redirect: "//attacker.example/" };
    render(<LoginComponent />);

    submitLogin();

    await waitFor(() => expect(state.navigate).toHaveBeenCalledWith({ to: "/" }));
  });

  it("rejects redirect targets containing control characters", async () => {
    state.locationSearch = { redirect: "/analyses\u0000unexpected" };
    render(<LoginComponent />);

    submitLogin();

    await waitFor(() => expect(state.navigate).toHaveBeenCalledWith({ to: "/" }));
  });
});
