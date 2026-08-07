import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ResponsiveDataView } from "./responsive-data-view";

describe("ResponsiveDataView", () => {
  it("renders children in the ready state", () => {
    render(
      <ResponsiveDataView status="ready">
        <ul>
          <li>item</li>
        </ul>
      </ResponsiveDataView>,
    );
    expect(screen.getByText("item")).toBeInTheDocument();
  });

  it("renders the default LoadingState while loading", () => {
    const { container } = render(<ResponsiveDataView status="loading">x</ResponsiveDataView>);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(container.querySelectorAll(".shimmer").length).toBeGreaterThan(0);
  });

  it("renders a custom loading view", () => {
    render(
      <ResponsiveDataView status="loading" loadingView={<div>spinner-custom</div>}>
        x
      </ResponsiveDataView>,
    );
    expect(screen.getByText("spinner-custom")).toBeInTheDocument();
  });

  it("renders the default ErrorState with retry in the error state", () => {
    const onRetry = vi.fn();
    render(
      <ResponsiveDataView status="error" error="nope" onRetry={onRetry}>
        x
      </ResponsiveDataView>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("nope");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders the default EmptyState in the empty state", () => {
    render(<ResponsiveDataView status="empty">x</ResponsiveDataView>);
    expect(screen.getByRole("status")).toHaveTextContent("No data");
  });

  it("applies minHeight to slot wrappers", () => {
    render(
      <ResponsiveDataView status="loading" minHeight="320px">
        x
      </ResponsiveDataView>,
    );
    const wrapper = screen.getByRole("status").parentElement;
    expect(wrapper).toHaveStyle({ minHeight: "320px" });
  });
});
