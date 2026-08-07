import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { LoadingState } from "./loading-state";
import { ErrorState } from "./error-state";
import { EmptyState } from "./empty-state";
import { DemoState } from "./demo-state";

describe("LoadingState", () => {
  it("renders skeleton rows with a status role by default", () => {
    const { container } = render(<LoadingState rows={2} />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(container.querySelectorAll(".shimmer").length).toBe(2);
  });

  it("renders a spinner variant with a custom label", () => {
    render(<LoadingState variant="spinner" label="Fetching…" />);
    expect(screen.getByRole("status")).toHaveTextContent("Fetching…");
  });

  it("supports a custom skeleton shape", () => {
    const { container } = render(
      <LoadingState rows={1} shape={<div className="shimmer rounded-full h-10 w-10" />} />,
    );
    expect(container.querySelectorAll(".shimmer").length).toBe(1);
  });
});

describe("ErrorState", () => {
  it("renders message, retry button and request id", () => {
    const onRetry = vi.fn();
    render(
      <ErrorState
        message="The API is unreachable"
        onRetry={onRetry}
        requestId="req-42"
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("The API is unreachable");
    expect(alert).toHaveTextContent("req-42");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("uses default title and hides retry when no callback is given", () => {
    render(<ErrorState />);
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("EmptyState", () => {
  it("defaults to the no-data copy", () => {
    render(<EmptyState />);
    expect(screen.getByRole("status")).toHaveTextContent("No data");
    expect(screen.getByRole("status")).toHaveTextContent(
      "There are no records to display yet.",
    );
  });

  it("uses the filtered copy and a default icon in filtered mode", () => {
    const { container } = render(<EmptyState mode="filtered" />);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("No results found");
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("lets callers override title, description, icon and action", () => {
    render(
      <EmptyState title="Custom" description="Custom desc" action={<button>Go</button>} />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Custom");
    expect(screen.getByRole("button", { name: "Go" })).toBeInTheDocument();
  });
});

describe("DemoState", () => {
  it("renders a non-blocking banner with title, description and children", () => {
    render(
      <DemoState
        description="Read-only view"
        children={<span>readonly badge</span>}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Demo mode");
    expect(screen.getByRole("status")).toHaveTextContent("Read-only view");
    expect(screen.getByText("readonly badge")).toBeInTheDocument();
  });
});
