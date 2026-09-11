import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./error-boundary";
import { RouteErrorBoundary } from "./route-error-boundary";

function ThrowingChild(): never {
  throw new Error("sensitive internal failure");
}

/**
 * Fails on the first render *after mount*, not during the initial render.
 *
 * React 19 retries a component that throws before it ever commits, so a child
 * that throws on its very first render recovers on its own and the boundary
 * never shows a fallback. Flipping to the failure on a user event makes the
 * exception happen after commit, which is the case the retry button covers.
 */
function TransientChild() {
  const [failed, setFailed] = useState(false);
  if (failed) throw new Error("temporary failure");
  return (
    <button type="button" onClick={() => setFailed(true)}>
      trigger failure
    </button>
  );
}

describe("Admin error boundaries", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  it("renders a safe global recovery UI instead of a blank page", () => {
    render(
      <ErrorBoundary>
        <ThrowingChild />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("管理后台暂时无法显示");
    expect(screen.queryByText("sensitive internal failure")).not.toBeInTheDocument();
  });

  it("retries a transient route render failure", async () => {
    const user = userEvent.setup();
    render(
      <RouteErrorBoundary>
        <TransientChild />
      </RouteErrorBoundary>,
    );

    await user.click(screen.getByRole("button", { name: "trigger failure" }));

    expect(screen.getByRole("alert")).toHaveTextContent("此页面出错了");
    // The button's accessible name includes its icon label ("reload 重试").
    await user.click(screen.getByRole("button", { name: /重试/ }));
    expect(
      await screen.findByRole("button", { name: "trigger failure" }),
    ).toBeInTheDocument();
  });

  it("offers an in-app dashboard route from a failed page", () => {
    render(
      <RouteErrorBoundary>
        <ThrowingChild />
      </RouteErrorBoundary>,
    );

    expect(screen.getByRole("link", { name: "返回仪表盘" })).toHaveAttribute("href", "/");
  });
});
