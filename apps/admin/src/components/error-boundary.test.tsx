import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./error-boundary";
import { RouteErrorBoundary } from "./route-error-boundary";

function ThrowingChild(): never {
  throw new Error("sensitive internal failure");
}

let attempts = 0;
function TransientChild() {
  attempts += 1;
  if (attempts === 1) throw new Error("temporary failure");
  return <p>recovered content</p>;
}

describe("Admin error boundaries", () => {
  beforeEach(() => {
    attempts = 0;
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

    expect(screen.getByRole("alert")).toHaveTextContent("此页面出错了");
    await user.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("recovered content")).toBeInTheDocument();
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
