import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { PageHeader } from "./page-header";

describe("PageHeader", () => {
  it("renders title, description and actions", () => {
    render(
      <PageHeader
        title="Mutants"
        description="Browse all soybean mutants"
        actions={<button>New</button>}
      />,
    );
    expect(screen.getByRole("heading", { name: "Mutants" })).toBeInTheDocument();
    expect(screen.getByText("Browse all soybean mutants")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New" })).toBeInTheDocument();
  });

  it("renders a breadcrumb trail with links and current page", () => {
    render(
      <PageHeader
        title="Detail"
        breadcrumb={[
          { label: "Home", href: "/" },
          { label: "Mutants", href: "/mutants" },
          { label: "Detail" },
        ]}
      />,
    );
    const nav = screen.getByRole("navigation", { name: "Breadcrumb" });
    const home = screen.getByRole("link", { name: "Home" });
    expect(home).toHaveAttribute("href", "/");
    expect(nav.querySelectorAll("li").length).toBe(3);
    expect(within(nav).getByText("Detail")).toHaveAttribute("aria-current", "page");
  });

  it("accepts a custom breadcrumb node", () => {
    render(
      <PageHeader title="X" breadcrumb={<div data-testid="custom-crumb">custom</div>} />,
    );
    expect(screen.getByTestId("custom-crumb")).toBeInTheDocument();
  });

  it("omits optional regions when not provided", () => {
    render(<PageHeader title="Only title" />);
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
